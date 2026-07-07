# Benchmark comparison

| Metric | openai | groq llama-3.1-8b (k=2, free tier) | Delta (B - A) |
| --- | --- | --- | --- |
| Refusal accuracy | 100% | 70% | -29.6 pts |
| Faithfulness | 100% | 93% | -7.1 pts |
| Relevance | 100% | 100% | +0.0 pts |
| Citation rate | 100% | 100% | +0.0 pts |
| Retrieval hit rate | 100% | 100% | +0.0 pts |
| Answer-keyword rate | 91% | 71% | -19.5 pts |
| Retrieval latency p50 | 89 ms | 148 ms | +60 ms |
| Retrieval latency p95 | 115 ms | 164 ms | +50 ms |

## Counts

| Metric | openai | groq llama-3.1-8b (k=2, free tier) |
| --- | --- | --- |
| Total cases | 27 | 27 |
| Judged cases | 22 | 14 |
| Retrieval checked | 22 | 22 |
