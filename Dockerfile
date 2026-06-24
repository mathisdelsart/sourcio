# Serving image for the FastAPI app.
# Builds with uv against the pinned uv.lock and installs only the extras
# needed to serve the API (api + agent). The heavy `ingestion` extra (torch,
# marker-pdf) is intentionally excluded to keep the image small.

FROM python:3.12-slim

# Copy the uv binary from the official distroless image (pinned major version).
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first for better layer caching. Only the lockfile and
# project metadata are needed to resolve and sync the environment.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra api --extra agent

# Copy only the application source needed at runtime. An explicit allowlist
# keeps local-only paths (worktrees, editor config, course PDFs) out of the
# image without having to enumerate them in .dockerignore.
COPY README.md config.py retrieval.py answer.py ask.py ./
COPY api/ ./api/
COPY agent/ ./agent/
COPY ingestion/ ./ingestion/
COPY eval/ ./eval/

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
