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
    POST /reviews           record a recall rating and reschedule a notion (SM-2)
    POST /reviews/enqueue   add a notion to the review queue, due immediately
    GET  /reviews/due       notions due for spaced-repetition review

The layer stays thin: each route delegates to the existing grounded functions
and graph nodes. No retrieval or prompting logic is reimplemented here. The API
is stateful: a ``student_id`` identifies the user (get-or-create), ``/ask`` turns
are persisted as conversation history, and ``/history`` replays them.

This module owns the application object (``app``), its startup lifespan,
middleware, CORS and the unhandled-exception handler. The route handlers live in
``api.routers`` (one ``APIRouter`` per domain) and the shared dependencies and
Pydantic models in ``api.deps`` / ``api.schemas``.

The grounded functions and graph nodes are imported here and re-exported so the
route modules resolve them through this module at call time (``api.main.answer``
etc.). This preserves the single, swappable indirection point the test suite
monkeypatches; ``_engine`` and ``get_settings`` are likewise read through this
module so tests can bind an in-memory database and override settings.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

# Grounded functions and graph nodes, imported here so they are attributes of
# this module (``api.main.answer`` etc.). The route modules call them through
# ``api.main`` at request time, which keeps a single indirection point the tests
# monkeypatch. They are re-exports; see ``__all__``.
from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.quiz import generate_quiz, grade_quiz_answer, summarize_quiz
from agent.nodes.reexplain import reexplain, stream_reexplain
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
    reviews,
    sessions,
    source,
)
from api.routers import (
    grade as grade_router,
)
from api.routers import (
    reexplain as reexplain_router,
)
from core.answer import answer, stream_answer
from core.config import get_settings
from core.courses import list_chapters, list_courses
from core.documents import (
    delete_documents,
    list_documents,
    read_stored_file,
    rename_chapter,
    rename_course,
    save_upload,
    stream_ingest,
)
from core.sources import get_source
from db.session import (
    configure_session_factory,
    create_engine_from_settings,
    get_session,
    init_db,
)

logger = logging.getLogger("api")

# Re-exported names: attributes the route modules resolve through ``api.main`` at
# call time and the test suite monkeypatches. Listed here so the linter treats
# them as intentional re-exports rather than unused imports.
__all__ = [
    "answer",
    "app",
    "configure_engine",
    "delete_documents",
    "generate",
    "generate_quiz",
    "get_session",
    "get_settings",
    "get_source",
    "grade",
    "grade_quiz_answer",
    "list_chapters",
    "list_courses",
    "list_documents",
    "read_stored_file",
    "reexplain",
    "rename_chapter",
    "rename_course",
    "save_upload",
    "stream_answer",
    "stream_ingest",
    "stream_reexplain",
    "summarize_quiz",
]

# Bound on startup (or injected by tests via ``configure_engine``). Keeping the
# engine module-level lets tests swap in an in-memory SQLite database.
_engine: Engine | None = None


def configure_engine(engine: Engine) -> None:
    """Bind the API to ``engine``, create tables, and configure the session factory.

    Tests call this with an in-memory SQLite engine; startup calls it with the
    engine built from ``Settings.database_url``.
    """
    global _engine
    _engine = engine
    init_db(engine)
    configure_session_factory(engine)


# The placeholder secret shipped for local development. It MUST be overridden
# before enabling ``require_auth`` — otherwise anyone knowing this public default
# could forge a valid access token.
_INSECURE_JWT_DEFAULT = "dev-insecure-change-me"
# Minimum length accepted for a JWT signing secret when auth is required. A short
# secret is brute-forceable and defeats the point of signing.
_MIN_JWT_SECRET_LEN = 16


def _validate_jwt_secret(settings: Any) -> None:
    """Fail fast when auth is required but the JWT secret is unsafe.

    Only enforced when ``require_auth`` is on (a public/shared deployment). The
    default placeholder secret or any secret shorter than
    :data:`_MIN_JWT_SECRET_LEN` characters is rejected with a clear
    ``RuntimeError`` so the operator sets a strong ``JWT_SECRET`` instead of
    silently running with a forgeable one. With ``require_auth`` off (local dev)
    the placeholder is left alone so nothing changes for single-user runs.
    """
    if not settings.require_auth:
        return
    secret = settings.jwt_secret
    if secret == _INSECURE_JWT_DEFAULT or len(secret) < _MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            "REQUIRE_AUTH is enabled but JWT_SECRET is unsafe "
            "(the insecure default or shorter than "
            f"{_MIN_JWT_SECRET_LEN} characters). Set a strong, random JWT_SECRET "
            "before running with authentication enabled."
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure structured logging and the database on startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    # Refuse to boot a public (auth-required) deployment with a forgeable secret.
    _validate_jwt_secret(settings)
    if _engine is None:
        configure_engine(create_engine_from_settings())
    yield


app = FastAPI(
    title="grounded-rag",
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
    origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()
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
app.include_router(reviews.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)
