# ingestion/

The offline pipeline, run once per course: turn a PDF (or `.md` / `.txt`) into searchable, citable
chunks in Qdrant. Mangled mathematics is the project's main grounding risk, so extraction is
math-aware and routes per page.

## Pipeline and key modules

```
PDF / .md / .txt -> extract/load -> chunk -> embed -> index -> Qdrant
```

| File | Responsibility |
| --- | --- |
| `run.py` | Entry point (`python -m ingestion.run <path> --course "..."`). Processes pages in batches (extract -> chunk -> index) so a mid-run crash keeps earlier progress. |
| `extract.py` | Math-aware PDF extraction with per-page routing: plain pages go through PyMuPDF (free); math/figure pages are rasterized and transcribed by a vision model into Markdown with LaTeX preserved. Parallel vision calls with 429-retry backoff. |
| `load.py` | Plain-text loading for `.md` / `.txt` prose — no vision model; split into overlapping windows, emitting the same `Page` contract. |
| `chunk.py` | Adaptive chunking by `doc_type`: one slide -> one chunk; prose -> ~500-token windows with overlap. Stable `uuid5` chunk ids make re-ingestion idempotent. |
| `embed.py` | Local multilingual embeddings (`BAAI/bge-m3`), L2-normalized, model cached. Also exposes bge-m3 lexical (sparse) weights for hybrid retrieval. |
| `index.py` | Upsert `{vector, payload}` into the Qdrant `courses` collection (cosine). Opt-in `--sparse` adds a named sparse vector for hybrid. |
| `schema.py` | The shared data contract for the whole pipeline: `Page`, `Chunk`, `Retrieved`. |

## How it fits

This package is the only writer to Qdrant; `core/retrieval.py` is the reader. The `Retrieved.citation()`
label built from the stored payload is what the answer layer remaps `[n]` markers to. Details in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Run it

```bash
docker compose up -d qdrant
uv run python -m ingestion.run path/to/course.pdf --course "Wavelet Transform" --hybrid
# flags: --pages, --concurrency, --batch-size, --sparse (enable hybrid retrieval)
uv run python -m pytest tests/test_extract.py tests/test_ingest_text.py -q
```
</content>
