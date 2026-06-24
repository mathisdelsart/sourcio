# grounded-rag

**An AI tutor that answers strictly from your own course material, always citing the source, and refuses anything it does not cover.**

`grounded-rag` indexes your courses once (slides, exercise sets, summaries) into a persistent vector
store, then answers questions using *only* those documents. Every claim is backed by a citation
(course, chapter, page), and when nothing in the material is relevant enough, the system says so
instead of guessing. The running use case is a study assistant over university courses, but the
pipeline is document-agnostic.

## Why it beats a generic chatbot for studying

| Generic chatbot | grounded-rag |
| --- | --- |
| Documents are lost between conversations | **Persistent indexed knowledge base** (Qdrant), courses indexed once |
| Drifts to out-of-source methods and content | **Strict grounding** behind a calibrated **similarity threshold**: irrelevant retrieval becomes an explicit refusal |
| References cannot be verified | **Systematic citations** (course / chapter / page) on every answer |
| Can hallucinate confidently | **Faithfulness guard**: an offline judge checks that answers are supported by the retrieved sources |

Citations are produced **by construction**, not on trust. The model only ever sees numbered sources
`[1] [2] [3]` and is instructed to cite those indices; the code then remaps each `[n]` to its real
source label. The model never handles page numbers, so it cannot invent one.

## Architecture

The system splits into an **offline** ingestion pass (run once per course) and an **online** agent
that serves requests, plus an offline **quality / evaluation** layer.

```
OFFLINE — ingestion (once per course)
  PDF
   -> math-aware extraction        (slides -> Markdown + LaTeX preserved)
   -> adaptive chunking            (one slide ≈ one chunk; prose split with overlap)
   -> multilingual embeddings      (BAAI/bge-m3, local)
   -> Qdrant upsert                ({vector, payload: course/chapter/page/text})

ONLINE — agent (per request)
              ┌─ explain     RAG -> grounded, cited answer (or refusal)
   router ────┼─ generate    grounded exercise + reference solution
   (intent)   ├─ grade       LLM-as-a-judge on the student's answer
              └─ reexplain   rephrase, keeping conversation memory

QUALITY — offline / CI
  reference questions -> answer -> faithfulness + relevance judge -> pass/fail gate
```

**Math-aware extraction.** Pages are rasterized and transcribed by a vision model into Markdown with
LaTeX kept inline, so formulas survive ingestion. A `--hybrid` flag routes plain-text pages to fast,
free PyMuPDF extraction and reserves the vision path for math- and figure-heavy pages. Transcriptions
run concurrently (`--concurrency`), and `--pages` / `--max-pages` allow targeting a subset.

**Adaptive chunking.** Chunking follows the document type: slide decks map roughly one slide to one
chunk (so unrelated slides are not glued together), while prose is split into overlapping windows.

**Retrieval with refusal.** A question is embedded with the same model used at indexing time, and the
top-k chunks are fetched from Qdrant with a `score_threshold`. If nothing clears the threshold, the
answer layer returns an explicit refusal rather than answering from the model's own knowledge. The
threshold is calibrated empirically (in-course questions accepted, out-of-course questions rejected).

**Agent.** A LangGraph router classifies the intent (`explain` / `generate` / `grade` / `reexplain`)
and dispatches to the matching node, with a deterministic keyword fallback if the model output is
unusable. `generate` is itself grounded in retrieval so exercises stay calibrated to the course's own
notation.

**Quality layer.** An offline judge (distinct from the product-side grading node) checks answers for
**faithfulness** (every claim supported by the retrieved sources, no outside knowledge) and
**relevance**, plus **refusal accuracy** on questions that should be rejected. It runs from a
reference dataset and exits non-zero on regression, so it can gate CI.

## Tech stack

`Python` · `LangChain` / `LangGraph` · `FastAPI` · `Qdrant` · `Docker` · `GitHub Actions`

- **Embeddings:** local multilingual `BAAI/bge-m3` (documents and questions are in French) — free, no API call.
- **PDF extraction:** PyMuPDF for plain-text pages; a vision model for math/figure pages.
- **Model-agnostic LLM factory:** `get_llm(role)` selects a model per role from `LLM_<ROLE>` env vars,
  defaulting to a small OpenAI chat model. Swapping models (small router, larger generator/grader) is
  an environment change, not a code change.
- **Packaging:** `uv` (lockfile, no `requirements.txt`). **Lint/format:** `ruff`.

## Quickstart

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Docker.

```bash
# 1. Install dependencies (extras are installed per phase)
uv sync --extra ingestion --extra agent

# 2. Start the vector database
docker compose up -d qdrant

# 3. Configure the environment
cp .env.example .env        # then set OPENAI_API_KEY

# 4. Ingest a course PDF (vision extraction; --hybrid for cheaper text pages)
uv run python -m ingestion.run path/to/course.pdf --course "Wavelet Transform" --hybrid

# 5. Ask a grounded, cited question from the CLI
uv run python -m ask "What is a piecewise constant approximation?"

# 6. (Optional) run the offline faithfulness/relevance evaluation
uv run python -m eval.run_eval
```

### Service interface (API)

The same capabilities are exposed as an HTTP service (FastAPI):

| Endpoint | Role |
| --- | --- |
| `POST /ask` | ask a question / re-explain |
| `POST /exercise` | generate an exercise (never returns the reference solution) |
| `POST /grade` | grade a student's answer |
| `GET /health` | health check |

Run it with:

```bash
uv run uvicorn api.main:app --reload
```

## Example

A grounded answer cites only the sources it relies on:

```
$ uv run python -m ask "What is a piecewise constant approximation?"

A piecewise constant approximation represents a signal as a sum of scaled,
shifted box functions that are constant on each dyadic interval, capturing the
signal's average over that interval (Wavelet Transform, Chap. 2, p.11).

Sources:
  - (Wavelet Transform, Chap. 2, p.11)
```

A question the course does not cover is refused, not answered:

```
$ uv run python -m ask "How do I set up a Kubernetes cluster?"

This is not covered in the course material.
```

## Metrics

Tracked by the offline evaluation harness (`eval/run_eval.py`) over the reference dataset:

- **Refusal accuracy** — out-of-course questions correctly refused.
- **Faithfulness rate** — answers fully supported by their retrieved sources.
- **Relevance rate** — answers that actually address the question.
- **Retrieval precision** — the right chunk retrieved for in-course questions.

> TODO: publish a measured headline number (for example, faithfulness rate on the reference set)
> once the dataset is expanded.

## Notes

- Demo screenshot / GIF: _TODO_.
- `.env`, secrets, and course PDFs are never committed (personal data).
- Author: `mathisdelsart`.
