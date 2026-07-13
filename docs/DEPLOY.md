# Cloud deployment (Vercel + Hugging Face Spaces + Qdrant Cloud + Groq)

This guide stands the whole tutor up on free tiers with a **free hosted LLM**, so
the **owner pays $0** and **visitors do not need their own key**. Every visitor
registers an account and only ever sees the documents they uploaded (per-account
isolation is enforced by `REQUIRE_AUTH=true`).

| Layer | Host | Free tier |
|---|---|---|
| Web frontend (`web/`, Next.js) | **Vercel** | Hobby plan |
| API service (`api.main:app`) | **Hugging Face Spaces** (Docker) | Free CPU Space |
| Vector store (course chunks) | **Qdrant Cloud** | Free 1 GB cluster |
| LLM | **Groq** (`LLM_PROVIDER=groq`) | Free tier, no card |

The pieces fit together as: the browser loads the Vercel app, which calls the
Hugging Face Space API, which retrieves grounded chunks from Qdrant Cloud and asks
a Groq-hosted Llama model to answer over them. Groq exposes an OpenAI-style API
and is wired through the model-agnostic factory in `core/config.py`, so no code
changes are needed — only environment variables. (The API ships as a CPU-only
Docker image — the root `Dockerfile`; see [The API Docker image](#the-api-docker-image).)

---

## 0. Prerequisites

- The repo pushed to GitHub (Vercel and Hugging Face import from a Git repo).
- The course deck PDF available locally for the one-time ingestion step.
- Accounts (all free, no card): **Groq**, **Qdrant Cloud**, **Hugging Face**,
  **Vercel**. You can sign in to most with GitHub.

Qdrant Cloud authentication is already wired: `core/config.py` exposes
`qdrant_api_key`, and both `core/retrieval.py` and `ingestion/index.py` pass it to
`QdrantClient`. A blank key is a no-op for a local cluster, so nothing extra is
required to target the cloud beyond setting `QDRANT_API_KEY`.

---

## 1. Groq — the free hosted LLM

1. Sign up at <https://console.groq.com> and create an **API key**.
2. That single key (`GROQ_API_KEY`) is all the API needs. Setting
   `LLM_PROVIDER=groq` routes every chat role (router, explain, generate, grade,
   judge) to `groq:llama-3.3-70b-versatile` (override with `GROQ_CHAT_MODEL`).
   `langchain-groq` reads `GROQ_API_KEY` straight from the environment, so no base
   URL or per-role config is needed.
3. Groq has **no vision model**, so the `extract` (vision) role falls back to the
   OpenAI default. That role is only exercised during ingestion of scanned/slide
   PDFs, a one-time offline step (section 2) — it is never invoked by the deployed
   `/ask`, `/exercise`, `/quiz`, or `/grade` endpoints. The public API therefore
   runs entirely on Groq.

The `groq` extra pulls the integration (`uv sync --extra groq`); on the Space it is
installed via the Docker image, so you do not install it by hand.

---

## 2. Qdrant Cloud — the vector store (and one-time ingestion)

1. Sign up at <https://cloud.qdrant.io> and create a **free cluster** (1 GB is
   plenty for a course deck of a few dozen slides).
2. From the cluster page copy two values:
   - the **cluster URL** (`https://xxxx-xxxx.<region>.cloud.qdrant.io`; it serves
     HTTPS on port `6333`),
   - an **API key** (create one in the cluster's API-keys section).
3. **Ingest the deck into the cloud cluster.** Ingestion runs on your machine (it
   needs the local `bge-m3` embedding model and PyMuPDF). Point it at the cloud
   cluster via the same `QDRANT_*` variables the app reads. The math-aware PDF path
   calls the **vision LLM**, so provide an `OPENAI_API_KEY` for this one-time step
   (Groq has no vision) and budget a little credit for it:

   ```bash
   export QDRANT_URL="https://xxxx-xxxx.<region>.cloud.qdrant.io:6333"
   export QDRANT_API_KEY="<your-qdrant-cloud-api-key>"
   export OPENAI_API_KEY="<key-for-the-one-time-vision-extraction>"

   uv run --extra ingestion python -m ingestion.run <your-course>.pdf \
     --course "ELEC2885 Wavelet Transform" --concurrency 1
   ```

   The flags (`--hybrid`, `--pages`, `--concurrency`, `--batch-size`) match local
   ingestion — see the README. Add `--sparse` if you intend to enable hybrid
   retrieval on the Space.
4. Note the collection name. The default is `courses` (`QDRANT_COLLECTION`); keep
   it unless you change it consistently here and in the Space secrets.

> Free-tier note: idle Qdrant Cloud free clusters can be paused. If the demo
> returns connection errors after inactivity, wake the cluster from the console.

---

## 3. API on Hugging Face Spaces — the backend

1. Create a new **Space** at <https://huggingface.co/new-space>:
   - **SDK: Docker** (blank template).
   - **Hardware: CPU basic** (the free tier).
2. Make the Space build from this repo's `Dockerfile`: connect the Space to your
   GitHub repo, or push the repo (including the root `Dockerfile`) to the Space's
   own Git remote. No extra config is needed — the `Dockerfile` defines the
   entrypoint and honors `$PORT`.
3. Set the Space **secrets** (Settings → Variables and secrets). For this free-tier
   deployment set: `LLM_PROVIDER=groq` + `GROQ_API_KEY`, `QDRANT_URL` +
   `QDRANT_API_KEY` (Qdrant Cloud), `REQUIRE_AUTH=true` + a strong `JWT_SECRET`,
   `CORS_ORIGINS` (your Vercel URL), and `PORT=7860`. Optionally add `DATABASE_URL`
   (durable Postgres), the retrieval flags, the four `R2_*` (durable uploads) and
   the three `LANGFUSE_*` (tracing). See the full
   [environment variable reference](#environment-variables) for every option.
   Secrets (`*_KEY`, `*_SECRET*`, `JWT_SECRET`, DB password) go in the Space's
   **Secrets**; the rest can be **Variables**.

   > Generate a strong `JWT_SECRET`, e.g.
   > `python -c "import secrets;print(secrets.token_urlsafe(48))"`. The app refuses
   > to boot with the insecure default when `REQUIRE_AUTH=true`.

4. **Port.** Spaces injects `$PORT` (commonly `7860`) and routes traffic to it; the
   `Dockerfile` binds `uvicorn` to `${PORT:-8000}`, so the same image works there
   with no change. On other platforms, set `PORT` to what the platform expects.
5. Wait for the build, then confirm the API is live:

   ```
   https://<user>-<space-name>.hf.space/health   ->  {"status":"ok"}
   https://<user>-<space-name>.hf.space/ready     ->  readiness (deps reachable)
   https://<user>-<space-name>.hf.space/docs      ->  interactive API docs
   ```

   The Space's public URL is the API base URL used by the frontend.

> **Persistence:** the default SQLite database lives inside the container and is
> reset when the Space rebuilds or sleeps, so accounts and history are **ephemeral**
> on the free tier. Grounded answers, exercises and grading still work (the course
> lives in Qdrant), but users lose their logins. For durable data, point
> `DATABASE_URL` at a managed Postgres — see [OPERATIONS.md](OPERATIONS.md).
> Uploaded file originals are likewise ephemeral on local disk in production; make
> them durable with Cloudflare R2 — see [Durable file storage](#durable-file-storage-cloudflare-r2).

> Free CPU Spaces sleep when idle and cold-start on the next request; the first call
> after a nap is slow while the embedding model loads. Expected on the free tier.

---

## 4. Web on Vercel — the frontend

The Next.js app lives in `web/`. `web/vercel.json` pins the framework to Next.js.

1. At <https://vercel.com/new>, **import** the GitHub repo.
2. Set **Root Directory** to `web/`. This is essential: the Next.js project is in
   the subdirectory, not at the repo root. Vercel then auto-detects Next.js.
3. Add the **Environment Variables** (Project Settings → Environment Variables) for
   the Production environment:

   | Variable | Value | Required |
   |---|---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | your Space URL, e.g. `https://<user>-<space-name>.hf.space` | **yes** |
   | `NEXT_PUBLIC_API_KEY` | the same value you set as the API `API_KEY` secret | **open demo:** leave unset. **Password-gated:** see below |

   `NEXT_PUBLIC_*` variables are inlined into the client bundle at build time. If
   you change either value, **redeploy**. The base URL is read in `web/lib/api/client.ts`;
   a trailing slash is fine (it is trimmed).

   > **Do not bake `NEXT_PUBLIC_API_KEY` when you want a password gate.** Inlining it
   > makes the public site auto-send the key to everyone, defeating the gate. Leave
   > it unset and have gated visitors paste the key in Settings — see
   > [Access modes](#access-modes-open-demo-vs-password-gated).
4. Deploy. Vercel gives a public URL (e.g. `https://<project>.vercel.app`). Set the
   Space's `CORS_ORIGINS` to exactly that origin (section 3). Open the app: the
   health indicator turns green once it reaches the Space, and — after you register
   and log in — Ask / Re-explain / Exercise / Grade / Quiz / History work end to end.

---

## Access modes: open demo vs. password-gated

The API supports two deployment postures. Pick one deliberately — the trade-off is
public reach vs. private control, and the wiring differs.

### Open demo (default)

- API: `LLM_PROVIDER=groq`, **no** `API_KEY`.
- Vercel: **do not** set `NEXT_PUBLIC_API_KEY`.

Anyone can open the app, register an account, and use it on the free Groq tier.
`REQUIRE_AUTH=true` still isolates each account to its own documents/history. This
is the right choice for a public portfolio demo. Note the Groq free tier is
token-rate-limited under load, so a burst of simultaneous users may hit a
rate-limit error and should retry.

### Password-gated (recruiters only)

- API: set `API_KEY=<a long random secret>` (e.g.
  `python -c "import secrets;print(secrets.token_urlsafe(24))"`).
- Vercel: **do NOT set `NEXT_PUBLIC_API_KEY`.** Baking it into the build makes the
  public site auto-send the key to every visitor, defeating the gate.

With `API_KEY` set and `NEXT_PUBLIC_API_KEY` unset, the deployed site cannot call
the API until a visitor supplies the key: they open the app, go to **Settings**, and
paste the secret (sent as the `X-API-Key` header on every request). Share the key
privately with the people you want to let in. The shared secret *is* the gate — no
email/user management or invite system — with the trade-off that anyone holding it
has full access and there is no per-person revocation short of rotating the key.

---

## Seed a demo account at deploy time

So a visitor sees a filled, working app on first load (not an empty shell): after
deploying, **register one demo account** through the app and **ingest a neutral,
non-personal sample course** into it (a public lecture deck, an open-courseware
chapter — anything you are comfortable showing the world). Then display those demo
credentials on the landing page so anyone can log in and try Ask / Exercise / Quiz
immediately.

> **Never expose personal documents in the public demo.** Do not ingest your CV,
> thesis, private notes, or any sensitive material into the demo account — once
> ingested, its content is retrievable by anyone who logs in. Keep the demo corpus
> strictly neutral and shareable.

---

## The API Docker image

The API ships as a **CPU-only** Docker image (the root `Dockerfile`), meant for
free/low-cost tiers (Hugging Face Spaces, Render). It installs a CPU build of
`torch` so no CUDA wheels are pulled, keeping it small enough for those tiers.

> **Local development is unchanged.** Day-to-day, only the vector store runs in
> Docker (`docker compose up -d qdrant`); the API and web app run on the host
> (`make api` / `make web`). The default `torch` build is multi-gigabyte (CUDA),
> which is why the API is not containerized locally — this image exists for the
> cloud, where a self-contained CPU-only artifact is what the platform expects.

**Contains:** Python 3.12; a CPU-only `torch` from the PyTorch CPU wheel index; the
runtime deps the API needs (base + the `api` and `agent` extras, `langfuse` for
optional tracing, `sentence-transformers` for local `bge-m3` query embeddings and
the cross-encoder reranker, `boto3` for optional R2 storage); and the application
source (`api/`, `core/`, `agent/`, `db/`, and the schema/embed/index parts of
`ingestion/`). **Deliberately excluded:** the Next.js frontend (deployed on
Vercel), the Ollama client (`local` extra), the PyMuPDF ingestion runtime (offline
only), and Alembic (the API creates its tables via SQLAlchemy on startup).

**Build and run standalone** (e.g. to test the image locally):

```bash
docker build -t sourcio-api .

# Example: OpenAI + a remote Qdrant
docker run --rm -p 8000:8000 \
  -e QDRANT_URL="https://your-qdrant-host:6333" \
  -e OPENAI_API_KEY="sk-..." \
  sourcio-api

# Example: fully local LLM via an Ollama server reachable from the container
docker run --rm -p 8000:8000 \
  -e QDRANT_URL="https://your-qdrant-host:6333" \
  -e LLM_PROVIDER=ollama \
  -e OLLAMA_BASE_URL="http://your-ollama-host:11434" \
  sourcio-api
```

Then check `http://localhost:8000/health` and the docs at `http://localhost:8000/docs`.

---

## Environment variables

The single reference for the API's environment. Only `QDRANT_URL` and the
provider key are required for a minimal run; the rest are opt-in.

| Variable | Required | Purpose |
|---|---|---|
| `QDRANT_URL` | yes | Qdrant endpoint holding the indexed course chunks (default `http://localhost:6333`). |
| `QDRANT_API_KEY` | yes (Qdrant Cloud) | API key for a hosted Qdrant cluster; unset for a local Qdrant. |
| `QDRANT_COLLECTION` | no | Collection name (default `courses`). |
| `OPENAI_API_KEY` | yes (OpenAI) | Provider key when using the default OpenAI models. |
| `LLM_PROVIDER` | no | `groq` (free hosted) or `ollama` (local) to route every role off OpenAI. |
| `GROQ_API_KEY` | yes (`LLM_PROVIDER=groq`) | Key for the free hosted Groq LLM. |
| `OLLAMA_BASE_URL` | no | Ollama server URL when `LLM_PROVIDER=ollama` (default `http://localhost:11434`). |
| `LLM_<ROLE>` | no | Per-role model override (e.g. `LLM_GENERATE=gpt-4o`), provider prefix allowed. |
| `DATABASE_URL` | no | Relational store (default `sqlite:///./app.db`; a `postgresql+psycopg://` URL for persistence — see [OPERATIONS.md](OPERATIONS.md)). |
| `REQUIRE_AUTH` | yes (public) | `true` forces a valid JWT on every data endpoint and isolates each account. Leave unset only for a private/local instance. |
| `JWT_SECRET` | yes (`REQUIRE_AUTH=true`) | Strong random secret used to sign auth tokens. The app refuses to boot with a weak/default value when auth is on. |
| `CORS_ORIGINS` | yes (browser client) | Comma-separated allowed origins (e.g. the Vercel web URL); the browser app cannot call the API without it. |
| `API_KEY` | no | When set, clients must send a matching `X-API-Key` header on the mutating endpoints and `/history`; `/health` stays open. See [Access modes](#access-modes-open-demo-vs-password-gated). |
| `RATE_LIMIT_PER_MINUTE` | no | Per-IP request cap. **Auto-defaults to 60/min when `REQUIRE_AUTH=true`**; set a higher value to raise the ceiling. `0`/unset means "auto" (off locally, 60 in public mode). |
| `MAX_UPLOAD_MB` | no | Maximum accepted upload size in MB (default 25); larger files are rejected with HTTP 413. |
| `ENABLE_HSTS` | no | `true` to send the HSTS header (HTTPS deployments). |
| `RERANKER_MODEL` | no | Enables the cross-encoder reranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`); adds CPU cost per query. |
| `MULTI_QUERY` / `HYDE` | no | Opt-in retrieval strategies (query rewriting / hypothetical-doc embedding). |
| `SIMILARITY_THRESHOLD` | no | Refusal floor for retrieval (default `0.35`); tune per corpus. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | no | LangFuse tracing; both keys present ⇒ every LLM call is traced. See [OPERATIONS.md](OPERATIONS.md). |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | no | Cloudflare R2 durable upload storage; set all four to enable — see below. |
| `PORT` | no | Port the server binds to (default `8000`). Hugging Face Spaces injects this (commonly `7860`). |

Remaining fine-tuning settings (reranker tuning, hybrid retrieval, LLM cache,
budget cap) live in `.env.example`.

---

## Durable file storage (Cloudflare R2)

Uploaded course-file originals (the PDF/`.md`/`.txt` a user uploads, kept so they
can re-open the intact file later) are saved to local disk by default — zero setup,
fine for local dev. In production that disk is the container's own ephemeral
filesystem, so a redeploy or a free-tier sleep/wake cycle silently deletes every
stored original: "view original file" then 404s even though the course is still
fully indexed and answerable. Setting the four `R2_*` variables switches storage to
Cloudflare R2 (an S3-compatible object store with a generous free tier), which
survives restarts. Leaving any of them unset keeps the exact local-disk behavior —
entirely optional.

### Setup steps (Cloudflare dashboard)

1. **Create a Cloudflare account** (free tier is sufficient) at
   <https://dash.cloudflare.com/sign-up>.
2. In the sidebar go to **R2 Object Storage** → **Create bucket**. Name it (e.g.
   `sourcio-uploads`) with default settings (no public access needed — the API
   reads/writes via the S3 API with a secret key). This name is your **`R2_BUCKET`**.
3. Find your **Account ID** (Cloudflare dashboard overview, right-hand sidebar, and
   the R2 landing page). This is **`R2_ACCOUNT_ID`**.
4. Create an API token scoped to just this bucket: **R2 Object Storage** → **Manage
   R2 API Tokens** → **Create API Token**, with **Object Read & Write** permission,
   restricted to the bucket from step 2, and no/long expiry.
5. Cloudflare shows the credentials **once** — copy both: **Access Key ID** →
   **`R2_ACCESS_KEY_ID`**, **Secret Access Key** → **`R2_SECRET_ACCESS_KEY`**.
6. Set all four on the deployed API (HF Space → Settings → Secrets, or `docker run
   -e ...`), then redeploy/restart. No code change, re-ingestion, or migration is
   needed — the next upload is written to R2 automatically, and existing local-disk
   files remain viewable via the local fallback read path.

---

## Alternatives

- **Google Gemini free tier.** Gemini also offers a free tier via
  `langchain-google-genai` (add it as a dependency). It plugs into the same
  factory: use a per-role prefix `LLM_<ROLE>=google_genai:gemini-1.5-flash` (with
  `GOOGLE_API_KEY` set). A global `LLM_PROVIDER=gemini` switch is not wired today;
  the per-role prefix path already works with any provider `init_chat_model`
  understands, so it needs no code change beyond installing the integration.
- **Bring-your-own-key (visitor pays).** The app already supports a visitor pasting
  their own OpenAI/Anthropic key in the UI (sent per-request as `X-OpenAI-Key`,
  used transiently, never stored), so premium usage runs on the visitor's own
  credit while the free Groq default stays the baseline.

---

## Cost & limits

- **The owner pays $0.** Qdrant Cloud (free cluster), Hugging Face (free CPU
  Space), Vercel (Hobby), and Groq (free tier) all cost nothing for a demo of this
  size, and visitors need no key of their own.
- **Free-tier rate limits.** Groq (and Gemini) free tiers cap requests/tokens per
  minute — fine for a light-traffic demo; a burst of simultaneous users may hit a
  rate-limit error and should retry. Set `LLM_BUDGET_TOKENS` and/or `API_KEY` on
  the Space for an extra ceiling.
- **Built-in per-IP throttle.** With `REQUIRE_AUTH=true` the API auto-applies a
  60/min per-IP cap (excess → HTTP 429), so a public deployment is protected
  without extra config. Raise it with an explicit `RATE_LIMIT_PER_MINUTE`. Uploads
  are additionally capped at `MAX_UPLOAD_MB` (default 25 MB, rejected with 413).
- **Ingestion is the one paid touchpoint** — and only if you ingest scanned/slide
  PDFs, whose math-aware vision extraction uses OpenAI. Run it once, locally,
  against the cloud cluster (section 2). `.md`/`.txt` prose ingestion uses no LLM at
  all (only local embeddings), so those uploads are free even on the Space.

---

## Deployment order, at a glance

1. **Groq**: create the API key.
2. **Qdrant Cloud**: create the free cluster, copy URL + API key, ingest the deck
   (one-time, needs an OpenAI key for vision).
3. **Hugging Face Space**: Docker Space from the root `Dockerfile`; set
   `LLM_PROVIDER=groq` + `GROQ_API_KEY` + `QDRANT_URL` + `QDRANT_API_KEY` +
   `REQUIRE_AUTH=true` + a strong `JWT_SECRET` + `CORS_ORIGINS` + `PORT=7860`
   (+ optional `API_KEY`); confirm `/health` and `/ready`.
4. **Vercel**: import the repo, Root Directory `web/`, set `NEXT_PUBLIC_API_BASE_URL`
   (the Space URL), deploy, and point the Space's `CORS_ORIGINS` at the Vercel domain.
