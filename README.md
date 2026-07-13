<div align="center">

# Sourcio

**An AI tutor that answers only from your own courses — always cited, never invented.**

[![CI](https://img.shields.io/github/actions/workflow/status/mathisdelsart/sourcio/ci.yml?branch=main&label=CI&logo=github)](https://github.com/mathisdelsart/sourcio/actions/workflows/ci.yml)
![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/web-Next.js-000000?logo=nextdotjs&logoColor=white)
![Qdrant](https://img.shields.io/badge/vectors-Qdrant-DC244C)
![Tests](https://img.shields.io/badge/tests-879-blue)

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

- **Grounded, cited answers** — every response is backed by the exact course passages it used.
- **Honest refusals** — out-of-course questions get *"not covered in the course material"*, never a guess.
- **Streaming responses** — answers render token by token over Server-Sent Events.
- **Re-explain by level** — beginner / intermediate / advanced rephrasing that keeps conversation memory.
- **Exercises and quizzes** — course-grounded practice with automatic grading (reference solutions stay server-side).
- **Spaced-repetition review** — SM-2 scheduling to revisit notions at the right time.
- **Threads, history and feedback** — named conversation threads, an activity feed, and per-answer ratings.
- **Multi-format ingestion** — PDF slides via a vision model (math/LaTeX preserved), plus `.md` / `.txt` prose.
- **Multi-user by design** — JWT auth with per-account document isolation and background ingestion.
- **Multilingual** — English, French and Dutch UI and answers.

## How it works

Sourcio splits into an **offline** ingestion pass (run once per course) and an **online** agent that
serves requests, guarded by an offline **evaluation** layer.

```
OFFLINE — ingest once per course
  PDF / .md / .txt
   -> math-aware extraction   (slides -> Markdown + LaTeX preserved)
   -> adaptive chunking       (one slide ~ one chunk; prose split with overlap)
   -> local embeddings        (BAAI/bge-m3, multilingual, free)
   -> Qdrant                  ({vector, payload: course / chapter / page / text})

ONLINE — answer a question
  question
   -> embed + retrieve top-k from Qdrant, with a similarity threshold
   -> if nothing clears the threshold -> refuse ("not covered in the course")
   -> otherwise -> grounded answer with citations remapped by the code
```

The product serves explicit endpoints — `/ask`, `/exercise`, `/grade`, `/quiz` — each dispatching to
its grounded node. The same intent-routing is also implemented agentically as a LangGraph router +
state graph (`agent/graph.py`), kept as a tested reference of the agentic design. Optional, opt-in
retrieval boosters — a cross-encoder reranker, hybrid dense + BM25 fusion, multi-query expansion, HyDE,
neighbor-chunk expansion — widen recall while the refusal guard stays intact. Full module-level
walkthrough in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Results

Benchmarked end to end on a real 123-page Master's thesis (a dense deep-RL / MicroRTS work) indexed
into Qdrant — a 27-question suite (13 factual, 3 math, 6 synthesis, and 5 deliberately out-of-scope)
run through the offline harness (`eval/`, see [`eval/README.md`](eval/README.md)) and graded by an
LLM-as-a-judge. Numbers are honest and labeled, not marketing.

**With OpenAI `gpt-4o-mini`:**

| Metric | Result |
| --- | --- |
| **Refusal accuracy** — answers in-scope questions, refuses all 5 out-of-scope | **100%** |
| **Faithfulness** — every claim supported by the retrieved sources | **100%** |
| **Citation rate** — the answer carries a `[n]` source marker | **100%** |
| **Retrieval hit-rate** — the relevant passage is retrieved | **100%** |
| Answer-keyword match | 91% |
| **Retrieval latency** | p50 **89 ms** · p95 **115 ms** |

**Model comparison** (same suite, same fixed judge):

| Metric | OpenAI `gpt-4o-mini` | Groq `llama-3.1-8b` (free) |
| --- | --- | --- |
| Refusal accuracy | **100%** | 70% |
| Faithfulness | **100%** | 93% |
| Citation rate | 100% | 100% |
| Retrieval hit-rate | 100% | 100% |

Retrieval is model-independent (identical hit-rate and citations either way); the gap is in *understanding*
a dense technical thesis, where the capable model wins. The free Groq tier is token-limited (~6k tokens/min),
so its run used a reduced retrieval context — fine for a demo, but the OpenAI numbers are the reference.

Retrieval boosters, measured separately on a slide deck: a cross-encoder reranker lifted hit-rate
**73% -> 82%**; opt-in hybrid dense + BM25 (RRF) added **+9 pts** hit-rate and +6.6 NDCG@5.

> **CI:** 879 tests, green — ruff + pytest + pyright + a coverage gate (>=84%) on every PR.

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
see **[docs/RUN-LOCAL.md](docs/RUN-LOCAL.md)**.

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

## Repository map

Each directory has its own README with a local guide to its files.

| Path | What lives there |
| --- | --- |
| [`ingestion/`](ingestion/README.md) | Offline pipeline: PDF/prose -> extraction -> chunking -> embeddings -> Qdrant |
| [`core/`](core/README.md) | Retrieval, threshold-based refusal, citation-by-construction, the LLM factory |
| [`agent/`](agent/README.md) | The explain / generate / grade / re-explain / quiz nodes, plus a LangGraph router + state graph (agentic reference) |
| [`api/`](api/README.md) | FastAPI service: endpoints, auth, middleware, background jobs |
| [`web/`](web/README.md) | Next.js web app (the primary UI) |
| [`db/`](db/README.md) | SQLAlchemy models and the engine/session layer |
| [`eval/`](eval/README.md) | Offline evaluation: faithfulness judge, threshold calibration, A/B retrieval, benchmarks |
| [`tests/`](tests/README.md) | Test suite (pytest) |
| [`alembic/`](alembic/) | Database migrations |

## Documentation

| Guide | Topic |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design choices and a module-level walkthrough of the whole system |
| [docs/RUN-LOCAL.md](docs/RUN-LOCAL.md) | Run the full stack (Qdrant + API + web) locally and free with Ollama |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Cloud deployment (Vercel + HF Spaces + Qdrant Cloud + Groq), the API Docker image, env-var reference, and R2 storage |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Optional ops: PostgreSQL backend and LangFuse tracing |

---

Built by [**mathisdelsart**](https://github.com/mathisdelsart) as an AI-engineering portfolio project.
`.env`, secrets, and course PDFs are never committed (personal data).
</content>
</invoke>
