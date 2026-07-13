# The relational store — SQLAlchemy, Alembic, Postgres

## Two stores, deliberately

The system has two databases with disjoint responsibilities. They are not redundant, and
conflating them is the most common misreading of the architecture.

| | **Qdrant** | **The SQL store** |
| --- | --- | --- |
| Holds | Course chunks as vectors + payload | Users, students, messages, exercises, grades, quizzes, feedback |
| Answers | *Which passage is relevant?* | *Who is this, and what have they done?* |
| Index | Approximate nearest neighbour (HNSW) | B-trees, foreign keys |
| Loss impact | Courses must be re-ingested | Accounts and history are lost |

A vector store is poorly suited to "list this user's threads, newest first"; a relational
store is poorly suited to "find the semantically nearest passage".

## SQLAlchemy

Chosen for **portability**. The models use only portable column types, so the same code runs
on SQLite locally and on PostgreSQL in production with no rewrite — the URL changes and
nothing else does.

This is what makes *zero-setup local development, managed Postgres in production* achievable,
which is the difference between a project that can be cloned and run and one that cannot.

Conventions: one session per request, closed at the end; relationships declared with
`cascade="all, delete-orphan"` so deleting a student removes their messages rather than
orphaning them.

## Alembic — migrations as an append-only ledger

Schema changes are versioned scripts chained by `down_revision`, so any database can be
walked forward or back to a given revision.

**The rule this project enforces:** migrations are never edited or deleted retroactively.

When spaced repetition was removed (scheduler, endpoints, model, tests), the migration that
created its table — `0007_reviews.py` — was **kept**. Deleting it would orphan `0008`, whose
`down_revision` points at it, and would rewrite history that other databases have already
applied. The table is dropped **forward** by a new migration, `0011`, which remains reversible.

Migrations are a ledger, not a source file. Corrections are appended, not backdated.

## SQLite in development, Postgres in production

SQLite is a file, which is ideal locally: no service, no setup.

In a container, that file lives on the container's filesystem, **which is ephemeral**. On
Hugging Face Spaces — and on most PaaS — a rebuild or a sleep/wake cycle destroys it, taking
every account and every conversation with it.

**The failure mode is delayed, which is what makes it dangerous.** Immediately after a
deployment everything appears durable, because the container has not yet restarted. The data
disappears at the *next* restart, long after the deployment has been verified.

Production therefore points `DATABASE_URL` at a managed Postgres (Neon). Because the ORM is
already portable, this is a one-line environment change.

**Driver naming.** Providers issue a `postgresql://…` URL; SQLAlchemy requires the driver to
be named: `postgresql+psycopg://…`. Omitting `+psycopg` fails at startup with an error that
does not obviously identify the cause.

**Connection pooling.** SQLAlchemy pools by default. Against a serverless Postgres such as
Neon, opening a connection is comparatively expensive, so the deployment uses Neon's **pooled**
endpoint (`-pooler` in the hostname) rather than the direct one.

## Considered and rejected: pgvector

Storing vectors in Postgres alongside the relational data was a serious alternative: one
service instead of two, and transactional consistency between chunks and their metadata. It
was rejected on filtering ergonomics and headroom at scale — see [qdrant.md](qdrant.md) — but
the decision is close, and at the current corpus size either would be defensible.

## Known considerations

- **N+1 queries.** Loading twenty threads and then lazily loading each one's messages is
  twenty-one queries; `selectinload` / `joinedload` is the fix. The hot path (`/ask`) touches
  few rows and has not been affected.
- **Session lifetime.** A session held across requests leaks state and connections. One
  session per request, always.
