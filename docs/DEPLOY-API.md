# Deploying the API service (CPU-only Docker image)

This document describes the production Docker image for the **API service**
(`api.main:app`). It is meant for **cloud deployment** on free or low-cost tiers
(e.g. Hugging Face Spaces, Render). The image is CPU-only: it installs a CPU build
of `torch` so no CUDA wheels are pulled, keeping it small enough for those tiers.

> **Local development is unchanged.** Day-to-day, only the vector store runs in
> Docker (`docker compose up -d qdrant`); the API and UI run on the host (`make
> api` / `make ui`). The default `torch` build is multi-gigabyte (CUDA), which is
> why the API is not containerized locally. This image exists for the cloud, where
> a self-contained, CPU-only artifact is what the platform expects.

## What the image contains

- Python 3.12 (matches `requires-python`).
- **CPU-only `torch`**, installed from the PyTorch CPU wheel index
  (`https://download.pytorch.org/whl/cpu`) before anything else, so no CUDA
  libraries are pulled.
- The runtime dependencies the API needs: base deps plus the `api` and `agent`
  extras, `langfuse` (optional tracing), `sentence-transformers` for local
  `bge-m3` query embeddings and the cross-encoder reranker, and `boto3` for the
  optional Cloudflare R2 durable file storage (see below — inert unless the
  `R2_*` variables are set).
- The application source: `api/`, `core/`, `agent/`, `db/`, and `ingestion/`
  (only its schema/embed/index modules are imported by the retrieval path).

Deliberately **excluded**: Streamlit UI, the Ollama client (`local` extra), the
PDF ingestion runtime (PyMuPDF — offline only), and Alembic (the API creates its
tables via SQLAlchemy on startup, so no migration step runs on boot).

## Build

```bash
docker build -t grounded-rag-api .
```

The `torch` download is large (CPU wheels). The build caches it in its own layer,
so repeated builds are fast as long as the dependency layers are unchanged.

## Run

The API needs a reachable Qdrant collection and an LLM provider. Example with
OpenAI and a remote Qdrant:

```bash
docker run --rm -p 8000:8000 \
  -e QDRANT_URL="https://your-qdrant-host:6333" \
  -e OPENAI_API_KEY="sk-..." \
  grounded-rag-api
```

Fully local LLM via Ollama instead of OpenAI (point at an Ollama server reachable
from the container):

```bash
docker run --rm -p 8000:8000 \
  -e QDRANT_URL="https://your-qdrant-host:6333" \
  -e LLM_PROVIDER=ollama \
  -e OLLAMA_BASE_URL="http://your-ollama-host:11434" \
  grounded-rag-api
```

Then check `http://localhost:8000/health` and the docs at
`http://localhost:8000/docs`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `QDRANT_URL` | yes | Qdrant endpoint holding the indexed course chunks (default `http://localhost:6333`). |
| `QDRANT_API_KEY` | yes (Qdrant Cloud) | API key for a hosted Qdrant (Cloud) cluster; unset for a local Qdrant. |
| `QDRANT_COLLECTION` | no | Collection name (default `courses`). |
| `OPENAI_API_KEY` | yes (OpenAI) | Provider key when using the default OpenAI models. |
| `LLM_PROVIDER` | no | `groq` (free hosted) or `ollama` (local) to route every role off OpenAI. |
| `GROQ_API_KEY` | yes (`LLM_PROVIDER=groq`) | Key for the free hosted Groq LLM. |
| `OLLAMA_BASE_URL` | no | Ollama server URL when `LLM_PROVIDER=ollama` (default `http://localhost:11434`). |
| `LLM_<ROLE>` | no | Per-role model override (e.g. `LLM_GENERATE=gpt-4o`), provider prefix allowed. |
| `DATABASE_URL` | no | Relational store (default `sqlite:///./app.db`; set a Postgres URL for persistence). |
| `REQUIRE_AUTH` | yes (public) | `true` forces a valid JWT on every data endpoint. Leave unset only for a private/local instance. |
| `JWT_SECRET` | yes (`REQUIRE_AUTH=true`) | Strong random secret used to sign auth tokens. The app refuses to boot with a weak/default value when auth is on. |
| `CORS_ORIGINS` | yes (browser client) | Comma-separated allowed origins (e.g. the Vercel web URL); the browser app cannot call the API without it. |
| `ENABLE_HSTS` | no | `true` to send the HSTS header (HTTPS deployments). |
| `API_KEY` | no | When set, clients must send a matching `X-API-Key` header on the mutating endpoints and `/history`. `/health` stays open. |
| `RERANKER_MODEL` | no | Enables the cross-encoder reranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`). |
| `MULTI_QUERY` / `HYDE` | no | Opt-in retrieval strategies (query rewriting / hypothetical-doc embedding). |
| `SIMILARITY_THRESHOLD` | no | Refusal floor for retrieval (default `0.35`); tune per corpus. |
| `LANGFUSE_PUBLIC_KEY` | no | LangFuse public key; set together with the secret key to enable tracing (see `OBSERVABILITY.md`). |
| `LANGFUSE_SECRET_KEY` | no | LangFuse secret key (set as a **secret**). Both keys present ⇒ every LLM call is traced. |
| `LANGFUSE_HOST` | no | LangFuse base URL (default `https://cloud.langfuse.com`; the SDK var is `LANGFUSE_HOST`, not `LANGFUSE_BASE_URL`). |
| `R2_ACCOUNT_ID` | no | Cloudflare account id; also derives the R2 endpoint. Set together with the three below to enable durable file storage (see below). |
| `R2_ACCESS_KEY_ID` | no | R2 API token access key id. |
| `R2_SECRET_ACCESS_KEY` | no | R2 API token secret (set as a **secret**). |
| `R2_BUCKET` | no | R2 bucket name that stores uploaded course-file originals. |
| `PORT` | no | Port the server binds to (default `8000`). See the Hugging Face note below. |

