"""Tests for the relational persistence layer.

An in-memory SQLite database is used; no network, no LLM provider is touched.
The module is skipped when the optional ``api`` extra (SQLAlchemy) is not
installed, so CI without extras collects cleanly.
"""

import pytest

pytest.importorskip("sqlalchemy")

from db import (  # noqa: E402
    Exercise,
    Grade,
    Message,
    Student,
    add_exercise,
    add_grade,
    add_message,
    create_engine_from_settings,
    get_session,
    init_db,
    recent_messages,
)


@pytest.fixture
def engine():
    """A fresh in-memory SQLite engine with tables created."""
    eng = create_engine_from_settings("sqlite:///:memory:")
    init_db(eng)
    return eng


def _make_student(session, external_id="student-1"):
    student = Student(external_id=external_id)
    session.add(student)
    session.flush()
    return student


def test_create_student(engine):
    with get_session(engine) as session:
        student = _make_student(session)
        assert student.id is not None
        assert student.created_at is not None


def test_exercise_with_reference_solution_round_trip(engine):
    with get_session(engine) as session:
        student = _make_student(session)
        exercise = add_exercise(
            session,
            student_id=student.id,
            course="Linear Algebra",
            notion="Eigenvalues",
            problem="Find the eigenvalues of [[2, 0], [0, 3]].",
            reference_solution="The eigenvalues are 2 and 3.",
        )
        exercise_id = exercise.id

    with get_session(engine) as session:
        stored = session.get(Exercise, exercise_id)
        assert stored is not None
        assert stored.reference_solution == "The eigenvalues are 2 and 3."
        assert stored.notion == "Eigenvalues"
        assert stored.student.external_id == "student-1"


def test_grade_references_exercise_and_student(engine):
    with get_session(engine) as session:
        student = _make_student(session)
        exercise = add_exercise(
            session,
            student_id=student.id,
            course="Calculus",
            notion="Derivatives",
            problem="Differentiate x^2.",
            reference_solution="2x",
        )
        grade = add_grade(
            session,
            exercise_id=exercise.id,
            student_id=student.id,
            answer="2x",
            score=1.0,
            feedback="Correct.",
        )
        grade_id = grade.id

    with get_session(engine) as session:
        stored = session.get(Grade, grade_id)
        assert stored is not None
        assert stored.score == 1.0
        assert stored.feedback == "Correct."
        assert stored.exercise.reference_solution == "2x"
        assert stored.student.external_id == "student-1"


def test_relationships_back_populate(engine):
    with get_session(engine) as session:
        student = _make_student(session)
        add_exercise(
            session,
            student_id=student.id,
            course="C",
            notion="N",
            problem="P",
            reference_solution="S",
        )
        session.flush()
        session.refresh(student)
        assert len(student.exercises) == 1
        assert student.exercises[0].course == "C"


def test_messages_read_back_ordered(engine):
    with get_session(engine) as session:
        student = _make_student(session)
        student_id = student.id
        for role, content in [
            ("user", "first"),
            ("assistant", "second"),
            ("user", "third"),
        ]:
            add_message(session, student_id=student_id, role=role, content=content)

    with get_session(engine) as session:
        history = recent_messages(session, student_id)
        assert [m.content for m in history] == ["first", "second", "third"]
        assert isinstance(history[0], Message)


def test_recent_messages_limit_keeps_newest_chronological(engine):
    with get_session(engine) as session:
        student = _make_student(session)
        student_id = student.id
        for i in range(5):
            add_message(session, student_id=student_id, role="user", content=f"m{i}")

    with get_session(engine) as session:
        history = recent_messages(session, student_id, limit=2)
        # The two newest, returned oldest-first.
        assert [m.content for m in history] == ["m3", "m4"]
