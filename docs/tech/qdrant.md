# Qdrant — vector store

## Role in the system

Holds every course chunk as a vector plus a payload, and answers the only question
retrieval asks: *which passages, among those this user owns and within this course and
chapter, are nearest to the question?*

## Why a vector database rather than in-memory search

At the current corpus size a brute-force cosine over a NumPy array would work. A database
is warranted by four requirements taken together:

- **persistence** — survive a restart without re-embedding the corpus;
- **metadata filtering combined with vector search** — the decisive one, below;
- **sub-linear search** as corpora grow;
- **concurrent access** from a multi-user API.

The architecture is sized for a user uploading a 500-page course, not for the twelve chunks
in the benchmark corpus. That is a deliberate choice, and at present it is over-provisioned.

## Why Qdrant

| | Assessment |
| --- | --- |
| **FAISS** | A library, not a service: no persistence, no filtering, no concurrency. Suitable for a notebook. |
| **Pinecone** | Managed and capable, but a paid SaaS. Incompatible with the project's requirement to run locally at zero cost. |
| **pgvector** | A serious alternative: Postgres is already in the stack, so it removes a service and gives transactional consistency between chunks and metadata. Weaker filtering ergonomics and less headroom at scale. Defensible; the choice could reasonably have gone the other way. |
| **Qdrant** (chosen) | Open source, single container, first-class payload filtering, free managed tier for production. |

Payload filtering decided it.

## Point structure

A point is one chunk:

```
vector  -> 1024 floats, L2-normalised     (what search ranks on)
payload -> { text, course, chapter, page, document, owner }
```

The payload is not ranked over, but it is **filterable** and it is returned with the hit.
The split is load-bearing:

- `text` is what enters the prompt;
- `course` / `chapter` / `page` are read **by the code**, never shown to the model — this is
  what makes citation-by-construction possible ([rag.md](rag.md));
- `owner` enforces tenant isolation.

Keeping the chunk text in the payload duplicates it, but means a single query returns
everything needed to both rank and cite. The alternative — a second round-trip per hit to
fetch text — would put an avoidable hop on the hot path.

## Filtering and isolation

Retrieval is never an unfiltered vector search. It is scoped by owner, and optionally by
course and chapter:

```python
Filter(must=[FieldCondition(key="owner", match=MatchValue(value=owner))])
```

Qdrant applies the filter **inside** the ANN search rather than as a post-filter. This
matters for correctness, not just speed: post-filtering retrieves top-k globally and may be
left with two results after filtering, silently degrading recall. A pre-filtered search
returns the top-k *that satisfy the filter*.

**Isolation is enforced at the query, not in application code** (`core/retrieval.py`):

- **No shared branch.** A chunk with no owner matches **nobody**, not everybody. This closes
  the common multi-tenant leak in which material ingested before per-account scoping remains
  visible to all accounts.
- **Fail closed.** If the effective owner resolves to `None`, reads return empty and deletes
  remove nothing — never "everything".
- **Single-source lookups are scoped identically.** `GET /source/{chunk_id}` returns **404**
  for a chunk owned by another account — not 403 — so its existence is never disclosed and
  ids cannot be probed.

This is verified rather than assumed: the endpoint benchmark includes a question whose
subject is covered only by *another account's* indexed corpus. The benchmark account is
correctly refused.

## HNSW

Qdrant indexes with HNSW (Hierarchical Navigable Small World): a layered proximity graph,
sparse at the top with long-range links and progressively denser below. A search walks
greedily toward the query, descending layers, covering distance quickly and then refining
locally.

It is **approximate** — a true nearest neighbour can be missed — in exchange for roughly
logarithmic rather than linear search. For RAG, where the top five of thousands feed a
prompt, the trade is effectively free. Recall/speed is tunable (`ef`, `M`); the defaults are
used here and have not been tuned.

## Scaling considerations (not yet needed)

- Payload indexes on `owner` and `course`, so filtering does not degrade into a scan.
- Memory: one million chunks × 1024 dims × 4 bytes ≈ 4 GB of raw vectors. Qdrant supports
  scalar and product quantisation, trading a little recall for a large reduction in RAM.
- The architecture does not otherwise change, which was the point of adopting a vector
  database before it was strictly necessary.
