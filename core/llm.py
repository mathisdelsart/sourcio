"""Model-agnostic LLM factory.

Models are never hard-coded in a node: everything goes through `get_llm(role)`,
driven by the `LLM_<ROLE>` / `LLM_PROVIDER` environment variables (via
`core.config.Settings`), so models can be swapped without code changes. The
factory also composes two opt-in, zero-cost-when-disabled concerns -- LangFuse
tracing (`core.obs`) and the token-budget guard (`core.budget`) -- and configures
the optional response cache once per process.

Kept separate from `core.config` (which owns only the `Settings` model and
`get_settings`) so the settings surface stays free of the heavy LangChain factory
and its provider-resolution logic.
"""

import os

from langchain.chat_models import init_chat_model

from core.budget import get_budget_callbacks
from core.config import get_settings
from core.obs import get_callbacks

# Path for the on-disk LLM cache when `llm_cache="sqlite"`.
_SQLITE_CACHE_PATH = ".llm_cache.sqlite"

# Guard so the global LLM cache is configured at most once per process.
_cache_configured = False


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
    # Decide once: mark configured up front so a disabled-cache config also short
    # circuits on later calls instead of re-parsing settings every time.
    _cache_configured = True

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
       be targeted. When set to "groq", every non-vision role resolves to
       `groq:<groq_chat_model>` (langchain-groq reads GROQ_API_KEY from the
       environment, so no kwargs are injected); the `extract` (vision) role falls
       back to the OpenAI default since Groq has no vision model.
    3. The OpenAI default `gpt-4o-mini`.

    Returns the model string (possibly `provider:model`) and a kwargs dict passed
    through to `init_chat_model` (e.g. `base_url` for Ollama). Groq needs no
    kwargs, so its dict is empty.
    """
    override = os.getenv(f"LLM_{role.upper()}")
    settings = get_settings()

    # An explicit per-role override always wins, including its own provider prefix.
    # Only Ollama needs a base_url forwarded; groq:/openai: prefixes pass through
    # verbatim with no provider kwargs.
    if override:
        kwargs: dict = {}
        if override.startswith("ollama:"):
            kwargs["base_url"] = settings.ollama_base_url
        return override, kwargs

    provider = settings.llm_provider.strip().lower()

    # Global Ollama switch: pick a sensible default model id per role.
    if provider == "ollama":
        model_id = settings.ollama_vision_model if role == "extract" else settings.ollama_chat_model
        return f"ollama:{model_id}", {"base_url": settings.ollama_base_url}

    # Global Groq switch: free-tier hosted chat model for every role except the
    # vision `extract` role, which Groq cannot serve and which falls back to the
    # OpenAI default (ingestion is a one-time offline step, never on the API).
    if provider == "groq":
        if role == "extract":
            return "gpt-4o-mini", {}
        return f"groq:{settings.groq_chat_model}", {}

    # Default: OpenAI gpt-4o-mini, unchanged.
    return "gpt-4o-mini", {}


def _is_openai_model(model: str) -> bool:
    """Return whether a resolved model string targets OpenAI.

    `init_chat_model` accepts an optional `provider:model` prefix. A model routed
    to Ollama or Groq carries an explicit `ollama:`/`groq:` prefix, so anything
    without one (the bare `gpt-4o-mini` default, an explicit `openai:...`, etc.)
    is served by OpenAI.
    """
    return not (model.startswith("ollama:") or model.startswith("groq:"))


def _resolve_openai_model(role: str) -> str:
    """Resolve the OpenAI model id for a role when a caller supplies their own key.

    A visitor's own OpenAI key overrides the global provider for this one call, so
    the role must resolve to an OpenAI model regardless of `LLM_PROVIDER`. An
    explicit `LLM_<ROLE>` override is honoured only when it names an OpenAI model
    (a bare id or an `openai:` prefix); an Ollama/Groq-prefixed override is ignored
    in favour of the OpenAI default `gpt-4o-mini`, since the caller's key
    authenticates OpenAI and could not talk to those providers.
    """
    override = os.getenv(f"LLM_{role.upper()}")
    if override and _is_openai_model(override):
        return override
    return "gpt-4o-mini"


def _is_anthropic_model(model: str) -> bool:
    """Return whether a resolved model string names an Anthropic (Claude) model.

    `init_chat_model` understands an `anthropic:` provider prefix; a bare Claude
    id (e.g. `claude-haiku-4-5`) is also treated as Anthropic.
    """
    return model.startswith("anthropic:") or "claude" in model


def _resolve_anthropic_model(role: str) -> str:
    """Resolve the Anthropic model string for a role when a caller supplies an Anthropic key.

    A visitor's own Anthropic key (prefix `sk-ant-`) overrides the global provider
    for this one call, so the role must resolve to an Anthropic model regardless of
    `LLM_PROVIDER`. An explicit `LLM_<ROLE>` override is honoured only when it names
    an Anthropic/Claude model; otherwise the `anthropic_chat_model` default is used.
    The result is returned with an explicit `anthropic:` prefix so `init_chat_model`
    routes it to ChatAnthropic (and the per-call key to it).
    """
    override = os.getenv(f"LLM_{role.upper()}")
    if override and _is_anthropic_model(override):
        model = override
    else:
        model = get_settings().anthropic_chat_model
    return model if model.startswith("anthropic:") else f"anthropic:{model}"


def get_llm(role: str = "default", api_key: str | None = None):
    """Build a chat model for the given role, selected by the `LLM_<ROLE>` env var.

    Defaults to OpenAI `gpt-4o-mini`. Set `LLM_<ROLE>=ollama:<model>` or the
    global `LLM_PROVIDER=ollama` to run a local Ollama model instead (zero-cost,
    fully offline), or `LLM_PROVIDER=groq` (with `GROQ_API_KEY` set) to route
    non-vision roles to a free-tier Groq-hosted model. Uses `temperature=0` for
    reproducibility.

    `api_key` is an optional per-call key that may be an OpenAI OR an Anthropic key,
    auto-detected from its prefix. When it is a non-empty string it switches THIS
    call to that provider regardless of the global provider:

    * a key starting with `sk-ant-` routes to Anthropic — the role resolves to its
      Anthropic model (the `LLM_<ROLE>` value when that names a Claude model, else
      the `anthropic_chat_model` default) and the key authenticates ChatAnthropic;
    * any other key routes to OpenAI — the role resolves to its OpenAI model (the
      `LLM_<ROLE>` value when that names an OpenAI model, else the OpenAI default
      `gpt-4o-mini`) and the key authenticates the model instead of the process
      `OPENAI_API_KEY`.

    This lets a visitor use — and pay for — a premium model everywhere (Ask,
    exercises, quizzes, grading, the router, PDF extraction) on their own credit,
    while the free Groq/Ollama models remain the default when no key is supplied.
    The key is passed straight into `init_chat_model` (which maps it to the
    provider SDK's credential) and lives only on the returned model instance for
    the duration of this call; it is never cached globally, stored or logged. When
    `api_key` is None/empty the resolution is unchanged (Groq/Ollama/OpenAI per
    env), so the free path is byte-identical.
    """
    # Configure the global LLM cache once (no-op unless `llm_cache` is set), so
    # repeated identical prompts are served from cache instead of re-billed. The
    # response cache keys on the prompt + model, never on `api_key`, so a
    # per-request key is never persisted across callers.
    configure_cache()

    if api_key:
        # A caller's own key overrides the global provider for this call. Detect the
        # provider from the key prefix: `sk-ant-` -> Anthropic, otherwise OpenAI.
        # Resolve to that provider's model for the role and authenticate it with the
        # key. The key is mapped by `init_chat_model` to the provider SDK's
        # credential (ChatOpenAI's `openai_api_key` / ChatAnthropic's `anthropic_api_key`)
        # and never leaves the returned instance.
        if api_key.startswith("sk-ant-"):
            model = _resolve_anthropic_model(role)
        else:
            model = _resolve_openai_model(role)
        provider_kwargs: dict = {"api_key": api_key}
    else:
        model, provider_kwargs = _resolve_model(role)
    llm = init_chat_model(model, temperature=0, **provider_kwargs)

    # Compose callbacks: LangFuse tracing (opt-in) and the token budget guard
    # (opt-in). Each helper returns an empty list when disabled, so when both
    # features are off the model is returned unchanged (no behavior change).
    callbacks = get_callbacks() + get_budget_callbacks(get_settings().llm_budget_tokens)
    if callbacks:
        llm = llm.with_config(callbacks=callbacks)
    return llm
