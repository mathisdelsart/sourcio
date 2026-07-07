<div align="center">

# Sourcio

**An AI tutor that answers only from your own courses — always cited, never invented.**

[![CI](https://img.shields.io/github/actions/workflow/status/mathisdelsart/sourcio/ci.yml?branch=main&label=CI&logo=github)](https://github.com/mathisdelsart/sourcio/actions/workflows/ci.yml)
![Coverage](https://img.shields.io/badge/coverage-87%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/web-Next.js-000000?logo=nextdotjs&logoColor=white)
![Qdrant](https://img.shields.io/badge/vectors-Qdrant-DC244C)
![Tests](https://img.shields.io/badge/tests-700+-blue)

</div>

Sourcio indexes your course material once — slides, exercise sets, summaries — into a persistent
vector store, then answers questions using **only** those documents. Every claim carries a citation
(course, chapter, page), and when nothing in the material is relevant enough, the tutor says so
instead of guessing. The running use case is a study assistant over university courses, but the
pipeline is document-agnostic.

> Sourcio is a portfolio project — a hands-on showcase of a production-shaped RAG stack
> (retrieval, agentic orchestration, LLM-as-a-judge evaluation, a typed API and web app, CI/CD).

---

## Why not just use a generic chatbot?

| A generic chatbot… | Sourcio instead… |
| --- | --- |
| Loses your documents between conversations | Keeps a **persistent, indexed knowledge base** (Qdrant) — courses indexed once |
| Drifts to methods and content outside your syllabus | Stays **strictly grounded** in your material behind a calibrated similarity threshold |
| Gives answers you cannot verify | Attaches a **citation** (course / chapter / page) to every claim |
| Can hallucinate with confidence | **Refuses** when the course does not cover the question, instead of inventing |

Citations are produced *by construction*: the model only ever sees numbered sources `[1] [2] [3]`
and cites those indices; the code then remaps each `[n]` to its real chapter and page. The model
never handles page numbers, so it cannot invent one.

## Key features

- 📚 **Grounded, cited answers** — every response is backed by the exact course passages it used.
- 🚫 **Honest refusals** — out-of-course questions get *"not covered in the course material"*, never a guess.
- ⚡ **Streaming responses** — answers render token by token over Server-Sent Events.
- 🎓 **Re-explain by level** — beginner / intermediate / advanced rephrasing that keeps conversation memory.
- ✍️ **Exercises & quizzes** — course-grounded practice with automatic grading at chosen rigor levels (reference solutions stay server-side).
- 🔁 **Spaced-repetition review** — SM-2 scheduling to revisit notions at the right time.
- 🧵 **Threads, history & feedback** — named conversation threads, an activity feed, and per-answer 👍/👎.
- 📄 **Multi-format ingestion** — PDF slides via a vision model (math/LaTeX preserved), plus `.md` / `.txt` prose.
- 🔐 **Multi-user by design** — JWT auth with per-account document isolation and background ingestion.
- 🌍 **Multilingual** — English, French and Dutch UI and answers.

## How it works

Sourcio splits into an **offline** ingestion pass (run once per course) and an **online** agent that
serves requests, guarded by an offline **evaluation** layer.

```
OFFLINE — ingest once per course
  PDF / .md / .txt
   → math-aware extraction   (slides → Markdown + LaTeX preserved)
   → adaptive chunking       (one slide ≈ one chunk; prose split with overlap)
   → local embeddings        (BAAI/bge-m3, multilingual, free)
   → Qdrant                  ({vector, payload: course / chapter / page / text})

ONLINE — answer a question
  question
   → embed + retrieve top-k from Qdrant, with a similarity threshold
   → if nothing clears the threshold → refuse ("not covered in the course")
   → otherwise → grounded answer with citations remapped by the code
```

A LangGraph router classifies intent (explain / generate exercise / grade / re-explain) and dispatches
to the matching node. Optional, opt-in retrieval boosters — a cross-encoder reranker, hybrid
dense + BM25 fusion, multi-query expansion, HyDE, neighbor-chunk expansion — widen recall while the
refusal guard stays intact. Full module-level walkthrough in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Results

Measured end to end on a full 63-slide *Wavelet Transform* course indexed into Qdrant, then evaluated
with the offline harness (`eval/`). Numbers are honest and labeled, not marketing.

| Metric | Result | How it was measured |
| --- | --- | --- |
| **Threshold calibration** | 100% in/out separation | In-course scores 0.57–0.68 vs out-of-course 0.28–0.43; threshold ≈ 0.50 |
| **Retrieval hit-rate** | **73% → 82%** (+9 pts) | With the cross-encoder reranker enabled |
| **Hybrid retrieval** | **+9.1 pts** hit-rate, +6.6 NDCG@5 | Dense + BM25 (RRF) vs dense-only; the *delta* is what's comparable |
| **Faithfulness** | 75% | Offline LLM-as-a-judge: every claim supported by the retrieved sources |
| **Relevance** | 100% | Same judge: answers actually address the question |
| **Retrieval latency** | p50 **67 ms** · p95 **466 ms** | Query embedding + Qdrant search; LLM-independent |
| **Test suite / CI** | 700+ tests, green | ruff + pytest + pyright + coverage gate on every PR |

> **Honest caveat.** The test deck is *constructive* (formula slides, few prose definitions), so some
> definitional questions are refused rather than answered. That is the grounding guard working as
> intended: declining beats inventing a definition the slides never state.

## Tech stack

**Backend** Python · FastAPI · LangChain / LangGraph · SQLAlchemy + Alembic
**Retrieval** Qdrant · `BAAI/bge-m3` local embeddings · cross-encoder reranker
**Frontend** Next.js (App Router) · TypeScript · Tailwind CSS
**Ops** Docker · GitHub Actions (ruff · pytest · pyright · coverage) · LangFuse (opt-in)

The LLM layer is model-agnostic: a single `get_llm(role)` factory picks a model per role from env
vars (OpenAI by default). Point it at a local [Ollama](https://ollama.com) server and the entire
pipeline — embeddings, reranker, and Qdrant are already local — runs offline at **zero cost**.

## Getting started

The fastest path is fully local and free (LLM via Ollama). Requires Docker, [`uv`](https://docs.astral.sh/uv/),
Node.js 18+, and a running [Ollama](https://ollama.com) server.

```bash
# 1. Vector store (Docker)
docker compose up -d qdrant

# 2. API on :8000 — local Ollama provider, zero paid calls (own terminal)
LLM_PROVIDER=ollama make api

# 3. Web frontend on :3000 (own terminal)
make web
```

Open <http://localhost:3000>, ask an in-course question (grounded, cited) and an out-of-course one
(honest refusal). For the full recipe — pulling models, ingesting a course, resetting the dev DB —
see **[docs/RUN-LOCAL.md](docs/RUN-LOCAL.md)** and **[docs/LOCAL.md](docs/LOCAL.md)**.

<details>
<summary>Prefer the CLI / OpenAI?</summary>

```bash
uv sync --extra ingestion --extra agent
docker compose up -d qdrant
cp .env.example .env                 # then set OPENAI_API_KEY
uv run python -m ingestion.run path/to/course.pdf --course "Wavelet Transform" --hybrid
uv run python -m core.ask "What is a piecewise constant approximation?"
```

Run the API with `uv run uvicorn api.main:app --reload` and browse the interactive docs at
<http://localhost:8000/docs>.
</details>

## Documentation

| Guide | Topic |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module-level walkthrough of the whole system |
| [docs/RUN-LOCAL.md](docs/RUN-LOCAL.md) | Run the full stack (Qdrant + API + web) locally |
| [docs/LOCAL.md](docs/LOCAL.md) | Fully local, zero-cost runs with Ollama |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Free-tier live deployment (Vercel + Hugging Face Spaces + Qdrant Cloud) |
| [docs/DEPLOY-API.md](docs/DEPLOY-API.md) | The CPU-only Docker image for the API service |
| [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md) | Opt-in LangFuse tracing |
| [docs/POSTGRES.md](docs/POSTGRES.md) | Switch the relational store to PostgreSQL |
| [docs/DEMO.md](docs/DEMO.md) | Demo recording storyboard |

## Demo

<!-- demo video to be embedded here -->

_A short walkthrough video is coming — asking an in-course question (grounded, cited answer), an
out-of-course one (honest refusal), then generating and grading an exercise, all from the web UI._
The click-by-click recording script lives in **[docs/DEMO.md](docs/DEMO.md)**.

---

Built by [**mathisdelsart**](https://github.com/mathisdelsart) as an AI-engineering portfolio project.
`.env`, secrets, and course PDFs are never committed (personal data).
