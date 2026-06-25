# Architecture

`grounded-rag` is a course tutor that answers questions **strictly from the
user's own course material**. The guiding principle drives every design choice:
never leave the course, always cite the source, and refuse when a question is
not covered. This document explains how the system is put together so a new
contributor can find their way around.

## Guiding principle

| Risk with a general assistant | How `grounded-rag` addresses it |
| --- | --- |
| Documents are lost between conversations | A persistent vector store (Qdrant), courses indexed once |
| Answers drift to out-of-course methods | Retrieval is restricted to the course; nothing else is in context |
| No verifiable sources | Citations (course, chapter, page) are produced by construction |
| The model may hallucinate | A similarity threshold refuses uncovered questions, and an offline faithfulness judge guards against unsupported claims |

## Component overview

The system has two phases. **Offline ingestion** turns course PDFs into
searchable, citable chunks. **Online serving** answers a student's message
through an agent graph. A separate **quality layer** evaluates the system
offline / in CI.

```
                         OFFLINE INGESTION (once per course)
  course.pdf
      |
      v
  ingestion/extract.py     math-aware, per-page routing
      |                    plain text -> PyMuPDF (free)
      |                    math/figure -> vision model -> Markdown + LaTeX
      v
  ingestion/chunk.py       adaptive: 1 slide -> 1 chunk, {course, chapter, page}
      |
      v
  ingestion/embed.py       local multilingual embeddings (BAAI/bge-m3)
      |
      v
  ingestion/index.py  -->  [ Qdrant ]  collection "courses": {vector, payload}
                                |
================================|=====================================
                                |        ONLINE SERVING (per request)
  client (Streamlit ui/ or HTTP)|
      |                         |
      v                         |
  api/main.py  (FastAPI)        |
      |   \                     |
      |    \---------> core/retrieval.py --> [ Qdrant ]  top-k + threshold (+ opt-in hybrid RRF)
      |   /                          \
      v  v                            +--> core/answer.py  citation-by-construction
  agent/graph.py (LangGraph)               (answer + stream_answer; used by /ask, /ask/stream, explain)
      |
   router --> explain | generate | grade | reexplain | quiz   (agent/nodes/*)
      |              |        |        |
      |              v        v        v
      |          [ SQL store: students, exercises, grades, messages ]
      |                                (db/, via agent/persistence.py)
      v
  core/config.get_llm(role)  model-agnostic factory  (+ core/obs.py LangFuse, core/budget.py)

                         QUALITY LAYER (offline / CI)
  eval/run_eval.py     faithfulness + relevance + refusal + retrieval-hit
  eval/calibrate.py    empirically calibrate the similarity threshold
  ui/metrics.py        read-only dashboard over eval results + DB stats
```

## Offline ingestion pipeline

Run once per course: `python -m ingestion.run path/to/course.pdf --course "..."`
(`ingestion/run.py`); add `--sparse` to also index bge-m3 lexical vectors and
enable opt-in hybrid retrieval. The shared data contract for the whole pipeline
lives in `ingestion/schema.py` (`Page`, `Chunk`, `Retrieved`).

### 1. Math-aware extraction (`ingestion/extract.py`)

Course material is slide decks where formulas are often rendered as images or as
text that a plain PDF parser garbles. Mangled mathematics is the project's main
grounding risk, so extraction is **math-aware** and routes per page:

- A cheap PyMuPDF heuristic (`needs_vision`, over `PageFeatures`) classifies each
  page. A page needs vision when it embeds images, exposes math-like symbols, or
  yields very little recoverable text.
- **Plain-text pages** are extracted for free with PyMuPDF (`hybrid=True`).
- **Math/figure-heavy pages** are rasterized and transcribed by a vision model
  into Markdown with **LaTeX preserved** ($...$ / $$...$$).

Two optimizations keep this fast and resilient:

- **Parallel vision calls**: pending pages are transcribed concurrently
  (`ThreadPoolExecutor`, bounded by `concurrency`) while output order is kept.
- **Rate-limit resilience**: `with_rate_limit_retry` retries only HTTP 429
  errors with exponential backoff; any other exception is re-raised so real bugs
  surface. The sleep and the transcriber are injectable, so tests run with no API
  call and no real waiting.

