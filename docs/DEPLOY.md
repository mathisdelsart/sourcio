# Free-tier live deployment (Vercel + Hugging Face Spaces + Qdrant Cloud)

This guide stands the whole tutor up on free tiers, with a bring-your-own-key
(BYO) LLM so the owner pays effectively nothing:

| Layer | Host | Free tier |
|---|---|---|
| Web frontend (`web/`, Next.js) | **Vercel** | Hobby plan |
| API service (`api.main:app`) | **Hugging Face Spaces** (Docker) | Free CPU Space |
| Vector store (course chunks) | **Qdrant Cloud** | Free 1 GB cluster |
| LLM | **OpenAI**, BYO key | pay-per-use, capped low |

The pieces fit together as: the browser loads the Vercel app, which calls the
Hugging Face Space API, which retrieves grounded chunks from Qdrant Cloud and
asks OpenAI to answer over them.

The image and its environment are documented in [DEPLOY-API.md](./DEPLOY-API.md);
this guide reuses that image and focuses on wiring the three hosted services
together on their free tiers. Read that file for the full API environment-variable
table.

> **Heads-up before you start (one code change required).** Qdrant Cloud requires
> an **API key** on every request. The code currently builds the Qdrant client
> from the URL only (`QdrantClient(url=...)`), with no API-key path, in both
> `core/retrieval.py` and `ingestion/index.py`. Until those two call sites also
> pass `api_key=...`, the API and the ingestion CLI cannot authenticate to a
> Qdrant Cloud cluster. See **"Required follow-up: wire the Qdrant Cloud API
> key"** at the end of this guide for the exact change. Everything else below is
> ready as-is.

---

## 0. Prerequisites

- The repo pushed to GitHub (Vercel and Hugging Face import from a Git repo).
- An OpenAI API key with a **low usage cap** set in the OpenAI billing dashboard
  (this is the only paid component; keep the cap tight, e.g. a few dollars).
- The course deck PDF available locally for the one-time ingestion step.
- The Qdrant client wiring change applied (see the follow-up section), since the
  cloud cluster needs an API key.

Accounts to create (all free to sign up): **Qdrant Cloud**, **Hugging Face**,
**Vercel**. You can sign in to each with GitHub.

---

## 1. Qdrant Cloud — the vector store

1. Sign up at <https://cloud.qdrant.io> and create a **free cluster** (1 GB is
   plenty for a single course deck of a few dozen slides).
