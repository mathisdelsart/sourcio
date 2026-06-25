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


# --- callbacks are threaded into every LLM call site ------------------------
#
# These tests assert each LLM call passes the callbacks from ``get_callbacks()``
# in its invocation config, so a LangFuse-enabled run traces every step. They
# also cover the disabled path: ``get_callbacks()`` returns ``[]`` and the call
# still works, threading a harmless empty list.


class _CapturingLLM:
    """Chat model stand-in recording the ``config`` of each invoke/stream."""

    def __init__(self, reply: str = "reply") -> None:
        self._reply = reply
        self.configs: list = []

    def invoke(self, _messages, config=None):
        self.configs.append(config)
        return type("Msg", (), {"content": self._reply})()

    def stream(self, _messages, config=None):
        self.configs.append(config)
        yield type("Chunk", (), {"content": self._reply})()


def _patch_callbacks(monkeypatch, module, callbacks):
    """Force ``module.get_callbacks`` to return a known callback list."""
    monkeypatch.setattr(module, "get_callbacks", lambda: callbacks)


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_answer_threads_callbacks(monkeypatch, callbacks):
    import core.answer as answer_mod
    from ingestion.schema import Chunk, Retrieved

    results = [Retrieved(chunk=Chunk(id="1", course="C", page=1, text="t"), score=0.9)]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    llm = _CapturingLLM("grounded [1].")
    monkeypatch.setattr(answer_mod, "get_llm", lambda role: llm)
    _patch_callbacks(monkeypatch, answer_mod, callbacks)

    answer_mod.answer("q")
    assert llm.configs == [{"callbacks": callbacks}]


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_stream_answer_threads_callbacks(monkeypatch, callbacks):
    import core.answer as answer_mod
    from ingestion.schema import Chunk, Retrieved

    results = [Retrieved(chunk=Chunk(id="1", course="C", page=1, text="t"), score=0.9)]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    llm = _CapturingLLM("grounded [1].")
    monkeypatch.setattr(answer_mod, "get_llm", lambda role: llm)
    _patch_callbacks(monkeypatch, answer_mod, callbacks)

    list(answer_mod.stream_answer("q"))
    assert llm.configs == [{"callbacks": callbacks}]


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_router_threads_callbacks(monkeypatch, callbacks):
    import agent.graph as graph_mod

    llm = _CapturingLLM("explain")
    monkeypatch.setattr(graph_mod, "get_llm", lambda role="default": llm)
    _patch_callbacks(monkeypatch, graph_mod, callbacks)

    graph_mod.classify_intent("what is x?")
    assert llm.configs == [{"callbacks": callbacks}]


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_generate_threads_callbacks(monkeypatch, callbacks):
    import agent.nodes.generate as gen_mod
    import core.retrieval as retrieval_mod
    from ingestion.schema import Chunk, Retrieved

    results = [Retrieved(chunk=Chunk(id="1", course="C", page=1, text="t"), score=0.9)]
    monkeypatch.setattr(retrieval_mod, "retrieve", lambda *a, **k: results)
    monkeypatch.setattr(gen_mod, "persist_exercise", lambda *a, **k: None)
    llm = _CapturingLLM("EXERCISE:\nE\n\nSOLUTION:\nS")
    monkeypatch.setattr(gen_mod, "get_llm", lambda role="default": llm)
    _patch_callbacks(monkeypatch, gen_mod, callbacks)

    gen_mod.generate({"message": "notion"})
    assert llm.configs == [{"callbacks": callbacks}]


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_grade_threads_callbacks(monkeypatch, callbacks):
    import agent.nodes.grade as grade_mod

    monkeypatch.setattr(grade_mod, "persist_grade", lambda *a, **k: None)
    llm = _CapturingLLM('{"score": 80, "feedback": "ok"}')
    monkeypatch.setattr(grade_mod, "get_llm", lambda role="default": llm)
    _patch_callbacks(monkeypatch, grade_mod, callbacks)

    grade_mod.grade({"message": "ans", "exercise": {"solution": "ref"}})
    assert llm.configs == [{"callbacks": callbacks}]


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_reexplain_threads_callbacks(monkeypatch, callbacks):
    import agent.nodes.reexplain as re_mod

    llm = _CapturingLLM("simpler version")
    monkeypatch.setattr(re_mod, "get_llm", lambda role="default": llm)
    _patch_callbacks(monkeypatch, re_mod, callbacks)

    re_mod.reexplain({"message": "again", "answer": "previous"})
    assert llm.configs == [{"callbacks": callbacks}]


@pytest.mark.parametrize("callbacks", [["cb-sentinel"], []])
def test_eval_judge_threads_callbacks(monkeypatch, callbacks):
    import core.config as cfg
    import core.obs as obs_mod
    from eval.run_eval import _default_judge_fn

    llm = _CapturingLLM('{"faithful": true, "relevant": true}')
    monkeypatch.setattr(cfg, "get_llm", lambda role="default": llm)
    monkeypatch.setattr(obs_mod, "get_callbacks", lambda: callbacks)

    judge = _default_judge_fn()
    judge("q", "a", ["src"])
    assert llm.configs == [{"callbacks": callbacks}]
