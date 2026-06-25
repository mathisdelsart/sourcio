"""SQLAlchemy ORM models for the relational store.

Holds students, generated exercises with their reference solution, grades, and
conversation history. SQLAlchemy 2.0 declarative style (``Mapped`` /
``mapped_column``). The store is SQLite in development and PostgreSQL later; the
URL is the only thing that changes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class User(Base):
    """A registered account that can authenticate with email and password.

    The password is never stored in clear text: only its bcrypt hash is kept.
    A user may own zero or more ``Student`` identities. The link is optional on
    the ``Student`` side, so anonymous, ``external_id``-keyed students created by
    the tutor endpoints without a logged-in caller remain unlinked and existing
    flows are unaffected.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
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
