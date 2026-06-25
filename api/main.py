"""FastAPI application exposing the tutor endpoints.

Endpoints:
    GET  /health            health check
    POST /ask               answer a question, grounded in the course (explain path)
    POST /reexplain         rephrase the last tutor answer at a chosen level
    POST /exercise          generate an exercise (never returns the reference solution)
    POST /grade             grade a student's answer
    POST /quiz              generate a grounded multi-question quiz (no solutions)
    POST /quiz/{id}/grade   grade one quiz answer against its stored reference
    GET  /courses           list the distinct courses indexed in Qdrant
    GET  /source/{chunk_id} fetch a cited source chunk's text and metadata
    GET  /history/{id}      recent conversation turns for a student
    POST /sessions          open a named conversation thread for a student
    GET  /sessions/{id}     list a student's conversation threads
    GET  /sessions/{id}/{sid}/messages  messages of one thread (chronological)
    POST /feedback          record a thumbs up/down on a tutor answer
    GET  /feedback/summary  thumbs up/down counts for a student
    POST /reviews           record a recall rating and reschedule a notion (SM-2)
    GET  /reviews/due       notions due for spaced-repetition review

The layer stays thin: each route delegates to the existing grounded functions
and graph nodes. No retrieval or prompting logic is reimplemented here. The API
is stateful: a ``student_id`` identifies the user (get-or-create), ``/ask`` turns
are persisted as conversation history, and ``/history`` replays them.
"""

import hmac
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Engine, func, select

from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.quiz import generate_quiz, grade_quiz_answer
from agent.nodes.reexplain import reexplain
from agent.state import Level, TutorState, to_history
from api.auth import (
    CurrentUser,
    LoginRequest,
    OptionalUser,
    RegisterRequest,
    TokenResponse,
    UserOut,
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
from core.scheduling import MAX_QUALITY, MIN_QUALITY, schedule
from core.sources import get_source
from db.models import Feedback, Review, Student
from db.models import Message as MessageModel
from db.models import Session as SessionModel
from db.session import (
    add_message,
    configure_session_factory,
    create_engine_from_settings,
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
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
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


def _resolve_student(session: Any, external_id: str, user: UserOut | None) -> Student:
    """Get-or-create the student and, when authenticated, claim ownership.

    Anonymous requests (``user is None``) behave exactly as before: the student
    is keyed solely by ``external_id`` and left unlinked. When a valid bearer
    token is present, the resolved student is associated with that user if it has
    no owner yet (``user_id`` stays untouched once set, so a student already
    owned by someone else is never re-claimed). This is purely additive: it never
    changes the answer, only the ownership link.
    """
    student = get_or_create_student(session, external_id)
    if user is not None and student.user_id is None:
        student.user_id = user.id
        session.flush()
    return student


def _resolve_session_id(session: Any, student_id: int, session_id: int | None) -> int | None:
    """Validate that ``session_id`` is a thread owned by ``student_id``.

    Returns the id unchanged when it names one of the student's threads. When it
    is ``None`` (the default), the turn stays unthreaded and ``None`` is
    returned, so existing behaviour is preserved. An id that does not belong to
    the student yields 404 rather than silently mis-attaching the message.
    """
    if session_id is None:
        return None
    thread = session.scalar(
        select(SessionModel).where(
            SessionModel.id == session_id, SessionModel.student_id == student_id
        )
    )
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found for this student.",
        )
    return session_id


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


class AskResponse(BaseModel):
    """A grounded answer, refused when the course does not cover the question."""

    answer: str
    refused: bool
    sources: list[str]


class ReexplainRequest(BaseModel):
    """A request to rephrase the student's last tutor answer at a given level."""

    student_id: str
    level: Level = "beginner"


class ReexplainResponse(BaseModel):
    """The rephrased explanation (or a friendly note when nothing to re-explain)."""

    answer: str


class ExerciseRequest(BaseModel):
    """A notion to build a practice exercise on, for a student."""

    student_id: str
    notion: str


class ExerciseResponse(BaseModel):
    """A course-grounded exercise. The reference solution is withheld."""

    problem: str
    refused: bool
    id: int | None = None


class GradeRequest(BaseModel):
    """A student's answer to grade, optionally against a prior exercise."""

    student_id: str
    message: str
    exercise: dict[str, Any] | None = None


class GradeResponse(BaseModel):
    """The judge's verdict on the student's answer."""

    score: int
    feedback: str


class QuizRequest(BaseModel):
    """A notion to build a multi-question quiz on, for a student.

    ``n`` is the desired number of questions; it is clamped to a small range so a
    request can never ask for an unbounded quiz.
    """

    student_id: str
    notion: str
    n: int = Field(default=3, ge=1, le=10)


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
    """A student's answer to one quiz question, graded against its reference."""

    student_id: str
    question_id: int
    answer: str


class HistoryItem(BaseModel):
    """A single persisted conversation turn."""

    role: str
    content: str
    created_at: str


class CoursesResponse(BaseModel):
    """The distinct courses currently indexed in Qdrant, sorted."""

    courses: list[str]


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
def ask(request: AskRequest, user: UserOut | None = OptionalUser) -> dict[str, Any]:
    """Answer a question grounded in the course, or refuse if uncovered.

    The question and the assistant's answer are persisted as conversation
    history for the student. When the request carries a valid bearer token, the
    student is linked to that account so the turns become the user's own.
    """
    result = answer(request.question, k=request.k, course=request.course, chapter=request.chapter)
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
        request.question, k=request.k, course=request.course, chapter=request.chapter
    ):
        if event.get("type") == "sources":
            final_answer = event.get("answer", final_answer)
            payload = {
                "type": "sources",
                "sources": event.get("sources", []),
                "refused": event.get("refused", False),
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
def ask_stream(request: AskRequest, user: UserOut | None = OptionalUser) -> StreamingResponse:
    """Stream a grounded answer token by token as Server-Sent Events.

    Mirrors ``/ask`` (same request model, auth and history persistence, and
    optional ownership linking) but returns a ``text/event-stream`` response:
    token deltas arrive first, then a final sources/refusal event. ``/ask`` stays
    available for non-streaming clients.
    """
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
def reexplain_answer(request: ReexplainRequest) -> dict[str, str]:
    """Rephrase the student's last tutor answer at the requested level.

    The recent conversation is rebuilt from the database and handed to the
    ``reexplain`` node, which reformulates the last grounded explanation without
    running retrieval again. The new explanation is persisted as an assistant
    turn so the conversation stays continuous. When the student has no prior
    answer, a friendly note is returned instead of crashing.
    """
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == request.student_id))
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


