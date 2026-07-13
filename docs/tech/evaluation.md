# Evaluation

## Role in the system

A RAG system cannot be validated with `assert output == expected`: the output differs on
every run and is still correct. The question is not whether the string matches, but whether
**every claim is supported by a source the answer cites**, and whether the system **refuses
what it should refuse**.

The evaluation layer answers those questions, and it runs in CI.

## The three LLM roles, which are not interchangeable

Conflating them is the most common misreading of this codebase:

| Role | Location | Runs in production |
| --- | --- | --- |
| **Exercise grader** | `agent/nodes/grade.py` — grades the *student's* answer | **Yes** |
| **Faithfulness judge** | `eval/run_eval.py` — checks that *Sourcio* does not hallucinate | No, offline |
| **Benchmark reviewer** | `eval/live_eval.py` — reviews benchmark output | No, test harness |

## Two harnesses

**Offline** (`run_eval`, `benchmark`, `calibrate`, `ab_retrieval`) calls the library
directly. `calibrate` and `ab_retrieval` use **no LLM at all**, so they are free,
deterministic and can be iterated on indefinitely. Run these after touching retrieval.

**Live** (`live_eval`) drives the **real HTTP API** of a running deployment — the same
endpoints, filters and headers the web app uses. This is the only harness that exercises the
*product*: authentication, chapter scoping, error paths, streaming.

They catch different classes of defect. The live harness found a bug the offline one
structurally could not: an opt-in booster made retrieval **model-dependent**, so the same
question was answered for one visitor and refused for another. See [rag.md](rag.md).

## Metrics

Deterministic, requiring no judge:

- **Refusal accuracy** — did it refuse what it should have refused?
- **Citation rate** — does the answer carry an `[n]` source marker?
- **Retrieval hit-rate** — was the passage that answers the question retrieved?

Judged by a second model:

- **Faithfulness** — is each claim supported by the retrieved passages?
- **Relevance** — does the answer address the question asked?

The deterministic metrics are load-bearing precisely because they need no judge. Where a
claim can be checked without an LLM, it is.

## Measured results

Endpoint benchmark, 71 cases against the live deployment, `gpt-4o-mini`:

| Metric | Result |
| --- | --- |
| Citation rate | **28/28 — 100%** |
| Answer-vs-refuse decision | **67/71 — 94%** |
| Refusal accuracy (out-of-scope cases only) | **22/23 — 96%** |
| Cross-account isolation | refused |
| Calls completed | 71/71 |

Retrieval, 50 labelled questions (32 in-course, 18 out-of-scope), owner-scoped:

| Metric | Result |
| --- | --- |
| Retrieval hit-rate | **32/32 — 100%** |
| Multi-query vs plain dense | identical — no gain on this corpus |

Faithfulness is **not** currently reported. It requires an LLM judge that has not been run
against the present corpus, and an unmeasured number is not a result.

## An LLM judge is an instrument, and it requires calibration

Running the endpoint benchmark with `gpt-4o-mini` as reviewer produced verdicts such as
*"the answer fails to cite Chapter 2"* — when the answer demonstrably did cite Chapter 2, in
the payload the reviewer had been handed. It also rejected a correct algebraic rearrangement
of a formula present in the cited source as "unsupported".

**Most of its failures were false.** Two changes followed:

1. **The reviewer is opt-in** (`--judge`), not enabled by default. A wrong verdict is worse
   than no verdict, because it directs effort at a defect that does not exist.
2. **The reviewer was being asked to verify grounding without being shown the sources.** The
   API returns citations as *labels* (`(Finance, Ch.1, p.2)`) — sufficient for a human, who
   can open the source, but the reviewer received only JSON. It could see *that* a source
   was cited, never *what it said*. Each citation is now hydrated with its full chunk text
   before review.

Several benchmark cases carry a **single verifiable number** in the source (4321.94,
231,676, 7.09) specifically so that a reviewer waving through a confidently wrong figure is
detectable.

## Threshold calibration

`SIMILARITY_THRESHOLD` decides refusal, so it is derived from data rather than chosen by
intuition. `eval/calibrate.py` scores every labelled question and sweeps candidate
thresholds.

Result on the benchmark corpus:

- in-course: **0.47 – 0.71**
- out-of-scope: **0.31 – 0.57**
- the classes **overlap**; no threshold separates them

The tool's recommended value (0.572) maximises raw classification accuracy — by falsely
refusing **7 of 32 legitimate questions**. That is the wrong trade for a tutor: a false
refusal on a genuine course question is far more damaging than an adjacent question reaching
the model, which then refuses it anyway.

**The report is input to a judgement, not a value to be pasted into the config.** The floor
stays deliberately low and the semantic work is done by the grounded prompt.

## Scoping: the harness must query what the API queries

The offline harness originally queried the **entire** Qdrant collection, unscoped, while the
API always scopes retrieval to the caller's own documents.

Consequently an "out-of-scope" question could be answered from **another account's** course,
and the harness recorded the missing refusal as a **product failure**. It was measuring a
situation that cannot occur in production and attributing the result to the product.

Both `run_eval` and `calibrate` now take `--owner`. The general point is that an evaluation
harness is code, it has defects, and an unaudited evaluation is not evidence.

## Known limitation: judging an LLM with an LLM

The circularity is real and is mitigated rather than eliminated: the judge is a different
model from the one under test; it is given the retrieved sources, so it checks a claim
against evidence rather than against its own knowledge; and the metrics that matter most —
refusal accuracy, citation rate, retrieval hit-rate — are deterministic and need no judge at
all.
