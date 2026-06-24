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


@pytest.fixture(autouse=True)
def _reset_budget_handlers(monkeypatch):
    """Isolate the process-wide budget handler cache between tests."""
    monkeypatch.setattr(budget, "_HANDLERS", {})


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


def test_get_budget_callbacks_returns_shared_handler_for_cap():
    """The same cap yields the same handler instance, so usage is process-wide."""
    (first,) = budget.get_budget_callbacks(500)
    (second,) = budget.get_budget_callbacks(500)
    assert first is second  # cached, not freshly constructed per retrieval

    # A different cap gets its own independent handler.
    (other,) = budget.get_budget_callbacks(999)
    assert other is not first


def test_budget_accumulates_across_separate_retrievals():
    """Tokens add up across distinct `get_budget_callbacks` calls for one cap.

    This is the cost-guard fix: each `get_llm` invocation fetches callbacks
    afresh, but they must share a handler so cumulative usage trips the cap.
    """
    (h1,) = budget.get_budget_callbacks(100)
    h1.on_llm_end(_result(60))  # first "call"

    (h2,) = budget.get_budget_callbacks(100)  # second "call": fresh retrieval
    assert h2 is h1
    assert h2.total_tokens == 60  # carries over, not reset to zero

    with pytest.raises(budget.BudgetExceeded):
        h2.on_llm_end(_result(50))  # 110 > 100 cumulative -> trips
    assert h2.total_tokens == 110


def test_get_llm_reuses_shared_budget_handler(monkeypatch):
    """`config.get_llm` attaches the shared handler so usage is cumulative."""
    for var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setattr(config, "_cache_configured", False)
    monkeypatch.setattr(
        config, "get_settings", lambda: config.Settings(llm_cache="", llm_budget_tokens=100)
    )

    captured = {}

    class _FakeLLM:
        def with_config(self, callbacks):
            captured["callbacks"] = callbacks
            return self

    monkeypatch.setattr(config, "init_chat_model", lambda model, temperature: _FakeLLM())

    config.get_llm()
    first = captured["callbacks"]
    config.get_llm()
    second = captured["callbacks"]

    # Both invocations attach the very same handler instance.
    assert len(first) == 1 and len(second) == 1
    assert first[0] is second[0]
    assert first[0] is budget.get_budget_handler(100)


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
