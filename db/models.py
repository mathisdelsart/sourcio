"""SQLAlchemy ORM models for the relational store.

Holds students, generated exercises with their reference solution, grades, and
conversation history. SQLAlchemy 2.0 declarative style (``Mapped`` /
``mapped_column``). The store is SQLite in development and PostgreSQL later; the
URL is the only thing that changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class User(Base):
    """A registered account that authenticates with a username and password.

    The password is never stored in clear text: only its bcrypt hash is kept.
    The ``username`` is a public pseudonym used both as the login identifier and
    the display name; it is unique first-come-first-served (uniqueness is enforced
    case-insensitively in the auth layer). A user may own zero or more ``Student``
    identities. The link is optional on the ``Student`` side, so anonymous,
    ``external_id``-keyed students created by the tutor endpoints without a
    logged-in caller remain unlinked and existing flows are unaffected.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique login identifier and display name (a pseudonym).
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Kept for backward compatibility only: this is a demo with username-only
    # auth, so no email is collected. Nullable so existing rows and every new
    # username-only registration stay valid.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # Redundant now that the username is the display name; kept as a harmless
    # nullable column so no data migration is needed. No longer read or written.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    students: Mapped[list[Student]] = relationship(back_populates="user")


class Student(Base):
    """A user revising their courses."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="students")
    exercises: Mapped[list[Exercise]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    grades: Mapped[list[Grade]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    quizzes: Mapped[list[Quiz]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Exercise(Base):
    """An exercise generated for a student, with its reference solution."""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    course: Mapped[str] = mapped_column(String(255))
    notion: Mapped[str] = mapped_column(String(255))
    problem: Mapped[str] = mapped_column(Text)
    reference_solution: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="exercises")
    grades: Mapped[list[Grade]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )


class Grade(Base):
    """A graded answer (LLM-as-a-Judge output).

    A grade links to the source it was marked against: either a standalone
    ``Exercise`` or a single ``QuizQuestion``. Exactly one of the two foreign
    keys is set; the other stays ``None``.
    """

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True, nullable=True
    )
    quiz_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    answer: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    exercise: Mapped[Exercise | None] = relationship(back_populates="grades")
    quiz_question: Mapped[QuizQuestion | None] = relationship(back_populates="grades")
    student: Mapped[Student] = relationship(back_populates="grades")


class Quiz(Base):
    """A multi-question quiz generated for a student on a single notion."""

    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    notion: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="quizzes")
    questions: Mapped[list[QuizQuestion]] = relationship(
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.position",
    )


class QuizQuestion(Base):
    """One grounded question of a quiz, with its server-side reference solution."""

    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    problem: Mapped[str] = mapped_column(Text)
    reference_solution: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")
    grades: Mapped[list[Grade]] = relationship(
        back_populates="quiz_question", cascade="all, delete-orphan"
    )


class Session(Base):
    """A named conversation thread grouping a student's messages.

    A student can hold several threads (e.g. one per topic). The ``title`` is
    optional so an untitled thread is valid. Messages reference a thread through
    a nullable ``Message.session_id``; existing, unthreaded messages stay valid
    with ``session_id = NULL``, so this model is purely additive.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(back_populates="session")


class Message(Base):
    """A single turn of conversation history (e.g. ``user`` or ``assistant``)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    # Optional id of the domain object an activity turn refers to (an exercise id
    # for ``role="exercise"``, a quiz id for ``role="quiz"``), so the history can
    # link back and fetch the full item for review. Nullable and unconstrained:
    # plain Q&A turns leave it ``None`` and it is not a foreign key so a deleted
    # exercise/quiz simply yields a 404 on review rather than breaking history.
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="messages")
    session: Mapped[Session | None] = relationship(back_populates="messages")


class Feedback(Base):
    """A student's thumbs up/down on a tutor answer, kept for later evaluation.

    The rating is ``1`` for thumbs up and ``-1`` for thumbs down. The question
    and answer text are captured verbatim so each row is self-contained and can
    feed offline evaluation without joining back to volatile conversation
    history. The optional ``note`` lets the student explain a thumbs down.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="feedback")


class Review(Base):
    """A spaced-repetition schedule for one notion a student is revising.

    Exactly one row exists per ``(student, notion)`` pair (enforced by a unique
    constraint): each recall rating upserts this row rather than appending a new
    one. The SM-2 state (``ease``, ``interval_days``, ``repetitions``) is updated
    by :func:`core.scheduling.schedule`, and ``due_at`` is the next moment the
    notion should be reviewed. ``last_reviewed`` is ``NULL`` until the first
    recall is recorded. This model is purely additive and does not touch any
    existing table.
    """

    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("student_id", "notion", name="uq_reviews_student_notion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    notion: Mapped[str] = mapped_column(Text)
    ease: Mapped[float] = mapped_column(Float, default=2.5, server_default=text("2.5"))
    interval_days: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    repetitions: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_reviewed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="reviews")


class IngestJob(Base):
    """A background document-ingestion job, persisted so it survives restarts.

    Ingesting a document runs on a daemon thread and can take minutes; the client
    polls to follow it and re-attaches after a page refresh. Keeping the record in
    the database instead of only in process memory means a server restart — common
    on free hosting tiers that sleep idle apps — no longer loses an in-flight job,
    so the client sees the real status instead of a spurious "reset". The full
    record is stored as JSON in ``data`` (the exact shape the API returns); a few
    columns are mirrored for ordering (``created_at``) and retention pruning
    (``finished_at``). Answer jobs stay in memory (they update per token, which
    would be far too write-heavy to persist) — see :mod:`core.jobs`.
    """

    __tablename__ = "ingest_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
