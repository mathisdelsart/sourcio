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
from answer import REFUSAL
from ingestion.schema import Chunk, Retrieved


def _retrieved(page: int, text: str, score: float = 0.9) -> Retrieved:
    chunk = Chunk(id=f"id{page}", course="Course", page=page, text=text)
    return Retrieved(chunk=chunk, score=score)


@pytest.fixture
def fake_retrieve(monkeypatch):
    """Patch retrieval.retrieve so generate never touches Qdrant.

    Returns a setter; pass a list of Retrieved (or [] to simulate a miss).
    """
    holder = {"results": [], "question": None}

    def _retrieve(question, **kwargs):
        holder["question"] = question
        return holder["results"]

    import retrieval as retrieval_mod

    monkeypatch.setattr(retrieval_mod, "retrieve", _retrieve)
    return holder


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


def test_graph_routes_generate_and_populates_exercise(fake_llm, fake_retrieve):
    fake_retrieve["results"] = [_retrieved(7, "Integral definition.")]
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


def test_generate_node_grounds_on_retrieved_chunks(fake_llm, fake_retrieve):
    fake_retrieve["results"] = [
        _retrieved(3, "Approximation space V_j."),
        _retrieved(4, "Projection onto V_j."),
    ]
    fake_llm["reply"] = "EXERCISE:\nDo this.\n\nSOLUTION:\nThe answer."
    out = generate({"message": "the approximation space"})

    assert set(out) == {"exercise", "retrieved"}
    assert out["exercise"]["problem"] == "Do this."
    assert out["exercise"]["solution"] == "The answer."
    assert out["exercise"]["refused"] is False
    # Sources backing the exercise are surfaced, like explain does.
    assert out["retrieved"] == [
        "(Course, p.3)",
        "(Course, p.4)",
    ]
    # Retrieval drove the exercise: the prompt must contain the chunk text.
    human_msg = fake_llm["last"].calls[0][-1][1]
    assert "Approximation space V_j." in human_msg
    assert "Projection onto V_j." in human_msg


def test_generate_node_refuses_when_nothing_retrieved(fake_llm, fake_retrieve):
    fake_retrieve["results"] = []  # nothing relevant in the course
    out = generate({"message": "rough-set equivalence relations"})

    assert out["exercise"]["refused"] is True
    assert out["exercise"]["problem"] == REFUSAL
    assert out["exercise"]["solution"] == ""
    assert out["retrieved"] == []
    # The model was never asked to invent an exercise.
    assert fake_llm["last"] is None


def test_grade_node_parses_verdict_and_uses_reference(fake_llm):
    fake_llm["reply"] = 'Verdict: {"score": 55, "feedback": "Partly right."} done'
    out = grade({"message": "my answer", "exercise": {"solution": "ref"}})
    assert set(out) == {"grade"}
    assert out["grade"]["score"] == 55
    assert out["grade"]["feedback"] == "Partly right."
    # The internal raw model output must not leak into the verdict.
    assert set(out["grade"]) == {"score", "feedback"}


def test_grade_node_handles_unparseable_verdict(fake_llm):
    fake_llm["reply"] = "totally unstructured"
    out = grade({"message": "my answer"})
    assert out["grade"]["score"] == 0
    assert out["grade"]["feedback"] == "totally unstructured"
    assert "raw" not in out["grade"]


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


def test_reexplain_uses_last_tutor_turn_when_several(fake_llm):
    fake_llm["reply"] = "Even simpler."
    history = [
        {"role": "tutor", "content": "Old explanation."},
        {"role": "student", "content": "still lost"},
        {"role": "tutor", "content": "Latest explanation [2]."},
    ]
    out = reexplain({"message": "again", "history": history})
    assert out["answer"] == "Even simpler."
    human_msg = fake_llm["last"].calls[0][-1][1]
    # The most recent tutor turn is the one rephrased, not an earlier one.
    assert "Latest explanation [2]." in human_msg
    assert "Old explanation." not in human_msg


# --- persistence: exercises and grades are stored, optionally ----------------

sqlalchemy = pytest.importorskip("sqlalchemy")


