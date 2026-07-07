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
    GET  /documents         inventory of indexed material by course and chapter
    POST /documents/upload  ingest an uploaded file under a course/chapter
    DELETE /documents       delete a course's (or one chapter's) indexed points
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
"""

import hmac
import json
import logging
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Engine, func, select

from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.quiz import generate_quiz, grade_quiz_answer, summarize_quiz
from agent.nodes.reexplain import reexplain, stream_reexplain
from agent.state import Level, Rigor, TutorState, to_history
from api.auth import (
    CurrentUser,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    get_current_user,
    get_optional_user,
    login_user,
    register_user,
)
from api.logging_config import configure_logging, request_id_var
from api.middleware import (
    REQUEST_ID_HEADER,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from core.answer import answer, stream_answer
from core.config import get_settings
from core.courses import list_courses
from core.documents import (
    delete_documents,
    list_documents,
    save_upload,
    stored_file_path,
    stream_ingest,
)
from core.jobs import create_job, get_job, list_jobs, update_job
from core.scheduling import MAX_QUALITY, MIN_QUALITY, schedule
from core.sources import get_source
from db.models import Exercise, Feedback, Grade, Quiz, QuizQuestion, Review, Student
from db.models import Message as MessageModel
from db.models import Session as SessionModel
from db.session import (
    add_message,
    configure_session_factory,
    create_engine_from_settings,
    delete_messages,
    get_or_create_student,
    get_session,
    init_db,
    recent_messages,
)

logger = logging.getLogger("api")

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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure structured logging and the database on startup."""
    configure_logging(get_settings().log_level)
    if _engine is None:
        configure_engine(create_engine_from_settings())
    yield


app = FastAPI(
    title="grounded-rag",
    description="Course tutor grounded in your own material.",
    lifespan=lifespan,
)

# Hardening middleware (all opt-in/safe). Security headers are always added and
# never alter the body or status. Rate limiting is a no-op unless
# `rate_limit_per_minute` is positive, so the default config is unthrottled. The
# request-id middleware is always active and only adds a header + logging
# context.
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


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce API-key authentication when one is configured.

    When ``Settings.api_key`` is empty (the default) the API stays fully open and
    this dependency is a no-op, preserving backward compatibility. When a key is
    set, the request must carry a matching ``X-API-Key`` header; otherwise the
    request is rejected with 401. ``/health`` never depends on this guard.
    """
    expected = get_settings().api_key
    if not expected:
        return
    if not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


def get_data_user(authorization: str | None = Header(default=None)) -> UserOut | None:
    """Resolve the caller for data endpoints, honouring ``REQUIRE_AUTH``.

    When ``require_auth`` is on, a valid bearer token is mandatory (401
    otherwise); when off, authentication stays optional (anonymous allowed),
    preserving the MVP behaviour byte-for-byte.
    """
    if get_settings().require_auth:
        return get_current_user(authorization)
    return get_optional_user(authorization)


# Re-exported so routes can declare the flag-aware data dependency concisely.
DataUser = Depends(get_data_user)

STUDENT_FOREIGN = "This student belongs to another account."


def _resolve_student(session: Any, external_id: str, user: UserOut | None) -> Student:
    """Get-or-create the student and, when authenticated, claim/enforce ownership.

    Anonymous requests (``user is None``, i.e. no bearer token) behave exactly as
    before: the student is keyed solely by ``external_id`` and left unlinked. As
    soon as a valid bearer token is present the caller is isolated to their own
    students: an unowned student is linked to that user, and touching a student
    that belongs to a *different* account is rejected with 403. This holds
    whenever a user is authenticated, independently of ``require_auth`` (that flag
    only additionally *forces* a token via the sign-in gate). This never changes
    the answer, only the ownership link.
    """
    student = get_or_create_student(session, external_id)
    if user is None:
        return student
    if student.user_id is None:
        student.user_id = user.id
        session.flush()
    elif student.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STUDENT_FOREIGN)
    return student


def _student_for_read(session: Any, external_id: str, user: UserOut | None) -> Student | None:
    """Look up a student by ``external_id`` for a read/scoped route.

    Returns the ``Student`` or ``None``. Whenever a caller is authenticated (a
    bearer token was sent, so ``user`` is not ``None``), a student that exists but
    is not owned by ``user`` is treated as inaccessible: raise 403 (never leak
    another tenant's data). This holds independently of ``require_auth``. A missing
    student still returns ``None`` so callers keep their existing empty/404
    behaviour. For an anonymous caller (``user is None``) this is a plain lookup,
    so the anonymous flow is unchanged.
    """
    student = session.scalar(select(Student).where(Student.external_id == external_id))
    if student is None:
        return None
    if user is not None and student.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=STUDENT_FOREIGN)
    return student


def _scoped_read_owner(external_id: str | None, user: UserOut | None) -> str | None:
    """Return the owner id to scope a read by, enforcing ownership when authenticated.

    ``external_id`` is the request's effective ``student_id`` (``u<id>`` when
    logged in, the device id when anonymous). When ``None`` (existing callers that
    do not scope) the read stays global (returns ``None``). Otherwise, when the
    caller is authenticated, a student that belongs to a *different* account is
    rejected with 403 (via :func:`_student_for_read`), so one account can never
    read another's material by passing its id. The owner string is returned
    unchanged so the core layer scopes retrieval/listing to "mine or shared".
    """
    if external_id is None:
        return None
    with get_session(_engine) as session:
        _student_for_read(session, external_id, user)
    return external_id


def _resolve_session_id(session: Any, student_id: int, session_id: int | None) -> int | None:
    """Validate that ``session_id`` is a thread owned by ``student_id``.

    Returns the id unchanged when it names one of the student's threads. When it
    is ``None`` (the default), the turn stays unthreaded. A stale or unknown id
    (for example a thread id persisted in the browser after a database reset, or
    one belonging to another student) is treated as "no thread" — it returns
    ``None`` rather than failing the request, since the query already filters by
    ``student_id`` so the message can never be mis-attached.
    """
    if session_id is None:
        return None
    thread = session.scalar(
        select(SessionModel).where(
            SessionModel.id == session_id, SessionModel.student_id == student_id
        )
    )
    return session_id if thread is not None else None


# Distinct message roles for the activity feed. ``user``/``assistant`` are the
# Q&A turns written by /ask and /reexplain; these two label exercise and quiz
# activity so the history can style them apart. ``Message.role`` is a plain
# string column (no enum/CHECK), so new values are safe, and ``to_history`` maps
# unknown roles through unchanged — they are never treated as tutor context, so
# reexplain keeps reformulating the last real answer only.
ROLE_EXERCISE = "exercise"
ROLE_QUIZ = "quiz"


def _record_activity(
    external_id: str,
    user: UserOut | None,
    session_id: int | None,
    *,
    role: str,
    content: str,
    ref_id: int | None = None,
) -> None:
    """Persist one activity item (exercise/quiz) as a message, like /ask does.

    The student is resolved (and ownership enforced) exactly as for a question,
    and the item is attached to the active thread when ``session_id`` names one
    of the student's threads. Kept concise on purpose: callers pass a short
    summary, never a full JSON blob. ``ref_id`` links the turn back to the
    persisted exercise/quiz so the history can fetch the full item for review.
    """
    with get_session(_engine) as session:
        student = _resolve_student(session, external_id, user)
        thread_id = _resolve_session_id(session, student.id, session_id)
        add_message(
            session,
            student_id=student.id,
            role=role,
            content=content,
            session_id=thread_id,
            ref_id=ref_id,
        )


class AskRequest(BaseModel):
    """A question to answer from the course, on behalf of a student.

    ``course`` and ``chapter`` optionally restrict retrieval to a single course
    (and chapter). Both default to ``None`` so existing callers keep searching
    the whole collection unchanged.
    """

    student_id: str
    question: str
    k: int = Field(default=5, ge=1)
    course: str | None = None
    chapter: str | None = None
    session_id: int | None = None
    # Optional locale code ('en'/'fr'/'nl') to force the default answer language;
    # None keeps the model answering in the question's own language.
    language: str | None = None


class Citation(BaseModel):
    """A cited source: its inline marker number, chunk id (to fetch its excerpt)
    and label.

    ``n`` is the 1-based index exactly as written inline in the answer (``[n]``),
    so a UI can render a numbered legend matching the markers.
    """

    n: int
    id: str
    label: str


class AskResponse(BaseModel):
    """A grounded answer, refused when the course does not cover the question."""

    answer: str
    refused: bool
    sources: list[str]
    # Structured citations carry the chunk id so a UI can open the exact source
    # excerpt via GET /source/{id}; `sources` keeps the plain labels.
    citations: list[Citation] = []


class ReexplainRequest(BaseModel):
    """A request to rephrase the student's last tutor answer at a given level."""

    student_id: str
    level: Level = "beginner"


