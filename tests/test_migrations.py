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
from sqlalchemy import create_engine, inspect

pytest.importorskip("alembic.config")

from alembic.config import Config  # noqa: E402

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
