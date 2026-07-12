"""Tests for configuration and the model-agnostic LLM factory.

Run fully offline: no API keys, no Ollama server, no model pulls. The
`init_chat_model` constructor is patched so the factory's routing is asserted
without ever contacting a provider, and `get_settings`'s cache is cleared so the
Ollama environment variables take effect within a test.
"""

import pytest

import core.config as config
import core.llm as llm
from core.config import get_settings
from core.llm import _resolve_model


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Reset the cached Settings around each test so env overrides do not leak."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_defaults():
    settings = get_settings()
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.qdrant_collection == "courses"
    assert 0.0 <= settings.similarity_threshold <= 1.0


def test_settings_cached():
    assert get_settings() is get_settings()


# --- LLM factory routing -----------------------------------------------------


def _fresh_settings(monkeypatch, **env):
    """Set env vars and rebuild the (cached) Settings so they take effect."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_resolve_model_defaults_to_openai(monkeypatch):
    # No LLM_* env, no provider switch: the OpenAI default is unchanged.
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    model, kwargs = _resolve_model("explain")
    assert model == "gpt-4o-mini"
    assert kwargs == {}


def test_resolve_model_per_role_openai_override(monkeypatch):
    # A plain LLM_<ROLE> selects another OpenAI model, no provider kwargs.
    monkeypatch.setenv("LLM_GENERATE", "gpt-4o")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    model, kwargs = _resolve_model("generate")
    assert model == "gpt-4o"
    assert kwargs == {}


def test_resolve_model_per_role_ollama_prefix_wins(monkeypatch):
    # An explicit ollama: prefix wins even over the global provider, and the
    # base_url is forwarded.
    _fresh_settings(
        monkeypatch,
        LLM_PROVIDER="openai",
        OLLAMA_BASE_URL="http://localhost:11434",
    )
    monkeypatch.setenv("LLM_EXPLAIN", "ollama:llama3.1")
    model, kwargs = _resolve_model("explain")
    assert model == "ollama:llama3.1"
    assert kwargs == {"base_url": "http://localhost:11434"}


def test_resolve_model_global_ollama_switch_chat_role(monkeypatch):
    monkeypatch.delenv("LLM_ROUTER", raising=False)
    _fresh_settings(
        monkeypatch,
        LLM_PROVIDER="ollama",
        OLLAMA_CHAT_MODEL="llama3.1",
        OLLAMA_BASE_URL="http://localhost:11434",
    )
    model, kwargs = _resolve_model("router")
    assert model == "ollama:llama3.1"
    assert kwargs == {"base_url": "http://localhost:11434"}


def test_resolve_model_global_ollama_switch_extract_uses_vision(monkeypatch):
    # The extract role needs a multimodal model under the global switch.
    monkeypatch.delenv("LLM_EXTRACT", raising=False)
    _fresh_settings(
        monkeypatch,
        LLM_PROVIDER="ollama",
        OLLAMA_VISION_MODEL="llama3.2-vision",
    )
    model, _ = _resolve_model("extract")
    assert model == "ollama:llama3.2-vision"


def test_resolve_model_per_role_override_beats_global_default_model(monkeypatch):
    # Under the global switch, a non-prefixed LLM_<ROLE> still wins verbatim.
    _fresh_settings(monkeypatch, LLM_PROVIDER="ollama")
    monkeypatch.setenv("LLM_GRADE", "ollama:mistral")
    model, kwargs = _resolve_model("grade")
    assert model == "ollama:mistral"
    assert kwargs == {"base_url": get_settings().ollama_base_url}


def test_resolve_model_global_groq_switch_chat_role(monkeypatch):
    # The global Groq switch resolves non-vision roles to groq:<model> with no
    # provider kwargs (langchain-groq reads GROQ_API_KEY from the environment).
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(
        monkeypatch,
        LLM_PROVIDER="groq",
        GROQ_CHAT_MODEL="llama-3.3-70b-versatile",
    )
    model, kwargs = _resolve_model("explain")
    assert model == "groq:llama-3.3-70b-versatile"
    assert kwargs == {}


def test_resolve_model_global_groq_switch_extract_falls_back_to_openai(monkeypatch):
    # Groq has no vision model, so the extract role falls back to the OpenAI
    # default (ingestion is a one-time offline step, never on the deployed API).
    monkeypatch.delenv("LLM_EXTRACT", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq")
    model, kwargs = _resolve_model("extract")
    assert model == "gpt-4o-mini"
    assert kwargs == {}


def test_resolve_model_per_role_groq_prefix_no_base_url(monkeypatch):
    # An explicit groq: prefix passes through verbatim, with no base_url injected.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_GENERATE", "groq:llama-3.1-8b-instant")
    get_settings.cache_clear()
    model, kwargs = _resolve_model("generate")
    assert model == "groq:llama-3.1-8b-instant"
    assert kwargs == {}


def test_get_llm_default_builds_openai_model(monkeypatch):
    # Prove the default path passes the OpenAI model + temperature=0 to the
    # constructor, with no provider kwargs, contacting nothing.
    monkeypatch.delenv("LLM_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    get_settings.cache_clear()

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("default")
    assert captured["model"] == "gpt-4o-mini"
    assert captured["kwargs"].get("temperature") == 0
    assert "base_url" not in captured["kwargs"]


def test_get_llm_ollama_builds_local_model(monkeypatch):
    # Under the global Ollama switch the factory builds an Ollama model with the
    # base_url forwarded and temperature=0, without contacting any server.
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(
        monkeypatch,
        LLM_PROVIDER="ollama",
        OLLAMA_CHAT_MODEL="llama3.1",
        OLLAMA_BASE_URL="http://ollama.internal:11434",
    )

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain")
    assert captured["model"] == "ollama:llama3.1"
    assert captured["kwargs"].get("base_url") == "http://ollama.internal:11434"
    assert captured["kwargs"].get("temperature") == 0


def test_get_llm_forwards_api_key_for_openai_model(monkeypatch):
    # A per-call api_key is forwarded to init_chat_model for the OpenAI-fallback
    # case (the vision extract role under the Groq provider), so a visitor's own
    # key authenticates their scanned-PDF ingestion instead of the env key.
    monkeypatch.delenv("LLM_EXTRACT", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("extract", api_key="sk-test")
    assert captured["model"] == "gpt-4o-mini"
    assert captured["kwargs"].get("api_key") == "sk-test"


def test_get_llm_key_forces_openai_for_groq_role(monkeypatch):
    # New semantics: a per-call key overrides the global provider EVERYWHERE. A
    # normally-Groq role resolves to the OpenAI default and forwards the key, so a
    # visitor's own key drives a premium model for Ask/exercise/quiz/grade too.
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain", api_key="sk-test")
    assert captured["model"] == "gpt-4o-mini"
    assert captured["kwargs"].get("api_key") == "sk-test"
    assert captured["kwargs"].get("temperature") == 0


def test_get_llm_key_forces_openai_over_ollama_provider(monkeypatch):
    # Likewise under the global Ollama switch: a supplied key forces OpenAI (no
    # ollama: prefix, no base_url) so the key can never be sent to the wrong host.
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="ollama")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain", api_key="sk-test")
    assert captured["model"] == "gpt-4o-mini"
    assert captured["kwargs"].get("api_key") == "sk-test"
    assert "base_url" not in captured["kwargs"]


def test_get_llm_key_honours_openai_per_role_override(monkeypatch):
    # An explicit OpenAI-named LLM_<ROLE> override is used verbatim when a key is
    # supplied (a bigger OpenAI model for that role), still authenticated by the key.
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq", LLM_EXPLAIN="openai:gpt-4o")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain", api_key="sk-test")
    assert captured["model"] == "openai:gpt-4o"
    assert captured["kwargs"].get("api_key") == "sk-test"


def test_get_llm_anthropic_key_forces_anthropic_model(monkeypatch):
    # An `sk-ant-` key is auto-detected and routes THIS call to Anthropic: the role
    # resolves to the anthropic_chat_model default (prefixed `anthropic:`) and the
    # key is forwarded to init_chat_model (which maps it to ChatAnthropic).
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain", api_key="sk-ant-xxx")
    assert captured["model"].startswith("anthropic:")
    assert captured["model"] == f"anthropic:{get_settings().anthropic_chat_model}"
    assert captured["kwargs"].get("api_key") == "sk-ant-xxx"
    assert captured["kwargs"].get("temperature") == 0


def test_get_llm_anthropic_key_honours_claude_per_role_override(monkeypatch):
    # An explicit LLM_<ROLE> naming a claude model is honored under an sk-ant- key.
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq", LLM_EXPLAIN="anthropic:claude-opus-4-8")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain", api_key="sk-ant-xxx")
    assert captured["model"] == "anthropic:claude-opus-4-8"
    assert captured["kwargs"].get("api_key") == "sk-ant-xxx"


def test_get_llm_openai_key_still_forces_openai(monkeypatch):
    # A non-`sk-ant-` key keeps the existing OpenAI behavior (byte-identical).
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain", api_key="sk-xxx")
    assert captured["model"] == "gpt-4o-mini"
    assert captured["kwargs"].get("api_key") == "sk-xxx"


def test_get_llm_no_key_leaves_groq_resolution_unchanged(monkeypatch):
    # Without a key the resolution is byte-identical to before: the free Groq
    # model, no api_key kwarg. This is the default free path.
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="groq")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain")
    assert captured["model"].startswith("groq:")
    assert "api_key" not in captured["kwargs"]


def test_get_llm_no_key_leaves_ollama_resolution_unchanged(monkeypatch):
    # Without a key an Ollama role is untouched: ollama: prefix, base_url, no key.
    monkeypatch.delenv("LLM_EXPLAIN", raising=False)
    _fresh_settings(monkeypatch, LLM_PROVIDER="ollama")

    captured = {}

    def fake_init(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.get_llm("explain")
    assert captured["model"].startswith("ollama:")
    assert "api_key" not in captured["kwargs"]


# --- Effective rate limit ----------------------------------------------------


def test_effective_rate_limit_auto_off_in_local_dev():
    # Auto (0) + require_auth False (local dev): stays off.
    settings = config.Settings(rate_limit_per_minute=0, require_auth=False)
    assert settings.effective_rate_limit_per_minute == 0


def test_effective_rate_limit_auto_defaults_to_60_in_public_mode():
    # Auto (0) + require_auth True (public mode): sane default throttle.
    settings = config.Settings(rate_limit_per_minute=0, require_auth=True)
    assert settings.effective_rate_limit_per_minute == 60


def test_effective_rate_limit_explicit_override_wins_regardless_of_auth():
    # An explicit positive value always wins over the auto default, in both modes.
    local = config.Settings(rate_limit_per_minute=30, require_auth=False)
    public = config.Settings(rate_limit_per_minute=30, require_auth=True)
    assert local.effective_rate_limit_per_minute == 30
    assert public.effective_rate_limit_per_minute == 30


def test_max_upload_mb_default():
    assert config.Settings().max_upload_mb == 100


def test_ingest_parallelism_defaults():
    settings = config.Settings()
    assert settings.ingest_concurrency == 12
    assert settings.ingest_batch_size == 16
