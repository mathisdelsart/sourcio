"""Tests for the opt-in LLM cache and token budget cap.

No network, no real LLM, no API calls: synthetic results and monkeypatched
factory internals only.
"""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

import budget
import config


def _result(total_tokens: int) -> LLMResult:
    """Build a synthetic `LLMResult` carrying a provider-style token usage block."""
    return LLMResult(
        generations=[[]],
        llm_output={"token_usage": {"total_tokens": total_tokens}},
    )


def test_get_budget_callbacks_disabled_returns_empty():
    """A zero (or negative) cap disables the guard and attaches nothing."""
    assert budget.get_budget_callbacks(0) == []
    assert budget.get_budget_callbacks(-5) == []


def test_budget_callback_accumulates_and_raises():
    """Tokens accumulate across calls and raise once the running total exceeds the cap."""
    (handler,) = budget.get_budget_callbacks(100)

    handler.on_llm_end(_result(40))
    assert handler.total_tokens == 40  # under cap, no raise

    handler.on_llm_end(_result(50))
    assert handler.total_tokens == 90  # still under cap

    with pytest.raises(budget.BudgetExceeded):
        handler.on_llm_end(_result(20))  # 110 > 100 -> raises
    assert handler.total_tokens == 110


def test_budget_callback_reads_usage_metadata():
    """When no provider usage block is present, per-generation metadata is used."""
    message = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
    )
    result = LLMResult(generations=[[ChatGeneration(message=message)]], llm_output={})
    (handler,) = budget.get_budget_callbacks(1000)
    handler.on_llm_end(result)
    assert handler.total_tokens == 30


def test_configure_cache_memory(monkeypatch):
    """`configure_cache` installs an InMemoryCache for the "memory" mode."""
    from langchain_core.caches import InMemoryCache

    # Reset the once-only guard so the helper runs in this test.
    monkeypatch.setattr(config, "_cache_configured", False)
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(llm_cache="memory"))

    captured = {}
    monkeypatch.setattr(
        "langchain_core.globals.set_llm_cache",
        lambda cache: captured.__setitem__("cache", cache),
    )

    config.configure_cache()
    assert isinstance(captured["cache"], InMemoryCache)


def test_configure_cache_disabled_is_noop(monkeypatch):
    """`configure_cache` does nothing when `llm_cache` is empty."""
    monkeypatch.setattr(config, "_cache_configured", False)
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(llm_cache=""))

    captured = {}
    monkeypatch.setattr(
        "langchain_core.globals.set_llm_cache",
        lambda cache: captured.__setitem__("cache", cache),
    )

    config.configure_cache()
    assert "cache" not in captured


def test_get_llm_unchanged_when_both_features_disabled(monkeypatch):
    """With cache and budget off (and no LangFuse), `get_llm` returns the raw model."""
    for var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setattr(config, "_cache_configured", False)
    monkeypatch.setattr(
        config, "get_settings", lambda: config.Settings(llm_cache="", llm_budget_tokens=0)
    )

    sentinel = object()
    captured = {}

    def fake_init_chat_model(model, temperature):
        captured["model"] = model
        captured["temperature"] = temperature
        return sentinel

    monkeypatch.setattr(config, "init_chat_model", fake_init_chat_model)

    result = config.get_llm()

    # No callbacks attached, no cache installed: model returned exactly as built.
    assert result is sentinel
    assert captured == {"model": "gpt-4o-mini", "temperature": 0}
