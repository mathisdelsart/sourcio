# core/

The grounding engine. Everything that keeps an answer inside the course lives here: retrieval with a
similarity threshold, the by-construction citation mechanism, honest refusal, and the model-agnostic
LLM factory. The API and the agent nodes call into this package; they never re-implement retrieval or
prompting.

## Key modules

| File | Responsibility |
| --- | --- |
| `retrieval.py` | `retrieve(question, k, course, chapter)` — embed the query, fetch top-k from Qdrant above the similarity threshold, apply course/chapter filters. Hosts the opt-in modes: cross-encoder reranker, hybrid dense + sparse (RRF), multi-query, HyDE, neighbor expansion. Each preserves the refusal guard. |
| `answer.py` | The one place retrieval, threshold, refusal and citation meet. Numbers chunks `[1] [2] [3]`, prompts the model to cite by index only, then `_remap_citations` rewrites `[n]` to `(course, chapter, p.N)`. Provides both blocking `answer` and streaming `stream_answer`. |
| `query.py` | Query rewriting used by the opt-in modes: multi-query expansion and HyDE hypothetical-passage generation. |
| `config.py` | `Settings` (env-driven) and `get_llm(role)` — the model-agnostic factory. Also configures the optional LLM response cache. |
| `courses.py` | Discover the distinct courses currently indexed in Qdrant. |
| `documents.py` | Read-only inventory of indexed material (grouped by course/chapter/page) plus delete, backing the Documents UI. |
| `sources.py` | Fetch a single chunk by id for the "view source" feature. |
| `jobs.py` | In-process registry of background jobs (document ingestion, streamed answers) so long uploads survive an HTTP request and can be polled. |
| `storage.py` | Durable object storage (Cloudflare R2) for uploaded originals; falls back to local disk when unset. |
| `scheduling.py` | The SM-2 spaced-repetition scheduler (LLM-free). |
| `obs.py` | Opt-in LangFuse callbacks and the per-stage latency timer (zero-cost when off). |
| `budget.py` | Token-budget callback that raises `BudgetExceeded` at a configured cap. |
| `errors.py` | Turns opaque provider capacity errors into an actionable message. |
| `ask.py` | CLI entry point: `python -m core.ask "..."`. |

## How it fits

Ingestion writes chunks into Qdrant; `core/` reads them back, grounds an answer, and cites it. The
agent graph (`agent/`) and the HTTP layer (`api/`) are thin wrappers over these functions. Design
rationale is in [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Try it

```bash
docker compose up -d qdrant                 # vector store must be reachable
uv run python -m core.ask "What is a piecewise constant approximation?"
uv run python -m pytest tests/test_retrieval.py tests/test_grounding.py -q
```
</content>
