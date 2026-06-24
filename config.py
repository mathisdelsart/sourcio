"""Central configuration and a model-agnostic LLM factory.

Models are never hard-coded in a node. Everything goes through `get_llm(role)`,
driven by environment variables, so models can be swapped without code changes.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from pydantic_settings import BaseSettings, SettingsConfigDict

from budget import get_budget_callbacks
from obs import get_callbacks

# Load `.env` into the process environment so provider SDKs (e.g. OpenAI) can
# read OPENAI_API_KEY directly. pydantic-settings only populates Settings fields.
load_dotenv()

# Path for the on-disk LLM cache when `llm_cache="sqlite"`.
_SQLITE_CACHE_PATH = ".llm_cache.sqlite"

# Guard so the global LLM cache is configured at most once per process.
_cache_configured = False


class Settings(BaseSettings):
    """Application settings, overridable via `.env` or environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "courses"

    # Multilingual embeddings (documents and questions are in French).
    embedding_model: str = "BAAI/bge-m3"

    # Retrieval threshold, calibrated empirically. Below it, the answer is refused.
    similarity_threshold: float = 0.5

    # Relational store (SQLite in development, PostgreSQL later).
    database_url: str = "sqlite:///./app.db"

    # LLM response cache (opt-in cost saver). "" disables it; "memory" uses an
    # in-process cache; "sqlite" persists to disk across runs.
    llm_cache: str = ""

    # Token budget cap for the LLM factory (opt-in guard). 0 disables it; a
    # positive value stops generation once accumulated usage exceeds the cap.
    llm_budget_tokens: int = 0


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()


def configure_cache() -> None:
    """Configure LangChain's global LLM cache from settings, at most once.

    Driven by the `llm_cache` setting: "" disables caching, "memory" uses an
    in-process `InMemoryCache`, and "sqlite" persists to disk. The SQLite backend
    lives in `langchain_community`; if that optional package is unavailable we
    fall back to the in-memory cache so this never adds a hard dependency.
    """
    global _cache_configured
    if _cache_configured:
        return

    from langchain_core.caches import InMemoryCache
    from langchain_core.globals import set_llm_cache

    mode = get_settings().llm_cache.strip().lower()
    if not mode:
        return

    if mode == "sqlite":
        try:
            from langchain_community.cache import SQLiteCache

            cache = SQLiteCache(database_path=_SQLITE_CACHE_PATH)
        except ImportError:
            # Optional backend missing: degrade gracefully to in-memory caching.
            cache = InMemoryCache()
    else:
        cache = InMemoryCache()

    set_llm_cache(cache)
    _cache_configured = True


def get_llm(role: str = "default"):
    """Build a chat model for the given role, selected by the `LLM_<ROLE>` env var.

    Defaults to `gpt-4o-mini`. Uses `temperature=0` for reproducibility.
    """
    # Configure the global LLM cache once (no-op unless `llm_cache` is set), so
    # repeated identical prompts are served from cache instead of re-billed.
    configure_cache()

    model = os.getenv(f"LLM_{role.upper()}", "gpt-4o-mini")
    llm = init_chat_model(model, temperature=0)

    # Compose callbacks: LangFuse tracing (opt-in) and the token budget guard
    # (opt-in). Each helper returns an empty list when disabled, so when both
    # features are off the model is returned unchanged (no behavior change).
    callbacks = get_callbacks() + get_budget_callbacks(get_settings().llm_budget_tokens)
    if callbacks:
        llm = llm.with_config(callbacks=callbacks)
    return llm