The vision prompt and the code-fence stripping (`_strip_code_fence`) keep the
stored Markdown clean. Heuristic and routing functions are pure, so they are
unit-testable without a PDF (`tests/test_extract.py`).

### 2. Adaptive chunking (`ingestion/chunk.py`)

Chunking adapts to `doc_type`. Slides carry little text but strong per-slide
structure, so **one slide maps to one chunk** (token splitting would glue slides
together). Each chunk carries `{course, chapter, page}` metadata used to build
citations. Empty pages are dropped, and a few chunks are logged for visual
inspection before the pipeline is trusted. Chunk ids are **stable UUIDs**
(`uuid5` over `course-pN`), so re-ingesting a course overwrites rather than
duplicates — ingestion is idempotent. The prose path (~500-token windows with
overlap) is reserved for when a prose document is first ingested.

### 3. Embeddings (`ingestion/embed.py`)

Documents and queries are embedded by the **same** local multilingual model
(`BAAI/bge-m3`, configurable via `Settings.embedding_model`) so both sides share
one vector space. Vectors are L2-normalized, making cosine similarity equal to
the dot product. The model is loaded once and cached. bge-m3 also exposes
**lexical (sparse) weights** (`embed_sparse_texts` / `embed_sparse_query`), used
by the opt-in hybrid retrieval path.

### 4. Indexing (`ingestion/index.py`)

Each chunk is embedded and upserted into the Qdrant collection (`courses`, cosine
distance, created on first use). The payload stores the chunk text plus its
citation metadata, so retrieval can both rank and cite without a second lookup.

Sparse indexing is **opt-in** (`--sparse`): when enabled, the collection uses
named vectors — a dense cosine vector plus a named sparse vector holding the
bge-m3 lexical weights — which is what the hybrid retrieval path fuses at query
time. Dense-only ingestion (the default) leaves the collection sparse-free, and
hybrid retrieval falls back to dense against it.

`ingestion/run.py` processes pages in **batches** (extract → chunk → index per
batch): a crash mid-run keeps the progress of earlier batches, and the stable
chunk ids make a re-run safe.

## Online serving

### Retrieval with threshold-based refusal (`core/retrieval.py`)

`retrieve(question, k, course, chapter)` embeds the question, queries Qdrant for
the top-k most similar chunks, and applies the **similarity threshold**
(`Settings.similarity_threshold`) as Qdrant's `score_threshold`. An optional
payload filter restricts retrieval to a course and/or chapter. An empty result
means nothing in the course is relevant enough, which the answer layer turns into
an explicit refusal rather than a guess.

The threshold is not a magic number: it depends on the embedding model and is
calibrated empirically (see `eval/calibrate.py`).

An **opt-in hybrid dense + sparse path** (`Settings.hybrid_retrieval`, set via
`HYBRID_RETRIEVAL=1`) fuses two branches with **Reciprocal Rank Fusion (RRF)**
through Qdrant's Query API: a dense kNN branch (bge-m3 dense vectors, still
filtered by the similarity threshold so grounding is preserved) and a lexical
**sparse** branch (bge-m3 lexical weights, a BM25-style signal). It engages only
when the collection actually carries the named sparse vector
(`_collection_has_sparse`); if hybrid is requested but the collection has no
sparse vector, retrieval transparently **falls back to dense**. Sparse vectors
are produced at ingest time when the course is indexed with `--sparse`
(`ingestion/embed.py:embed_sparse_texts`, `ingestion/index.py`), so hybrid
retrieval needs a one-off `--sparse` re-ingest of the course.

### Citation-by-construction (`core/answer.py`)

This is the single place where retrieval, the threshold, refusal, and citation
all live, so the grounding guarantees cannot drift. The mechanism makes invented
page numbers impossible:

1. Retrieved chunks are numbered `[1] [2] [3]` and shown to the model.
2. The system prompt instructs the model to answer **only** from those sources,
   cite each claim with an index, and reply with the exact refusal string if the
   sources do not answer the question.