@pytest.fixture
def db_factory(monkeypatch):
    """Inject an in-memory SQLite session factory into the persistence layer.

    Yields ``(SessionLocal, set_factory)``: the bound session factory for direct
    inspection, and the helper that wired it into ``agent.persistence``. A single
    shared in-memory engine keeps the schema alive across sessions.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    import agent.persistence as persistence
    from db.session import SessionLocal, init_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(engine)
    SessionLocal.configure(bind=engine)
    persistence.set_session_factory(SessionLocal.begin)
    yield SessionLocal
    persistence.set_session_factory(None)


def test_generate_persists_exercise_with_reference_solution(fake_llm, fake_retrieve, db_factory):
    from sqlalchemy import select

    from db.models import Exercise, Student

    fake_retrieve["results"] = [_retrieved(3, "Integral definition.")]
    fake_llm["reply"] = "EXERCISE:\nCompute X.\n\nSOLUTION:\nX = 42."

    out = generate({"message": "integrals", "student_id": "alice"})
    assert out["exercise"]["refused"] is False
    assert "id" in out["exercise"]

    with db_factory() as session:
        student = session.scalar(select(Student).where(Student.external_id == "alice"))
        assert student is not None
        exercises = session.scalars(select(Exercise)).all()
        assert len(exercises) == 1
        stored = exercises[0]
        assert stored.student_id == student.id
        assert stored.problem == "Compute X."
        assert stored.reference_solution == "X = 42."
        assert stored.notion == "integrals"
        assert stored.course == "Course"


def test_grade_persists_grade_linked_to_exercise(fake_llm, fake_retrieve, db_factory):
    from sqlalchemy import select

    from db.models import Grade

    # First create and store an exercise, then grade an answer against it.
    fake_retrieve["results"] = [_retrieved(5, "Reference material.")]
    fake_llm["reply"] = "EXERCISE:\nDo it.\n\nSOLUTION:\nThe answer."
    gen = generate({"message": "limits", "student_id": "bob"})
    exercise = gen["exercise"]

    fake_llm["reply"] = '{"score": 75, "feedback": "Almost."}'
    out = grade({"message": "my attempt", "student_id": "bob", "exercise": exercise})
    assert out["grade"]["score"] == 75

    with db_factory() as session:
        grades = session.scalars(select(Grade)).all()
        assert len(grades) == 1
        stored = grades[0]
        assert stored.exercise_id == exercise["id"]
        assert stored.answer == "my attempt"
        assert stored.score == 75
        assert stored.feedback == "Almost."


def test_grade_skips_persistence_without_stored_exercise(fake_llm, db_factory):
    from sqlalchemy import select

    from db.models import Grade

    fake_llm["reply"] = '{"score": 50, "feedback": "ok"}'
    # No exercise id: nothing to link a grade to, so persistence is skipped.
    out = grade({"message": "answer", "student_id": "carol", "exercise": {"solution": "ref"}})
    assert out["grade"]["score"] == 50

    with db_factory() as session:
        assert session.scalars(select(Grade)).all() == []


def test_nodes_work_with_persistence_disabled(fake_llm, fake_retrieve, monkeypatch):
    """Without an injected factory and no configured DB, nodes still run."""
    import agent.persistence as persistence
    import db.session as db_session

    # Ensure no factory is wired and the default resolution finds no engine.
    persistence.set_session_factory(None)

    def _no_engine(*_args, **_kwargs):
        raise RuntimeError("no engine configured")

    # Simulate an unconfigured database: the default resolution must degrade to
    # a no-op instead of crashing the node.
    monkeypatch.setattr(db_session, "get_session", _no_engine)

    fake_retrieve["results"] = [_retrieved(1, "Some material.")]
    fake_llm["reply"] = "EXERCISE:\nTry this.\n\nSOLUTION:\nDone."
    gen = generate({"message": "topic", "student_id": "dave"})
    assert gen["exercise"]["refused"] is False
    # No id is surfaced when nothing was persisted.
    assert "id" not in gen["exercise"]

    fake_llm["reply"] = '{"score": 90, "feedback": "Great."}'
    graded = grade({"message": "ans", "student_id": "dave", "exercise": gen["exercise"]})
    assert graded["grade"]["score"] == 90


def test_persistence_skipped_without_student_id(fake_llm, fake_retrieve, db_factory):
    from sqlalchemy import select

    from db.models import Exercise

    fake_retrieve["results"] = [_retrieved(2, "Material.")]
    fake_llm["reply"] = "EXERCISE:\nQ.\n\nSOLUTION:\nA."
    # No student_id: persistence is skipped even though a DB is configured.
    out = generate({"message": "topic"})
    assert "id" not in out["exercise"]

    with db_factory() as session:
        assert session.scalars(select(Exercise)).all() == []
