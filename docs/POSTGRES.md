# PostgreSQL backend (optional)

The relational store (students, generated exercises with their reference
solutions, grades, and conversation history) is accessed through SQLAlchemy and
is driven entirely by the `DATABASE_URL` setting. The default is local SQLite,
which needs no setup:

```
DATABASE_URL=sqlite:///./app.db   # default; nothing to install
```

PostgreSQL is a drop-in alternative for shared or production deployments. The
ORM models use only portable column types, so no migration rewrite is needed —
you install the driver, run a Postgres instance, point `DATABASE_URL` at it, and
apply the existing Alembic migrations.

## 1. Install the driver

The driver lives in the optional `postgres` extra (psycopg 3, the binary
build, so no system libpq is required):

```
uv sync --extra api --extra postgres
```

This is additive: SQLite users never need it.

## 2. Run PostgreSQL locally (compose profile)

A `postgres` service is defined in `docker-compose.yml` behind the `postgres`
compose profile, so it is **not** started by the default vector-store command:

```
# Default — starts Qdrant only (unchanged):
docker compose up -d qdrant

# Opt in to the local PostgreSQL backend:
docker compose --profile postgres up -d postgres
```

The service uses these documented defaults (override them via the environment or
an `.env` file: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`):

| Setting  | Default    |
| -------- | ---------- |
| user     | `grounded` |
| password | `grounded` |
| database | `grounded` |
| port     | `5432`     |

Data persists in the named volume `postgres_storage`. A `pg_isready`
healthcheck reports when the database is accepting connections.

## 3. Point the app at PostgreSQL

Set `DATABASE_URL` (e.g. in `.env`) using the `postgresql+psycopg` driver
prefix so SQLAlchemy uses psycopg 3:

```
DATABASE_URL=postgresql+psycopg://grounded:grounded@localhost:5432/grounded
```

The engine factory (`db/session.py`) selects driver `connect_args` from the URL
scheme, so the SQLite-only `check_same_thread` flag is never sent to psycopg.

## 4. Apply migrations

Alembic resolves its URL from the same `DATABASE_URL` setting at runtime (see
`alembic/env.py`), so no `alembic.ini` change is needed. With `DATABASE_URL`
pointing at PostgreSQL and the database up:

```
uv run --extra migrations --extra postgres alembic upgrade head
```

This creates the schema on the fresh PostgreSQL database. Use
`alembic revision --autogenerate -m "..."` as usual to add new migrations; they
are dialect-agnostic.

## 5. Production

Use a managed PostgreSQL service (e.g. a cloud-hosted instance) rather than the
compose container, which is intended for local development. Supply credentials
through `DATABASE_URL` as an environment variable / secret, keep the password
out of source control, and run `alembic upgrade head` as part of your deploy.

## Verifying without a running server

You can confirm the driver and engine wiring offline (no connection is opened
until the first query):

```
uv run python -c "from db.session import create_engine_from_settings; \
e = create_engine_from_settings('postgresql+psycopg://u:p@localhost:5432/db'); \
print(e.dialect.name, e.dialect.driver)"
# -> postgresql psycopg
```
