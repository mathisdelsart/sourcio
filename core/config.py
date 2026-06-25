"""Central configuration and a model-agnostic LLM factory.

Models are never hard-coded in a node. Everything goes through `get_llm(role)`,
driven by environment variables, so models can be swapped without code changes.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.budget import get_budget_callbacks
from core.obs import get_callbacks

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

    # Cross-encoder reranker (opt-in precision boost, no re-ingestion needed).
    # "" disables it (dense path unchanged); a model name (e.g.
    # "cross-encoder/ms-marco-MiniLM-L-6-v2") enables reranking. It needs the
    # `ingestion` extra (sentence-transformers) and runs locally.
    reranker_model: str = ""

    # When the reranker is enabled, how many candidates to fetch from Qdrant
    # before reranking and truncating back to k. Ignored when disabled.
    rerank_candidates: int = 20

    # Relational store (SQLite in development, PostgreSQL later).
    database_url: str = "sqlite:///./app.db"

    # LLM response cache (opt-in cost saver). "" disables it; "memory" uses an
    # in-process cache; "sqlite" persists to disk across runs.
    llm_cache: str = ""

    # Token budget cap for the LLM factory (opt-in guard). 0 disables it; a
    # positive value stops generation once accumulated usage exceeds the cap.
    llm_budget_tokens: int = 0

    # API-key authentication (opt-in). "" leaves the API fully open; a non-empty
    # value requires clients to send a matching `X-API-Key` header on the
    # mutating endpoints and `/history`. `/health` is always open.
    api_key: str = ""

    # Global LLM provider switch for fully local, zero-cost runs. "" keeps the
    # default OpenAI provider; "ollama" routes every role to a local Ollama chat
    # model (see `get_llm`). Per-role `LLM_<ROLE>` values may still carry their
    # own `provider:model` prefix, which always wins over this global default.
    llm_provider: str = ""

    # Base URL of the local Ollama server, used only when the Ollama provider is
    # active. The default matches Ollama's out-of-the-box bind address.
    ollama_base_url: str = "http://localhost:11434"

    # Default Ollama model ids used when `llm_provider="ollama"` and a role has no
    # explicit `LLM_<ROLE>` override. The extract role needs a multimodal model to
    # transcribe rasterized slides; the others use a general chat model.
    ollama_chat_model: str = "llama3.1"
    ollama_vision_model: str = "llama3.2-vision"


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


def _resolve_model(role: str) -> tuple[str, dict]:
    """Resolve the model id and provider kwargs for a role.

    Selection order, most specific first:

    1. `LLM_<ROLE>` env var. Its value may carry an explicit `provider:model`
       prefix understood by `init_chat_model` (e.g. `ollama:llama3.1`), in which
       case it is used verbatim and wins over the global provider.
    2. The global `llm_provider` setting. When set to "ollama", every role
       without its own override resolves to a local Ollama model: the multimodal
       `ollama_vision_model` for the `extract` role and `ollama_chat_model`
       otherwise. The Ollama `base_url` is forwarded so a non-default server can
       be targeted.
    3. The OpenAI default `gpt-4o-mini`.

    Returns the model string (possibly `provider:model`) and a kwargs dict passed
    through to `init_chat_model` (e.g. `base_url` for Ollama).
    """
    override = os.getenv(f"LLM_{role.upper()}")
    settings = get_settings()

    # An explicit per-role override always wins, including its own provider prefix.
    if override:
        kwargs: dict = {}
        if override.startswith("ollama:"):
            kwargs["base_url"] = settings.ollama_base_url
        return override, kwargs

    # Global Ollama switch: pick a sensible default model id per role.
    if settings.llm_provider.strip().lower() == "ollama":
        model_id = settings.ollama_vision_model if role == "extract" else settings.ollama_chat_model
        return f"ollama:{model_id}", {"base_url": settings.ollama_base_url}

    # Default: OpenAI gpt-4o-mini, unchanged.
    return "gpt-4o-mini", {}


def get_llm(role: str = "default"):
    """Build a chat model for the given role, selected by the `LLM_<ROLE>` env var.

    Defaults to OpenAI `gpt-4o-mini`. Set `LLM_<ROLE>=ollama:<model>` or the
    global `LLM_PROVIDER=ollama` to run a local Ollama model instead (zero-cost,
    fully offline). Uses `temperature=0` for reproducibility.
    """
    # Configure the global LLM cache once (no-op unless `llm_cache` is set), so
    # repeated identical prompts are served from cache instead of re-billed.
    configure_cache()

    model, provider_kwargs = _resolve_model(role)
    llm = init_chat_model(model, temperature=0, **provider_kwargs)

    # Compose callbacks: LangFuse tracing (opt-in) and the token budget guard
    # (opt-in). Each helper returns an empty list when disabled, so when both
    # features are off the model is returned unchanged (no behavior change).
    callbacks = get_callbacks() + get_budget_callbacks(get_settings().llm_budget_tokens)
    if callbacks:
        llm = llm.with_config(callbacks=callbacks)
    return llm
