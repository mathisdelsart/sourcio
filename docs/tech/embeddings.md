# Embeddings — `BAAI/bge-m3`

## Role in the system

Every chunk and every query is turned into a 1024-dimension vector. Retrieval is a nearest
neighbour search in that space, which is what allows a question phrased in the student's
own words to find a passage that shares none of them.

## Why bge-m3 rather than a hosted embedding API

| | OpenAI `text-embedding-3` | `BAAI/bge-m3` (chosen) |
| --- | --- | --- |
| Cost | Per token, on every query, permanently | **Free** — runs locally |
| Multilingual | Good | **Purpose-built** (the app serves EN / FR / NL) |
| Data residency | Course documents leave the machine | Nothing leaves |
| Offline operation | Not possible | **Possible** — the full pipeline runs with zero API calls |
| Sparse vectors | No | **Yes** — enables hybrid retrieval at no extra cost |

The deciding factor is that embedding happens on **every query, forever**. A hosted
embedding API is a permanent per-query tax on a component a local model handles equally
well. It is also what makes a genuine claim possible: pointed at a local Ollama server, the
entire pipeline — embeddings, reranker, vector store — runs offline at zero cost.

## Implementation notes

**L2 normalisation.** Vectors are normalised to unit length at index time. Two consequences:

- cosine similarity becomes exactly the dot product, which is cheaper to compute;
- scores become **comparable across chunks**, which is the only reason a fixed similarity
  threshold is meaningful at all. Without normalisation, `0.35` would represent a different
  bar for every chunk.

**Symmetry.** Documents and queries are embedded by the same model
(`Settings.embedding_model`). Using different models on the two sides places them in
different vector spaces and makes the distances meaningless.

**Caching.** The model is loaded once per process and cached. On a cold container this load
dominates the first request.

## Chunking

Retrieval quality is bounded by chunk quality; no amount of downstream tuning recovers from
a bad split.

**Slides: one slide, one chunk.** A slide is already a semantic unit — a heading and its
content. Splitting by token count would glue the end of one slide to the start of the next,
producing a vector that represents neither. This is the dominant document type here.

**Prose (`.md`, `.txt`): ~500-token windows with overlap.** Overlap prevents a concept that
straddles a boundary from being lost by both chunks.

**Stable identifiers.** Chunk ids are `uuid5(course-pN)` — deterministic. Re-ingesting a
course therefore **overwrites** rather than duplicating, making ingestion idempotent.

## Why the similarity classes overlap

Measured on the benchmark corpus: in-course questions score 0.47–0.71, out-of-scope
questions 0.31–0.57. The ranges overlap, and this is not a tuning failure.

An embedding encodes **aboutness**, not **answerability**. Whether a passage *answers* a
question is a property of the relationship between the two, not of either text — and a
distance in vector space cannot express it. That determination requires reading, which is
why the refusal guard does not rely on the threshold alone. See [rag.md](rag.md).

## Related techniques implemented here

**Hybrid retrieval (dense + BM25, fused with RRF).** Dense retrieval handles paraphrase
("discount a future cash flow" → "present value"). Lexical search handles the opposite case:
exact terms, formula names, rare tokens. Reciprocal Rank Fusion combines the two ranked
lists **by rank rather than score** (`Σ 1/(k + rank)`), because the two scoring systems are
not on a comparable scale. bge-m3 emits both dense and sparse (lexical) weights, so hybrid
requires no second model — only ingesting with `--sparse`.

**Cross-encoder reranking.** A bi-encoder such as bge-m3 embeds query and document
*independently*, which is what makes document vectors precomputable and search fast — but
the two never interact. A cross-encoder processes `(query, document)` jointly and is
substantially more accurate, at a cost that makes it impossible to run over a whole
collection. It is therefore applied to re-rank the top ~20 candidates the bi-encoder
returned.

Measured here: no change in hit-rate (dense was already 32/32) at **+220 ms per query**. It
is disabled in production.
