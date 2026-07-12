# Operations (Postgres + observability)

Two optional operational add-ons: a durable PostgreSQL backend for accounts and
history, and LangFuse tracing for the LLM pipeline. Both are opt-in — the app
runs fully on its defaults (local SQLite, no tracing) without either.

For cloud deployment and the Cloudflare R2 durable-upload option, see
[DEPLOY.md](DEPLOY.md).

---

## PostgreSQL backend (optional)

The relational store (students, generated exercises with their reference
solutions, grades, and conversation history) is accessed through SQLAlchemy and
driven entirely by the `DATABASE_URL` setting. The default is local SQLite, which
needs no setup:

```
DATABASE_URL=sqlite:///./app.db   # default; nothing to install
```

PostgreSQL is a drop-in alternative for shared or production deployments (on the
free HF Space, SQLite is ephemeral — a rebuild or idle sleep wipes accounts and
history, so a managed Postgres is what makes them durable). The ORM models use
only portable column types, so no migration rewrite is needed: install the
driver, run a Postgres instance, point `DATABASE_URL` at it, and apply the
existing Alembic migrations.

### 1. Install the driver

The driver lives in the optional `postgres` extra (psycopg 3, binary build, so no
system libpq is required). It is additive — SQLite users never need it:

```
uv sync --extra api --extra postgres
```

### 2. Run PostgreSQL locally (compose profile)

A `postgres` service is defined in `docker-compose.yml` behind the `postgres`
compose profile, so it is **not** started by the default vector-store command:

```
# Default — starts Qdrant only (unchanged):
docker compose up -d qdrant

# Opt in to the local PostgreSQL backend:
docker compose --profile postgres up -d postgres
```

Documented defaults (override via the environment or `.env`: `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`):

| Setting  | Default    |
| -------- | ---------- |
| user     | `grounded` |
| password | `grounded` |
| database | `grounded` |
| port     | `5432`     |

Data persists in the named volume `postgres_storage`; a `pg_isready` healthcheck
reports when the database is accepting connections.

### 3. Point the app at PostgreSQL

Set `DATABASE_URL` (e.g. in `.env`) using the `postgresql+psycopg` driver prefix
so SQLAlchemy uses psycopg 3:

```
DATABASE_URL=postgresql+psycopg://grounded:grounded@localhost:5432/grounded
```

The engine factory (`db/session.py`) selects driver `connect_args` from the URL
scheme, so the SQLite-only `check_same_thread` flag is never sent to psycopg.

### 4. Apply migrations

Alembic resolves its URL from the same `DATABASE_URL` setting at runtime (see
`alembic/env.py`), so no `alembic.ini` change is needed. With `DATABASE_URL`
pointing at PostgreSQL and the database up:

```
uv run --extra migrations --extra postgres alembic upgrade head
```

Use `alembic revision --autogenerate -m "..."` as usual to add new migrations;
they are dialect-agnostic.

### 5. Production

Use a managed PostgreSQL service rather than the compose container (which is for
local development). Supply credentials through `DATABASE_URL` as an environment
variable / secret, keep the password out of source control, and run
`alembic upgrade head` as part of your deploy.

### Verifying without a running server

The driver and engine wiring can be confirmed offline (no connection is opened
until the first query):

```
uv run python -c "from db.session import create_engine_from_settings; \
e = create_engine_from_settings('postgresql+psycopg://u:p@localhost:5432/db'); \
print(e.dialect.name, e.dialect.driver)"
# -> postgresql psycopg
```

---

## Observability (LangFuse tracing, optional)

Tracing is **fully opt-in** and **zero-cost when off**. With no LangFuse
credentials in the environment, every LLM call passes an empty callback list
(`[]`), a harmless no-op, so behavior and cost are unchanged.

### What is traced

When enabled, each LLM step becomes a LangFuse observation with its latency,
token usage and estimated cost:

- **Explain** — the grounded answer, blocking and streaming (`core/answer.py`).
- **Generate** — exercise + reference solution (`agent/nodes/generate.py`).
- **Grade** — the product judge that marks the student's answer
  (`agent/nodes/grade.py`).
- **Reexplain** — the level-aware rephrasing (`agent/nodes/reexplain.py`).
- **Quiz** — grounded quiz generation and per-answer grading
  (`agent/nodes/quiz.py`).
- **Judge** — the offline faithfulness/relevance judge used by the evaluation
  harness (`eval/run_eval.py`).

The agentic router in `agent/graph.py` (intent classification) is traced too if
you run the graph, but the deployed product serves explicit endpoints and does
not route through it — see [ARCHITECTURE.md](ARCHITECTURE.md). Retrieval and
per-stage latency are tracked separately by the in-process timer in
`core/obs.py`, which feeds the retrieval-latency percentiles in the README.

### How it works

`core/obs.get_callbacks()` returns a list with a LangFuse `CallbackHandler` when
credentials are present, or `[]` otherwise. Each call site passes that list
through the invocation config:

```python
get_llm("explain").invoke(messages, config={"callbacks": get_callbacks()})
```

The handler reads its credentials from the environment, so no keys are hard-coded
anywhere.

### How to enable

1. Get LangFuse credentials, either way works:
   - **Cloud (free tier):** sign up at <https://cloud.langfuse.com>, create a
     project, copy its public and secret keys.
   - **Self-host:** run LangFuse locally (Docker), create a project the same way,
     and point `LANGFUSE_HOST` at your instance.
2. Install the optional extra:

   ```bash
   uv sync --extra obs
   ```

3. Set the three environment variables (e.g. in `.env`):

   ```bash
   LANGFUSE_PUBLIC_KEY=pk-...
   LANGFUSE_SECRET_KEY=sk-...
   LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
   ```

   Tracing activates only when **both** keys are set; `LANGFUSE_HOST` defaults to
   the cloud endpoint when omitted.

4. Run any query (an `/ask` call, an agent turn, or the eval harness). The traces
   — retrieval → LLM → judge — appear in the LangFuse UI with latency, tokens and
   cost. To turn tracing off again, unset the keys.
