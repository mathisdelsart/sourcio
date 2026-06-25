"""Tests for opt-in LangFuse tracing. No network, no real LLM, no API calls."""

import pytest

import core.config as config
import core.obs as obs

_LANGFUSE_ENV = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


def _clear_langfuse_env(monkeypatch):
    for var in _LANGFUSE_ENV:
        monkeypatch.delenv(var, raising=False)


def test_disabled_without_env(monkeypatch):
    """When no LangFuse env is set, tracing is off and no callbacks are produced."""
    _clear_langfuse_env(monkeypatch)
    assert obs.tracing_enabled() is False
    assert obs.get_callbacks() == []


def test_get_llm_unchanged_when_langfuse_absent(monkeypatch):
    """`get_llm` returns the raw model untouched when tracing is disabled."""
    _clear_langfuse_env(monkeypatch)

    sentinel = object()
    captured = {}

    def fake_init_chat_model(model, temperature):
        captured["model"] = model
        captured["temperature"] = temperature
        return sentinel

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    result = config.get_llm()

    # No callbacks attached: the model is returned exactly as built.
    assert result is sentinel
    assert captured == {"model": "gpt-4o-mini", "temperature": 0}


def test_role_selects_model(monkeypatch):
    """Role-based env override still drives model selection, tracing off."""
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LLM_GENERATE", "gpt-4o")

    captured = {}

    def fake_init_chat_model(model, temperature):
        captured["model"] = model
        return object()

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    config.get_llm("generate")
    assert captured["model"] == "gpt-4o"


def test_enabled_with_env_and_langfuse(monkeypatch):
    """With env set and langfuse importable, callbacks are non-empty."""
    pytest.importorskip("langfuse")

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")

    assert obs.tracing_enabled() is True
    callbacks = obs.get_callbacks()
    assert len(callbacks) >= 1


def test_get_llm_attaches_callbacks_when_enabled(monkeypatch):
    """When tracing is enabled, `get_llm` wires callbacks via `with_config`."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    # Mock the handler list so the test never imports langfuse or hits a server.
    fake_callback = object()
    monkeypatch.setattr(config, "get_callbacks", lambda: [fake_callback])

    captured = {}

    class FakeModel:
        def with_config(self, callbacks):
            captured["callbacks"] = callbacks
            return "configured-model"

    monkeypatch.setattr(config, "init_chat_model", lambda model, temperature: FakeModel())

    result = config.get_llm()
    assert result == "configured-model"
    assert captured["callbacks"] == [fake_callback]
