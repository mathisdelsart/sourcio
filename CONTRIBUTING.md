# Contributing

Thanks for working on `sourcio`. This guide covers local setup, the test
and lint workflow, and the branch / PR conventions enforced by CI. For the
system design, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) for dependency management (no
  `requirements.txt`; the lockfile is `uv.lock`)
- Docker (for the Qdrant vector database)

## Setup

```bash
# Install everything: all optional extras + the dev group
uv sync --all-extras --group dev    # or: make install

# Start Qdrant in the background
docker compose up -d qdrant         # or: make qdrant

# Configure environment
cp .env.example .env                # then fill in OPENAI_API_KEY
```

`.env` is gitignored — never commit it, an API key, or any course PDF. The full
list of settings (LLM roles, Qdrant URL, database URL, optional cache, budget
cap, API-key auth, LangFuse) is documented in `.env.example`.

### Optional extras

Dependencies are split into extras so each part can be installed independently.
`make install` (`uv sync --all-extras --group dev`) pulls the lot; install a
subset with, e.g., `uv sync --extra api --extra agent --group dev`.

| Extra | What it adds | When you need it |
| --- | --- | --- |
| `api` | FastAPI, uvicorn, SQLAlchemy, bcrypt, PyJWT | Running the API |
| `agent` | LangGraph | The agent graph (the nodes themselves need nothing extra) |
| `ingestion` | PyMuPDF, sentence-transformers | Ingesting PDFs, and any local embedding — so also **retrieval** |
| `obs` | LangFuse | Opt-in tracing |
| `migrations` | Alembic | Changing the DB schema |
| `postgres` | psycopg 3 | Targeting a managed Postgres (what production runs on) |
| `groq` | langchain-groq | The free hosted provider (`LLM_PROVIDER=groq`) |
| `local` | langchain-ollama | Fully local, zero-cost runs (`LLM_PROVIDER=ollama`) |
| `storage` | boto3 | Durable upload storage on Cloudflare R2 |

## Running tests

```bash
uv run python -m pytest -q          # or: make test
```

Tests are designed to run without any API call: the LLM, judge, retriever, and
database session are all injectable, and tests pass fakes. **Some tests skip
gracefully when an optional extra is absent** — they use
`pytest.importorskip(...)` for packages such as `fastapi`, `sqlalchemy`,
`httpx`, `langfuse`, and `alembic`. A bare `uv sync --group dev` therefore still
collects and runs the pure-logic tests, skipping the rest. To run the **full**
suite, install the extras (`make install` / `uv sync --all-extras --group dev`).

## Linting and formatting

`ruff` handles both linting and formatting (line length 100).

```bash
uv run ruff check .                 # lint            (make lint)
uv run ruff format .                # format          (make fmt)
uv run ruff format --check .        # format check    (make fmt-check)
```

`make check` runs lint, format check, and tests together — run it before
opening a PR.

## Pre-commit hooks

A [`pre-commit`](https://pre-commit.com/) configuration runs ruff (lint with
autofix and format) plus a few cheap hygiene hooks (trailing whitespace,
end-of-file, YAML and merge-conflict checks, large-file guard) on every commit,
so local commits match the `quality` CI job. The ruff hook is pinned to the same
ruff version as `pyproject.toml` / `uv.lock` to avoid drift with CI.

Enable the hooks once after cloning:

```bash
make hooks                          # uv run pre-commit install + run on all files
```

Thereafter the hooks run automatically on `git commit`. To run them on the whole
repo at any time:

```bash
uv run pre-commit run --all-files
```

The hooks are scoped to Python; the `web/` JavaScript frontend and the lockfile
are excluded.

## Makefile targets

Run `make` (or `make help`) for the full, self-documenting list — each target
carries its own one-line description, so this doc does not restate them. The
everyday ones are `make dev` (Qdrant + API + web), `make check` (lint + format
check + tests), and `make hooks`.

Note that `make eval-report` and `make ingest` make real provider API calls,
unlike the unit tests.

## Branch and PR workflow

`main` is protected — never push to it directly. Work on a feature branch and
open a Pull Request.

1. Branch off `main` with a descriptive, prefixed name, e.g.
   `feat/hybrid-retrieval` or `fix/threshold-calibration`.
2. Use **Conventional Commits** for messages, in the imperative mood:
   `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`, `ci:`.
   Example: `feat(ingestion): math-aware PDF extraction`.
3. Keep a PR focused on one deliverable.
4. Open a PR against `main`. CI must be green to merge.

All committed content (code, comments, docstrings, commit messages, PR
descriptions) is in professional English.

## Continuous integration

Four workflows live in `.github/workflows/`. Only the first two run on a PR, and
only the first one blocks a merge.

| Workflow | Runs on | Blocks merge |
| --- | --- | --- |
| `ci.yml` (job: **quality**) | every PR, and pushes to `main` | **yes** — the required check |
| `codeql.yml` | every PR, and pushes to `main` | no |
| `docker-publish.yml` | a `v*` **tag**, or manually | no — never on a PR |
| `smoke.yml` | manually only | no — it needs a live deployment |

**quality** installs the dev group plus the `api`, `agent` and `obs` extras, then
enforces the gate: `ruff check`, `ruff format --check`, `pyright`, and `pytest`
with a coverage floor (`--cov-fail-under`).

Reproduce it locally before opening a PR: the pre-commit hooks cover the ruff half,
and `make check` covers lint + format + tests. Note `make check` does **not** run
`pyright` — run `uvx pyright` if you changed types.