3. The model **never sees a page number** — it only handles indices.
4. The code (`_remap_citations`) maps each `[n]` back to its real source label
   `(course, chapter, p.N)` via `Retrieved.citation()`. Only the sources the
   answer actually relies on are returned (`_cited_indices`).

If retrieval finds nothing, `answer` returns the refusal directly without calling
the model. The CLI entry point is `core/ask.py` (`python -m core.ask "..."`).

**Streaming** (`stream_answer`) mirrors `answer` step for step — same retrieval,
threshold/refusal and citation-by-construction — but yields incrementally. It
emits `{"type": "token", "text": ...}` deltas as the model produces them, then a
single `{"type": "sources", ...}` final event with the fully remapped answer,
the cited source labels, and the `refused` flag. Citation remapping runs **once,
on the assembled text**, so streamed `[n]` markers can never leak an invented
page. `POST /ask/stream` serializes these events as Server-Sent Events and
persists the question and assembled answer when the stream completes.

### Agent graph (`agent/`)

The online flow is a LangGraph `StateGraph` (`agent/graph.py`) threading a single
`TutorState` TypedDict (`agent/state.py`). The router classifies the message into
one of four intents and dispatches to a node; each node writes only its own
output key.

```
            +-- explain    RAG -> grounded, sourced explanation
  router ---+-- generate   builds an exercise + reference solution
            +-- grade      LLM-as-a-judge marks the student's answer
            +-- reexplain  rephrases the last answer at a chosen level
```

- **Router** (`classify_intent`): asks `get_llm("router")` for a single intent
  label, with a deterministic keyword fallback so it never emits an invalid
  route. The valid labels derive from the `Intent` literal, so the prompt and the
  routing table cannot drift.
- **explain** (`agent/nodes/explain.py`): owns no RAG logic; delegates to
  `answer.answer` and appends the turn to `history`.
- **generate** (`agent/nodes/generate.py`): retrieves chunks for the notion and
  builds an exercise + reference solution **only** from them, refusing when
  nothing is retrieved (mirroring `core/answer.py`). The reference solution is stored
  server-side and never returned by the API.
- **grade** (`agent/nodes/grade.py`): judge #1, the **product** feature. Marks
  the student's answer against the reference solution and returns a numeric score
  plus feedback. Distinct from the eval/faithfulness judge.
- **reexplain** (`agent/nodes/reexplain.py`): reuses `history` instead of
  re-retrieving, so the rephrasing stays anchored to already-grounded content,
  and re-pitches it at the requested `Level` (beginner / intermediate /
  advanced).

The `generate` route also backs **quiz mode** (`agent/nodes/quiz.py`):
`generate_quiz(notion, n, student_id)` builds a multi-question quiz grounded
strictly in retrieval (refusing when nothing is retrieved), persists the quiz and
its questions with their reference solutions server-side, and surfaces only
`{id, problem}` per question. `grade_quiz_answer` loads the stored reference
solution server-side and grades one answer with the same product-side judge as
`grade`. Both are exposed by `POST /quiz` and `POST /quiz/{quiz_id}/grade`.

`langgraph` is imported lazily inside `build_graph`, so the router and nodes stay
importable and unit-testable without the optional `agent` extra installed.

### Persistence (`agent/persistence.py`)

Nodes durably store the exercises they generate and the grades they produce.
Persistence is **best-effort and fully optional**: with no `student_id`, no
configured database, or no `db` package, the helpers are no-ops and the node
keeps working. The session factory is injectable, so tests bind it to an
in-memory SQLite engine.

### API (`api/main.py`)

A thin FastAPI layer; each route delegates to the existing grounded functions and
nodes — no retrieval or prompting is reimplemented.

| Endpoint | Role |
| --- | --- |
| `GET /health` | liveness probe (always open) |
| `POST /ask` | answer a question, grounded; persists the turn as history |
| `POST /ask/stream` | same answer as Server-Sent Events: token deltas, then a final sources/refusal event; persists on completion |
| `POST /reexplain` | rephrase the last answer at a chosen level (beginner / intermediate / advanced) |
| `POST /exercise` | generate an exercise; never returns the reference solution |
| `POST /grade` | grade a student's answer |
| `POST /quiz` | generate a grounded multi-question quiz; reference solutions stay server-side |
| `POST /quiz/{quiz_id}/grade` | grade one quiz answer against its stored reference solution (404 on unknown question) |
| `GET /history/{student_id}` | recent conversation turns, chronological |

