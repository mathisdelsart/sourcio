"""Optional, decoupled persistence for agent node outputs.

Nodes call into this module to durably store the exercises they generate and the
grades they produce, plus conversation turns. Persistence is best-effort and
fully optional: when no ``student_id`` is present, or no database is configured,
or the ``db`` package is unavailable, the helpers are no-ops and the node keeps
working without a store.

The session factory is injectable. By default it resolves a session through
``db.session`` (the module-level ``SessionLocal``, configured elsewhere at
startup); tests inject a factory bound to an in-memory SQLite engine. Keeping the
import of ``db`` lazy means importing the agent layer never requires SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

# A session factory is a zero-argument callable returning a context manager that
# yields a SQLAlchemy ``Session``.
SessionFactory = Callable[[], Any]

# Process-wide override. When set (e.g. by tests), it takes precedence over the
# default ``db.session`` resolution. ``None`` means "use the default".
_session_factory: SessionFactory | None = None


def set_session_factory(factory: SessionFactory | None) -> None:
    """Inject (or clear) the session factory used to persist node outputs.

    ``factory`` is a zero-argument callable returning a context manager that
    yields a SQLAlchemy ``Session``. Pass ``None`` to restore the default
    ``db.session`` resolution.
    """
    global _session_factory
    _session_factory = factory


@contextmanager
def _resolve_session() -> Iterator[Any | None]:
    """Yield a session to write through, or ``None`` when persistence is off.

    Resolution order:
    1. an injected factory (tests / explicit wiring);
    2. otherwise ``db.session.get_session`` using the configured engine.

    Any import or configuration error degrades to ``None`` so a missing or
    unconfigured database never breaks a node.
    """
    if _session_factory is not None:
        with _session_factory() as session:
            yield session
        return

    try:
        from db.session import get_session
    except Exception:
        yield None
        return

    try:
        with get_session() as session:
            yield session
    except Exception:
        # No engine bound / connection failure: skip persistence silently.
        yield None


def _student_id(session: Any, external_id: str) -> int:
    """Return the internal id of the student with ``external_id``, creating it."""
    from db.session import get_or_create_student

    return get_or_create_student(session, external_id).id


def persist_exercise(
    student_external_id: str | None,
    *,
    course: str,
    notion: str,
    problem: str,
    reference_solution: str,
) -> int | None:
    """Persist a generated exercise; return its id, or ``None`` if skipped.

    Skips silently when there is no ``student_external_id`` or no database is
    available, so the generate node works with or without a store.
    """
    if not student_external_id:
        return None

    from db.session import add_exercise

    with _resolve_session() as session:
        if session is None:
            return None
        student_id = _student_id(session, student_external_id)
        exercise = add_exercise(
            session,
            student_id=student_id,
            course=course,
            notion=notion,
            problem=problem,
            reference_solution=reference_solution,
        )
        return exercise.id


def persist_grade(
    student_external_id: str | None,
    *,
    exercise_id: int | None,
    answer: str,
    score: float,
    feedback: str,
) -> int | None:
    """Persist a grade; return its id, or ``None`` if skipped.

    A grade requires an exercise to reference. When ``exercise_id`` is unknown
    (the answer was graded without a stored exercise) persistence is skipped, as
    it is when there is no student or database.
    """
    if not student_external_id or exercise_id is None:
        return None

    from db.session import add_grade

    with _resolve_session() as session:
        if session is None:
            return None
        student_id = _student_id(session, student_external_id)
        grade = add_grade(
            session,
            exercise_id=exercise_id,
            student_id=student_id,
            answer=answer,
            score=score,
            feedback=feedback,
        )
        return grade.id