2. Once it is running, copy two values from the cluster page:
   - the **cluster URL** (looks like `https://xxxx-xxxx.<region>.cloud.qdrant.io`;
     it serves HTTPS on port `6333`),
   - an **API key** (create one in the cluster's API-keys section).
3. **Ingest the deck into the cloud cluster.** Ingestion runs on your machine
   (it needs the local `bge-m3` embedding model and PyMuPDF), and it both creates
   the `courses` collection and upserts the chunks. Point it at the cloud cluster
   via the same `QDRANT_*` environment variables the app reads:

   ```bash
   export QDRANT_URL="https://xxxx-xxxx.<region>.cloud.qdrant.io:6333"
   export QDRANT_API_KEY="<your-qdrant-cloud-api-key>"

   uv run --group ingestion python -m ingestion.run <your-course>.pdf \
     --course "ELEC2885 Wavelet Transform" --hybrid --concurrency 1
   ```

   This requires the follow-up client change (so the ingestion client sends the
   API key). The exact flags (`--hybrid`, `--pages`, `--concurrency`, `--batch-size`)
   are unchanged from local ingestion — see the project README. Ingestion calls
   the vision LLM, so it spends a little OpenAI credit once; budget for it.

4. Note the collection name. The default is `courses` (`QDRANT_COLLECTION`); keep
   it unless you change it consistently here and in the Space secrets below.

> Free-tier note: idle Qdrant Cloud free clusters can be paused by the platform.
> If the demo returns connection errors after a period of inactivity, wake the
> cluster from the Qdrant Cloud console.

---

## 2. API on Hugging Face Spaces — the backend

The API ships as a CPU-only Docker image (the root `Dockerfile`). Hugging Face
Spaces can build and run that image directly.

1. Create a new **Space** at <https://huggingface.co/new-space>:
   - **SDK: Docker** (blank/from-scratch template).
   - **Hardware: CPU basic** (the free tier).
2. Make the Space build from this repo's `Dockerfile`. Two equivalent options:
   - Connect the Space to your GitHub repo, **or**
   - push the repo (including the root `Dockerfile`) to the Space's own Git remote.

   The Space builds the image and runs it; no extra config file is needed because
   the `Dockerfile` already defines the entrypoint and honors `$PORT`.
3. Set the Space **secrets** (Settings → Variables and secrets). These map onto the
   API environment variables documented in [DEPLOY-API.md](./DEPLOY-API.md):

   | Secret | Value | Why |
   |---|---|---|
   | `OPENAI_API_KEY` | your OpenAI key | The LLM provider. Spaces has **no** Ollama, so use OpenAI here. |
   | `QDRANT_URL` | the cluster URL (with `:6333`) | Points retrieval at Qdrant Cloud. |
   | `QDRANT_API_KEY` | the Qdrant Cloud API key | Authenticates to the cloud cluster (needs the follow-up wiring). |
   | `QDRANT_COLLECTION` | `courses` (optional) | Only if you renamed the collection. |
   | `API_KEY` | a random string (optional) | When set, clients must send `X-API-Key`. Use it to gate the public demo. |
   | `RERANKER_MODEL` | e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2` (optional) | Precision boost; adds CPU cost per query. |

4. **Port.** Hugging Face Spaces injects `$PORT` (commonly `7860`) and routes
   traffic to it. The `Dockerfile` already binds `uvicorn` to `${PORT:-8000}`, so
   no change is needed.
5. Wait for the build to finish, then open the Space. Its public URL is the API
   base URL, of the form `https://<user>-<space-name>.hf.space`. Confirm the API
   is live:

   ```
   https://<user>-<space-name>.hf.space/health   ->  {"status":"ok"}
   https://<user>-<space-name>.hf.space/docs      ->  interactive API docs
   ```

> Persistence note: the API's default SQLite database lives inside the container
> and is reset whenever the Space rebuilds or sleeps. Student history is therefore
> ephemeral on the free tier. For durable history, point `DATABASE_URL` at a
> managed Postgres (out of scope for the free-tier demo). Grounded answers,
> exercises, and grading all work without it.

> Free CPU Spaces sleep when idle and cold-start on the next request; the first
> call after a nap is slow while the model loads. This is expected on the free tier.

---

## 3. Web on Vercel — the frontend

The Next.js app lives in `web/`. `web/vercel.json` pins the framework to Next.js;
Vercel handles the build and routing from there.

1. At <https://vercel.com/new>, **import** the GitHub repo.
2. Set **Root Directory** to `web/`. This is essential: the Next.js project is in
   the subdirectory, not at the repo root. Vercel then auto-detects Next.js and
   uses `npm run build`.
3. Add the **Environment Variables** (Project Settings → Environment Variables),
   for the Production environment:

   | Variable | Value | Required |
   |---|---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | your Space URL, e.g. `https://<user>-<space-name>.hf.space` | **yes** |
   | `NEXT_PUBLIC_API_KEY` | the same value you set as the API `API_KEY` secret | only if you set `API_KEY` on the Space |

   Both are `NEXT_PUBLIC_*`, so they are inlined into the client bundle at build
   time. If you change either value, **redeploy** for it to take effect. The base
   URL is read in `web/lib/api.ts`; a trailing slash is fine (it is trimmed).
4. Deploy. Vercel gives you a public URL (e.g. `https://<project>.vercel.app`).
   Open it: the health indicator should turn green once it reaches the Space, and
   Ask / Re-explain / Exercise / Grade / History should work end to end.

> CORS: the browser calls the Space directly from the Vercel origin. If the
> browser console shows a CORS error, enable CORS for your Vercel origin on the
> API. That is a backend (`api/`) concern and out of scope for this config-only
> guide; note it here so it is not a surprise.

---

## 4. BYO-key and cost — keeping the owner at ~$0

- **The only paid component is OpenAI.** Qdrant Cloud (free cluster), Hugging Face
  (free CPU Space), and Vercel (Hobby) cost nothing for a demo of this size.
- For a private demo, the owner supplies their own `OPENAI_API_KEY` as the Space
  secret and keeps a **low budget cap** in the OpenAI dashboard. The repo also has
  an in-app budget guard: set `LLM_BUDGET_TOKENS` on the Space to stop generation
  once accumulated usage crosses a token cap (see `.env.example` / DEPLOY-API.md).
- For a **public** demo where visitors should pay for their own usage, you would
  need to accept a per-request key from the client rather than a single Space-wide
  `OPENAI_API_KEY`. The current API reads the key from its own environment, not
  from the request, so true visitor-BYO-key is **not** supported as shipped — it
  would require an API change. As shipped, the honest setup is: the **owner's** key
  on the Space, gated behind the optional `API_KEY` header and a tight budget cap.
- A fully free LLM (`LLM_PROVIDER=ollama`) is **not** an option on Hugging Face
  Spaces, which has no Ollama runtime — hence OpenAI for the hosted demo.

---

## Required follow-up: wire the Qdrant Cloud API key

Qdrant Cloud authenticates every request with an API key, but the client is
currently built from the URL only. Two one-line call sites need the key added.
This change is small but lives in files outside this config-only task, so it is
called out here rather than applied:

- `core/config.py` — add a setting:
  ```python
  qdrant_api_key: str | None = None
  ```
  It defaults to `None`, so the local `http://localhost:6333` path (no auth) is
  unchanged.
- `core/retrieval.py` (the `QdrantClient(url=settings.qdrant_url)` call) and
  `ingestion/index.py` (the `_client()` factory) — pass the key through:
  ```python
  QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
  ```
  Passing `api_key=None` is a no-op for a local cluster, so local behavior is
  preserved; a non-empty `QDRANT_API_KEY` enables Qdrant Cloud.

After this change, `QDRANT_API_KEY` (read by `pydantic-settings` into
`qdrant_api_key`) is all that is needed for both the ingestion step (section 1)
and the running API (section 2).

---

## Deployment order, at a glance

1. **Qdrant Cloud**: create the free cluster, copy URL + API key, ingest the deck.
2. **Hugging Face Space**: Docker Space from the root `Dockerfile`, set
   `OPENAI_API_KEY` + `QDRANT_URL` + `QDRANT_API_KEY` (+ optional `API_KEY`),
   confirm `/health`.
3. **Vercel**: import the repo, Root Directory `web/`, set
   `NEXT_PUBLIC_API_BASE_URL` (the Space URL) (+ optional `NEXT_PUBLIC_API_KEY`),
   deploy.

Do the Qdrant client follow-up before step 1, since both ingestion and the API
need it to reach the cloud cluster.
