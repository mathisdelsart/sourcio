"""FastAPI application exposing the tutor endpoints.

Endpoints:
    GET  /health            health check
    POST /ask               answer a question, grounded in the course (explain path)
    POST /reexplain         rephrase the last tutor answer at a chosen level
    POST /reexplain/stream  same, streamed token by token as Server-Sent Events
    POST /exercise          generate an exercise (never returns the reference solution)
    POST /grade             grade a student's answer
    POST /quiz              generate a grounded multi-question quiz (no solutions)
    POST /quiz/{id}/grade   grade one quiz answer against its stored reference
    GET  /exercise/{id}/review  full exercise (with solution) + latest grade, for review
    GET  /quiz/{id}/review  full quiz (with solutions) + per-question grades, for review
    GET  /courses           list the distinct courses indexed in Qdrant
    GET  /chapters          list the distinct chapters of a course (owner-scoped)
    GET  /documents         inventory of indexed material by course and chapter
    POST /documents/upload  ingest an uploaded file under a course/chapter
    DELETE /documents       delete a course's (or one chapter's) indexed points
    POST /documents/rename  rename a course and/or a chapter of the caller's material
    GET  /source/{chunk_id} fetch a cited source chunk's text and metadata
    GET  /history/{id}      recent conversation turns for a student
    POST /sessions          open a named conversation thread for a student
    GET  /sessions/{id}     list a student's conversation threads
    GET  /sessions/{id}/{sid}/messages  messages of one thread (chronological)
    POST /feedback          record a thumbs up/down on a tutor answer
    GET  /feedback/summary  thumbs up/down counts for a student

The layer stays thin: each route delegates to the existing grounded functions
and graph nodes. No retrieval or prompting logic is reimplemented here. The API
is stateful: a ``student_id`` identifies the user (get-or-create), ``/ask`` turns
are persisted as conversation history, and ``/history`` replays them.

This module owns the application object (``app``), its startup lifespan,
middleware, CORS and the unhandled-exception handler. The route handlers live in
``api.routers`` (one ``APIRouter`` per domain) and the shared dependencies and
Pydantic models in ``api.deps`` / ``api.schemas``.

The application object (``app``), startup lifespan, middleware, CORS and the
unhandled-exception handler live here. The grounded functions, graph nodes and
the database engine that route handlers call at request time live in the leaf
module ``api.runtime`` (which nothing imports back into ``api.main``, breaking
the import cycle); that is also the single indirection point the test suite
monkeypatches.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import runtime
from api.logging_config import configure_logging, request_id_var
from api.middleware import (
    REQUEST_ID_HEADER,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from api.routers import (
    ask,
    auth,
    courses,
    documents,
    exercise,
    feedback,
    health,
    history,
    quiz,
    sessions,
    source,
)
from api.routers import (
    grade as grade_router,
)
from api.routers import (
    reexplain as reexplain_router,
)

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure structured logging and the database on startup."""
    settings = runtime.get_settings()
    configure_logging(settings.log_level)
    # Refuse to boot a public (auth-required) deployment with a forgeable secret.
    runtime._validate_jwt_secret(settings)
    runtime.ensure_engine()
    yield


app = FastAPI(
    title="sourcio",
    description="Course tutor grounded in your own material.",
    lifespan=lifespan,
)

# Hardening middleware (all opt-in/safe). Security headers are always added and
# never alter the body or status. Rate limiting reads the effective limit: it is
# a no-op locally but auto-defaults to 60/min once public auth (`require_auth`)
# is enabled, so the default local config is unthrottled while a public
# deployment gets a sane throttle. The request-id middleware is always active and
# only adds a header + logging context.
#
# Starlette runs the last-added middleware first, so the request-id layer is
# outermost: it sets the request-id contextvar before anything else runs (so the
# security headers, the rate limiter's 429, and the global error handler are all
# logged with — and, for the response, carry — the id), and resets it last.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIdMiddleware)

# CORS added last so it is outermost: a browser preflight (OPTIONS) is answered
# before the auth/rate-limit layers. Allowed origins come from `cors_origins`
# (comma-separated); an empty value disables CORS. The default permits local dev
# origins so the `web/` frontend works out of the box; override CORS_ORIGINS in
# production with the deployed frontend URL.
_cors_origins = [
    origin.strip() for origin in runtime.get_settings().cors_origins.split(",") if origin.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _cors_headers_for(request: Request) -> dict[str, str]:
    """CORS headers to echo on an error response for an allowed origin.

    Starlette's ``ServerErrorMiddleware`` (which runs the 500 handler below) sits
    *outside* the ``CORSMiddleware``, so a 500 response would otherwise carry no
    ``Access-Control-Allow-Origin`` header and the browser would report a generic
    "could not reach the backend" instead of surfacing the real status/message.
    We mirror the middleware's decision here: echo the request ``Origin`` only
    when it is in the configured ``cors_origins`` (never a blanket ``*``), and set
    ``Access-Control-Allow-Credentials`` to match ``allow_credentials=True``.
    Returns an empty dict when CORS is disabled or the origin is not allowed.
    """
    origin = request.headers.get("origin")
    if not origin or origin not in _cors_origins:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a consistent JSON body for unhandled (500) errors, leaking nothing.

    This handler is intentionally scoped to *unhandled* exceptions only:
    FastAPI's own handling of ``HTTPException`` (401/404/...) and request
    validation (422) is left untouched, so every existing error-shape assertion
    keeps passing. Here we log the full exception server-side at error level
    (with traceback and the request id), then return a generic message plus the
    request id to the client; the exception type, args and stack trace are never
    sent to the client.

    The request id is read from the request scope's state rather than the
    contextvar: Starlette's error middleware runs above ``RequestIdMiddleware``,
    which has already reset the contextvar by the time this handler runs. We also
    re-attach the ``X-Request-ID`` response header here, since this 500 response
    bypasses that middleware's header-injecting wrapper.
    """
    request_id = request.scope.get("state", {}).get("request_id") or request_id_var.get()
    logger.error(
        "Unhandled exception while handling %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    # This 500 response bypasses both RequestIdMiddleware's header wrapper and the
    # CORSMiddleware, so re-attach the request id and the CORS headers here; without
    # the latter the browser masks the real error as an unreachable-backend failure.
    headers = _cors_headers_for(request)
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "type": "internal_server_error",
                "message": "An internal error occurred. Please retry later.",
                "request_id": request_id,
            }
        },
        headers=headers,
    )


# Wire the domain routers. Each module owns a self-consistent set of paths, so
# registration order does not change route matching.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(ask.router)
app.include_router(reexplain_router.router)
app.include_router(exercise.router)
app.include_router(grade_router.router)
app.include_router(quiz.router)
app.include_router(documents.router)
app.include_router(courses.router)
app.include_router(source.router)
app.include_router(history.router)
app.include_router(sessions.router)
app.include_router(feedback.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)
