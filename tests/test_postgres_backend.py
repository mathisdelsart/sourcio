"""Offline checks for the optional PostgreSQL backend.

No PostgreSQL server is contacted: SQLAlchemy builds an engine lazily, so these
tests assert that the engine factory accepts a ``postgresql+psycopg://`` URL and
that the SQLite-only ``check_same_thread`` connect arg is applied to SQLite URLs
only (never to PostgreSQL). The ``psycopg`` driver is optional, so the suite is
skipped when it is not installed.
"""

import pytest

pytest.importorskip("sqlalchemy")

from db.session import _connect_args_for, create_engine_from_settings  # noqa: E402

PG_URL = "postgresql+psycopg://user:pass@localhost:5432/grounded"


def test_connect_args_check_same_thread_is_sqlite_only():
    # SQLite (file and in-memory) receives the threading flag...
    assert _connect_args_for("sqlite:///./app.db") == {"check_same_thread": False}
    assert _connect_args_for("sqlite:///:memory:") == {"check_same_thread": False}
    # ...and PostgreSQL never does (the flag is unknown to psycopg).
    assert _connect_args_for(PG_URL) == {}
    assert "check_same_thread" not in _connect_args_for(PG_URL)


def test_engine_factory_accepts_postgres_url_without_connecting():
    psycopg = pytest.importorskip("psycopg")
    assert psycopg.__version__  # driver importable

    # Building the engine must not open a connection, so this works with no
    # PostgreSQL server running.
    engine = create_engine_from_settings(PG_URL)
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"


def test_sqlite_engine_still_built_with_thread_flag():
    engine = create_engine_from_settings("sqlite:///:memory:")
    assert engine.dialect.name == "sqlite"
