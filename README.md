<div align="center">

# Sourcio

**An AI tutor that answers only from your own courses — always cited, never invented.**

[![CI](https://img.shields.io/github/actions/workflow/status/mathisdelsart/sourcio/ci.yml?branch=main&label=CI&logo=github)](https://github.com/mathisdelsart/sourcio/actions/workflows/ci.yml)
![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/web-Next.js-000000?logo=nextdotjs&logoColor=white)
![Qdrant](https://img.shields.io/badge/vectors-Qdrant-DC244C)
![Tests](https://img.shields.io/badge/tests-853-blue)

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
| Drifts to methods and content outside your syllabus | Stays **strictly grounded**: retrieval only ever returns your material, and the model is shown nothing else |
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
   -> guard 1: nothing clears the threshold -> refuse, without calling the model
   -> guard 2: the model sees ONLY those chunks, and refuses if they do not
               cover the question (the floor is coarse; this is what catches
               a question that is merely *adjacent* to the course)
   -> otherwise -> grounded answer with citations remapped by the code
```

The product serves explicit endpoints — `/ask`, `/exercise`, `/grade`, `/quiz` — each dispatching to
its grounded node. The same intent-routing is also implemented agentically as a LangGraph router +
state graph (`agent/graph.py`), kept as a tested reference of the agentic design. Optional, opt-in
retrieval boosters — a cross-encoder reranker, hybrid dense + BM25 fusion, multi-query expansion, HyDE,
neighbor-chunk expansion — widen recall while the refusal guard stays intact. Full module-level
walkthrough in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Results

Every number below was measured against the **deployed** instance or the indexed corpus, with the
harness in [`eval/`](eval/README.md), on `gpt-4o-mini`. Nothing here is an estimate, and nothing is
carried over from an older run.

**Endpoint benchmark** — 71 cases driven through the live HTTP API (`/ask`, `/exercise`, `/quiz`) the
way the web app calls it, over six indexed chapters (finance, special relativity):

| Metric | Result |
| --- | --- |
| **Citation rate** — every answer carries a `[n]` source marker | **28/28 — 100%** |
| **Answer-vs-refuse decision** — answered what it should, refused what it should | **67/71 — 94%** |
| **Cross-account isolation** — a question covered only by *another* account's corpus | **refused** |
| Calls completed | 71/71, no errors |

**Retrieval** — 50 labelled questions (32 in-course, 18 deliberately out-of-scope), owner-scoped:

| Metric | Result |
| --- | --- |
| **Retrieval hit-rate** — the passage that answers the question is retrieved | **32/32 — 100%** |
| Query rewriting (multi-query) vs plain dense | **identical** — no gain on this corpus |

**The refusal guard, honestly.** Calibration (`eval/calibrate.py`) puts in-course questions at
**0.47–0.71** similarity and out-of-scope ones at **0.31–0.57** — the two **overlap**, so no threshold
separates them cleanly. The similarity floor is therefore a *coarse* first guard: it stops the
obviously unrelated, not everything. What catches a question that is merely *adjacent* to the course
(the Sharpe ratio in a finance course, the Schwarzschild radius in a relativity course) is the second
guard — the grounded prompt, shown only the retrieved chunks. That is where 23 of the benchmark's
refusal cases are decided, and it missed one.

> Faithfulness (is every claim supported by its cited source?) is measured by `eval/run_eval.py`, which
> calls an LLM judge. It is not reported here because it has not been re-run against this corpus, and a
> number you have not measured is not a result.

> **CI:** 853 tests, green — ruff + pytest + pyright + a coverage gate (>=84%) on every PR.

## Tech stack

**Backend** Python · FastAPI · LangChain / LangGraph · SQLAlchemy + Alembic
**Storage** Qdrant (vectors) · SQLite locally, managed PostgreSQL in production (accounts, history)
**Retrieval** `BAAI/bge-m3` local embeddings · cross-encoder reranker
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
