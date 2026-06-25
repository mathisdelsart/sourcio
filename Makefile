# Developer Makefile for grounded-rag.
# Common dev tasks wrapped behind short, self-documenting targets.
# Run `make` or `make help` to list everything.

# Use a consistent shell and fail fast on errors in recipes.
SHELL := /bin/sh

.DEFAULT_GOAL := help

.PHONY: help install local-install local qdrant lint fmt fmt-check test check api ui eval eval-report ingest ask up down clean

help: ## Show this help message
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} \
		/^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install all dependencies (extras + dev group)
	uv sync --all-extras --group dev

local-install: ## Install the Ollama provider extra for fully local runs
	uv sync --extra local

# Print the env needed to run the whole stack against a local Ollama server
# (zero cost, fully offline). Eval into your shell, then run make ask / api / ui.
# Usage: eval "$$(make local)" && make ask Q="..."
# Requires: `ollama serve` running and the chat/vision models pulled (see docs/LOCAL.md).
local: ## Print env to switch the stack to local Ollama (eval it in your shell)
	@echo "export LLM_PROVIDER=ollama"
	@echo "export OLLAMA_BASE_URL=http://localhost:11434"

qdrant: ## Start the Qdrant vector database in the background
	docker compose up -d qdrant

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

ui: ## Run the Streamlit UI
	uv run streamlit run ui/app.py

eval: ## Run the offline evaluation (faithfulness judge)
	uv run python -m eval.run_eval

# Run the eval and write metrics to eval/results.json for the dashboard.
# NOTE: this calls the OpenAI API (judge), unlike the pure unit tests.
eval-report: ## Run the eval and write eval/results.json (calls the API)
	uv run python -m eval.run_eval --out eval/results.json

# Ingest a PDF into Qdrant.
# Usage: make ingest PDF=path/to/file.pdf COURSE="Course Name"
ingest: ## Ingest a PDF (vars: PDF=..., COURSE="...")
	uv run python -m ingestion.run $(PDF) --course "$(COURSE)"

# Ask a question from the command line.
# Usage: make ask Q="your question"
ask: ## Ask a question (var: Q="...")
	uv run python -m ask "$(Q)"

up: ## Start all services (app + qdrant)
	docker compose up -d

down: ## Stop all services
	docker compose down

clean: ## Remove local caches (ruff, pytest, __pycache__)
	rm -rf .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
