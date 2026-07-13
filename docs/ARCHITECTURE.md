# Architecture

`sourcio` is a course tutor that answers questions **strictly from the
user's own course material**. The guiding principle drives every design choice:
never leave the course, always cite the source, and refuse when a question is
not covered. This document explains how the system is put together so a new
contributor can find their way around.

## Guiding principle

| Risk with a general assistant | How `sourcio` addresses it |
| --- | --- |
| Documents are lost between conversations | A persistent vector store (Qdrant), courses indexed once |
| Answers drift to out-of-course methods | Retrieval is restricted to the course; nothing else is in context |
| No verifiable sources | Citations (course, chapter, page) are produced by construction |
| The model may hallucinate | Refusal is guarded twice: a similarity floor drops clearly-unrelated questions before any LLM runs, and the grounded prompt refuses when the retrieved sources do not cover the request. An offline faithfulness judge checks the rest |

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
  ingestion/index.py  -->  [ Qdrant ]  collection "courses"
                                       point = one chunk:
                                         vector  -> the embedding (what search ranks on)
                                         payload -> {text, course, chapter, page, document, owner}


                         ONLINE SERVING (per request)

  client (web app or HTTP)
      |
      v
  api/routers/*            auth resolves the caller's `owner` id
      |
      v
  core/retrieval.py  ---->  [ Qdrant ]   top-k, filtered by owner + course + chapter
      |                                  (opt-in: reranker, hybrid BM25/RRF, HyDE, multi-query)
      |
      +-- nothing clears SIMILARITY_THRESHOLD --> REFUSAL  (the LLM is never called)
      |   (a coarse floor -- it stops the obviously unrelated, not everything)
      |
      v
  agent/nodes/{explain,generate,grade,reexplain,quiz}
      |          the node is shown only the chunk TEXT, numbered [1] [2] [3]
      |          -- never a page number, so it cannot invent one
      v
  core/answer.py           remaps each [n] -> (course, chapter, page) read from the payload
      |
      +-->  [ SQL: students, exercises, grades, messages ]  (db/, via agent/persistence.py)
      |
      v
  cited answer

  core/llm.py     get_llm(role)  model-agnostic factory   (+ core/obs.py, core/budget.py)
  agent/graph.py  LangGraph router + state graph -- an agentic *reference*, NOT the serving
                  path: every endpoint dispatches straight to its node above.


                         QUALITY LAYER

  OFFLINE (library-level, no HTTP)         corpus: eval/dataset.jsonl (50 cases)
    eval/run_eval.py      faithfulness + relevance + refusal + retrieval-hit  (LLM judge)
    eval/benchmark.py     the same, per LLM provider (+ citation rate, latency)
    eval/calibrate.py     derives SIMILARITY_THRESHOLD empirically         [no LLM, free]
    eval/ab_retrieval.py  dense vs hybrid on Recall@k / MRR / NDCG         [no LLM, free]

  LIVE (endpoint-level, real HTTP)         corpus: eval/live_eval_cases.json (71 cases)
    eval/live_eval.py     drives /ask, /exercise, /quiz against a running deployment --
                          the only harness that exercises the product rather than the library
```

Two things this diagram is drawn to make unmissable, because they are the whole
argument of the project:

- **Refusal is guarded twice, and the first guard is not a model.** When nothing
  clears the similarity floor, the pipeline stops *before* the LLM: a model that is
  never called cannot be talked into answering.

  Be precise about what that floor does, though. It is **coarse**. Measured on the
  benchmark corpus (`eval/calibrate.py`, 32 in-course vs 18 out-of-course
  questions), in-course questions score 0.47-0.71 and out-of-course ones score
  0.31-0.57: **the two overlap.** No threshold separates them cleanly, and the
  shipped default (0.35) is set low on purpose, to favour recall on real,
  heterogeneous documents. So most out-of-scope questions *do* reach the model.

  What refuses them is the **second** guard: the grounded prompt, which is shown
  only the retrieved chunks and instructed to refuse when they do not cover the
  request. That guard carries the bulk of the work, and it holds — 23 refusal cases
  in the endpoint benchmark, one miss.

  Claiming the model "is never called" would be a nicer story. It is not the true
  one, and a guarantee you have not measured is not a guarantee.
- **Citations cannot be hallucinated.** The node sees chunk text under opaque indices
  `[1] [2] [3]`. Page numbers live in the Qdrant payload and are stitched in afterwards
  by `core/answer.py`. The model never handles a page number, so it cannot invent one.

And one thing it is drawn to prevent: reading `agent/graph.py` as the request path. It
is not. It is a tested reference implementation of the same routing done agentically.

## Offline ingestion pipeline

Run once per course: `python -m ingestion.run path/to/course.pdf --course "..."`
(`ingestion/run.py`); add `--sparse` to also index bge-m3 lexical vectors and
enable opt-in hybrid retrieval. The same entry point also ingests prose `.md` and
`.txt` files, which take the overlapping-window chunking path instead of the
per-slide one. The shared data contract for the whole pipeline lives in
`ingestion/schema.py` (`Page`, `Chunk`, `Retrieved`).

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

`ingestion/run.py` processes pages in **batches** (extract -> chunk -> index per
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

**Advanced retrieval modes** are all **opt-in and default off**; each is gated by
a `Settings` flag (`core/config.py`) and **preserves the refusal guard** — the
dense similarity threshold still pre-filters, so an out-of-course question yields
nothing and is refused. They compose, and the answer layer selects them in
`core/answer.py:_retrieve`:

- **Cross-encoder reranker** (`reranker_model`, `rerank_candidates`): fetches more
  thresholded candidates, rescores each `(question, chunk)` pair locally with a
  cross-encoder (`rerank`), and keeps the best k. The returned `.score` becomes
  the cross-encoder relevance. No re-ingestion required.
- **Hybrid dense + sparse** (`hybrid_retrieval`, set via `HYBRID_RETRIEVAL=1`):
  fuses two branches with **Reciprocal Rank Fusion (RRF)** through Qdrant's Query
  API — a dense kNN branch (bge-m3 dense vectors, threshold-filtered) and a
  lexical **sparse** branch (bge-m3 lexical weights, a BM25-style signal,
  `sparse_vector_name`, `hybrid_prefetch`). It engages only when the collection
  actually carries the named sparse vector (`_collection_has_sparse`); if hybrid
  is requested but the collection has no sparse vector, retrieval transparently
  **falls back to dense**. Sparse vectors are produced at ingest time with
  `--sparse` (`ingestion/embed.py:embed_sparse_texts`, `ingestion/index.py`), so
  hybrid needs a one-off `--sparse` re-ingest.
- **Multi-query expansion** (`multi_query`, `multi_query_n`): `retrieve_multi`
  rewrites the question into a few diverse sub-queries
  (`core/query.py:expand_query`), retrieves per query, and fuses the candidate
  lists by chunk id (best score) before the threshold and the optional reranker
  apply. It only widens recall.
- **HyDE** (`hyde`): embeds a short hypothetical answer passage
  (`core/query.py:hyde_passage`) instead of the bare question for the dense
  branch, which often lands closer to indexed chunks; the threshold is applied to
  that probe unchanged. Multi-query takes precedence when both are set.
- **Neighbor-chunk expansion** (`neighbor_expansion`, `neighbor_window`): *after*
  the thresholded (and optionally reranked) top results are chosen, pulls adjacent
  slides/windows (same course/chapter, page within `±window`) via a payload-only
  `scroll` and appends them as context, de-duped and capped. It never runs on an
  empty retrieval (refusal untouched) and degrades to the un-expanded results on
  any error.

The dense, hybrid, and HyDE branches share `_fetch_candidates`; reranking and
neighbor expansion wrap whichever base path runs.

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

The agentic layer is a LangGraph `StateGraph` (`agent/graph.py`) threading a single
`TutorState` TypedDict (`agent/state.py`): a router classifies the message into one
of four intents and dispatches to a node, each writing only its own output key. The
**deployed product does not route through the graph** — each API endpoint (`/ask`,
`/exercise`, `/grade`, `/quiz`, `/reexplain`) calls the matching node/function
directly (via `api/runtime.py`), which is simpler and gives the UI explicit
actions. The graph is kept as a tested reference that exercises the same nodes and
the router, demonstrating the agentic routing/state pattern end to end.

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

### API (`api/`)

A thin FastAPI layer, organized as `main.py` (app creation and wiring) plus
per-domain routers. Each route delegates to the existing grounded functions and
nodes — no retrieval or prompting is reimplemented. Endpoints group by area:

| Area | Endpoint | Role |
| --- | --- | --- |
| Health | `GET /health` | liveness probe (always open) |
| Health | `GET /ready` | readiness probe: 200 once the database engine is bound, else 503 |
| Tutoring | `POST /ask` | answer a question, grounded; persists the turn as history |
| Tutoring | `POST /ask/stream` | same answer as Server-Sent Events: token deltas, then a final sources/refusal event; persists on completion |
| Tutoring | `POST /reexplain` | rephrase the last answer at a chosen level (beginner / intermediate / advanced) |
| Tutoring | `POST /exercise` | generate an exercise; never returns the reference solution |
| Tutoring | `POST /grade` | grade a student's answer |
| Quiz | `POST /quiz` | generate a grounded multi-question quiz; reference solutions stay server-side |
| Quiz | `POST /quiz/{quiz_id}/grade` | grade one quiz answer against its stored reference solution (404 on unknown question) |
| Feedback | `POST /feedback` | record a thumbs up/down on a tutor answer (rating validated to ±1) |
| Feedback | `GET /feedback/summary` | aggregate up/down counts for a student |
| Sessions | `POST /sessions` | open a named conversation thread for a student |
| Sessions | `GET /sessions/{student_id}` | list a student's threads, newest first |
| Sessions | `GET /sessions/{student_id}/{session_id}/messages` | one thread's messages, chronological (404 if not the student's) |
| Sessions | `GET /history/{student_id}` | recent conversation turns, chronological |
| Auth | `POST /auth/register` | create an account (bcrypt-hashed password); 409 on duplicate email |
| Auth | `POST /auth/login` | verify credentials, return a signed JWT bearer token |
| Auth | `GET /auth/me` | the authenticated user (bearer token required) |
| Auth | `GET /me/students` | student identities owned by the caller |
| Courses | `GET /courses` | distinct courses currently indexed in Qdrant |

The API is **stateful**: a `student_id` identifies the user (get-or-create),
`/ask` turns are persisted, and `/history` replays them. An optional
`session_id` on `/ask` attaches the turn to a named thread (`Session`), validated
to belong to the student.

Two **independent** auth layers coexist (`api/auth.py`, `api/main.py`):

- **Opt-in API key** (`Settings.api_key`): empty leaves the API open; a non-empty
  value requires a matching `X-API-Key` header on the mutating endpoints and
  `/history` (`require_api_key`). `/health` and `/ready` stay open.
- **JWT account auth**: `register` / `login` issue a bearer token (HS256, signed
  with `Settings.jwt_secret`, expiring after `jwt_expire_minutes`); bcrypt hashes
  the password. Auth is **additive** — when a request carries a valid token, the
  resolved student is linked to that account (`_resolve_student`), so its turns,
  exercises, quizzes and feedback become the user's own data, without changing any
  answer. Anonymous, `external_id`-keyed students stay unlinked.

The database engine is bound on startup (or injected by tests via
`configure_engine`).

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
| **SQL** (SQLite in dev, managed PostgreSQL in production) | users, students, exercises + reference solutions, grades, quizzes, conversation messages, threads, feedback |
| **LangFuse** (optional) | traces and per-step evaluation signals |

The relational layer uses SQLAlchemy 2.0 declarative models (`db/models.py`):

- `User` — a registered account (email + bcrypt password hash) that may own zero
  or more students; the link is optional, so anonymous `external_id`-keyed
  students stay unlinked and existing flows are unaffected.
- `Student` — a reviser, optionally owned by a `User` (`user_id`).
- `Exercise`, `Grade` — a generated exercise with its server-side reference
  solution, and a judged answer. A `Grade` links to either an `Exercise` or a
  `QuizQuestion` (exactly one foreign key set).
- `Quiz`, `QuizQuestion` — a multi-question quiz and its grounded questions, each
  with a withheld reference solution.
- `Session` — a named conversation thread grouping a student's messages; a
  `Message` references it through a nullable `session_id`, so unthreaded messages
  stay valid (purely additive).
- `Message` — one conversation turn.
- `Feedback` — a student's thumbs up/down (±1) on a tutor answer, capturing the
  question and answer verbatim for later offline evaluation.

The engine is created lazily from `Settings.database_url` (`db/session.py`), so
swapping SQLite for PostgreSQL is just a URL change — which is exactly how the
deployed instance runs, since a container's SQLite file would not survive a
restart. See [OPERATIONS.md](OPERATIONS.md). Schema migrations are managed by Alembic
(`alembic/`), which resolves the same URL at runtime and diffs against the
declarative `Base`.

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
and free — see [RUN-LOCAL.md](RUN-LOCAL.md). For serving, the API ships as a **CPU-only
Docker image** that installs a CPU-only `torch` to avoid multi-gigabyte CUDA
wheels; the image, its env-var reference, and the free-tier hosted path are all in
[DEPLOY.md](DEPLOY.md).

The factory also composes two opt-in, zero-cost-when-disabled cross-cutting
concerns:

- **LangFuse tracing + latency instrumentation** (`core/obs.py`): tracing
  activates only when LangFuse credentials are present (the package is imported
  lazily), staying zero-cost when off — see [OPERATIONS.md](OPERATIONS.md).
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

## Ops and hardening (`api/`)

Three concerns wrap the HTTP layer, all safe by default:

- **Structured logging + request id** (`api/logging_config.py`,
  `api/middleware.py:RequestIdMiddleware`): startup configures a JSON logger at
  `Settings.log_level`. Each request reuses an inbound `X-Request-ID` or generates
  one, propagates it through a contextvar so every log line carries it, and echoes
  it on the response. A global handler turns unhandled exceptions into a generic
  500 body (with the request id) without leaking the stack trace.
- **Readiness vs liveness**: `/health` is always-open liveness; `/ready` reports
  whether startup wiring (chiefly the database engine) completed, returning 503
  until then — safe for an orchestrator to poll.
- **Security headers + rate limiting** (`api/middleware.py`): security headers are
  added on every response (`SecurityHeadersMiddleware`), with
  `Strict-Transport-Security` only when `enable_hsts` is set (TLS deployments).
  The in-process limiter (`RateLimitMiddleware`) is a no-op unless
  `rate_limit_per_minute` is positive; when set it caps each client (by IP) per
  rolling minute and rejects excess with `429` + `Retry-After`. It is per-process,
  not a substitute for an edge limiter in a multi-replica deployment.

## Request lifecycle: `POST /ask`

A walkthrough of a single question, end to end:

1. **Client -> API.** The client (the web app or any HTTP caller) sends
   `{student_id, question, k}` to `POST /ask` (`api/`). If an API key is
   configured, `require_api_key` validates the `X-API-Key` header.
2. **API -> answer.** The route calls `answer(question, k)` (`core/answer.py`).
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
| Retrieval (threshold, filter, hybrid RRF, reranker, HyDE, multi-query, neighbors) | `core/retrieval.py` |
| Query rewriting (multi-query, HyDE) | `core/query.py` |
| Course discovery | `core/courses.py` |
| Grounded answer + citations + streaming | `core/answer.py` |
| CLI ask | `core/ask.py` |
| Agent graph + router (agentic reference; not in the request path) | `agent/graph.py`, `agent/state.py` |
| Agent nodes (explain / generate / grade / reexplain / quiz) | `agent/nodes/*.py` |
| Node persistence | `agent/persistence.py` |
| HTTP API | `api/` (`main.py` app + per-domain routers) |
| User auth (bcrypt + JWT) | `api/auth.py` |
| Logging / middleware (request-id, security headers, rate limit) | `api/logging_config.py`, `api/middleware.py` |
| Next.js web frontend (premium UI) | `web/` (`web/app/`, `web/components/`, `web/lib/`) |
| Relational store | `db/models.py`, `db/session.py`, `alembic/` |
| LLM factory, settings, cache | `core/config.py` |
| Tracing (LangFuse) / latency / budget | `core/obs.py`, `core/budget.py` |
| Deployment & ops guides | `docs/DEPLOY.md` (cloud + Docker image + env reference + R2), `docs/RUN-LOCAL.md` (Ollama), `docs/OPERATIONS.md` (Postgres + LangFuse) |
| Faithfulness eval / calibration | `eval/run_eval.py`, `eval/calibrate.py` |
| Containerization | `docker-compose.yml`, `Dockerfile` |
| CI | `.github/workflows/ci.yml` |
| Dev tasks | `Makefile` |
