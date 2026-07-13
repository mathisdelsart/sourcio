# Retrieval-augmented generation

## Role in the system

The product answers questions strictly from the user's own course material. RAG is the
mechanism: retrieve the relevant passages, put them in the prompt, and constrain the model
to answer from those passages alone.

## Why RAG rather than fine-tuning

Fine-tuning a model on each course was the alternative. It was rejected on three grounds,
the first of which is decisive:

| | Fine-tuning | RAG (chosen) |
| --- | --- | --- |
| **Citing a source** | Impossible — the document is dissolved into weights; there is no passage left to point at | Trivial — the passage is still there, and is what was put in the prompt |
| Adding a course | Retrain | Ingest (minutes, no GPU) |
| Refusing an uncovered question | The model learns fluency, not honesty | Retrieval returns nothing → refuse before the model runs |
| Cost per course | GPU hours | One embedding pass, locally |

Citation is the product's core promise. Fine-tuning cannot deliver it at all, which ends
the comparison.

## Citation by construction

The obvious implementation — put the sources in the prompt and ask the model to cite the
page — fails predictably. Page numbers are ordinary tokens; a fluent model will emit a
plausible one when it is unsure.

Instead, the model is shown only numbered chunk text:

```
[1] <chunk text>
[2] <chunk text>
[3] <chunk text>
```

It cites indices (`"…as shown in [2]"`). The code then reads chunk 2's payload from Qdrant
and rewrites the marker to `(Finance, Chapter 1, p.2)`.

The model never handles a page number, so it cannot invent one. This is a structural
guarantee rather than an instruction the model may or may not follow, and it is the reason
the payload schema (`text`, `course`, `chapter`, `page`) is designed the way it is — see
[qdrant.md](qdrant.md).

## The refusal guard

An instruction to "refuse when unsure" is unreliable: the model is trained to be helpful,
and will eventually produce a plausible answer. Refusal therefore rests on three
mechanisms, only one of which is the model.

**1. A similarity floor.** If nothing retrieved clears `SIMILARITY_THRESHOLD`, the request
is refused **without calling the model at all** (`core/answer.py`). A model that is never
invoked cannot be argued into answering.

**2. The grounded prompt.** The model is shown only the retrieved chunks and is instructed
to refuse when they do not cover the request. This carries the bulk of the semantic work.

**3. The no-citation guard.** An answer that cites *no source at all* is converted into a
refusal (`core/answer.py`). This is not a request to the model — it is an observation about
its output. Zero `[n]` markers means the answer was produced from the model's own
knowledge rather than from the course, so it is dropped. This is why the citation rate is
exactly 100% and not merely high: an uncited answer cannot leave the system.

### Why the floor is deliberately coarse

Calibration on the benchmark corpus (`eval/calibrate.py`, 32 in-course and 18 out-of-scope
questions) gives:

- in-course similarity: **0.47 – 0.71**
- out-of-scope similarity: **0.31 – 0.57**

**The two distributions overlap**, so no threshold separates them, and no better embedding
model would. The overlap is semantic, not technical: an embedding encodes what a text is
*about*, not whether it *answers*. "How do I compute the Sharpe ratio?" is a finance
question, and a chunk about variance and risk is finance — a high similarity there is the
embedding behaving correctly.

Raising the threshold to catch every out-of-scope question (0.572) would falsely refuse
**7 of 32 legitimate questions**. For a tutor, a false refusal on a real course question is
considerably worse than an adjacent question reaching the model, which then refuses it
anyway.

The floor is therefore a cheap pre-filter for the plainly unrelated, and the semantic
decision belongs to guards 2 and 3. Measured end to end: **22 of 23 out-of-scope requests
refused (96%)**.

## Advanced retrieval: implemented, measured, disabled

The project implements a cross-encoder reranker, hybrid dense + BM25 fusion (RRF),
multi-query expansion, HyDE and neighbour expansion. All are opt-in and **off by default**.

Measured on the benchmark corpus:

| Configuration | Retrieval hit-rate | Cost |
| --- | --- | --- |
| Dense only | **32/32** | 285 ms/query |
| + multi-query | 32/32 | + one LLM call per query |
| + cross-encoder reranker | 32/32 | **+220 ms/query** |

Dense retrieval already achieves a perfect score on this corpus, so no booster has room to
improve it. They are consequently disabled in production. They remain in the codebase
because they are not useless in general — on a large, technical corpus, hybrid retrieval
and reranking matter — but on twelve tightly-scoped chunks they add cost and latency for no
measurable gain.

### A booster must never narrow recall

Multi-query and HyDE rewrite the query with an LLM, which places a model *inside the
retrieval path* — and retrieval is where refusal is decided.

This produced a production defect, found by the endpoint benchmark. A visitor supplying
their own API key was served by a different rewriting model, whose rewrite drifted far
enough that nothing cleared the threshold. **The same question was answered for one visitor
and refused for the next**, on the paying path the product actively recommends.

The fix (`core/answer.py`): a recall booster is only permitted to *widen* recall, so when
it returns nothing, retrieval falls back to the plain dense query. A refusal must mean "the
course does not cover this", never "the rewriter drifted". A genuinely uncovered question
is still refused, because the dense baseline finds nothing either.

## Definitions used throughout the codebase

- **Chunk** — a retrievable unit. One slide maps to one chunk; prose is split into
  ~500-token windows with overlap. See [embeddings.md](embeddings.md).
- **Top-k** — the number of chunks retrieved. Higher k means more context, more tokens, and
  more opportunity to pull in something irrelevant.
- **Grounding** — every claim in the answer is supported by a retrieved passage.
- **Faithfulness** — whether each claim is actually supported by the source it cites.
  Measured offline by a second model ([evaluation.md](evaluation.md)). **Faithfulness is not
  refusal**: refusal is a live guard, faithfulness is an after-the-fact audit.
