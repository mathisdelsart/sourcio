"""FastAPI application exposing the tutor endpoints.

Endpoints:
    GET  /health            health check
    POST /ask               answer a question, grounded in the course (explain path)
    POST /exercise          generate an exercise (never returns the reference solution)
    POST /grade             grade a student's answer
    GET  /history/{id}      recent conversation turns for a student

The layer stays thin: each route delegates to the existing grounded functions
and graph nodes. No retrieval or prompting logic is reimplemented here. The API
is stateful: a ``student_id`` identifies the user (get-or-create), ``/ask`` turns
are persisted as conversation history, and ``/history`` replays them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from agent.nodes.generate import generate
from agent.nodes.grade import grade
from answer import answer
from db.models import Student
from db.session import (
    add_message,
    configure_session_factory,
    create_engine_from_settings,
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


def _get_or_create_student(session: Session, student_id: str) -> Student:
    """Return the student with this external id, creating one if needed."""
    student = session.scalar(select(Student).where(Student.external_id == student_id))
    if student is None:
        student = Student(external_id=student_id)
        session.add(student)
        session.flush()
    return student


class AskRequest(BaseModel):
    """A question to answer from the course, on behalf of a student."""

    student_id: str
    question: str
    k: int = Field(default=5, ge=1)


class AskResponse(BaseModel):
    """A grounded answer, refused when the course does not cover the question."""

    answer: str
    refused: bool
    sources: list[str]


class ExerciseRequest(BaseModel):
    """A notion to build a practice exercise on, for a student."""

    student_id: str
    notion: str


class ExerciseResponse(BaseModel):
    """A course-grounded exercise. The reference solution is withheld."""

    problem: str
    refused: bool


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


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> dict[str, Any]:
    """Answer a question grounded in the course, or refuse if uncovered.

    The question and the assistant's answer are persisted as conversation
    history for the student.
    """
    result = answer(request.question, k=request.k)
    with get_session(_engine) as session:
        student = _get_or_create_student(session, request.student_id)
        add_message(session, student_id=student.id, role="user", content=request.question)
        add_message(session, student_id=student.id, role="assistant", content=result["answer"])
    return {
        "answer": result["answer"],
        "refused": result["refused"],
        "sources": result["sources"],
    }


@app.post("/exercise", response_model=ExerciseResponse)
def exercise(request: ExerciseRequest) -> dict[str, Any]:
    """Generate a course-grounded exercise on the requested notion.

    The reference solution stays server-side and is never returned. The student
    is ensured to exist; exercise persistence is owned by the agent node.
    """
    with get_session(_engine) as session:
        _get_or_create_student(session, request.student_id)
    state = generate({"message": request.notion})
    built = state["exercise"]
    return {"problem": built["problem"], "refused": built["refused"]}


@app.post("/grade", response_model=GradeResponse)
def grade_answer(request: GradeRequest) -> dict[str, Any]:
    """Grade the student's answer, optionally against a prior exercise.

    The student is ensured to exist; grade persistence is owned by the agent node.
    """
    with get_session(_engine) as session:
        _get_or_create_student(session, request.student_id)
    state: dict[str, Any] = {"message": request.message}
    if request.exercise is not None:
        state["exercise"] = request.exercise
    verdict = grade(state)["grade"]
    return {"score": verdict["score"], "feedback": verdict["feedback"]}


@app.get("/history/{student_id}", response_model=list[HistoryItem])
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
