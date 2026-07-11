# eval/

The offline quality layer — the system-quality guard against hallucination, distinct from the
product-side grading of a student's answer. It runs locally and in CI so a regression fails the build.

## What runs here

| File | Responsibility |
| --- | --- |
| `run_eval.py` | Faithfulness evaluation (judge #2). For each question in `dataset.jsonl`, calls the answer function; checks refusal cases refused, and scores answerable cases for faithfulness and relevance, plus an optional retrieval-hit check. Answer function, judge and retriever are injectable, so unit tests run with no API call. |
| `calibrate.py` | Empirically calibrate the similarity threshold: measure top retrieval similarity per labeled question and sweep candidates to best separate in-course from out-of-course. |
| `ab_retrieval.py` | A/B harness comparing retrieval configurations on Recall@k / MRR / NDCG. |
| `benchmark.py`, `bench_runner.py` | Run the full retrieve -> answer -> judge pipeline over a case set, once per LLM provider. |
| `compare_report.py`, `report.py` | Render results into Markdown tables (side-by-side provider comparison; eval report). |
| `dataset.jsonl` | Reference questions for the faithfulness eval. |
| `thesis_benchmark.jsonl`, `benchmark_cases.json` | The 27-case provider benchmark set and its cases. |

## How it fits

The judge here verifies the bot does not hallucinate; the product judge that marks a student's answer
lives in `agent/nodes/grade.py`. Both use the model-agnostic factory. See
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Run it

```bash
uv run python -m eval.run_eval                       # faithfulness judge (calls the LLM)
uv run python -m eval.run_eval --out eval/results.json
uv run python -m pytest tests/test_eval.py tests/test_calibrate.py tests/test_ab_retrieval.py -q
```

The provider benchmark and how to compare two runs: [BENCHMARK.md](BENCHMARK.md).
</content>
