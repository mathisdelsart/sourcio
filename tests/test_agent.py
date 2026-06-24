"""Tests for the agentic layer: router, node wiring, and graph routing.

No real API or vector store is touched. ``config.get_llm`` is monkeypatched to
return a fake chat model that yields canned outputs, and ``answer.answer`` is
monkeypatched where the explain node would otherwise run RAG.
"""

import pytest

import config
from agent import graph as graph_mod
from agent.graph import INTENTS, build_graph, classify_intent, route
from agent.nodes.explain import explain
from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.reexplain import reexplain


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Minimal stand-in for a chat model: returns a fixed reply on invoke."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        return _FakeMessage(self.reply)


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch get_llm everywhere so no role ever reaches a real provider."""

    holder = {"reply": "", "last": None}

    def _factory(role: str = "default"):
        llm = _FakeLLM(holder["reply"])
        holder["last"] = llm
        return llm

    monkeypatch.setattr(config, "get_llm", _factory)
    # Nodes import get_llm by name into their own module namespace.
    monkeypatch.setattr(graph_mod, "get_llm", _factory)
    import agent.nodes.generate as gen_mod
    import agent.nodes.grade as grade_mod
    import agent.nodes.reexplain as re_mod

    monkeypatch.setattr(gen_mod, "get_llm", _factory)
    monkeypatch.setattr(grade_mod, "get_llm", _factory)
    monkeypatch.setattr(re_mod, "get_llm", _factory)
    return holder


# --- (a) router maps each intent label to the correct node -------------------


@pytest.mark.parametrize("label", list(INTENTS))
def test_route_maps_each_intent_to_its_node(label):
    assert route({"intent": label}) == label


def test_route_defaults_to_explain_for_unknown_intent():
    assert route({"intent": "bogus"}) == "explain"
    assert route({}) == "explain"


@pytest.mark.parametrize("label", list(INTENTS))
def test_classify_uses_router_llm_label(fake_llm, label):
    fake_llm["reply"] = f"  {label.upper()}  "  # trimmed + lowercased by classifier
    assert classify_intent("any message") == label


def test_classify_falls_back_to_keywords_when_llm_unusable(fake_llm):
    fake_llm["reply"] = "not-a-valid-label"
    assert classify_intent("Please give me an exercise on Fourier") == "generate"
    assert classify_intent("Can you grade my answer?") == "grade"
    assert classify_intent("Explain that again, simpler") == "reexplain"
    assert classify_intent("What is a wavelet?") == "explain"


# --- (b) compiled graph routes a message to the expected node ----------------


def test_graph_routes_generate_and_populates_exercise(fake_llm):
    fake_llm["reply"] = "EXERCISE:\nCompute X.\n\nSOLUTION:\nX = 42."
    app = build_graph()
    out = app.invoke({"message": "Give me an exercise on integrals"})
    assert out["intent"] == "generate"
    assert out["exercise"]["problem"] == "Compute X."
    assert out["exercise"]["solution"] == "X = 42."


def test_graph_routes_grade_and_populates_grade(fake_llm):
    fake_llm["reply"] = '{"score": 80, "feedback": "Good method."}'
    # Force the router to pick grade via a keyword, since the same fake reply is
    # also what the grade node returns.
    app = build_graph()
    out = app.invoke({"message": "grade my answer: X = 42", "exercise": {"solution": "X = 42"}})
    assert out["intent"] == "grade"
    assert out["grade"]["score"] == 80
    assert out["grade"]["feedback"] == "Good method."


def test_graph_routes_reexplain_and_populates_answer(fake_llm):
    fake_llm["reply"] = "Here it is, simpler."
    app = build_graph()
    out = app.invoke(
        {
            "message": "I don't understand, explain again",
            "history": [{"role": "tutor", "content": "Original explanation [1]."}],
        }
    )
    assert out["intent"] == "reexplain"
    assert out["answer"] == "Here it is, simpler."
    assert out["history"][-1]["intent"] == "reexplain"


# --- (c) explain delegates to answer.answer ----------------------------------


def test_explain_delegates_to_answer(monkeypatch):
    captured = {}

    def fake_answer(question, **kwargs):
        captured["question"] = question
        return {
            "answer": "A wavelet is ... (Course, p.11)",
            "refused": False,
            "sources": ["(Course, p.11)"],
            "raw": "A wavelet is ... [1]",
        }

    # explain imports answer lazily from the answer module, so patch it there.
    import answer as answer_mod

    monkeypatch.setattr(answer_mod, "answer", fake_answer)

    out = explain({"message": "What is a wavelet?"})
    assert captured["question"] == "What is a wavelet?"
    assert out["answer"] == "A wavelet is ... (Course, p.11)"
    assert out["retrieved"] == ["(Course, p.11)"]
    assert out["history"][-1]["intent"] == "explain"


def test_graph_routes_explain_via_answer(monkeypatch, fake_llm):
    fake_llm["reply"] = "explain"  # router classifies as explain

    def fake_answer(question, **kwargs):
        return {
            "answer": "Grounded reply",
            "refused": False,
            "sources": [],
            "raw": "Grounded reply",
        }

    import answer as answer_mod

    monkeypatch.setattr(answer_mod, "answer", fake_answer)

    app = build_graph()
    out = app.invoke({"message": "What is a wavelet?"})
    assert out["intent"] == "explain"
    assert out["answer"] == "Grounded reply"


# --- node-level checks: each node writes only its own key --------------------


def test_generate_node_parses_exercise_and_solution(fake_llm):
    fake_llm["reply"] = "EXERCISE:\nDo this.\n\nSOLUTION:\nThe answer."
    out = generate({"message": "limits"})
    assert set(out) == {"exercise"}
    assert out["exercise"]["problem"] == "Do this."
    assert out["exercise"]["solution"] == "The answer."


def test_grade_node_parses_verdict_and_uses_reference(fake_llm):
    fake_llm["reply"] = 'Verdict: {"score": 55, "feedback": "Partly right."} done'
    out = grade({"message": "my answer", "exercise": {"solution": "ref"}})
    assert set(out) == {"grade"}
    assert out["grade"]["score"] == 55
    assert out["grade"]["feedback"] == "Partly right."


def test_grade_node_handles_unparseable_verdict(fake_llm):
    fake_llm["reply"] = "totally unstructured"
    out = grade({"message": "my answer"})
    assert out["grade"]["score"] == 0
    assert out["grade"]["feedback"] == "totally unstructured"


def test_reexplain_uses_previous_tutor_turn(fake_llm):
    fake_llm["reply"] = "Simpler version."
    history = [
        {"role": "student", "content": "q"},
        {"role": "tutor", "content": "First explanation [1]."},
    ]
    out = reexplain({"message": "again please", "history": history})
    assert out["answer"] == "Simpler version."
    # The previous tutor explanation was fed to the model, not re-retrieved.
    human_msg = fake_llm["last"].calls[0][-1][1]
    assert "First explanation [1]." in human_msg
