"""Relational persistence layer (SQLAlchemy ORM).

Stores students, exercises with their reference solution, grades, and
conversation history. Standalone for now; the agent layer will wire into it
later.
"""

from db.models import Base, Exercise, Grade, Message, Student
from db.session import (
    add_exercise,
    add_grade,
    add_message,
    configure_session_factory,
    create_engine_from_settings,
    get_session,
    init_db,
    recent_messages,
)

__all__ = [
    "Base",
    "Student",
    "Exercise",
    "Grade",
    "Message",
    "create_engine_from_settings",
    "init_db",
    "configure_session_factory",
    "get_session",
    "add_exercise",
    "add_grade",
    "add_message",
    "recent_messages",
]
