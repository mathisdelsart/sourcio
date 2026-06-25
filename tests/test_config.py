"""Tests for configuration and the model-agnostic LLM factory.

Run fully offline: no API keys, no Ollama server, no model pulls. The
`init_chat_model` constructor is patched so the factory's routing is asserted
without ever contacting a provider, and `get_settings`'s cache is cleared so the
Ollama environment variables take effect within a test.
"""

import pytest

import core.config as config
from core.config import _resolve_model, get_settings


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

    monkeypatch.setattr(config, "init_chat_model", fake_init)
    config.get_llm("default")
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

    monkeypatch.setattr(config, "init_chat_model", fake_init)
    config.get_llm("explain")
    assert captured["model"] == "ollama:llama3.1"
    assert captured["kwargs"].get("base_url") == "http://ollama.internal:11434"
    assert captured["kwargs"].get("temperature") == 0
