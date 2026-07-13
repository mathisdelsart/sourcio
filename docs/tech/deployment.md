# Deployment and CI

Companion to [DEPLOY.md](../DEPLOY.md), which is the step-by-step procedure. This note records
why the topology is what it is.

## Topology

```
Vercel                  Hugging Face Space (Docker)        Managed services
┌──────────┐  HTTPS     ┌────────────────────────┐         ┌──────────────┐
│ Next.js  │──────────► │ FastAPI (uvicorn)      │────────►│ Qdrant Cloud │
│ (static) │            │ + bge-m3 embeddings    │         └──────────────┘
└──────────┘            │ + cross-encoder (opt)  │         ┌──────────────┐
                        └────────────────────────┘────────►│ Neon Postgres│
                                                           └──────────────┘
```

Three hosts, each chosen for what it is suited to: the frontend is static and belongs on a CDN;
the API needs a Python runtime with several gigabytes of ML wheels; and the stateful components
must **outlive the container**, which is the constraint that determines everything else.

## The Docker image

**CPU-only torch, installed first.** A default `pip install torch` pulls the CUDA build:
multiple gigabytes of GPU libraries that will never execute on a CPU host.

```dockerfile
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.12.*"
```

Installing it from PyTorch's CPU index, as its own layer, does two things: it removes most of
the image size, and it lets the heavy download **cache independently** of the application
dependency layer, so changing a Python dependency does not re-download torch.

**Multi-stage build.** Stage one builds a virtualenv; stage two copies only that virtualenv and
the source. Build tooling never reaches the runtime image.

**Minimal surface.** Only the modules the API imports are copied (`api/`, `core/`, `agent/`,
`db/`, `ingestion/`). Tests, documentation and the frontend are excluded — a smaller image and a
smaller attack surface.

**Non-root user**, and a `HEALTHCHECK` against `/health` so the platform can distinguish "the
process started" from "the application is ready".

## Ephemeral filesystems

A container's disk does not survive a restart. On a free Space, a rebuild or a sleep/wake cycle
discards it. Two consequences shaped the architecture:

1. **SQLite is unusable in production.** The file, and every account in it, is lost at the next
   restart. Hence managed Postgres — see [database.md](database.md).
2. **Uploaded originals do not persist.** The course remains indexed and answerable (chunks live
   in Qdrant, which is external), but "view original file" returns 404. Hence optional Cloudflare
   R2 object storage.

**The failure is delayed, which is what makes it hazardous.** Immediately after a deployment
everything appears durable, because the container has not yet restarted. The loss occurs at the
*next* restart, after the deployment has been verified and attention has moved on.

Anything a container writes to its own disk is a temporary file, whether or not that was the
intent.

## Continuous integration

One workflow gates merges — `ci.yml`, job `quality`:

- `ruff check` — lint
- `ruff format --check` — formatting
- `pyright` — static type checking
- `pytest` with a coverage floor (`--cov-fail-under`)

CodeQL runs on every pull request but does not block. The Docker publish workflow fires on a
`v*` tag, never on a pull request. The smoke workflow is manual, as it requires a live
deployment.

**853 tests, no network and no model load.** This is a design constraint rather than an
accident: the LLM, the judge, the retriever and the database session are all injectable, so
tests pass fakes. A suite requiring an API key is a suite that does not get run.

### A blind spot worth recording

`get_llm` wraps the model in `.with_config(callbacks=...)` **only when callbacks exist**. CI has
no `.env`, so callbacks were always empty and that branch never executed. On a developer machine
with LangFuse configured it did execute, and failed.

**Eleven tests failed for anyone with observability configured, while CI remained green.**

Green CI demonstrates that the code works *in CI's environment*. Where that environment differs
systematically from the one people develop in, the signal is weaker than it appears. The fix was
an autouse fixture making the test environment hermetic.

## Operational characteristics

**Cold start.** A free CPU Space sleeps when idle; the first request after a nap pays for loading
the embedding model. Mitigated by lazy loading and a small image, not eliminated.

**First limit reached under load** is the LLM provider's rate limit, well before the application
itself. Observed directly: the 71-case benchmark exhausted the free tier's per-minute token
budget and received a series of `413`s. The API translates provider capacity errors into an
actionable message — advising the caller to supply their own key — rather than surfacing an
opaque provider error.

**Horizontal scaling** is not currently needed. The application is already stateless (JWT,
external database, external vector store), so it would be a deployment change rather than a
rewrite.
