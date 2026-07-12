# Developer Makefile for grounded-rag.
# Common dev tasks wrapped behind short, self-documenting targets.
# Run `make` or `make help` to list everything.

# Use a consistent shell and fail fast on errors in recipes.
SHELL := /bin/sh

.DEFAULT_GOAL := help

.PHONY: help install local-install local qdrant hooks lint fmt fmt-check test check api web dev eval eval-report ingest ingest-prod ask up down clean reset-db

help: ## Show this help message
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} \
		/^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install all dependencies (extras + dev group)
	uv sync --all-extras --group dev

local-install: ## Install the Ollama provider extra for fully local runs
	uv sync --extra local

# Print the env needed to run the whole stack against a local Ollama server
# (zero cost, fully offline). Eval into your shell, then run make ask / api / web.
# Usage: eval "$$(make local)" && make ask Q="..."
# Requires: `ollama serve` running and the chat/vision models pulled (see docs/RUN-LOCAL.md).
local: ## Print env to switch the stack to local Ollama (eval it in your shell)
	@echo "export LLM_PROVIDER=ollama"
	@echo "export OLLAMA_BASE_URL=http://localhost:11434"

qdrant: ## Start the Qdrant vector database in the background
	docker compose up -d qdrant

# Install the git pre-commit hook and run it once over the whole repo. The hook
# mirrors the ruff checks CI enforces, so local commits match CI.
hooks: ## Install pre-commit hooks and run them on all files
	uv run pre-commit install
	uv run pre-commit run --all-files

lint: ## Run the ruff linter
	uv run ruff check .

fmt: ## Format the code with ruff
	uv run ruff format .

fmt-check: ## Check formatting without modifying files
	uv run ruff format --check .

test: ## Run the test suite
	uv run python -m pytest -q

check: lint fmt-check test ## Run lint, format check, and tests

api: ## Run the FastAPI app with autoreload
	uv run uvicorn api.main:app --reload

web: ## Run the Next.js web frontend (installs deps, http://localhost:3000)
	cd web && npm install && npm run dev

# Orchestrate the full local stack for free (Ollama provider, zero paid calls).
# Qdrant is started detached here; the API and the web dev server are both
# long-running foreground processes, so this target starts Qdrant and then
# prints the exact two commands to run, one per terminal. See docs/RUN-LOCAL.md.
dev: qdrant ## Start the full local stack (Qdrant up + the two commands to run)
	@echo ""
	@echo "Qdrant is up (http://localhost:6333). Now run these in two terminals:"
	@echo ""
	@echo "  1) API  (port 8000):  LLM_PROVIDER=ollama make api"
	@echo "  2) Web  (port 3000):  make web"
	@echo ""
	@echo "Prereqs: 'ollama serve' running with models pulled (see docs/RUN-LOCAL.md)."
	@echo "Full guide: docs/RUN-LOCAL.md"

eval: ## Run the offline evaluation (faithfulness judge)
	uv run python -m eval.run_eval

# Run the eval and write metrics to eval/results.json for the dashboard.
# NOTE: this calls the OpenAI API (judge), unlike the pure unit tests.
eval-report: ## Run the eval and write eval/results.json (calls the API)
	uv run python -m eval.run_eval --out eval/results.json

# Ingest a PDF into the local Qdrant.
# Usage: make ingest PDF=path/to/file.pdf COURSE="Course Name"
ingest: ## Ingest a PDF into local Qdrant (vars: PDF=..., COURSE="...")
	uv run python -m ingestion.run $(PDF) --course "$(COURSE)"

# Ingest a PDF into the PRODUCTION Qdrant Cloud, loading prod-only credentials
# from .env.prod (gitignored, kept out of the repo). Deliberately separate from
# `make ingest` (local) so a normal dev run can never write to prod by accident.
# Usage: make ingest-prod PDF=path/to/file.pdf COURSE="Course Name"
ingest-prod: ## Ingest a PDF into PROD Qdrant Cloud (loads .env.prod; vars: PDF=..., COURSE="...")
	@test -f .env.prod || { echo "Error: .env.prod not found (create it with your Neon + Qdrant Cloud credentials)"; exit 1; }
	set -a; . ./.env.prod; set +a; uv run --extra ingestion python -m ingestion.run "$(PDF)" --course "$(COURSE)"

# Ask a question from the command line.
# Usage: make ask Q="your question"
ask: ## Ask a question (var: Q="...")
	uv run python -m core.ask "$(Q)"

up: ## Start the vector store (Qdrant; the only default compose service)
	docker compose up -d

down: ## Stop all services
	docker compose down

clean: ## Remove local caches (ruff, pytest, __pycache__)
	rm -rf .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# Delete the local SQLite dev database so it is recreated with the current
# schema on the next API start. Use this after a model/migration change when
# the stale app.db triggers "no such column"/"no such table" errors. Only
# touches the local sqlite file and its WAL/SHM sidecars; nothing else.
reset-db: ## Remove the local SQLite dev DB (recreated on next API start)
	rm -f app.db app.db-wal app.db-shm
	@echo "removed local app.db — it will be recreated on the next API start"
