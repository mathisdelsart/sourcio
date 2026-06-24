"""Tests for the metrics dashboard pure helpers.

No network, no LLM provider and no Streamlit import: only the pure helpers from
``ui.metrics`` are exercised. The database part uses an in-memory SQLite engine
and is skipped when SQLAlchemy (the ``api`` extra) is not installed, so the
dev-only test run stays green.
"""

from __future__ import annotations

import json

import pytest

from ui.metrics import (
    DEFAULT_RESULTS_PATH,
    MetricCard,
    format_metric_cards,
    format_stats,
    gather_db_stats,
    load_default_metrics,
    load_metrics_file,
)

# --- format_metric_cards ----------------------------------------------------


def test_format_metric_cards_from_dict_renders_percentages():
    metrics = {
        "faithfulness_rate": 1.0,
        "relevance_rate": 0.9,
        "refusal_accuracy": 0.75,
        "retrieval_hit_rate": 0.5,
    }
    cards = format_metric_cards(metrics)
    assert [c.key for c in cards] == [
        "faithfulness_rate",
        "relevance_rate",
        "refusal_accuracy",
        "retrieval_hit_rate",
    ]
    displays = {c.key: c.display for c in cards}
    assert displays["faithfulness_rate"] == "100%"
    assert displays["relevance_rate"] == "90%"
    assert displays["refusal_accuracy"] == "75%"
    assert displays["retrieval_hit_rate"] == "50%"
    assert all(isinstance(c, MetricCard) for c in cards)


def test_format_metric_cards_handles_missing_metrics():
    cards = format_metric_cards({"faithfulness_rate": 1.0})
    by_key = {c.key: c for c in cards}
    assert by_key["faithfulness_rate"].value == 1.0
    assert by_key["relevance_rate"].value is None
    assert by_key["relevance_rate"].display == "n/a"


def test_format_metric_cards_empty_source():
    cards = format_metric_cards({})
    assert len(cards) == 4
    assert all(c.value is None and c.display == "n/a" for c in cards)


def test_format_metric_cards_none_source():
    cards = format_metric_cards(None)
    assert all(c.value is None for c in cards)


def test_format_metric_cards_ignores_bool_values():
    # A stray bool must not be coerced to 1.0/0.0 and shown as a percentage.
    cards = format_metric_cards({"faithfulness_rate": True})
    by_key = {c.key: c for c in cards}
    assert by_key["faithfulness_rate"].value is None


def test_format_metric_cards_from_metrics_like_object():
    class FakeMetrics:
        faithfulness_rate = 0.8
        relevance_rate = 1.0
        refusal_accuracy = 1.0

    cards = format_metric_cards(FakeMetrics())
    by_key = {c.key: c for c in cards}
    assert by_key["faithfulness_rate"].display == "80%"
    # An attribute the object does not expose stays absent.
    assert by_key["retrieval_hit_rate"].value is None


# --- load_metrics_file ------------------------------------------------------


def test_load_metrics_file_reads_json(tmp_path):
    path = tmp_path / "results.json"
    payload = {"faithfulness_rate": 1.0, "relevance_rate": 0.9}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_metrics_file(path) == payload


def test_load_metrics_file_missing_returns_empty(tmp_path):
    assert load_metrics_file(tmp_path / "does-not-exist.json") == {}


def test_load_metrics_file_invalid_json_returns_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_metrics_file(path) == {}


def test_load_metrics_file_non_object_returns_empty(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_metrics_file(path) == {}


# --- load_default_metrics ---------------------------------------------------


def test_default_results_path_points_at_eval_results():
    assert DEFAULT_RESULTS_PATH == "eval/results.json"


def test_load_default_metrics_uses_explicit_path(tmp_path):
    path = tmp_path / "results.json"
    payload = {"faithfulness_rate": 1.0, "relevance_rate": 0.8}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_default_metrics(path) == payload


def test_load_default_metrics_reads_default_results_file(tmp_path, monkeypatch):
    # The dashboard default path is relative; resolve it against a temp cwd so
    # the real results file (if any) is never touched and no network happens.
    monkeypatch.chdir(tmp_path)
    results = tmp_path / "eval" / "results.json"
    results.parent.mkdir(parents=True)
    payload = {"faithfulness_rate": 0.95, "refusal_accuracy": 1.0}
    results.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_default_metrics()
    assert loaded == payload
    by_key = {c.key: c for c in format_metric_cards(loaded)}
    assert by_key["faithfulness_rate"].display == "95%"


def test_load_default_metrics_missing_default_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_default_metrics() == {}


# --- format_stats -----------------------------------------------------------


def test_format_stats_renders_all_entities():
    out = format_stats({"students": 2, "exercises": 5, "grades": 3, "messages": 10})
    assert "**Students:** 2" in out
    assert "**Exercises:** 5" in out
    assert "**Grades:** 3" in out
    assert "**Messages:** 10" in out
    assert out.count("\n") == 3  # four bullet lines


def test_format_stats_missing_keys_default_to_zero():
    out = format_stats({})
    assert "**Students:** 0" in out
    assert "**Messages:** 0" in out


# --- gather_db_stats --------------------------------------------------------


def test_gather_db_stats_none_session_returns_zeros():
    assert gather_db_stats(None) == {
        "students": 0,
        "exercises": 0,
        "grades": 0,
        "messages": 0,
    }


# The DB-backed counting needs SQLAlchemy (the ``api`` extra).
sqlalchemy = pytest.importorskip("sqlalchemy")


@pytest.fixture
def session():
    """A session bound to a fresh in-memory SQLite database with tables."""
    from db import create_engine_from_settings, get_session, init_db

    engine = create_engine_from_settings("sqlite:///:memory:")
    init_db(engine)
    with get_session(engine) as sess:
        yield sess


def test_gather_db_stats_empty_database(session):
    assert gather_db_stats(session) == {
        "students": 0,
        "exercises": 0,
        "grades": 0,
        "messages": 0,
    }


def test_gather_db_stats_counts_rows(session):
    from db import Student, add_exercise, add_grade, add_message

    student = Student(external_id="student-1")
    session.add(student)
    session.flush()

    exercise = add_exercise(
        session,
        student_id=student.id,
        course="algebra",
        notion="matrices",
        problem="Compute the determinant.",
        reference_solution="det = 0",
    )
    add_grade(
        session,
        exercise_id=exercise.id,
        student_id=student.id,
        answer="0",
        score=100.0,
        feedback="Correct.",
    )
    add_message(session, student_id=student.id, role="user", content="hello")
    add_message(session, student_id=student.id, role="assistant", content="hi")
    session.flush()

    assert gather_db_stats(session) == {
        "students": 1,
        "exercises": 1,
        "grades": 1,
        "messages": 2,
    }


def test_gather_db_stats_swallows_errors_to_zero():
    class BrokenSession:
        def scalar(self, *_args, **_kwargs):
            raise RuntimeError("no such table")

    assert gather_db_stats(BrokenSession()) == {
        "students": 0,
        "exercises": 0,
        "grades": 0,
        "messages": 0,
    }
