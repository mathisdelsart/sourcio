# eval/

The offline quality layer — the system-quality guard against hallucination,
distinct from the product-side grading of a student's answer. It runs locally and
in CI (via `tests/`) so a regression fails the build.

## What runs here

| File | Responsibility |
| --- | --- |
| `run_eval.py` | Faithfulness evaluation (judge #2). For each question in `dataset.jsonl`, calls the answer function; checks refusal cases refused, and scores answerable cases for faithfulness and relevance, plus an optional retrieval-hit check. Answer function, judge and retriever are injectable, so unit tests run with no API call. The canonical harness (`make eval`). |
| `report.py` | Renders a `run_eval` metrics dict into a Markdown report (used by `run_eval --report`). |
| `calibrate.py` | Empirically calibrate the similarity threshold: measure top retrieval similarity per labeled question and sweep candidates to best separate in-course from out-of-course. |
| `ab_retrieval.py` | LLM-free A/B harness comparing retrieval configurations (dense vs hybrid) on Recall@k / MRR / NDCG. |
| `benchmark.py` | **Offline** provider benchmark: extends `run_eval` with extra metrics (citation rate, answer-keyword, latency) over `thesis_benchmark.jsonl`, run once per LLM provider. See [Provider benchmark](#provider-benchmark) below. |
| `compare_report.py` | Render two `benchmark.py` JSON runs into a side-by-side Markdown table. |
| `live_eval.py` | **Live** end-to-end runner: drives the running HTTP API (`/ask`, `/exercise`, `/quiz`) over `live_eval_cases.json` with an external LLM reviewer, writing each run under `eval/live_runs/`. A manual smoke tool, not run in CI. |
| `dataset.jsonl` | Reference questions for the faithfulness eval (`run_eval`, `calibrate`, `ab_retrieval`). |
| `thesis_benchmark.jsonl` | The 27-case provider benchmark set for `benchmark.py`. |
| `live_eval_cases.json` | Cases for the live `live_eval.py`. |

## How it fits

The judge here verifies the bot does not hallucinate; the product judge that marks
a student's answer lives in `agent/nodes/grade.py`. Both use the model-agnostic
factory. See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Run it

```bash
uv run python -m eval.run_eval                       # faithfulness judge (calls the LLM)
uv run python -m eval.run_eval --out eval/results.json
uv run python -m pytest tests/test_eval.py tests/test_calibrate.py tests/test_ab_retrieval.py -q
```

## Provider benchmark

`benchmark.py` runs the full pipeline (retrieve → answer → judge) over
`eval/thesis_benchmark.jsonl`, a 27-case set drawn from a DRL / MicroRTS master
thesis indexed in Qdrant. Run it twice — once per LLM provider — then compare side
by side, to show the grounded system behaves consistently across a paid (OpenAI)
and a free-tier (Groq) model.

`thesis_benchmark.jsonl` uses the same schema as `dataset.jsonl` (`question`,
`expect_refusal`, `note`, `expect_keywords`) plus an optional `category`: **factual**
(13) single-fact questions, **math** (3) formulas/arithmetic, **synthesis** (6)
short reasoning, **refuse** (5) out-of-scope. That is 22 answer-cases + 5
refuse-cases.

**Metrics per run:** refusal accuracy, faithfulness / relevance (judge #2),
citation rate, retrieval hit rate, answer-keyword rate, and retrieval latency
p50/p95 (needs `LATENCY_ENABLED`).

Prerequisites: Qdrant up with the thesis indexed, DB migrated. Add `--course
"<name>"` to scope retrieval to the thesis if the collection holds several courses.
Real runs make paid API calls.

```bash
# OpenAI (default provider)
LATENCY_ENABLED=1 uv run python -m eval.benchmark \
  --out eval/bench-openai.json --latency-out eval/bench-openai-latency.json

# Groq (free tier)
LATENCY_ENABLED=1 LLM_PROVIDER=groq GROQ_API_KEY=... uv run python -m eval.benchmark \
  --out eval/bench-groq.json --latency-out eval/bench-groq-latency.json

# Compare the two into a Markdown table (the stored `provider` field labels the
# columns automatically; override with --label-a / --label-b)
uv run python -m eval.compare_report \
  eval/bench-openai.json eval/bench-groq.json --out eval/bench-compare.md
```