@app.post("/exercise", response_model=ExerciseResponse, dependencies=[Depends(require_api_key)])
def exercise(request: ExerciseRequest, user: UserOut | None = OptionalUser) -> dict[str, Any]:
    """Generate a course-grounded exercise on the requested notion.

    The reference solution stays server-side and is never returned. The student
    is ensured to exist (and linked to the caller when authenticated); exercise
    persistence is owned by the agent node, which needs the ``student_id`` to
    store the exercise. The persisted exercise id is surfaced so a later
    ``/grade`` call can link the grade back to it.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    state = generate({"message": request.notion, "student_id": request.student_id})
    # generate always populates "exercise" (a built exercise or a refusal).
    built = state.get("exercise")
    assert built is not None
    return {"problem": built["problem"], "refused": built["refused"], "id": built.get("id")}


@app.post("/grade", response_model=GradeResponse, dependencies=[Depends(require_api_key)])
def grade_answer(request: GradeRequest, user: UserOut | None = OptionalUser) -> dict[str, Any]:
    """Grade the student's answer, optionally against a prior exercise.

    The student is ensured to exist (and linked to the caller when
    authenticated); grade persistence is owned by the agent node, which needs the
    ``student_id`` (and the exercise's id) to link the grade to its exercise.
    """
    with get_session(_engine) as session:
        _resolve_student(session, request.student_id, user)
    state: TutorState = {"message": request.message, "student_id": request.student_id}
    if request.exercise is not None:
        state["exercise"] = request.exercise
    # grade always populates "grade" with the judge's verdict.
    verdict = grade(state).get("grade")
    assert verdict is not None
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


@app.post("/quiz", response_model=QuizResponse, dependencies=[Depends(require_api_key)])
def quiz(request: QuizRequest, user: UserOut | None = OptionalUser) -> dict[str, Any]:
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
    return generate_quiz(request.notion, request.n, request.student_id)


@app.post(
    "/quiz/{quiz_id}/grade",
    response_model=GradeResponse,
    dependencies=[Depends(require_api_key)],
)
def quiz_grade(
    quiz_id: int, request: QuizGradeRequest, user: UserOut | None = OptionalUser
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
    verdict = grade_quiz_answer(quiz_id, request.question_id, request.answer, request.student_id)
    if verdict is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz question not found.",
        )
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


@app.get(
    "/courses",
    response_model=CoursesResponse,
    dependencies=[Depends(require_api_key)],
)
def courses() -> dict[str, list[str]]:
    """List the distinct courses currently indexed in Qdrant.

    Lets a client discover the available courses dynamically (e.g. to populate a
    picker) instead of hardcoding them. Returns an empty list when nothing is
    indexed yet; it never reaches the LLM and runs no retrieval.
    """
    return {"courses": list_courses()}


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
def history(student_id: str, limit: int = 20) -> list[dict[str, str]]:
    """Return the student's most recent turns in chronological order.

    An unknown student yields an empty history rather than an error.
    """
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == student_id))
        if student is None:
            return []
        rows = recent_messages(session, student.id, limit=limit)
        return [
            {
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]


@app.post(
    "/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_session(
    request: SessionCreateRequest, user: UserOut | None = OptionalUser
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
def list_sessions(student_id: str) -> list[dict[str, Any]]:
    """List a student's conversation threads, newest first.

    An unknown student yields an empty list rather than an error.
    """
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == student_id))
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
def session_messages(student_id: str, session_id: int) -> list[dict[str, str]]:
    """Return the messages of one thread in chronological order.

    Yields 404 when the thread does not exist or does not belong to the student,
    so a caller can never read another student's thread.
    """
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == student_id))
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
            }
            for row in rows
        ]


@app.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def submit_feedback(
    request: FeedbackRequest, user: UserOut | None = OptionalUser
) -> dict[str, int]:
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
def feedback_summary(student_id: str) -> dict[str, int]:
    """Return thumbs up/down counts for a student.

    An unknown student yields zero counts rather than an error. Useful for a
    lightweight quality signal without exposing individual feedback rows.
    """
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == student_id))
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
def record_review(request: ReviewRequest, user: UserOut | None = OptionalUser) -> dict[str, Any]:
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


@app.get(
    "/reviews/due",
    response_model=list[ReviewSchedule],
    dependencies=[Depends(require_api_key)],
)
def due_reviews(student_id: str) -> list[dict[str, Any]]:
    """List the student's notions due for review, soonest first.

    A notion is due when its ``due_at`` is at or before "now". Newly created
    rows default ``due_at`` to their creation time, so brand-new notions are due
    immediately and surface here too. An unknown student yields an empty list
    rather than an error. This route reaches no LLM and runs no retrieval.
    """
    now = datetime.now(UTC)
    with get_session(_engine) as session:
        student = session.scalar(select(Student).where(Student.external_id == student_id))
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
