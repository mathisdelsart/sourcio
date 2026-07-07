# Free-tier live deployment (Vercel + Hugging Face Spaces + Qdrant Cloud + Groq)

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
Hugging Face Space API, which retrieves grounded chunks from Qdrant Cloud and
asks a Groq-hosted Llama model to answer over them. Groq exposes an OpenAI-style
API and is wired through the model-agnostic factory in `core/config.py`, so no
code changes are needed — only environment variables.

The image and its environment are documented in [DEPLOY-API.md](./DEPLOY-API.md);
this guide reuses that image and focuses on wiring the four hosted services
together on their free tiers.

---

## 0. Prerequisites

- The repo pushed to GitHub (Vercel and Hugging Face import from a Git repo).
- The course deck PDF available locally for the one-time ingestion step.
- Accounts (all free to sign up, no card required): **Groq**, **Qdrant Cloud**,
  **Hugging Face**, **Vercel**. You can sign in to most with GitHub.

Qdrant Cloud authentication is already wired: `core/config.py` exposes
`qdrant_api_key`, and both `core/retrieval.py` and `ingestion/index.py` pass it
to `QdrantClient`. A blank key is a no-op for a local cluster, so nothing extra is
required to target the cloud beyond setting `QDRANT_API_KEY`.

---

## 1. Groq — the free hosted LLM

1. Sign up at <https://console.groq.com> and create an **API key**.
2. That single key (`GROQ_API_KEY`) is all the API needs. Setting
   `LLM_PROVIDER=groq` routes every chat role (router, explain, generate, grade,
   judge) to `groq:llama-3.3-70b-versatile` (override with `GROQ_CHAT_MODEL`).
   `langchain-groq` reads `GROQ_API_KEY` straight from the environment, so no
   base URL or per-role config is needed.
3. Groq has **no vision model**, so the `extract` (vision) role falls back to the
   OpenAI default. That role is only exercised during ingestion of scanned/slide
   PDFs, which is a one-time offline step (section 2) — it is never invoked by the
   deployed `/ask`, `/exercise`, `/quiz`, or `/grade` endpoints. The public API
   therefore runs entirely on Groq.

The `groq` extra pulls the integration: `uv sync --extra groq`. On the Space it is
installed via the Docker image; you do not install it by hand.

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
   cluster via the same `QDRANT_*` variables the app reads. The math-aware PDF
   path calls the **vision LLM**, so provide an `OPENAI_API_KEY` for this one-time
   step (Groq has no vision) and budget a little credit for it:

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

The API ships as a CPU-only Docker image (the root `Dockerfile`); Hugging Face
Spaces builds and runs it directly.

1. Create a new **Space** at <https://huggingface.co/new-space>:
   - **SDK: Docker** (blank template).
   - **Hardware: CPU basic** (the free tier).
2. Make the Space build from this repo's `Dockerfile`: connect the Space to your
   GitHub repo, or push the repo (including the root `Dockerfile`) to the Space's
   own Git remote. No extra config is needed — the `Dockerfile` defines the
   entrypoint and honors `$PORT`.
3. Set the Space **secrets** (Settings → Variables and secrets). These map onto the
   API environment variables in [DEPLOY-API.md](./DEPLOY-API.md):

   | Secret | Value | Why |
   |---|---|---|
   | `LLM_PROVIDER` | `groq` | Route every chat role to the free Groq-hosted model. |
   | `GROQ_API_KEY` | your Groq key | Authenticates to Groq. |
   | `QDRANT_URL` | the cluster URL (with `:6333`) | Points retrieval at Qdrant Cloud. |
   | `QDRANT_API_KEY` | the Qdrant Cloud API key | Authenticates to the cloud cluster. |
   | `QDRANT_COLLECTION` | `courses` (optional) | Only if you renamed the collection. |
   | `REQUIRE_AUTH` | `true` | **Mandatory login + per-account isolation:** every visitor must register, and each account only sees its own documents/history. |
   | `JWT_SECRET` | a long random string | Signs access tokens. Never ship the insecure default. Generate e.g. `python -c "import secrets;print(secrets.token_urlsafe(48))"`. |
   | `CORS_ORIGINS` | your Vercel domain, e.g. `https://<project>.vercel.app` | Lets the browser call the Space from the Vercel origin. |
   | `ENABLE_HSTS` | `true` (optional) | The Space serves HTTPS, so HSTS is appropriate. |
   | `API_KEY` | a random string (optional) | Extra gate: clients must send `X-API-Key`. Coexists with `REQUIRE_AUTH`. |
   | `OPENAI_API_KEY` | your OpenAI key (optional) | Only if visitors will **upload their own PDFs** on the deployed app: the vision extraction path needs it. Not required for the pre-ingested course or for `.md`/`.txt` uploads. |
   | `RERANKER_MODEL` | e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2` (optional) | Precision boost; adds CPU cost per query. |

4. **Port.** Spaces injects `$PORT` (commonly `7860`); the `Dockerfile` already
   binds `uvicorn` to `${PORT:-8000}`, so no change is needed.
5. Wait for the build, then confirm the API is live:

   ```
   https://<user>-<space-name>.hf.space/health   ->  {"status":"ok"}
   https://<user>-<space-name>.hf.space/ready     ->  readiness (deps reachable)
   https://<user>-<space-name>.hf.space/docs      ->  interactive API docs
   ```

   The Space's public URL (`https://<user>-<space-name>.hf.space`) is the API base
   URL used by the frontend.

