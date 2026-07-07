# syntax=docker/dockerfile:1

# CPU-only production image for the grounded-rag API service.
#
# This image is for CLOUD DEPLOYMENT only (e.g. Hugging Face Spaces, Render).
# Local development stays host-based: `docker compose up -d qdrant` runs only the
# vector store, while the API and UI run on the host (see README). Containerizing
# the API for the cloud is worth it; doing so locally is not, because the default
# torch build pulls multi-gigabyte CUDA wheels. The key trick below is installing
# a CPU-only torch from PyTorch's CPU wheel index so no CUDA libraries are pulled.

# ---------------------------------------------------------------------------
# Stage 1 — builder: create a self-contained virtualenv with all runtime deps.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Faster, quieter, reproducible Python/pip behavior.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build the virtualenv in an isolated location we copy wholesale into the runtime
# stage. Putting its bin first on PATH means subsequent `pip`/`python` target it.
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
RUN python -m venv "$VIRTUAL_ENV"

# 1) Install CPU-only torch FIRST, from PyTorch's CPU wheel index. Doing this as a
#    dedicated layer (a) avoids the default CUDA wheels (~multi-GB), and (b) lets
#    the heavy download cache independently of the app dependency layer below.
#    The version is pinned to match the project lockfile (torch 2.12.x).
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.12.*"

# 2) Install the remaining runtime dependencies from PyPI. Only the extras the API
#    actually needs at runtime are installed (justification):
#      - base deps (langchain, langchain-openai, qdrant-client, pydantic-settings)
#      - langchain-groq -> the free hosted Groq LLM provider (LLM_PROVIDER=groq)
#      - langchain-anthropic -> ChatAnthropic, so a visitor's own Anthropic key
#        (a `sk-ant-` key on the X-OpenAI-Key header) drives a premium Claude model
#      - psycopg[binary] -> the Postgres driver, for a managed DATABASE_URL
#        (postgresql+psycopg://...); harmless when the default SQLite is used
#      - bcrypt + pyjwt -> auth (password hashing + JWT access tokens); imported
#        at startup by api.auth, so the API will not boot without them
#      - python-multipart -> FastAPI multipart parsing for POST /documents/upload
#      - pymupdf -> PDF text extraction for uploaded course PDFs (the online
#        upload path, not just the offline CLI)
#      - `api`    -> FastAPI, uvicorn, sqlalchemy (the web layer)
#      - `agent`  -> langgraph (the explain/generate/grade/reexplain nodes)
#      - `obs`    -> langfuse (optional tracing; tiny, keeps observability working)
#      - sentence-transformers -> local bge-m3 query embeddings + the cross-encoder
#        reranker (pulled in by retrieval at runtime). It lives in the `ingestion`
#        extra alongside PyMuPDF, but PyMuPDF is only used by the offline PDF
#        ingestion CLI (not the API), so it is installed directly to keep the image
#        lean. torch is already present from the CPU index above, so this resolves
#        against it instead of re-downloading the CUDA build.
#    NOT installed: `ui` (Streamlit, served separately), `local` (Ollama client,
#    only for fully-local runs), `migrations` (the API creates tables via
#    SQLAlchemy on startup, not Alembic). Image PDF pages still need a vision LLM
#    (OPENAI_API_KEY); text PDFs and .md/.txt work with the deps above.
RUN pip install \
    "langchain>=0.3" \
    "langchain-core>=1.4" \
    "langchain-openai>=0.2" \
    "langchain-groq>=0.2" \
    "langchain-anthropic>=0.3" \
    "bcrypt>=4.0" \
    "pyjwt>=2.8" \
    "python-multipart>=0.0.9" \
    "pymupdf>=1.24" \
    "pydantic-settings>=2.5" \
    "python-dotenv>=1.0" \
    "qdrant-client>=1.12" \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy>=2.0" \
    "psycopg[binary]>=3.1" \
    "pydantic>=2.13" \
    "langgraph>=0.2" \
    "langfuse>=2.0" \
    "sentence-transformers>=3.0"

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim image carrying only the venv and the app source.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    # HF Spaces sets $PORT (commonly 7860); default to 8000 otherwise.
    PORT=8000

# curl is used by the container HEALTHCHECK only. Installed without recommends and
# with the apt cache cleaned to keep the layer small.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user, and make the app directory writable by it: with the
# default `DATABASE_URL=sqlite:///./app.db`, the API creates the SQLite file under
# the working directory on startup, so it must be owned by the runtime user. (For
# durable storage, point `DATABASE_URL` at managed Postgres instead.)
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app \
    && chown appuser:appuser /app
WORKDIR /app

# Copy the prebuilt virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Copy only the source the API imports at runtime. `.dockerignore` keeps the rest
# (tests, web, ui, docs, data) out of the build context. Modules included:
#   - api/       FastAPI app (entrypoint api.main:app)
#   - core/      answer, retrieval, config, obs, budget
#   - agent/     LangGraph nodes (generate/grade/reexplain/explain) and state
#   - db/        SQLAlchemy models + session (tables created on startup)
#   - ingestion/ schema, embed, index (imported by core.retrieval for query
#                embeddings); the PDF-only modules are inert without PyMuPDF.
COPY --chown=appuser:appuser api/ ./api/
COPY --chown=appuser:appuser core/ ./core/
COPY --chown=appuser:appuser agent/ ./agent/
COPY --chown=appuser:appuser db/ ./db/
COPY --chown=appuser:appuser ingestion/ ./ingestion/

USER appuser

EXPOSE 8000

# Liveness probe against the always-open /health endpoint, honoring $PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

# Honor $PORT (HF Spaces injects it) with a default of 8000. A shell wraps the
# command so the variable is expanded at runtime; the exec/JSON form invokes that
# shell explicitly (it cannot expand variables on its own).
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
