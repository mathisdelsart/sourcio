"""Tests for spaced-repetition scheduling: pure SM-2 math, API, and migration.

The pure ``core.scheduling.schedule`` math is checked against hand-computed SM-2
values (no I/O, no clock). The API tests bind the app to an in-memory SQLite
database and exercise ``POST /reviews`` and ``GET /reviews/due`` with no LLM,
vector store, or network call. The migration test applies the Alembic migrations
to a throwaway SQLite file. The API and migration sections are skipped when their
optional extras are absent so CI without extras collects cleanly.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.scheduling import MIN_EASE, ReviewState, schedule

# --- pure SM-2 math ----------------------------------------------------------


def test_fresh_perfect_recall_grows_and_raises_ease():
    state = schedule(ease=2.5, interval_days=0, repetitions=0, quality=5)
    assert state.repetitions == 1
    assert state.interval_days == 1
    assert math.isclose(state.ease, 2.6)


def test_quality_four_keeps_ease_steady():
    state = schedule(ease=2.5, interval_days=0, repetitions=0, quality=4)
    assert state.repetitions == 1
    assert state.interval_days == 1
    assert math.isclose(state.ease, 2.5)


def test_quality_three_passes_but_lowers_ease():
    state = schedule(ease=2.5, interval_days=0, repetitions=0, quality=3)
    assert state.repetitions == 1
    assert state.interval_days == 1
    assert math.isclose(state.ease, 2.36)


def test_second_success_uses_six_day_interval():
    state = schedule(ease=2.6, interval_days=1, repetitions=1, quality=5)
    assert state.repetitions == 2
    assert state.interval_days == 6


def test_third_success_multiplies_interval_by_ease():
    state = schedule(ease=2.6, interval_days=6, repetitions=2, quality=5)
    assert state.repetitions == 3
    # ease becomes 2.7, interval = round(6 * 2.7) = 16.
    assert math.isclose(state.ease, 2.7)
    assert state.interval_days == round(6 * 2.7)


@pytest.mark.parametrize("quality", [0, 1, 2])
def test_failure_resets_streak_and_interval(quality):
    state = schedule(ease=2.5, interval_days=30, repetitions=5, quality=quality)
    assert state.repetitions == 0
    assert state.interval_days == 1


def test_ease_is_floored():
    # A long streak of poor recalls would drive ease below the floor; it clamps.
    state = schedule(ease=1.3, interval_days=10, repetitions=4, quality=0)
    assert state.ease == MIN_EASE
    assert isinstance(state, ReviewState)


@pytest.mark.parametrize("quality", [-1, 6, 100])
def test_out_of_range_quality_raises(quality):
    with pytest.raises(ValueError):
        schedule(ease=2.5, interval_days=0, repetitions=0, quality=quality)


# --- API ---------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api.main import app  # noqa: E402
from db.models import Review  # noqa: E402


@pytest.fixture
def client():
    """Bind the API to a fresh in-memory SQLite DB and yield a test client."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    with TestClient(app) as test_client:
        yield test_client
    api_main._engine = None


def _post_review(client, **overrides):
    body = {"student_id": "s1", "notion": "wavelets", "quality": 5}
    body.update(overrides)
    return client.post("/reviews", json=body)


def test_review_creates_row_and_computes_due_at(client):
    before = datetime.now(UTC)
    response = _post_review(client, quality=5)
    assert response.status_code == 200
    payload = response.json()
    assert payload["notion"] == "wavelets"
    assert payload["interval_days"] == 1
    assert math.isclose(payload["ease"], 2.6)

    due_at = datetime.fromisoformat(payload["due_at"])
    expected = before + timedelta(days=1)
    # due_at is now + interval; allow a small slack for execution time.
    assert abs((due_at - expected).total_seconds()) < 60

    with api_main.get_session(api_main._engine) as session:
        row = session.scalar(select(Review).where(Review.notion == "wavelets"))
        assert row is not None
        assert row.repetitions == 1
        assert row.last_reviewed is not None


def test_review_upserts_single_row_per_notion(client):
    _post_review(client, quality=5)
    second = _post_review(client, quality=5)
    assert second.status_code == 200
    # Second success moves to the 6-day interval, still one row.
    assert second.json()["interval_days"] == 6

    with api_main.get_session(api_main._engine) as session:
        rows = list(session.scalars(select(Review).where(Review.notion == "wavelets")))
        assert len(rows) == 1
        assert rows[0].repetitions == 2


