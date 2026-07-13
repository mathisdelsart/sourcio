# eval/

The quality layer — the guard against hallucination, distinct from the
product-side grading of a student's answer. It runs locally and in CI (via
`tests/`) so a regression fails the build.

## One corpus

Everything here is measured against the **same six chapters**: Finance (ch. 1-3)
and Relativity (ch. 1-3), the documents in `uploads/bench/`. There is one dataset
(`dataset.jsonl`) and one case list (`live_eval_cases.json`); a metric you read
here and a metric you read there describe the same material.

That is deliberate. The harness previously ran against corpora that were no longer
indexed, which is the worst failure mode an eval can have: it still produces
numbers, they are just meaningless. Everything now targets a corpus that is
actually there.

## What the harness has actually told us

Two findings worth keeping, both from running it rather than reading it:

- **The similarity floor is coarse, and that is fine.** `calibrate.py --owner <id>` scores in-course
  questions at 0.47–0.71 and out-of-scope ones at 0.31–0.57. **The classes overlap**, so no threshold
  separates them; the tool's "recommended" value maximises accuracy by falsely refusing 7 of 32
  legitimate questions, which is the wrong trade for a tutor. The shipped floor stays deliberately low
  and the grounded prompt does the fine-grained refusing. Read the report, do not paste its number.
- **Query rewriting buys nothing here.** Dense retrieval already hits 32/32; `multi_query` matches it
  exactly, at the price of an extra LLM call per question — and, because it puts a model *inside* the
  retrieval path, it can make the same question answerable for one visitor and refused for another
  (fixed in #228, but the setting is still not worth enabling on a corpus like this one).

## Two benchmarks, two questions

- **`live_eval.py` — does the product work?** Drives the real HTTP API over
  `live_eval_cases.json`, the way the web app does. This is the one to run after a
  deploy.
- **`run_eval.py` + friends — does retrieval hallucinate?** Calls the library
  directly over `dataset.jsonl`, with an LLM judging faithfulness. This is the one
  to run after touching retrieval.

## What runs here

| File | Responsibility |
| --- | --- |
| `run_eval.py` | Faithfulness evaluation (judge #2). For each question in `dataset.jsonl`, calls the answer function; checks refusal cases refused, and scores answerable cases for faithfulness and relevance, plus an optional retrieval-hit check. Answer function, judge and retriever are injectable, so unit tests run with no API call. The canonical harness (`make eval`). |
| `report.py` | Renders a `run_eval` metrics dict into a Markdown report (used by `run_eval --report`). |
| `calibrate.py` | Empirically calibrate the similarity threshold: measure top retrieval similarity per labeled question and sweep candidates to best separate in-course from out-of-course. |
| `ab_retrieval.py` | LLM-free A/B harness comparing retrieval configurations (dense vs hybrid) on Recall@k / MRR / NDCG. |
| `benchmark.py` | **Offline** provider benchmark: extends `run_eval` with extra metrics (citation rate, answer-keyword, latency) over the same `dataset.jsonl`, run once per LLM provider. See [Provider benchmark](#provider-benchmark) below. |
| `compare_report.py` | Render two `benchmark.py` JSON runs into a side-by-side Markdown table. |
| `live_eval.py` | **Live** end-to-end runner: drives the running HTTP API (`/ask`, `/exercise`, `/quiz`) over `live_eval_cases.json` with an external LLM reviewer, writing each run under `eval/live_runs/`. A manual smoke tool, not run in CI. |
| `dataset.jsonl` | The 50-case labeled set (`run_eval`, `benchmark`, `calibrate`, `ab_retrieval`). |
| `live_eval_cases.json` | The 71-case endpoint set for `live_eval.py`. |

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
`eval/dataset.jsonl`. Run it twice — once per LLM provider — then compare side by
side, to show the grounded system behaves consistently across a paid (OpenAI) and
a free-tier (Groq) model.

`dataset.jsonl` carries `question`, `expect_refusal`, `note`, `expect_keywords`
plus a `category`: **factual** (17) single-fact questions, **math** (7)
formulas/arithmetic, **synthesis** (8) short reasoning, **refuse** (18)
out-of-scope. That is 32 answer-cases + 18 refuse-cases.

The refuse-cases outnumber what a pass/fail suite would need on purpose: `calibrate.py`
separates two score distributions, and estimating the out-of-scope one from a handful of
questions gives a threshold you cannot trust.

The refusal cases are deliberately **adjacent** to the material — the Sharpe ratio,
CAPM, the Schwarzschild radius — not absurd ones. Refusing "the capital of Belgium"
proves nothing about grounding; refusing CAPM *inside a finance course* does.

**Metrics per run:** refusal accuracy, faithfulness / relevance (judge #2),
citation rate, retrieval hit rate, answer-keyword rate, and retrieval latency
p50/p95 (needs `LATENCY_ENABLED`).

**Scope the run to the benchmark corpus with `--owner`.** Retrieval is owner-scoped
in the product but *unscoped* on the offline path, so a collection holding several
accounts' courses will happily answer an out-of-scope question from someone else's
documents — and the harness will score the missing refusal as a product failure.
Pass the account that owns `uploads/bench/` (`--owner u4` locally) so the run
measures the corpus the dataset was written against.

Prerequisites: Qdrant up with the six chapters indexed, DB migrated. Real runs make
paid API calls.

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
