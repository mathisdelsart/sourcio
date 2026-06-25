"""FastAPI application exposing the tutor endpoints.

Endpoints:
    GET  /health            health check
    POST /ask               answer a question, grounded in the course (explain path)
    POST /reexplain         rephrase the last tutor answer at a chosen level
    POST /exercise          generate an exercise (never returns the reference solution)
    POST /grade             grade a student's answer
    GET  /history/{id}      recent conversation turns for a student

The layer stays thin: each route delegates to the existing grounded functions
and graph nodes. No retrieval or prompting logic is reimplemented here. The API
is stateful: a ``student_id`` identifies the user (get-or-create), ``/ask`` turns
are persisted as conversation history, and ``/history`` replays them.
"""

import hmac
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select

from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.reexplain import reexplain
from agent.state import Level, TutorState, to_history
from core.answer import answer, stream_answer
from core.config import get_settings
from db.models import Student
from db.session import (
    add_message,
    configure_session_factory,
    create_engine_from_settings,
    get_or_create_student,
    get_session,
    init_db,
    recent_messages,
)

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
    """Initialize the database from the configured engine on startup."""
    if _engine is None:
        configure_engine(create_engine_from_settings())
    yield


app = FastAPI(
    title="grounded-rag",
    description="Course tutor grounded in your own material.",
    lifespan=lifespan,
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


class HistoryItem(BaseModel):
    """A single persisted conversation turn."""

    role: str
    content: str
    created_at: str


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
def ask(request: AskRequest) -> dict[str, Any]:
    """Answer a question grounded in the course, or refuse if uncovered.

    The question and the assistant's answer are persisted as conversation
    history for the student.
    """
    result = answer(request.question, k=request.k, course=request.course, chapter=request.chapter)
    with get_session(_engine) as session:
        student = get_or_create_student(session, request.student_id)
        add_message(session, student_id=student.id, role="user", content=request.question)
        add_message(session, student_id=student.id, role="assistant", content=result["answer"])
    return {
        "answer": result["answer"],
        "refused": result["refused"],
        "sources": result["sources"],
    }


def _stream_ask_events(request: AskRequest) -> Iterator[str]:
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
        student = get_or_create_student(session, request.student_id)
        add_message(session, student_id=student.id, role="user", content=request.question)
        add_message(session, student_id=student.id, role="assistant", content=final_answer)


REFUSAL_FALLBACK = "This is not covered in the course material."


@app.post("/ask/stream", dependencies=[Depends(require_api_key)])
def ask_stream(request: AskRequest) -> StreamingResponse:
    """Stream a grounded answer token by token as Server-Sent Events.

    Mirrors ``/ask`` (same request model, auth and history persistence) but
    returns a ``text/event-stream`` response: token deltas arrive first, then a
    final sources/refusal event. ``/ask`` stays available for non-streaming
    clients.
    """
    return StreamingResponse(
        _stream_ask_events(request),
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
def exercise(request: ExerciseRequest) -> dict[str, Any]:
    """Generate a course-grounded exercise on the requested notion.

    The reference solution stays server-side and is never returned. The student
    is ensured to exist; exercise persistence is owned by the agent node, which
    needs the ``student_id`` to store the exercise. The persisted exercise id is
    surfaced so a later ``/grade`` call can link the grade back to it.
    """
    with get_session(_engine) as session:
        get_or_create_student(session, request.student_id)
    state = generate({"message": request.notion, "student_id": request.student_id})
    # generate always populates "exercise" (a built exercise or a refusal).
    built = state.get("exercise")
    assert built is not None
    return {"problem": built["problem"], "refused": built["refused"], "id": built.get("id")}


@app.post("/grade", response_model=GradeResponse, dependencies=[Depends(require_api_key)])
def grade_answer(request: GradeRequest) -> dict[str, Any]:
    """Grade the student's answer, optionally against a prior exercise.

    The student is ensured to exist; grade persistence is owned by the agent
    node, which needs the ``student_id`` (and the exercise's id) to link the
    grade to its exercise.
    """
    with get_session(_engine) as session:
        get_or_create_student(session, request.student_id)
    state: TutorState = {"message": request.message, "student_id": request.student_id}
    if request.exercise is not None:
        state["exercise"] = request.exercise
    # grade always populates "grade" with the judge's verdict.
    verdict = grade(state).get("grade")
    assert verdict is not None
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)