Remaining optional settings (reranker tuning, hybrid retrieval, LLM cache, budget
cap) live in `.env.example`.

**Public deployment (this project's live HF Space) sets:** `QDRANT_URL` +
`QDRANT_API_KEY` (Qdrant Cloud), `DATABASE_URL` (Neon Postgres), `LLM_PROVIDER=groq`
+ `GROQ_API_KEY`, `REQUIRE_AUTH=true` + a strong `JWT_SECRET`, `CORS_ORIGINS` (the
Vercel URL), `PORT=7860`, optionally the retrieval flags, the four `R2_*`
(durable uploads) and the three `LANGFUSE_*` (tracing). Secrets (`*_KEY`,
`*_SECRET*`, `JWT_SECRET`, DB password) go in the Space's **Secrets**; the rest can
be **Variables**.

## Port handling and Hugging Face Spaces

The container reads `$PORT` and falls back to `8000`. Hugging Face Spaces injects
`PORT` (commonly `7860`) and routes traffic to it, so the same image works there
with no change — Spaces sets the variable for you. On other platforms, set `PORT`
to match what the platform expects, or map the default `8000`.

> Persistence note: the default SQLite database lives inside the container and is
> lost on redeploy. For durable student history, point `DATABASE_URL` at a managed
> Postgres instance. Likewise, Qdrant must be a service the container can reach;
> this image does not bundle a vector store. **Uploaded course-file originals**
> (the PDF/`.md`/`.txt` a user uploads, kept so they can re-open the intact file
> later) are written to local disk by default, which is *also* wiped on
> redeploy/sleep-wake — the indexed content survives fine in Qdrant, but the raw
> file does not. See the next section to make it durable.

## Durable file storage (Cloudflare R2)

Uploaded course-file originals are saved to local disk by default (zero setup,
fine for local dev). In production that disk is the container's own ephemeral
filesystem, so a redeploy or a free-tier sleep/wake cycle silently deletes every
stored original — "view original file" then 404s even though the course is
still fully indexed and answerable. Setting the four `R2_*` variables above
switches storage to Cloudflare R2 (an S3-compatible object store with a
generous free tier), which survives restarts. Leaving any of them unset keeps
the exact local-disk behavior — this is entirely optional.

### Setup steps (Cloudflare dashboard)

1. **Create a Cloudflare account** (if you don't have one already) at
   https://dash.cloudflare.com/sign-up — the free tier is sufficient.
2. In the dashboard sidebar, go to **R2 Object Storage** and click **Create
   bucket**. Give it a name (e.g. `sourcio-uploads`) and create it with the
   default settings (no public access needed — the API reads/writes it via the
   S3 API with a secret key, never a public URL). This name is your
   **`R2_BUCKET`** value.
3. Find your **Account ID**: it's shown on the main Cloudflare dashboard
   overview page (right-hand sidebar under your account), and also on the R2
   Object Storage landing page. This is your **`R2_ACCOUNT_ID`** value.
4. Create an API token scoped to just this bucket: in **R2 Object Storage** →
   **Manage R2 API Tokens** (or **Account API Tokens** from the R2 overview) →
   **Create API Token**. Configure it as:
   - **Permissions**: `Object Read & Write`
   - **Specify bucket(s)**: restrict to the bucket created in step 2 (don't
     grant account-wide access)
   - **TTL**: no expiry (or a long one — rotate manually later if desired)
5. Click **Create API Token**. Cloudflare shows the credentials **once** — copy
   both immediately:
   - **Access Key ID** → this is your **`R2_ACCESS_KEY_ID`**
   - **Secret Access Key** → this is your **`R2_SECRET_ACCESS_KEY`**
6. Set all four as environment variables on the deployed API (e.g. HF Spaces →
   your Space → **Settings** → **Repository secrets** / **Variables**, or via
   `docker run -e ...` for another host):
   ```
   R2_ACCOUNT_ID=<from step 3>
   R2_ACCESS_KEY_ID=<from step 5>
   R2_SECRET_ACCESS_KEY=<from step 5>
   R2_BUCKET=<from step 2>
   ```
7. Redeploy/restart the API so it picks up the new environment variables. No
   code change, no re-ingestion, and no migration is needed — the next upload
   is written to R2 automatically, and existing local-disk files (if the
   container hasn't restarted since they were uploaded) remain viewable too
   since local disk is kept as a fallback read path.
