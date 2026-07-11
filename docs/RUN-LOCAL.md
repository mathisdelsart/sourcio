# Run the whole stack locally for free

This guide ties the three pieces together — the Qdrant vector store (Docker),
the FastAPI backend (host), and the Next.js web frontend (host) — and runs them
with **no paid API calls** by pointing the LLM at a local
[Ollama](https://ollama.com) server. It is the end-to-end "run everything" recipe:
installing Ollama, which models to pull, the `LLM_PROVIDER=ollama` switch, and
wiring the three services together.

## Prerequisites

- **Docker** — runs Qdrant (`docker compose up -d qdrant`).
- **uv** — manages the Python backend (`make api`).
- **Node.js** (18+) and **npm** — run the web frontend (`make web`).
- **Ollama**, with the chat model (and, for ingestion, the vision model) pulled:

  ```sh
  ollama serve            # leave running
  ollama pull llama3.1    # chat model (router / explain / generate / grade)
  ```

  For math-aware PDF ingestion you also need a local vision model
  (e.g. `ollama pull llama3.2-vision`); prose `.md` / `.txt` ingestion needs none.

Everything else (embeddings `bge-m3`, the cross-encoder reranker) already runs
locally and free.

## One command to orchestrate

```sh
make dev
```

`make dev` starts Qdrant detached, then prints the two commands to run (the API
and the web server are long-running foreground processes, so each gets its own
terminal). Run them as shown below.

## The exact sequence

```sh
# 1) Vector store (Docker, detached)
make qdrant                              # http://localhost:6333

# 2) API on :8000 — Ollama provider, zero paid calls (own terminal)
LLM_PROVIDER=ollama make api             # http://localhost:8000

# 3) Web frontend on :3000 (own terminal)
make web                                 # http://localhost:3000
```

`make web` runs `npm install` then `npm run dev`. The first run installs the
frontend dependencies; later runs are fast.

> Need to ingest a course first? With the stack local, ingestion is also free:
> `make ingest PDF=path/to/course.pdf COURSE="..."` (optionally `--hybrid` to skip
> the vision model on text-heavy decks). See [ingestion/README.md](../ingestion/README.md).

## What the web frontend needs

The frontend talks to the API over HTTP. Point it at the backend with one
environment variable in `web/.env.local` (an example file already exists at
`web/.env.local.example` — copy it):

```sh
cd web
cp .env.local.example .env.local
```

```ini
# web/.env.local
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
# NEXT_PUBLIC_API_KEY=        # leave empty when the API runs without auth
```

Both values are also overridable at runtime from the in-app **Settings** panel.
The default base URL is already `http://localhost:8000`, so for the standard
local setup you can skip the file entirely.

## Cross-origin note

The web app (`:3000`) and the API (`:8000`) are different origins, so the
browser applies CORS to every request. If your API build does not allow the
`http://localhost:3000` origin, requests fail in the browser with a CORS error
even though the API is healthy. Two zero-cost ways to confirm/work around it:

- The header health badge polls `/health`; a quick `curl http://localhost:8000/health`
  from a terminal confirms the API itself is up independently of CORS.
- If the browser reports a CORS failure, enable the `http://localhost:3000`
  origin on the API (CORS middleware) and restart it — the frontend code itself
  needs no change.

## Troubleshooting

**`/ask` or registering returns a 500 with `no such column` / `no such table`**
in the API logs (e.g. `no such column: students.user_id`, or a missing
`users` / `sessions` / `reviews` table). Your local `app.db` predates a schema
change. The API's startup uses SQLAlchemy `create_all`, which adds missing
tables but never alters existing ones, so the dev DB must be reset (or migrated)
after a model or migration change. Fix it with either:

```sh
make reset-db                                   # delete app.db, recreated on next start
# or, to migrate in place instead of wiping data:
uv run --extra migrations alembic upgrade head
```

Then restart the API.

## 30-second smoke checklist

1. Open `http://localhost:3000` — the health badge in the header turns **green**.
2. **Ask** an *in-course* question (covered by an indexed deck) -> you get a
   grounded answer **with source citation chips** (chapter / page).
3. **Ask** an *out-of-course* question (not in any deck) -> you get an explicit
   **"refused — not covered"** response instead of an invented answer.

If all three hold, the full local, zero-cost stack is working end to end.