class ReexplainResponse(BaseModel):
    """The rephrased explanation (or a friendly note when nothing to re-explain)."""

    answer: str


class ExerciseRequest(BaseModel):
    """A free-form exercise request for a student.

    ``notion`` is the request itself (any exercise, in free form). ``course`` and
    ``chapter`` optionally scope retrieval so the exercise stays on the requested
    material; when both are None the whole collection is searched.
    """

    student_id: str
    notion: str
    course: str | None = None
    chapter: str | None = None
    # Optional locale code ('en'/'fr'/'nl') to force the exercise's language;
    # None keeps the model writing in the request's own language.
    language: str | None = None
    # Optional thread to attach the resulting activity item to, like /ask. When
    # None (or not owned by the student) the item stays in the flat history.
    session_id: int | None = None


class ExerciseResponse(BaseModel):
    """A course-grounded exercise. The reference solution is withheld."""

    problem: str
    refused: bool
    id: int | None = None


class GradeRequest(BaseModel):
    """A student's answer to grade, optionally against a prior exercise.

    ``rigor`` sets the marking strictness; an unsupported value is rejected with
    422 by the ``Rigor`` literal, matching how ``ReexplainRequest.level`` is
    validated.
    """

    student_id: str
    message: str
    exercise: dict[str, Any] | None = None
    rigor: Rigor = "standard"


class GradeResponse(BaseModel):
    """The judge's verdict on the student's answer."""

    score: int
    feedback: str


class QuizRequest(BaseModel):
    """A free-form quiz request for a student.

    ``notion`` is the request itself (any quiz, in free form). ``n`` is the
    desired number of questions; it is clamped to a small range so a request can
    never ask for an unbounded quiz. ``course`` and ``chapter`` optionally scope
    retrieval so the quiz stays on the requested material; when both are None the
    whole collection is searched.
    """

    student_id: str
    notion: str
    n: int = Field(default=3, ge=1, le=10)
    course: str | None = None
    chapter: str | None = None
    # Optional locale code ('en'/'fr'/'nl') to force the quiz's language; None
    # keeps the model writing in the request's own language.
    language: str | None = None
    # Optional thread to attach the resulting activity item to, like /ask. When
    # None (or not owned by the student) the item stays in the flat history.
    session_id: int | None = None


class QuizQuestionOut(BaseModel):
    """One quiz question, problem only. The reference solution is withheld."""

    id: int | None = None
    problem: str


class QuizResponse(BaseModel):
    """A course-grounded quiz. Reference solutions are never returned."""

    quiz_id: int | None = None
    notion: str
    questions: list[QuizQuestionOut]
    refused: bool


class QuizGradeRequest(BaseModel):
    """A student's answer to one quiz question, graded against its reference.

    ``rigor`` sets the marking strictness applied by the shared grade judge; an
    unsupported value is rejected with 422 by the ``Rigor`` literal, matching how
    ``GradeRequest.rigor`` is validated.
    """

    student_id: str
    question_id: int
    answer: str
    rigor: Rigor = "standard"


class QuizGradeAllItem(BaseModel):
    """One question's answer in a whole-quiz grading request."""

    question_id: int
    answer: str


class QuizGradeAllRequest(BaseModel):
    """All of a student's quiz answers, graded together for a final score.

    ``rigor`` sets the marking strictness applied to every answer; an unsupported
    value is rejected with 422 by the ``Rigor`` literal, matching ``GradeRequest``.
    """

    student_id: str
    answers: list[QuizGradeAllItem]
    rigor: Rigor = "standard"


class QuizGradeResult(BaseModel):
    """One question's verdict in a whole-quiz summary."""

    question_id: int
    score: int
    feedback: str


class QuizSummaryResponse(BaseModel):
    """A whole-quiz verdict: a final score and a personalized recommendation."""

    total: int
    results: list[QuizGradeResult]
    recommendation: str


class HistoryItem(BaseModel):
    """A single persisted conversation turn.

    ``ref_id`` links an activity turn (exercise/quiz) back to its domain object
    so the UI can fetch the full item for review; it is ``None`` for plain Q&A
    turns.
    """

    role: str
    content: str
    created_at: str
    ref_id: int | None = None


class CoursesResponse(BaseModel):
    """The distinct courses currently indexed in Qdrant, sorted."""

    courses: list[str]


