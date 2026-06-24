"""Alembic migration environment.

The database URL is resolved at runtime from ``config.get_settings().database_url``
(SQLite in development, PostgreSQL later) rather than being hardcoded in
``alembic.ini``. ``target_metadata`` points at the project's declarative ``Base``
so ``--autogenerate`` can diff models against the database.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure the project root is importable so ``config`` and ``db`` resolve when
# Alembic loads this file (it is executed outside the normal package context).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings  # noqa: E402
from db.models import Base  # noqa: E402

# Alembic Config object, providing access to values in alembic.ini.
config = context.config

# Resolve the database URL at runtime so it is never hardcoded in the .ini file.
# A caller (e.g. tests) may set ``sqlalchemy.url`` on the Config beforehand; in
# that case honour it instead of overriding with the application settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Configure logging from the .ini file, if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata used for autogenerate support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
