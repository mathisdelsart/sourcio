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
    DEFAULT_LATENCY_PATH,
    DEFAULT_RESULTS_PATH,
    LatencyRow,
    MetricCard,
    format_latency_rows,
    format_metric_cards,
    format_stats,
    gather_db_stats,
    load_default_latency,
    load_default_metrics,
    load_latency_file,
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


# --- format_latency_rows ----------------------------------------------------


def test_format_latency_rows_renders_known_stages_in_order():
    latency = {
        "retrieval": {"count": 3, "p50_ms": 12.0, "p95_ms": 40.0},
        "llm": {"count": 3, "p50_ms": 800.0, "p95_ms": 1500.0},
        "judge": {"count": 2, "p50_ms": 600.0, "p95_ms": 900.0},
    }
    rows = format_latency_rows(latency)
    assert [r.stage for r in rows] == ["retrieval", "llm", "judge"]
    by_stage = {r.stage: r for r in rows}
    assert by_stage["llm"].p95_ms == 1500.0
    assert by_stage["retrieval"].count == 3
    assert all(isinstance(r, LatencyRow) for r in rows)


def test_format_latency_rows_handles_missing_stage():
    rows = format_latency_rows({"retrieval": {"count": 1, "p50_ms": 5.0, "p95_ms": 5.0}})
    by_stage = {r.stage: r for r in rows}
    assert by_stage["retrieval"].p50_ms == 5.0
    # Stages absent from the source render with zero count and None figures.
    assert by_stage["llm"].count == 0
    assert by_stage["llm"].p50_ms is None
    assert by_stage["judge"].p95_ms is None


def test_format_latency_rows_empty_source():
    rows = format_latency_rows({})
    assert len(rows) == 3
    assert all(r.count == 0 and r.p50_ms is None and r.p95_ms is None for r in rows)


def test_format_latency_rows_none_source():
    rows = format_latency_rows(None)
    assert all(r.p50_ms is None for r in rows)


def test_format_latency_rows_ignores_non_numeric_and_bool():
    rows = format_latency_rows({"retrieval": {"count": True, "p50_ms": "fast", "p95_ms": None}})
    by_stage = {r.stage: r for r in rows}
    # A stray bool count is not coerced to 1; non-numeric figures stay None.
    assert by_stage["retrieval"].count == 0
    assert by_stage["retrieval"].p50_ms is None


# --- load_latency_file / load_default_latency -------------------------------


def test_load_latency_file_reads_json(tmp_path):
    path = tmp_path / "latency.json"
    payload = {"retrieval": {"count": 1, "p50_ms": 1.0, "p95_ms": 1.0}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_latency_file(path) == payload


def test_load_latency_file_missing_returns_empty(tmp_path):
    assert load_latency_file(tmp_path / "missing.json") == {}


def test_load_latency_file_non_object_returns_empty(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_latency_file(path) == {}


def test_default_latency_path_points_at_eval_latency():
    assert DEFAULT_LATENCY_PATH == "eval/latency.json"


def test_load_default_latency_uses_explicit_path(tmp_path):
    path = tmp_path / "latency.json"
    payload = {"llm": {"count": 1, "p50_ms": 2.0, "p95_ms": 2.0}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_default_latency(path) == payload


def test_load_default_latency_missing_default_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_default_latency() == {}


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


# --- _open_session_stats: default DB source ---------------------------------


def test_open_session_stats_defaults_to_settings_url(monkeypatch):
    """With no override, the dashboard reads the configured ``database_url``.

    The engine factory and session are stubbed (no real database), so this only
    asserts that the None path forwards to ``create_engine_from_settings`` with a
    falsy override, which resolves to ``Settings.database_url``.
    """
    import db.session as db_session
    from ui import metrics

    captured = {}

    def fake_create_engine_from_settings(url=None):
        captured["url"] = url
        return "ENGINE"

    class _FakeSession:
        def __enter__(self):
            return "SESSION"

        def __exit__(self, *_exc):
            return False

    def fake_get_session(engine=None):
        captured["engine"] = engine
        return _FakeSession()

    monkeypatch.setattr(db_session, "create_engine_from_settings", fake_create_engine_from_settings)
    monkeypatch.setattr(db_session, "get_session", fake_get_session)
    monkeypatch.setattr(metrics, "gather_db_stats", lambda session: {"seen": session})

    result = metrics._open_session_stats(None)

    # No override forwarded -> factory falls back to Settings.database_url.
    assert captured["url"] is None
    assert captured["engine"] == "ENGINE"
    assert result == {"seen": "SESSION"}


def test_open_session_stats_honors_override(monkeypatch):
    """An explicit URL override is passed straight through to the engine factory."""
    import db.session as db_session
    from ui import metrics

    captured = {}

    def fake_create_engine_from_settings(url=None):
        captured["url"] = url
        return "ENGINE"

    class _FakeSession:
        def __enter__(self):
            return "SESSION"

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(db_session, "create_engine_from_settings", fake_create_engine_from_settings)
    monkeypatch.setattr(db_session, "get_session", lambda engine=None: _FakeSession())
    monkeypatch.setattr(metrics, "gather_db_stats", lambda session: {})

    metrics._open_session_stats("sqlite:///override.db")
    assert captured["url"] == "sqlite:///override.db"