class DocumentChapter(BaseModel):
    """One chapter of a course and how many distinct pages it carries.

    ``chapter`` is ``None`` for material indexed without one (a UI groups it as
    "Uncategorized").
    """

    chapter: str | None = None
    pages: int


class DocumentCourse(BaseModel):
    """A course's indexed inventory: its chapters, page count and stored files."""

    course: str
    total_pages: int
    chapters: list[DocumentChapter]
    # Names of original uploaded files kept for this course (viewable via
    # GET /documents/file). Empty for material indexed outside the upload UI.
    files: list[str] = []


class DocumentDeleteResponse(BaseModel):
    """How many indexed points were removed by a delete request."""

    deleted: int


class SourceResponse(BaseModel):
    """A cited source chunk: its full text and citation metadata.

    Lets a UI turn a citation into a readable excerpt. ``chapter`` may be absent
    for material indexed without a chapter, so it is optional.
    """

    id: str
    course: str
    chapter: str | None = None
    page: int
    text: str


class ExerciseGradeReview(BaseModel):
    """The graded verdict on an exercise, surfaced for after-the-fact review."""

    answer: str
    score: float
    feedback: str
    created_at: str


class ExerciseReviewResponse(BaseModel):
    """A generated exercise reviewed after the fact.

    The reference solution IS returned here (unlike ``/exercise``): review is
    after-the-fact, so the student is meant to see the model answer. ``grade`` is
    the latest verdict on the exercise, or ``None`` if it was never graded.
    """

    problem: str
    reference_solution: str
    grade: ExerciseGradeReview | None = None


class QuizQuestionReview(BaseModel):
    """One quiz question reviewed after the fact, with its reference solution.

    ``answer``/``score``/``feedback`` come from the latest grade on the question
    and are ``None`` when it was never answered.
    """

    position: int
    problem: str
    reference_solution: str
    answer: str | None = None
    score: float | None = None
    feedback: str | None = None


class QuizReviewResponse(BaseModel):
    """A generated quiz reviewed after the fact.

    Reference solutions ARE returned (unlike ``/quiz``): review is after-the-fact.
    Questions are ordered by position.
    """

    notion: str
    questions: list[QuizQuestionReview]


class SessionCreateRequest(BaseModel):
    """A request to open a new conversation thread for a student."""

    student_id: str
    title: str | None = None


class SessionOut(BaseModel):
    """A conversation thread owned by a student."""

    id: int
    title: str | None
    created_at: str


class StudentOut(BaseModel):
    """A student identity owned by the authenticated caller."""

    id: int
    external_id: str
    created_at: str


class FeedbackRequest(BaseModel):
    """A student's thumbs up/down on a tutor answer.

    ``rating`` is ``1`` for thumbs up and ``-1`` for thumbs down (validated). The
    question and answer text are stored verbatim so the feedback is
    self-contained for later evaluation. ``note`` is optional (e.g. why the
    answer was unhelpful).
    """

    student_id: str
    rating: int = Field(description="1 for thumbs up, -1 for thumbs down.")
    question: str
    answer: str
    note: str | None = None

    @field_validator("rating")
    @classmethod
    def _rating_in_range(cls, value: int) -> int:
        """Reject any rating other than the two allowed values."""
        if value not in (1, -1):
            raise ValueError("rating must be 1 (up) or -1 (down).")
        return value


class FeedbackResponse(BaseModel):
    """The id of the persisted feedback row."""

    id: int


class FeedbackSummary(BaseModel):
    """Aggregate thumbs up/down counts for a student."""

    up: int
    down: int


class ReviewRequest(BaseModel):
    """A recall rating for one notion, driving its spaced-repetition schedule.

    ``quality`` is how well the student just recalled the notion, an integer in
    ``0..5`` (SM-2): ratings below ``3`` are lapses that reset the streak. The
    bound is validated, so an out-of-range value is rejected with 422.
    """

    student_id: str
    notion: str
    quality: int = Field(description="Recall quality in 0..5 (>=3 passes).")

    @field_validator("quality")
    @classmethod
    def _quality_in_range(cls, value: int) -> int:
        """Reject a recall quality outside the SM-2 ``0..5`` range."""
        if not (MIN_QUALITY <= value <= MAX_QUALITY):
            raise ValueError(f"quality must be in {MIN_QUALITY}..{MAX_QUALITY}.")
        return value


class EnqueueReviewRequest(BaseModel):
    """A request to add a notion to the spaced-repetition queue, due immediately.

    Unlike :class:`ReviewRequest` this carries no recall rating: the notion is
    seeded at the SM-2 defaults with ``due_at`` set to "now" so it surfaces in
    the due queue straight away, ready for its first rating.
    """

    student_id: str
    notion: str


class ReviewSchedule(BaseModel):
    """The spaced-repetition schedule of a notion after a recall."""

    notion: str
    ease: float
    interval_days: int
    due_at: str


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    """Readiness probe: report whether the service can serve traffic.

    Distinct from ``/health`` (liveness): readiness reflects that startup wiring
    completed, primarily that the database engine is bound. It performs a light,
    dependency-free check (no LLM, no network) so it is safe to poll frequently
    from an orchestrator. Returns 200 with ``{"status": "ready"}`` when the
    engine is configured, otherwise 503 with ``{"status": "not ready"}``.
    """
    if _engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready: database engine is not configured.",
        )
    return {"status": "ready"}


@app.get("/config")
def public_config() -> dict[str, bool]:
    """Expose non-sensitive server flags the frontend needs before authenticating.

    Fully open (no API key, no bearer token), like ``/health``: the frontend must
    be able to learn whether login is mandatory *before* the user has a token, so
    it can decide to show a blocking login gate. Currently returns only
    ``{"require_auth": bool}`` — whether every data endpoint requires a valid
    bearer token and enforces per-user student ownership.
    """
    return {"require_auth": get_settings().require_auth}


@app.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def auth_register(request: RegisterRequest) -> UserOut:
    """Create a new account from an email and password.

    The password is hashed with bcrypt before storage. Returns 201 with the
    minimal user info on success, 409 when the email is already registered, and
    422 on invalid input. This route is additive and does not affect the
    existing endpoints or the ``X-API-Key`` guard.
    """
    return register_user(request)


@app.post("/auth/login", response_model=TokenResponse)
def auth_login(request: LoginRequest) -> TokenResponse:
    """Verify credentials and return a signed bearer access token.

    Returns ``{access_token, token_type}`` on success or 401 on bad credentials
    (same message for unknown email and wrong password).
    """
    return login_user(request)


