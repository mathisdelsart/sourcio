"""SQLAlchemy ORM models for the relational store.

Holds students, generated exercises with their reference solution, grades, and
conversation history. SQLAlchemy 2.0 declarative style (``Mapped`` /
``mapped_column``). The store is SQLite in development and PostgreSQL later; the
URL is the only thing that changes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Student(Base):
    """A user revising their courses."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    exercises: Mapped[list[Exercise]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    grades: Mapped[list[Grade]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    messages: Mapped[list[Message]] = relationship(
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
    """A graded answer for an exercise (LLM-as-a-Judge output)."""

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    answer: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    exercise: Mapped[Exercise] = relationship(back_populates="grades")
    student: Mapped[Student] = relationship(back_populates="grades")


class Message(Base):
    """A single turn of conversation history (e.g. ``user`` or ``assistant``)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped[Student] = relationship(back_populates="messages")