def test_failed_review_resets_interval(client):
    _post_review(client, quality=5)
    _post_review(client, quality=5)
    failed = _post_review(client, quality=1)
    assert failed.status_code == 200
    assert failed.json()["interval_days"] == 1

    with api_main.get_session(api_main._engine) as session:
        row = session.scalar(select(Review).where(Review.notion == "wavelets"))
        assert row.repetitions == 0


@pytest.mark.parametrize("quality", [-1, 6, 7, 100])
def test_review_rejects_out_of_range_quality(client, quality):
    response = _post_review(client, quality=quality)
    assert response.status_code == 422
    with api_main.get_session(api_main._engine) as session:
        assert session.scalar(select(Review)) is None


def test_due_returns_new_and_overdue_only(client):
    # A fresh review is due immediately (due_at defaults to creation time), but a
    # just-passed one is scheduled into the future and must not appear.
    _post_review(client, notion="future-notion", quality=5)

    # Force a notion to be overdue by back-dating its due_at directly.
    with api_main.get_session(api_main._engine) as session:
        student = session.scalar(select(Review)).student_id
        overdue = Review(
            student_id=student,
            notion="overdue-notion",
            ease=2.5,
            interval_days=3,
            repetitions=2,
            due_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.add(overdue)

    response = client.get("/reviews/due", params={"student_id": "s1"})
    assert response.status_code == 200
    notions = [item["notion"] for item in response.json()]
    assert "overdue-notion" in notions
    assert "future-notion" not in notions


def test_due_sorted_soonest_first(client):
    _post_review(client, notion="seed", quality=5)
    with api_main.get_session(api_main._engine) as session:
        student_id = session.scalar(select(Review)).student_id
        session.add(
            Review(
                student_id=student_id,
                notion="older",
                due_at=datetime.now(UTC) - timedelta(days=5),
            )
        )
        session.add(
            Review(
                student_id=student_id,
                notion="newer",
                due_at=datetime.now(UTC) - timedelta(days=1),
            )
        )

    response = client.get("/reviews/due", params={"student_id": "s1"})
    notions = [item["notion"] for item in response.json()]
    assert notions.index("older") < notions.index("newer")


def test_due_unknown_student_is_empty(client):
    response = client.get("/reviews/due", params={"student_id": "nobody"})
    assert response.status_code == 200
    assert response.json() == []


# --- API-key authentication --------------------------------------------------

_API_KEY = "secret-key"


def _set_api_key(monkeypatch, key):
    from core.config import Settings

    settings = Settings(api_key=key)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/reviews", {"student_id": "s1", "notion": "n", "quality": 5}),
        ("get", "/reviews/due?student_id=s1", None),
    ],
)
def test_reviews_reject_missing_key(client, monkeypatch, method, path, body):
    _set_api_key(monkeypatch, _API_KEY)
    response = client.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body", "expected"),
    [
        ("post", "/reviews", {"student_id": "s1", "notion": "n", "quality": 5}, 200),
        ("get", "/reviews/due?student_id=s1", None, 200),
    ],
)
def test_reviews_accept_correct_key(client, monkeypatch, method, path, body, expected):
    _set_api_key(monkeypatch, _API_KEY)
    response = client.request(method, path, json=body, headers={"X-API-Key": _API_KEY})
    assert response.status_code == expected


def test_reviews_open_when_no_key_configured(client, monkeypatch):
    _set_api_key(monkeypatch, "")
    assert _post_review(client).status_code == 200


# --- migration ---------------------------------------------------------------

pytest.importorskip("alembic.config")

from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from alembic import command  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_config(database_url: str) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_reviews_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    db_path = tmp_path / "reviews_migration.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = _make_config(url)

    command.upgrade(cfg, "head")
    engine = create_engine(url, future=True)
    try:
        assert "reviews" in set(inspect(engine).get_table_names())
        columns = {c["name"] for c in inspect(engine).get_columns("reviews")}
        assert {
            "id",
            "student_id",
            "notion",
            "ease",
            "interval_days",
            "repetitions",
            "due_at",
            "last_reviewed",
            "created_at",
        } <= columns

        command.downgrade(cfg, "0006")
        assert "reviews" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