@app.get("/auth/me", response_model=UserOut)
def auth_me(current_user: UserOut = CurrentUser) -> UserOut:
    """Return the currently authenticated user.

    Protected by ``get_current_user``: the request must carry a valid
    ``Authorization: Bearer <jwt>`` header, otherwise 401 is returned.
    """
    return current_user


@app.get("/me/students", response_model=list[StudentOut])
def my_students(current_user: UserOut = CurrentUser) -> list[dict[str, Any]]:
    """List the student identities owned by the authenticated caller.

    Protected by ``get_current_user``: the request must carry a valid bearer
    token, otherwise 401 is returned. Only students linked to this user are
    returned, so a caller never sees another account's data or the anonymous,
    unlinked students. The list is newest-first.
    """
    with get_session(_engine) as session:
        rows = session.scalars(
            select(Student)
            .where(Student.user_id == current_user.id)
            .order_by(Student.created_at.desc(), Student.id.desc())
        )
        return [
            {
                "id": row.id,
                "external_id": row.external_id,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
def ask(request: AskRequest, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Answer a question grounded in the course, or refuse if uncovered.

    The question and the assistant's answer are persisted as conversation
    history for the student. When the request carries a valid bearer token, the
    student is linked to that account so the turns become the user's own.
    """
    result = answer(
        request.question,
        k=request.k,
        course=request.course,
        chapter=request.chapter,
        owner=request.student_id,
        language=request.language,
    )
    with get_session(_engine) as session:
        student = _resolve_student(session, request.student_id, user)
        thread_id = _resolve_session_id(session, student.id, request.session_id)
        add_message(
            session,
            student_id=student.id,
            role="user",
            content=request.question,
            session_id=thread_id,
        )
        add_message(
            session,
            student_id=student.id,
            role="assistant",
            content=result["answer"],
            session_id=thread_id,
        )
    return {
        "answer": result["answer"],
        "refused": result["refused"],
        "sources": result["sources"],
        "citations": result.get("citations", []),
    }


def _stream_ask_events(request: AskRequest, user: UserOut | None = None) -> Iterator[str]:
    """Serialize ``stream_answer`` as Server-Sent Events and persist on completion.

    Each item from the generator is emitted as one SSE ``data:`` line carrying a
    JSON object: ``{"type": "token", "text": ...}`` for each delta, then a final
    ``{"type": "sources", "sources": [...], "refused": ...}`` event. Once the
    stream ends, the question and the fully assembled assistant answer are
    persisted as conversation history, exactly like ``/ask``.
    """
    final_answer = REFUSAL_FALLBACK
    for event in stream_answer(
        request.question,
        k=request.k,
        course=request.course,
        chapter=request.chapter,
        owner=request.student_id,
        language=request.language,
    ):
        if event.get("type") == "sources":
            final_answer = event.get("answer", final_answer)
            payload = {
                "type": "sources",
                "sources": event.get("sources", []),
                "citations": event.get("citations", []),
                "refused": event.get("refused", False),
                # Forward the cleaned final answer so the client can replace the
                # raw token buffer (which may still show a trailing refusal the
                # model wrongly appended) with the server-cleaned text.
                "answer": final_answer,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        else:
            yield f"data: {json.dumps(event)}\n\n"

    with get_session(_engine) as session:
        student = _resolve_student(session, request.student_id, user)
        thread_id = _resolve_session_id(session, student.id, request.session_id)
        add_message(
            session,
            student_id=student.id,
            role="user",
            content=request.question,
            session_id=thread_id,
        )
        add_message(
            session,
            student_id=student.id,
            role="assistant",
            content=final_answer,
            session_id=thread_id,
        )


REFUSAL_FALLBACK = "This is not covered in the course material."


@app.post("/ask/stream", dependencies=[Depends(require_api_key)])
def ask_stream(request: AskRequest, user: UserOut | None = DataUser) -> StreamingResponse:
    """Stream a grounded answer token by token as Server-Sent Events.

    Mirrors ``/ask`` (same request model, auth and history persistence, and
    optional ownership linking) but returns a ``text/event-stream`` response:
    token deltas arrive first, then a final sources/refusal event. ``/ask`` stays
    available for non-streaming clients.
    """
    # Resolve (and, in require_auth mode, enforce ownership of) the student up
    # front so a foreign student is rejected with 403 *before* any bytes stream,
    # rather than after the answer has already been emitted. The generator
    # re-resolves at the end to persist the turn; by then the student is owned,
    # so that call is a no-op link.
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    return StreamingResponse(
        _stream_ask_events(request, user),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


NOTHING_TO_REEXPLAIN = "There is no previous answer to re-explain yet. Ask a question first."


def _last_tutor_answer(history: list[dict[str, str]]) -> str | None:
    """Return the most recent tutor turn's content, or None when there is none."""
    for turn in reversed(history):
        if turn.get("role") == "tutor" and turn.get("content"):
            return turn["content"]
    return None


@app.post("/reexplain", response_model=ReexplainResponse, dependencies=[Depends(require_api_key)])
def reexplain_answer(request: ReexplainRequest, user: UserOut | None = DataUser) -> dict[str, str]:
    """Rephrase the student's last tutor answer at the requested level.

    The recent conversation is rebuilt from the database and handed to the
    ``reexplain`` node, which reformulates the last grounded explanation without
    running retrieval again. The new explanation is persisted as an assistant
    turn so the conversation stays continuous. When the student has no prior
    answer, a friendly note is returned instead of crashing. In require_auth mode
    the student must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, request.student_id, user)
        if student is None:
            return {"answer": NOTHING_TO_REEXPLAIN}
        history = to_history(recent_messages(session, student.id))
        if _last_tutor_answer(history) is None:
            return {"answer": NOTHING_TO_REEXPLAIN}
        state: TutorState = {
            "student_id": request.student_id,
            "message": "Please re-explain that.",
            "level": request.level,
            "history": history,
        }
        rephrased = reexplain(state).get("answer", "")
        add_message(session, student_id=student.id, role="assistant", content=rephrased)
    return {"answer": rephrased}


def _reexplain_state(request: ReexplainRequest) -> TutorState | None:
    """Rebuild the re-explain state from stored history, or None when there is none.

    Returns None when the student is unknown or has no prior tutor answer, so the
    caller can surface the friendly ``NOTHING_TO_REEXPLAIN`` note instead of
    calling the model.
    """
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == request.student_id))
        if student is None:
            return None
        history = to_history(recent_messages(session, student.id))
        if _last_tutor_answer(history) is None:
            return None
        return {
            "student_id": request.student_id,
            "message": "Please re-explain that.",
            "level": request.level,
            "history": history,
        }


def _stream_reexplain_events(request: ReexplainRequest) -> Iterator[str]:
    """Serialize ``stream_reexplain`` as Server-Sent Events and persist on completion.

    Mirrors ``/ask/stream`` but token-only: no retrieval, so no "retrieving"
    stage and no sources event. When there is nothing to re-explain, the friendly
    note is emitted as a single token then a ``done`` event. Otherwise token
    deltas stream, then a final ``{"type": "done", "answer": ...}`` event, and the
    assembled re-explanation is persisted as an assistant turn.
    """
    state = _reexplain_state(request)
    if state is None:
        yield f"data: {json.dumps({'type': 'token', 'text': NOTHING_TO_REEXPLAIN})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'answer': NOTHING_TO_REEXPLAIN})}\n\n"
        return

    final_answer = ""
    for event in stream_reexplain(state):
        if event.get("type") == "done":
            final_answer = event.get("answer", "")
        yield f"data: {json.dumps(event)}\n\n"

    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == request.student_id))
        if student is not None:
            add_message(session, student_id=student.id, role="assistant", content=final_answer)


@app.post("/reexplain/stream", dependencies=[Depends(require_api_key)])
def reexplain_stream(request: ReexplainRequest) -> StreamingResponse:
    """Stream a re-explanation of the last tutor answer as Server-Sent Events.

    Mirrors ``/reexplain`` (same request model, auth and history persistence) but
    returns a ``text/event-stream`` response so the re-explanation types out.
    ``/reexplain`` stays available for non-streaming clients.
    """
    return StreamingResponse(
        _stream_reexplain_events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/exercise", response_model=ExerciseResponse, dependencies=[Depends(require_api_key)])
def exercise(request: ExerciseRequest, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Generate a course-grounded exercise on the requested notion.

    The reference solution stays server-side and is never returned. The student
    is ensured to exist (and linked to the caller when authenticated); exercise
    persistence is owned by the agent node, which needs the ``student_id`` to
    store the exercise. The persisted exercise id is surfaced so a later
    ``/grade`` call can link the grade back to it.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    state = generate(
        {
            "message": request.notion,
            "student_id": request.student_id,
            "course": request.course,
            "chapter": request.chapter,
            "language": request.language,
        }
    )
    # generate always populates "exercise" (a built exercise or a refusal).
    built = state.get("exercise")
    assert built is not None
    # Record the generated exercise as an activity turn so it shows in history
    # next to the Q&A. The activity content is the student's request (the typed
    # notion), so the history card shows the ask; the full problem/solution stays
    # behind the "Show details" fetch (GET /exercise/{id}/review). Skip on
    # refusal: an uncovered notion produces no activity.
    if not built["refused"]:
        _record_activity(
            request.student_id,
            user,
            request.session_id,
            role=ROLE_EXERCISE,
            content=request.notion,
            ref_id=built.get("id"),
        )
    return {"problem": built["problem"], "refused": built["refused"], "id": built.get("id")}


@app.post("/grade", response_model=GradeResponse, dependencies=[Depends(require_api_key)])
def grade_answer(request: GradeRequest, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Grade the student's answer, optionally against a prior exercise.

    The student is ensured to exist (and linked to the caller when
    authenticated); grade persistence is owned by the agent node, which needs the
    ``student_id`` (and the exercise's id) to link the grade to its exercise.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    state: TutorState = {
        "message": request.message,
        "student_id": request.student_id,
        "rigor": request.rigor,
    }
    if request.exercise is not None:
        state["exercise"] = request.exercise
    # grade always populates "grade" with the judge's verdict.
    verdict = grade(state).get("grade")
    assert verdict is not None
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


@app.post("/quiz", response_model=QuizResponse, dependencies=[Depends(require_api_key)])
def quiz(request: QuizRequest, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Generate a course-grounded quiz of ``n`` questions on the requested notion.

    Reference solutions stay server-side and are never returned: each question is
    surfaced as ``{id, problem}`` only. The student is ensured to exist (and
    linked to the caller when authenticated); quiz persistence is owned by the
    quiz node, which needs the ``student_id`` to store the quiz and its questions.
    A refusal (empty ``questions``) is returned when the course does not cover the
    notion.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    result = generate_quiz(
        request.notion,
        request.n,
        request.student_id,
        course=request.course,
        chapter=request.chapter,
        language=request.language,
    )
    # Record a concise activity turn (the notion + question count), never the full
    # quiz JSON. Skip on refusal: an uncovered notion produces no questions.
    if not result["refused"] and result["questions"]:
        count = len(result["questions"])
        summary = f"{result['notion']} ({count} question{'s' if count != 1 else ''})"
        _record_activity(
            request.student_id,
            user,
            request.session_id,
            role=ROLE_QUIZ,
            content=summary,
            ref_id=result.get("quiz_id"),
        )
    return result


@app.post(
    "/quiz/{quiz_id}/grade",
    response_model=GradeResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_grade(
    quiz_id: int, request: QuizGradeRequest, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Grade one quiz answer against the question's stored reference solution.

    The reference solution is never sent by the client: it is loaded server-side
    from the persisted quiz question. The student is ensured to exist (and linked
    to the caller when authenticated). The verdict is persisted as a grade linked
    to the question. An unknown question (or one not belonging to ``quiz_id``)
    yields 404.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    verdict = grade_quiz_answer(
        quiz_id, request.question_id, request.answer, request.student_id, request.rigor
    )
    if verdict is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz question not found.",
        )
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


@app.post(
    "/quiz/{quiz_id}/grade-all",
    response_model=QuizSummaryResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_grade_all(
    quiz_id: int, request: QuizGradeAllRequest, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Grade every answered question of a quiz at once and return a final score.

    Each answer is graded against its question's stored reference solution (loaded
    server-side, never sent by the client) and every verdict is persisted, exactly
    like one-by-one grading. The response carries the average score, the per-
    question verdicts, and a short study recommendation drawn from all the feedback
    in the language of the student's answers. The student is ensured to exist (and
    linked to the caller when authenticated). Questions that cannot be resolved are
    skipped rather than failing the whole request.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    answers = [{"question_id": a.question_id, "answer": a.answer} for a in request.answers]
    return summarize_quiz(quiz_id, answers, request.student_id, request.rigor)


@app.get(
    "/exercise/{exercise_id}/review",
    response_model=ExerciseReviewResponse,
    dependencies=[Depends(require_api_key)],
)
def exercise_review(
    exercise_id: int, student_id: str, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Return a generated exercise's full content for after-the-fact review.

    Unlike ``/exercise``, the reference solution is returned: review happens once
    the exercise is done, so the student is meant to see the model answer. The
    latest grade on the exercise (if any) is included so the student can see their
    answer, score and feedback. Ownership is enforced: the exercise must belong to
    ``student_id`` and, when authenticated, that student must belong to the caller
    (403 otherwise). An unknown or unowned exercise yields 404.
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        ex = None
        if student is not None:
            ex = session.scalar(
                select(Exercise).where(
                    Exercise.id == exercise_id, Exercise.student_id == student.id
                )
            )
        if ex is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Exercise not found for this student.",
            )
        latest = session.scalar(
            select(Grade)
            .where(Grade.exercise_id == ex.id)
            .order_by(Grade.created_at.desc(), Grade.id.desc())
        )
        grade_payload = None
        if latest is not None:
            grade_payload = {
                "answer": latest.answer,
                "score": latest.score,
                "feedback": latest.feedback,
                "created_at": latest.created_at.isoformat() if latest.created_at else "",
            }
        return {
            "problem": ex.problem,
            "reference_solution": ex.reference_solution,
            "grade": grade_payload,
        }


@app.get(
    "/quiz/{quiz_id}/review",
    response_model=QuizReviewResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_review(quiz_id: int, student_id: str, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Return a quiz's full content for after-the-fact review.

    Unlike ``/quiz``, each question's reference solution is returned, together
    with the student's latest answer, score and feedback per question (``None``
    when unanswered). Questions are ordered by position. Ownership is enforced:
    the quiz must belong to ``student_id`` and, when authenticated, that student
    must belong to the caller (403 otherwise). An unknown or unowned quiz yields
    404.
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        quiz_row = None
        if student is not None:
            quiz_row = session.scalar(
                select(Quiz).where(Quiz.id == quiz_id, Quiz.student_id == student.id)
            )
        if quiz_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quiz not found for this student.",
            )
        questions = session.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz_row.id)
            .order_by(QuizQuestion.position.asc(), QuizQuestion.id.asc())
        )
        reviewed: list[dict[str, Any]] = []
        for q in questions:
            latest = session.scalar(
                select(Grade)
                .where(Grade.quiz_question_id == q.id)
                .order_by(Grade.created_at.desc(), Grade.id.desc())
            )
            reviewed.append(
                {
                    "position": q.position,
                    "problem": q.problem,
                    "reference_solution": q.reference_solution,
                    "answer": latest.answer if latest is not None else None,
                    "score": latest.score if latest is not None else None,
                    "feedback": latest.feedback if latest is not None else None,
                }
            )
        return {"notion": quiz_row.notion, "questions": reviewed}


@app.get(
    "/courses",
    response_model=CoursesResponse,
    dependencies=[Depends(require_api_key)],
)
def courses(student_id: str | None = None, user: UserOut | None = DataUser) -> dict[str, list[str]]:
    """List the distinct courses currently indexed in Qdrant.

    Lets a client discover the available courses dynamically (e.g. to populate a
    picker) instead of hardcoding them. When ``student_id`` is given the list is
    scoped to that account's own courses plus the owner-less (shared/legacy)
    corpus; without it the whole collection is listed (unchanged). Returns an
    empty list when nothing is indexed yet; it never reaches the LLM and runs no
    retrieval.
    """
    owner = _scoped_read_owner(student_id, user)
    return {"courses": list_courses(owner=owner)}


@app.get(
    "/documents",
    response_model=list[DocumentCourse],
    dependencies=[Depends(require_api_key)],
)
def documents(
    student_id: str | None = None, user: UserOut | None = DataUser
) -> list[dict[str, Any]]:
    """Return the indexed material organized by course and chapter.

    Lets a client show what is indexed (and how much) so a user can manage it.
    The shape is ``[{course, total_pages, chapters: [{chapter, pages}]}]`` with a
    ``null`` chapter for material indexed without one. When ``student_id`` is
    given the inventory is scoped to that account's own material plus the
    owner-less (shared/legacy) corpus; without it everything is listed
    (unchanged). Returns an empty list when nothing is indexed yet; it never
    reaches the LLM and runs no retrieval.
    """
    owner = _scoped_read_owner(student_id, user)
    return list_documents(owner=owner)


@app.post(
    "/documents/upload",
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    course: Annotated[str, Form()],
    chapter: Annotated[str | None, Form()] = None,
    student_id: Annotated[str | None, Form()] = None,
    user: UserOut | None = DataUser,
) -> dict[str, str]:
    """Start ingesting an uploaded file as a background job and return its id.

    The original file is stored under ``uploads/<course>/`` so it can be re-opened
    later, then ingested incrementally on a daemon thread: ``.md``/``.txt`` via the
    prose loader, anything else via the math-aware PDF vision path. The request
    returns ``{"job_id": ...}`` immediately (HTTP 202) instead of streaming, so
    ingestion is not tied to the request lifetime — a browser refresh or
    navigation no longer aborts the ingest. The client polls
    ``GET /documents/jobs/{job_id}`` to follow (or, after a refresh, re-attach to)
    progress; the job record carries the same ``start``/``progress``/``done``/
    ``error`` shape as ``stream_ingest`` plus a ``status`` lifecycle field.

    Each document is scoped by its own identity, so a second file in the same
    course indexes independently; only re-uploading the same document skips
    already-indexed pages (never re-paying the vision model), and each batch is
    indexed as it is extracted, so a failure keeps the pages done so far.

    A plain daemon thread is used deliberately: FastAPI ``BackgroundTasks`` run
    within the request scope (defeating the purpose), and ``stream_ingest`` is a
    blocking, synchronous generator so it cannot run on the event loop. The job
    registry is in-process — see the multi-worker caveat in ``core.jobs``.
    """
    normalized_chapter = chapter.strip() if chapter and chapter.strip() else None
    # Resolve (and, when authenticated, enforce ownership of) the uploader so the
    # material is stamped with their owner id and scoped to their account. When no
    # student_id is sent (e.g. CLI-style callers) the upload stays owner-less
    # (shared/legacy), preserving the previous behaviour.
    owner: str | None = None
    if student_id is not None:
        with get_session(_engine) as session:
            _resolve_student(session, student_id, user)
        owner = student_id
    contents = await file.read()
    # Persist the original so the user can re-open the intact file later; ingest
    # from that stored path (its extension drives prose/PDF routing).
    stored_path = save_upload(contents, course, file.filename or "document")
    job_id = create_job(course, normalized_chapter, os.path.basename(stored_path))

    def run() -> None:
        """Drive the (blocking) ingest, mirroring each event into the job store."""
        try:
            for event in stream_ingest(stored_path, course, normalized_chapter, owner=owner):
                update_job(job_id, event)
                if event.get("type") == "error":
                    # stream_ingest reports a failed batch as an error event then
                    # returns; reflect it as a terminal status.
                    update_job(job_id, {"status": "error"})
                    return
            update_job(job_id, {"status": "done"})
        except Exception as exc:  # pragma: no cover - defensive; ingest guards itself
            update_job(job_id, {"status": "error", "type": "error", "message": str(exc)})

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/documents/jobs", dependencies=[Depends(require_api_key)])
def document_jobs() -> list[dict[str, Any]]:
    """List the current (running and recently finished) ingestion jobs."""
    return list_jobs()


@app.get("/documents/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def document_job(job_id: str) -> dict[str, Any]:
    """Return one ingestion job's record, or 404 if unknown or already pruned."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@app.get("/documents/file", dependencies=[Depends(require_api_key)])
def document_file(course: str, name: str) -> FileResponse:
    """Serve a stored original file so the user can re-open it intact.

    ``course`` and ``name`` identify a file previously saved by an upload. The
    path is resolved inside the course's upload directory with a traversal guard;
    an unknown file yields 404.
    """
    path = stored_file_path(course, name)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    return FileResponse(path, filename=os.path.basename(path))


@app.delete(
    "/documents",
    response_model=DocumentDeleteResponse,
    dependencies=[Depends(require_api_key)],
)
def remove_documents(
    course: str,
    chapter: str | None = None,
    student_id: str | None = None,
    user: UserOut | None = DataUser,
) -> dict[str, int]:
    """Delete a course's indexed points, optionally narrowed to one chapter.

    ``course`` is required; ``chapter`` (a query parameter) restricts the deletion
    to a single chapter when given. When ``student_id`` is given the deletion is
    scoped to that account's OWN points only (never the owner-less shared corpus
    or another account's material); the student is resolved and ownership enforced
    exactly as elsewhere. Without a ``student_id`` the deletion is unscoped
    (unchanged). Returns how many points were removed. A missing collection or an
    unknown course yields ``{"deleted": 0}`` rather than an error; it never
    reaches the LLM and runs no retrieval.
    """
    owner: str | None = None
    if student_id is not None:
        with get_session(_engine) as session:
            _resolve_student(session, student_id, user)
        owner = student_id
    return {"deleted": delete_documents(course, chapter, owner)}


@app.get(
    "/source/{chunk_id}",
    response_model=SourceResponse,
    dependencies=[Depends(require_api_key)],
)
def source(chunk_id: str) -> dict[str, Any]:
    """Return a cited source chunk's full text and citation metadata.

    Lets a client resolve a citation (the chunk id surfaced with an answer) into
    the underlying course excerpt, so a UI can show what an answer was grounded
    in. Yields 404 when the id is unknown or the collection is missing; it never
    reaches the LLM and runs no retrieval.
    """
    chunk = get_source(chunk_id)
    if chunk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source chunk not found.",
        )
    return chunk


@app.get(
    "/history/{student_id}",
    response_model=list[HistoryItem],
    dependencies=[Depends(require_api_key)],
)
def history(
    student_id: str, limit: int = 20, user: UserOut | None = DataUser
) -> list[dict[str, Any]]:
    """Return the student's most recent turns in chronological order.

    An unknown student yields an empty history rather than an error. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return []
        rows = recent_messages(session, student.id, limit=limit)
        return [
            {
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "ref_id": row.ref_id,
            }
            for row in rows
        ]


@app.delete(
    "/history/{student_id}",
    dependencies=[Depends(require_api_key)],
)
def clear_history(
    student_id: str, session_id: int | None = None, user: UserOut | None = DataUser
) -> dict[str, int]:
    """Delete a student's conversation messages and report how many were removed.

    With ``session_id`` set, only that thread's messages are cleared (after
    verifying the thread belongs to the student); without it, every message of
    the student is deleted. An unknown student, or a thread that is not owned by
    the student, yields ``{"deleted": 0}`` rather than an error, mirroring the
    idempotent style of the other delete routes. In require_auth mode the student
    must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return {"deleted": 0}
        if session_id is not None:
            thread = session.scalar(
                select(SessionModel).where(
                    SessionModel.id == session_id, SessionModel.student_id == student.id
                )
            )
            if thread is None:
                return {"deleted": 0}
        deleted = delete_messages(session, student.id, session_id=session_id)
        return {"deleted": deleted}


@app.post(
    "/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_session(
    request: SessionCreateRequest, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Open a new conversation thread for a student.

    The student is ensured to exist (and linked to the caller when
    authenticated). Returns 201 with the new thread's id, title and creation
    time. This route is additive: the existing flat ``/history`` keeps working
    and threads are entirely opt-in.
    """
    with get_session(_engine) as session:
        student = _resolve_student(session, request.student_id, user)
        thread = SessionModel(student_id=student.id, title=request.title)
        session.add(thread)
        session.flush()
        return {
            "id": thread.id,
            "title": thread.title,
            "created_at": thread.created_at.isoformat() if thread.created_at else "",
        }


@app.get(
    "/sessions/{student_id}",
    response_model=list[SessionOut],
    dependencies=[Depends(require_api_key)],
)
def list_sessions(student_id: str, user: UserOut | None = DataUser) -> list[dict[str, Any]]:
    """List a student's conversation threads, newest first.

    An unknown student yields an empty list rather than an error. In require_auth
    mode the student must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return []
        rows = session.scalars(
            select(SessionModel)
            .where(SessionModel.student_id == student.id)
            .order_by(SessionModel.created_at.desc(), SessionModel.id.desc())
        )
        return [
            {
                "id": row.id,
                "title": row.title,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]


@app.get(
    "/sessions/{student_id}/{session_id}/messages",
    response_model=list[HistoryItem],
    dependencies=[Depends(require_api_key)],
)
def session_messages(
    student_id: str, session_id: int, user: UserOut | None = DataUser
) -> list[dict[str, Any]]:
    """Return the messages of one thread in chronological order.

    Yields 404 when the thread does not exist or does not belong to the student,
    so a caller can never read another student's thread. In require_auth mode the
    student must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        thread = None
        if student is not None:
            thread = session.scalar(
                select(SessionModel).where(
                    SessionModel.id == session_id, SessionModel.student_id == student.id
                )
            )
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found for this student.",
            )
        rows = session.scalars(
            select(MessageModel)
            .where(MessageModel.session_id == thread.id)
            .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
        )
        return [
            {
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "ref_id": row.ref_id,
            }
            for row in rows
        ]


@app.delete(
    "/sessions/{student_id}/{session_id}",
    dependencies=[Depends(require_api_key)],
)
def delete_session_route(
    student_id: str, session_id: int, user: UserOut | None = DataUser
) -> dict[str, bool]:
    """Delete a conversation thread together with its messages.

    The thread's messages are removed as well, so deleting a thread clears that
    conversation rather than leaving orphaned turns in the flat history. Yields
    404 when the thread does not exist or is not owned by the student. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        thread = None
        if student is not None:
            thread = session.scalar(
                select(SessionModel).where(
                    SessionModel.id == session_id, SessionModel.student_id == student.id
                )
            )
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found for this student.",
            )
        # Delete the thread's messages, then the thread row itself.
        delete_messages(session, thread.student_id, session_id=thread.id)
        session.delete(thread)
    return {"deleted": True}


@app.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def submit_feedback(request: FeedbackRequest, user: UserOut | None = DataUser) -> dict[str, int]:
    """Persist a student's thumbs up/down on a tutor answer.

    The student is ensured to exist (and linked to the caller when
    authenticated). The captured question/answer text makes the feedback
    self-contained so it can later feed offline evaluation. Returns 201 with the
    new row id; an invalid ``rating`` is rejected with 422 by request
    validation. This route reaches no LLM and runs no retrieval.
    """
    with get_session(_engine) as session:
        student = _resolve_student(session, request.student_id, user)
        row = Feedback(
            student_id=student.id,
            rating=request.rating,
            note=request.note,
            question=request.question,
            answer=request.answer,
        )
        session.add(row)
        session.flush()
        feedback_id = row.id
    return {"id": feedback_id}


@app.get(
    "/feedback/summary",
    response_model=FeedbackSummary,
    dependencies=[Depends(require_api_key)],
)
def feedback_summary(student_id: str, user: UserOut | None = DataUser) -> dict[str, int]:
    """Return thumbs up/down counts for a student.

    An unknown student yields zero counts rather than an error. Useful for a
    lightweight quality signal without exposing individual feedback rows. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return {"up": 0, "down": 0}
        up = session.scalar(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.student_id == student.id, Feedback.rating == 1)
        )
        down = session.scalar(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.student_id == student.id, Feedback.rating == -1)
        )
    return {"up": up or 0, "down": down or 0}


@app.post(
    "/reviews",
    response_model=ReviewSchedule,
    dependencies=[Depends(require_api_key)],
)
def record_review(request: ReviewRequest, user: UserOut | None = DataUser) -> dict[str, Any]:
    """Record a recall rating for a notion and return its updated schedule.

    The student is ensured to exist (and linked to the caller when
    authenticated). At most one review row exists per ``(student, notion)``: an
    existing row is updated in place, otherwise a fresh one is created. The SM-2
    step is applied by ``core.scheduling.schedule`` and ``due_at`` is computed
    from a timezone-aware "now" plus the new interval. An out-of-range
    ``quality`` is rejected with 422 by request validation. This route reaches no
    LLM and runs no retrieval.
    """
    now = datetime.now(UTC)
    with get_session(_engine) as session:
        student = _resolve_student(session, request.student_id, user)
        row = session.scalar(
            select(Review).where(Review.student_id == student.id, Review.notion == request.notion)
        )
        if row is None:
            # A fresh notion starts from the SM-2 defaults; the column defaults
            # only materialise on flush, so seed the values explicitly here.
            row = Review(
                student_id=student.id,
                notion=request.notion,
                ease=2.5,
                interval_days=0,
                repetitions=0,
            )
            session.add(row)

        state = schedule(
            ease=row.ease,
            interval_days=row.interval_days,
            repetitions=row.repetitions,
            quality=request.quality,
        )
        row.ease = state.ease
        row.interval_days = state.interval_days
        row.repetitions = state.repetitions
        row.last_reviewed = now
        due_at = now + timedelta(days=state.interval_days)
        row.due_at = due_at
        session.flush()

        return {
            "notion": row.notion,
            "ease": row.ease,
            "interval_days": row.interval_days,
            "due_at": due_at.isoformat(),
        }


@app.post(
    "/reviews/enqueue",
    response_model=ReviewSchedule,
    dependencies=[Depends(require_api_key)],
)
def enqueue_review(
    request: EnqueueReviewRequest, user: UserOut | None = DataUser
) -> dict[str, Any]:
    """Add a notion to the spaced-repetition queue, due immediately.

    The student is ensured to exist (and linked to the caller when
    authenticated). At most one review row exists per ``(student, notion)``: an
    existing row is reset to the SM-2 defaults rather than duplicated. No SM-2
    step is applied; ``due_at`` is set to "now" so the notion is due right away
    and appears in ``GET /reviews/due``, ready for its first rating. This route
    reaches no LLM and runs no retrieval.
    """
    now = datetime.now(UTC)
    with get_session(_engine) as session:
        student = _resolve_student(session, request.student_id, user)
        row = session.scalar(
            select(Review).where(Review.student_id == student.id, Review.notion == request.notion)
        )
        if row is None:
            row = Review(student_id=student.id, notion=request.notion)
            session.add(row)
        # Seed (or reset) the SM-2 state so the notion is due immediately.
        row.ease = 2.5
        row.interval_days = 0
        row.repetitions = 0
        row.last_reviewed = None
        row.due_at = now
        session.flush()

        return {
            "notion": row.notion,
            "ease": row.ease,
            "interval_days": row.interval_days,
            "due_at": now.isoformat(),
        }


@app.get(
    "/reviews/due",
    response_model=list[ReviewSchedule],
    dependencies=[Depends(require_api_key)],
)
def due_reviews(student_id: str, user: UserOut | None = DataUser) -> list[dict[str, Any]]:
    """List the student's notions due for review, soonest first.

    A notion is due when its ``due_at`` is at or before "now". Newly created
    rows default ``due_at`` to their creation time, so brand-new notions are due
    immediately and surface here too. An unknown student yields an empty list
    rather than an error. This route reaches no LLM and runs no retrieval. In
    require_auth mode the student must belong to the caller (403 otherwise).
    """
    now = datetime.now(UTC)
    with get_session(_engine) as session:
        student = _student_for_read(session, student_id, user)
        if student is None:
            return []
        rows = session.scalars(
            select(Review)
            .where(Review.student_id == student.id, Review.due_at <= now)
            .order_by(Review.due_at.asc(), Review.id.asc())
        )
        return [
            {
                "notion": row.notion,
                "ease": row.ease,
                "interval_days": row.interval_days,
                "due_at": row.due_at.isoformat() if row.due_at else "",
            }
            for row in rows
        ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)
