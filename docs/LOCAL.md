# Run fully local (zero cost)

grounded-rag can run end to end with **no paid API calls** by swapping the LLM
provider from OpenAI to a local [Ollama](https://ollama.com) server. The rest of
the pipeline is already local and free:

- **Embeddings** (`BAAI/bge-m3`) run locally via `sentence-transformers`.
- **Reranker** (cross-encoder, opt-in) runs locally via `sentence-transformers`.
- **Vector store** (Qdrant) runs in a local Docker container.

So with Ollama supplying the chat (and, for ingestion, vision) model, the whole
stack costs nothing and works offline.

## 1. Install Ollama and pull models

```sh
# macOS (or download from https://ollama.com)
brew install ollama

# Start the server (leave it running)
ollama serve

# Chat model for the agent (router / explain / generate / grade / judge)
ollama pull llama3.1

# Multimodal model for ingestion (transcribing rasterized slides)
ollama pull llama3.2-vision
```

`llama3.1` is a solid general chat model; pick any chat model you have RAM for.
For vision, `llama3.2-vision` is a reasonable default; `minicpm-v` and
`qwen2-vl` are alternatives.

> **Quality caveat (vision/math).** Local vision models transcribe slides with
> noticeably lower fidelity on dense math/LaTeX than `gpt-4o`. For a grounded
> math tutor this matters: expect more formula errors. Two mitigations below.

## 2. Install the local provider extra

```sh
uv sync --extra local        # adds langchain-ollama
# or: make local-install
```

## 3. Switch the stack to Ollama

Two equivalent ways.

**Global switch (recommended)** — flip every role at once:

```sh
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434   # default; override if remote
# Optional model overrides (defaults shown):
# export OLLAMA_CHAT_MODEL=llama3.1
# export OLLAMA_VISION_MODEL=llama3.2-vision
```

`make local` prints these `export` lines so you can `eval "$(make local)"`.

**Per role** — a `provider:model` prefix on any `LLM_<ROLE>` wins over the
global setting, so you can mix providers:

```sh
export LLM_EXPLAIN=ollama:llama3.1
export LLM_GENERATE=ollama:llama3.1
```

The default (no env set) stays OpenAI `gpt-4o-mini`, so existing setups are
unaffected.

## 4. Ingest, ask, and run the UI — all offline

```sh
make qdrant                                  # start the vector store (Docker)

# Ingest a deck. With local vision:
uv run python -m ingestion.run path/to/deck.pdf --course "My Course"

# Ask a question (grounded + cited, no paid call):
make ask Q="Explain the wavelet transform"

# Or run the API + UI on the host:
make api    # http://localhost:8000
make ui     # http://localhost:8501
```

## Zero-cost ingestion without any vision model

If you do not want to pull a vision model at all, use the **hybrid** router with
PyMuPDF, which extracts plain-text pages for free and only routes math/figure
pages to vision. For text-heavy decks you can avoid vision entirely:

```sh
# Hybrid routing: plain-text pages go to free PyMuPDF; only math/figure pages
# would use vision. On a text-only deck, no vision call is ever made.
uv run python -m ingestion.run path/to/deck.pdf --course "My Course" --hybrid
```

For slides that genuinely contain rendered formulas, vision is still needed for
faithful LaTeX; pull `llama3.2-vision` and set `LLM_PROVIDER=ollama` as above,
accepting the lower math fidelity, or reserve OpenAI for the `extract` role only
(`LLM_EXTRACT=gpt-4o`) while keeping the rest local.