> Persistence note: the default SQLite database lives inside the container and is
> reset when the Space rebuilds or sleeps, so accounts and history are ephemeral
> on the free tier. For durable data, point `DATABASE_URL` at a managed Postgres
> (see [POSTGRES.md](./POSTGRES.md)). Grounded answers, exercises, and grading all
> work without it.

> Free CPU Spaces sleep when idle and cold-start on the next request; the first
> call after a nap is slow while the embedding model loads. Expected on the free tier.

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
   | `NEXT_PUBLIC_API_KEY` | the same value you set as the API `API_KEY` secret | only if you set `API_KEY` on the Space |

   Both are `NEXT_PUBLIC_*`, so they are inlined into the client bundle at build
   time. If you change either value, **redeploy**. The base URL is read in
   `web/lib/api.ts`; a trailing slash is fine (it is trimmed).
4. Deploy. Vercel gives a public URL (e.g. `https://<project>.vercel.app`). Set
   the Space's `CORS_ORIGINS` to exactly that origin (section 3). Open the app:
   the health indicator turns green once it reaches the Space, and — after you
   register and log in — Ask / Re-explain / Exercise / Grade / Quiz / History work
   end to end.

---

## 5. Alternatives

- **Google Gemini free tier.** Gemini also offers a free tier via
  `langchain-google-genai` (add it as a dependency). It plugs into the same
  factory: use a per-role prefix `LLM_<ROLE>=google_genai:gemini-1.5-flash` (with
  `GOOGLE_API_KEY` set). A global `LLM_PROVIDER=gemini` switch is not wired today;
  the per-role prefix path already works with any provider `init_chat_model`
  understands, so it needs no code change beyond installing the integration.
- **Bring-your-own-key (visitor pays).** Having each visitor supply their own
  OpenAI key would let the owner run at exactly $0 with no shared quota. The API
  currently reads the LLM key from its own environment, not from the request, so
  true per-visitor BYO-key is **not** supported as shipped — it would need a small
  API change to accept a per-request key and thread it into `get_llm`. Not enabled
  by default; the Groq free tier is the recommended zero-cost path instead.

---

## 6. Cost & limits

- **The owner pays $0.** Qdrant Cloud (free cluster), Hugging Face (free CPU
  Space), Vercel (Hobby), and Groq (free tier) all cost nothing for a demo of this
  size, and visitors need no key of their own.
- **Free-tier rate limits.** Groq (and Gemini) free tiers cap requests/tokens per
  minute. This is fine for a portfolio/demo with light traffic; a burst of
  simultaneous users may hit a rate-limit error and should retry. Set
  `LLM_BUDGET_TOKENS` and/or `API_KEY` on the Space if you want an extra ceiling.
- **Ingestion is the one paid touchpoint** — and only if you ingest scanned/slide
  PDFs, whose math-aware vision extraction uses OpenAI. Run it once, locally,
  against the cloud cluster (section 2). `.md`/`.txt` prose ingestion uses no LLM
  at all (only local embeddings), so those uploads are free even on the Space.

---

## Deployment order, at a glance

1. **Groq**: create the API key.
2. **Qdrant Cloud**: create the free cluster, copy URL + API key, ingest the deck
   (one-time, needs an OpenAI key for vision).
3. **Hugging Face Space**: Docker Space from the root `Dockerfile`; set
   `LLM_PROVIDER=groq` + `GROQ_API_KEY` + `QDRANT_URL` + `QDRANT_API_KEY` +
   `REQUIRE_AUTH=true` + a strong `JWT_SECRET` + `CORS_ORIGINS` (+ optional
   `API_KEY`); confirm `/health` and `/ready`.
4. **Vercel**: import the repo, Root Directory `web/`, set
   `NEXT_PUBLIC_API_BASE_URL` (the Space URL) (+ optional `NEXT_PUBLIC_API_KEY`),
   deploy, and point the Space's `CORS_ORIGINS` at the Vercel domain.
