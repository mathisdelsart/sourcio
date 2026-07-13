# api/

The FastAPI service. A thin HTTP layer: each route delegates to the grounded functions in `core/` and
the nodes in `agent/` — no retrieval or prompting is reimplemented here. The package is organized as
`main.py` (app creation and wiring) plus per-domain routers, with cross-cutting concerns in dedicated
modules.

## Structure

| File | Responsibility |
| --- | --- |
| `main.py` | Builds the app, binds the database engine on startup, and mounts the routers. |
| `routers/` | One module per domain (`ask`, `exercise`, `grade`, `quiz`, `documents`, `sessions`, `history`, `feedback`, `courses`, `source`, `health`, `account`). Each is a thin adapter over `core/` and `agent/`. |
| `schemas/` | Pydantic request/response models, split by domain. Validation and the OpenAPI schema are both derived from them. |
| `deps.py` | Shared FastAPI dependencies: the caller's identity from the JWT, the optional per-request visitor API key, the `X-API-Key` gate. |
| `runtime.py` | A leaf module holding the bound engine and the node/answer functions the routers call. It exists to break the import cycle between `main.py` and the routers, and it is the seam tests monkeypatch. |
| `jobs.py` | In-process registry of background jobs (document ingestion, streamed answers) so a long upload survives the HTTP request and can be polled. |
| `auth.py` | JWT account auth (HS256) and bcrypt password hashing; the opt-in `X-API-Key` gate. |
| `middleware.py` | Request-id propagation, security headers (HSTS when enabled), and an in-process per-IP rate limiter. |
| `logging_config.py` | JSON structured logging at `Settings.log_level`; a global handler turns unhandled errors into a generic 500 without leaking a stack trace. |

## Endpoint domains

| Domain | What it does |
| --- | --- |
| Health | `/health` liveness (always open); `/ready` readiness (503 until the DB engine is bound). |
| Ask / stream | Grounded answer, blocking and as Server-Sent Events; persists the turn as history. |
| Re-explain | Rephrase the last answer at a chosen level (blocking and streaming). |
| Exercise / Grade | Generate an exercise (reference solution withheld) and grade a student's answer. |
| Quiz | Generate a grounded multi-question quiz; grade one answer against its stored solution. |
| Documents | Upload course files, run ingestion as a background job, poll job status, list/delete/fetch originals. |
| Courses / Sources | List indexed courses; fetch a single source chunk by id. |
| Sessions / History | Named conversation threads and their messages; recent turns. |
| Feedback | Record and summarize thumbs up/down on answers. |
| Auth | Register, login (returns a bearer token), and the current user. |
| Config | Non-secret runtime configuration the web app reads. |

Full route-by-route table and the two independent auth layers (opt-in API key + additive JWT) are in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Run it

```bash
docker compose up -d qdrant
uv run uvicorn api.main:app --reload        # or: make api
# interactive docs at http://localhost:8000/docs
uv run python -m pytest tests/test_api.py tests/test_auth.py -q
```

Deploying the CPU-only Docker image (and the full env-var reference): [../docs/DEPLOY.md](../docs/DEPLOY.md).
</content>
