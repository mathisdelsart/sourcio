# LangFuse — LLM observability

## The problem it addresses

A single `/ask` request expands into: an embedding, a Qdrant query, a prompt assembled from
five chunks, a model call, and a citation remap. When the answer is wrong, "wrong" may mean
that retrieval returned the wrong chunks, that it returned the right ones and the model
ignored them, that the prompt was truncated, or that the model was correct and the citation
remap failed.

A request log records that the call took 4.2 s and returned 200. It records nothing about
which of those five stages failed, and the input — a user's question — is no longer available
to reproduce it.

## What a trace records

```
trace: /ask "how do I discount a cash flow?"
├── span: retrieve          (120 ms) → 3 chunks, scores 0.68 / 0.61 / 0.55
├── generation: gpt-4o-mini (2.1 s)
│     input:  <the exact prompt, with the three chunks inlined>
│     output: <the exact completion>
│     tokens: 1,240 in / 180 out     cost: $0.0004
└── span: citation remap    (2 ms)
```

Three things unavailable from logs:

1. **The exact prompt the model received** — not the template, the rendered string with the
   chunks actually retrieved. Most "the model is wrong" reports resolve to "the model was
   shown the wrong context", and this is where that becomes visible.
2. **Tokens and cost per call, per role.** In this system, vision extraction (per PDF page)
   dominates every other role.
3. **Latency attributed by stage.** The measurement that the cross-encoder reranker adds
   +220 ms per query came from this breakdown.

## Why LangFuse rather than a generic APM

A conventional APM (Datadog, OpenTelemetry) measures the wrong nouns. It is excellent at
"p99 latency of `POST /ask`" and has no concept of a prompt, a completion, a token count or a
cost. LLM data can be forced into span attributes, but prompt inspection, cost per model and
evaluation scores attached to traces are not recoverable from that.

The realistic alternative is **LangSmith** — capable, but SaaS-only and tied to the LangChain
ecosystem. LangFuse is open source and self-hostable, which is coherent with a project whose
stated property is that it can run locally at zero cost, and it keeps trace contents (which
include user questions and document text verbatim) on infrastructure the operator controls.

## Integration

Through LangChain's callback hook, so no call site is aware of it:

```python
callbacks = get_callbacks() + get_budget_callbacks(budget)
if callbacks:
    llm = llm.with_config(callbacks=callbacks)
```

`get_callbacks()` returns `[]` unless both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`
are set, and the `langfuse` package is not imported at all when tracing is disabled. Opt-in,
and free when off.

## A defect this design produced

`get_llm` calls `.with_config(...)` **only when callbacks exist**. CI has no `.env`, so
callbacks were always empty and that branch never executed. On a developer machine with
LangFuse configured, the branch did execute — and failed against the fake object the tests
inject.

**Eleven tests failed for anyone with observability configured, and CI remained green.** The
suite had no shared `conftest.py`, so every test silently inherited the developer's
environment.

The fix was an autouse fixture neutralising the ambient environment, so a local run matches
CI. The general point: an opt-in feature introduces a second code path, and a second code
path that exists only on some machines will not be exercised by a test suite that has not
been made hermetic.

## Operational considerations

- **Sampling.** 100% in development. In production, traces carry full prompts — which is both
  a storage cost and, potentially, user data.
- **PII.** Traces contain the user's question and their document text verbatim. On a
  self-hosted deployment this stays within the operator's infrastructure, which is part of the
  rationale above.
- **Evaluation scores can be attached to traces**, closing the loop between the offline
  faithfulness harness and the live request that produced the answer.

## What to monitor

HTTP latency and error rate confirm the API is up; they say nothing about answer quality. The
signals that matter are LLM-specific: retrieval scores drifting downward, a rising refusal
rate (the corpus no longer covers what users ask), a falling citation rate. Those live in
traces, not in HTTP metrics.