The API is **stateful**: a `student_id` identifies the user (get-or-create),
`/ask` turns are persisted, and `/history` replays them. **API-key auth** is
opt-in (`Settings.api_key`): empty leaves the API open; a non-empty value
requires a matching `X-API-Key` header on the mutating endpoints and `/history`,
while `/health` stays open. The database engine is bound on startup (or injected
by tests via `configure_engine`).

### UI (`ui/`)

`ui/app.py` is a Streamlit demo that calls the HTTP endpoints (via the typed
`TutorClient`) rather than importing library functions, so the UI and server
share one contract. `ui/metrics.py` is a read-only dashboard surfacing the
offline eval metrics (from `eval/results.json`) and DB usage stats. All
non-Streamlit logic lives in pure helpers that are unit-tested without the
optional `ui` extra (`tests/test_ui.py`, `tests/test_metrics.py`).

## Quality layer (offline / CI)

This is the system-quality guard against hallucination — **distinct** from the
product-side grading of a student's answer.

- **Faithfulness evaluation** (`eval/run_eval.py`, judge #2): for each reference
  question in `eval/dataset.jsonl`, it calls the answer function; refusal cases
  check that the system refused; answerable cases are scored by a judge for
  **faithfulness** (every claim supported by the sources) and **relevance**. An
  optional **retrieval-hit** check verifies an expected keyword was retrieved.
  Aggregated metrics (refusal accuracy, faithfulness, relevance, retrieval-hit)
  are compared against configurable thresholds, so CI can fail the build on a
  regression. The answer function, judge, and retriever are all injectable, so
  the harness is unit-tested with no API call.
- **Threshold calibration** (`eval/calibrate.py`): measures the top retrieval
  similarity per labeled question (no threshold applied) and sweeps candidate
  thresholds to find the one that best separates in-course from out-of-course
  questions. This is how `similarity_threshold` is set empirically rather than
  guessed.

## Storage layers

| Where | What |
| --- | --- |
| **Qdrant** | course chunks as `{vector, payload}` (collection `courses`) |
| **SQL** (SQLite in dev, PostgreSQL later) | students, exercises + reference solutions, grades, conversation messages |
| **LangFuse** (optional) | traces and per-step evaluation signals |

The relational layer uses SQLAlchemy 2.0 declarative models (`db/models.py`):
`Student`, `Exercise`, `Grade`, `Quiz`, `QuizQuestion`, `Message`. The engine is created lazily from
`Settings.database_url` (`db/session.py`), so swapping SQLite for PostgreSQL is
just a URL change. Schema migrations are managed by Alembic (`alembic/`), which
resolves the same URL at runtime and diffs against the declarative `Base`.

## The model-agnostic factory (`core/config.py`)

Models are **never hard-coded in a node**. Everything goes through
`get_llm(role)`, selected by the `LLM_<ROLE>` environment variable (defaulting to
`gpt-4o-mini`, `temperature=0`). Switching a role to a larger model is a single
env change — no code edit. Distinct roles exist for `extract`, `router`,
`explain`, `generate`, `grade`, and `judge`, so a small router and a larger
grader can coexist.

The same switch enables a **fully-local, zero-cost** run: `LLM_PROVIDER=ollama`
(or a per-role `LLM_<ROLE>=ollama:<model>`) routes every LLM to a local
[Ollama](https://ollama.com) server (`Settings.ollama_base_url`). Embeddings, the
reranker, and Qdrant are already local, so the whole pipeline then runs offline
and free — see [LOCAL.md](LOCAL.md). For serving, the API ships as a **CPU-only
Docker image** that installs a CPU-only `torch` to avoid multi-gigabyte CUDA
wheels; build and run details are in [DEPLOY-API.md](DEPLOY-API.md), and a
free-tier hosted path in [DEPLOY.md](DEPLOY.md).

The factory also composes two opt-in, zero-cost-when-disabled cross-cutting
concerns:

- **LangFuse tracing + latency instrumentation** (`core/obs.py`): tracing
  activates only when LangFuse credentials are present (the package is imported
  lazily), staying zero-cost when off — see [OBSERVABILITY.md](OBSERVABILITY.md).
  The same module owns a lightweight per-stage timer (`timer`, `record_sample`,
  `latency_stats`) that feeds the retrieval-latency percentiles reported in the
  README; it is what the streaming and answer paths wrap their `retrieval` and
  `llm` stages with.
- **Token budget guard** (`core/budget.py`): a callback that accumulates reported
  token usage and raises `BudgetExceeded` once a configured cap is reached. Off
  by default (`llm_budget_tokens=0`); it reads token counts straight from the
  result and never makes a network call.

An optional **LLM response cache** (`llm_cache`: `""`, `memory`, or `sqlite`) is
configured once per process to avoid re-billing identical prompts.

All settings live in `Settings` (`core/config.py`), overridable via `.env` or
environment variables. See `.env.example` for the full list.

## Request lifecycle: `POST /ask`

A walkthrough of a single question, end to end:

1. **Client → API.** The client (Streamlit UI or any HTTP caller) sends
   `{student_id, question, k}` to `POST /ask` (`api/main.py`). If an API key is
   configured, `require_api_key` validates the `X-API-Key` header.
2. **API → answer.** The route calls `answer(question, k)` (`core/answer.py`).
3. **Retrieve.** `answer` calls `retrieve` (`core/retrieval.py`), which embeds the
   question with `embed_query` (bge-m3) and queries Qdrant for the top-k chunks
   **above the similarity threshold**.
4. **Refuse early, if needed.** If nothing clears the threshold, `answer` returns
   the fixed refusal string without calling any model.
5. **Ground the answer.** Otherwise the chunks are numbered `[1] [2] [3]` and
   sent, with the strict system prompt, to `get_llm("explain")`
   (`config.get_llm`). The model cites by index only.
6. **Remap citations.** The code rewrites each `[n]` into its real
   `(course, chapter, p.N)` label and collects only the sources the answer
   actually used.
7. **Persist.** The API writes the user question and the assistant answer to the
   SQL store as conversation history (`db/session.add_message`).
8. **Respond.** The API returns `{answer, refused, sources}`; the UI renders the
   answer and its cited sources.

Throughout, any LLM call goes through the factory, so tracing and the budget
guard apply transparently when enabled.

## Where things live

| Concern | Module(s) |
| --- | --- |
| PDF extraction (math-aware) | `ingestion/extract.py` |
| Chunking | `ingestion/chunk.py` |
| Embeddings | `ingestion/embed.py` |
| Indexing into Qdrant | `ingestion/index.py` |
| Ingestion entry point | `ingestion/run.py` |
| Data contract | `ingestion/schema.py` |
| Retrieval + threshold + filter + hybrid RRF | `core/retrieval.py` |
| Grounded answer + citations + streaming | `core/answer.py` |
| CLI ask | `core/ask.py` |
| Agent graph + router | `agent/graph.py`, `agent/state.py` |
| Agent nodes (explain / generate / grade / reexplain / quiz) | `agent/nodes/*.py` |
| Node persistence | `agent/persistence.py` |
| HTTP API | `api/main.py` |
| Streamlit UI + metrics dashboard | `ui/app.py`, `ui/metrics.py` |
| Relational store | `db/models.py`, `db/session.py`, `alembic/` |
| LLM factory, settings, cache | `core/config.py` |
| Tracing (LangFuse) / latency / budget | `core/obs.py`, `core/budget.py` |
| Deployment guides | `docs/DEPLOY-API.md` (Docker image), `docs/DEPLOY.md` (free-tier), `docs/LOCAL.md` (Ollama), `docs/OBSERVABILITY.md` |
| Faithfulness eval / calibration | `eval/run_eval.py`, `eval/calibrate.py` |
| Containerization | `docker-compose.yml`, `Dockerfile` |
| CI | `.github/workflows/ci.yml` |
| Dev tasks | `Makefile` |
