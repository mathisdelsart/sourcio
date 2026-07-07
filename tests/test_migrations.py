"""Run the Alembic migrations against a temporary SQLite database.

These tests are skipped unless the optional ``migrations`` extra is installed
(``uv sync --extra migrations``). They never touch the network: migrations are
applied to a throwaway SQLite file. The CI matrix does not install the extra, so
``pytest.importorskip`` lets it skip gracefully there.

Note: the project ships a local ``alembic/`` directory, which is exposed as a
namespace package on the test path. Importing the bare ``alembic`` name would
therefore resolve to that directory rather than the library, so the skip guard
targets ``alembic.config`` (a real submodule of the installed package).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic.config")

from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

from alembic import command  # noqa: E402

EXPECTED_TABLES = {"students", "exercises", "grades", "messages"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_config(database_url: str) -> Config:
    """Build an Alembic config pointing at the project files and a test URL."""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    # env.py resolves the URL from settings; override it here for the test DB.
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A temporary SQLite URL, also exported so the app settings pick it up."""
    db_path = tmp_path / "migrations_test.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def test_upgrade_creates_all_tables(database_url: str) -> None:
    """``upgrade head`` creates the four expected tables."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert EXPECTED_TABLES <= tables


def test_downgrade_removes_all_tables(database_url: str) -> None:
    """``downgrade base`` removes every table created by the migration."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert not (EXPECTED_TABLES & tables)


def test_feedback_table_upgrade_and_downgrade(database_url: str) -> None:
    """The 0005 migration creates the ``feedback`` table, and ``downgrade`` drops it."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
    try:
        assert "feedback" in set(inspect(engine).get_table_names())
        columns = {c["name"] for c in inspect(engine).get_columns("feedback")}
        assert {"id", "student_id", "rating", "note", "question", "answer", "created_at"} <= columns

        command.downgrade(cfg, "0004")
        assert "feedback" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_sessions_table_upgrade_and_downgrade(database_url: str) -> None:
    """The 0006 migration adds the ``sessions`` table and ``messages.session_id``."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
    try:
        assert "sessions" in set(inspect(engine).get_table_names())
        session_cols = {c["name"] for c in inspect(engine).get_columns("sessions")}
        assert {"id", "student_id", "title", "created_at"} <= session_cols
        message_cols = {c["name"] for c in inspect(engine).get_columns("messages")}
        assert "session_id" in message_cols

        command.downgrade(cfg, "0005")
        assert "sessions" not in set(inspect(engine).get_table_names())
        message_cols = {c["name"] for c in inspect(engine).get_columns("messages")}
        assert "session_id" not in message_cols
    finally:
        engine.dispose()


def test_reviews_table_upgrade_and_downgrade(database_url: str) -> None:
    """The 0007 migration adds the ``reviews`` table, and ``downgrade`` drops it."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
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


def test_user_display_name_upgrade_and_downgrade(database_url: str) -> None:
    """The 0008 migration adds ``users.display_name``, and ``downgrade`` drops it."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
    try:
        user_cols = {c["name"] for c in inspect(engine).get_columns("users")}
        assert "display_name" in user_cols

        command.downgrade(cfg, "0007")
        user_cols = {c["name"] for c in inspect(engine).get_columns("users")}
        assert "display_name" not in user_cols
    finally:
        engine.dispose()


def test_message_ref_id_upgrade_and_downgrade(database_url: str) -> None:
    """The 0009 migration adds ``messages.ref_id``, and ``downgrade`` drops it."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
    try:
        message_cols = {c["name"] for c in inspect(engine).get_columns("messages")}
        assert "ref_id" in message_cols

        command.downgrade(cfg, "0008")
        message_cols = {c["name"] for c in inspect(engine).get_columns("messages")}
        assert "ref_id" not in message_cols
    finally:
        engine.dispose()


def test_user_username_upgrade_and_downgrade(database_url: str) -> None:
    """The 0010 migration adds ``users.username`` (unique) and relaxes ``email``.

    Upgrade adds the ``username`` column and makes ``email`` nullable; downgrade
    drops ``username`` and restores ``email`` to NOT NULL.
    """
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert "username" in columns
        assert columns["email"]["nullable"] is True
        index_names = {idx["name"] for idx in inspector.get_indexes("users")}
        assert "ix_users_username" in index_names

        command.downgrade(cfg, "0009")
        inspector = inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert "username" not in columns
        assert columns["email"]["nullable"] is False
    finally:
        engine.dispose()
