"""Engine and session helpers driven by ``Settings.database_url``.

The engine is created lazily (no connection at import time) so importing this
module never touches the database. Swapping SQLite for PostgreSQL is a matter of
changing ``database_url`` in the settings.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings
from db.models import Base, Exercise, Grade, Message, Student

# Bound on first use by ``get_session`` / ``configure_session_factory``.
SessionLocal = sessionmaker(class_=Session, expire_on_commit=False)


def _connect_args_for(database_url: str) -> dict:
    """Return driver ``connect_args`` appropriate for the given URL.

    SQLite needs ``check_same_thread=False`` so a connection can be shared across
    threads (the FastAPI app is multithreaded). This flag is SQLite-only and must
    not leak into other drivers, so it is applied only for ``sqlite`` URLs and an
    empty dict is returned for everything else (e.g. ``postgresql+psycopg://``).
    """
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def create_engine_from_settings(url: str | None = None) -> Engine:
    """Create an SQLAlchemy engine from the configured ``database_url``.

    Pass ``url`` to override the configured value (e.g. an in-memory database in
    tests). The engine is created but no connection is opened here. Driver
    ``connect_args`` are selected from the URL scheme so SQLite-only options are
    never passed to PostgreSQL (and vice versa).
    """
    database_url = url or get_settings().database_url
    return create_engine(database_url, future=True, connect_args=_connect_args_for(database_url))


def init_db(engine: Engine) -> None:
    """Create all tables on ``engine`` if they do not already exist."""
    Base.metadata.create_all(engine)


def configure_session_factory(engine: Engine) -> None:
    """Bind the module-level ``SessionLocal`` factory to ``engine``."""
    SessionLocal.configure(bind=engine)


@contextmanager
def get_session(engine: Engine | None = None) -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error.

    When ``engine`` is given, a session bound to it is used directly; otherwise
    the module-level ``SessionLocal`` factory is used (configure it first via
    ``configure_session_factory``).
    """
    session = SessionLocal(bind=engine) if engine is not None else SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_or_create_student(session: Session, external_id: str) -> Student:
    """Return the student with ``external_id``, creating one if needed.

    The new student is flushed so its ``id`` is available to callers that need
    to reference it (e.g. when persisting messages, exercises or grades).
    """
    student = session.scalar(select(Student).where(Student.external_id == external_id))
    if student is None:
        student = Student(external_id=external_id)
        session.add(student)
        session.flush()
    return student


def add_exercise(
    session: Session,
    *,
    student_id: int,
    course: str,
    notion: str,
    problem: str,
    reference_solution: str,
) -> Exercise:
    """Persist a generated exercise and return the flushed instance."""
    exercise = Exercise(
        student_id=student_id,
        course=course,
        notion=notion,
        problem=problem,
        reference_solution=reference_solution,
    )
    session.add(exercise)
    session.flush()
    return exercise


def add_grade(
    session: Session,
    *,
    exercise_id: int,
    student_id: int,
    answer: str,
    score: float,
    feedback: str,
) -> Grade:
    """Persist a grade for an exercise and return the flushed instance."""
    grade = Grade(
        exercise_id=exercise_id,
        student_id=student_id,
        answer=answer,
        score=score,
        feedback=feedback,
    )
    session.add(grade)
    session.flush()
    return grade


def add_message(session: Session, *, student_id: int, role: str, content: str) -> Message:
    """Append a conversation message and return the flushed instance."""
    message = Message(student_id=student_id, role=role, content=content)
    session.add(message)
    session.flush()
    return message


def recent_messages(session: Session, student_id: int, limit: int = 20) -> list[Message]:
    """Return the most recent messages for a student, oldest first.

    The newest ``limit`` messages are selected, then returned in chronological
    order so they can be replayed as conversation history.
    """
    from sqlalchemy import select

    stmt = (
        select(Message)
        .where(Message.student_id == student_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list(session.scalars(stmt))
    rows.reverse()
    return rows
