"""Tests for the grounded quiz node.

No real LLM or vector store is touched: ``get_llm`` and the lazy
``core.retrieval.retrieve`` import are monkeypatched, and persistence is bound to
a fresh in-memory SQLite database. The module is skipped when the optional
``api`` extra (SQLAlchemy) is not installed.
"""

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from agent.nodes.quiz import generate_quiz  # noqa: E402
from agent.nodes.quiz_grade import grade_quiz_answer, summarize_quiz  # noqa: E402
from db.models import Grade, Quiz, QuizQuestion  # noqa: E402
from db.session import configure_session_factory, get_session, init_db  # noqa: E402


@pytest.fixture
def engine():
    """A shared in-memory SQLite engine bound as the default session factory."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(eng)
    configure_session_factory(eng)
    return eng


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def invoke(self, _messages, config=None):
        return _FakeMessage(self._reply)


def _make_retrieved(text: str):
    from ingestion.schema import Chunk, Retrieved

    chunk = Chunk(id="1", course="Algebra", page=7, text=text, chapter="Ch.2")
    return [Retrieved(chunk=chunk, score=0.9)]


_TWO_QUESTIONS = (
    "### QUESTION 1\nProve closure.\n### SOLUTION 1\nBy axiom 1.\n"
    "### QUESTION 2\nProve identity.\n### SOLUTION 2\nThe neutral element e.\n"
)


def _patch_llm(monkeypatch, reply: str) -> None:
    monkeypatch.setattr(
        "agent.nodes.quiz.get_llm", lambda role="default", api_key=None: _FakeLLM(reply)
    )


def _patch_retrieve(monkeypatch, results, captured: dict | None = None) -> None:
    def _retrieve(*_a, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        return results

    monkeypatch.setattr("core.retrieval.retrieve", _retrieve)


def test_generate_quiz_threads_language_into_prompt(engine, monkeypatch):
    # A French UI request must inject the French output-language directive so the
    # quiz is written in French even though the sources are in English.
    captured: dict = {}

    class _CapturingLLM:
        def invoke(self, messages, config=None):
            captured["system"] = messages[0][1]
            return _FakeMessage(_TWO_QUESTIONS)

    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    monkeypatch.setattr(
        "agent.nodes.quiz.get_llm", lambda role="default", api_key=None: _CapturingLLM()
    )

    generate_quiz("groups", 2, "zoe", language="fr")

    assert "Write the quiz in French" in captured["system"]
    assert "even if the sources are written in another language" in captured["system"]


def test_generate_quiz_persists_quiz_and_questions(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)

    result = generate_quiz("groups", 2, "zoe")

    assert result["refused"] is False
    assert result["notion"] == "groups"
    assert isinstance(result["quiz_id"], int)
    assert [q["problem"] for q in result["questions"]] == [
        "Prove closure.",
        "Prove identity.",
    ]

    # A quiz row and its two question rows are persisted, in order.
    with get_session(engine) as session:
        quiz = session.get(Quiz, result["quiz_id"])
        assert quiz is not None
        assert quiz.notion == "groups"
        questions = list(
            session.scalars(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_id == quiz.id)
                .order_by(QuizQuestion.position)
            )
        )
        assert [q.position for q in questions] == [0, 1]
        assert questions[0].reference_solution == "By axiom 1."
        assert questions[1].reference_solution == "The neutral element e."


def test_generate_quiz_scopes_retrieval_by_course_and_chapter(engine, monkeypatch):
    captured: dict = {}
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."), captured)
    _patch_llm(monkeypatch, _TWO_QUESTIONS)

    result = generate_quiz("groups", 2, "zoe", course="Algebra", chapter="Ch.2")

    assert result["refused"] is False
    # The explicit course/chapter reached retrieval so the quiz stays on topic.
    assert captured["course"] == "Algebra"
    assert captured["chapter"] == "Ch.2"


def test_generate_quiz_never_returns_reference_solutions(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)

    result = generate_quiz("groups", 2, "zoe")

    # The return must carry problems only; no solution leaks anywhere in it.
    for q in result["questions"]:
        assert set(q.keys()) == {"id", "problem"}
    serialized = str(result)
    assert "By axiom 1." not in serialized
    assert "neutral element" not in serialized


def test_generate_quiz_refuses_when_not_covered(engine, monkeypatch):
    # Nothing retrieved: the node refuses rather than inventing questions.
    _patch_retrieve(monkeypatch, [])
    _patch_llm(monkeypatch, _TWO_QUESTIONS)

    result = generate_quiz("astrophysics", 3, "zoe")

    assert result["refused"] is True
    assert result["questions"] == []
    assert result["quiz_id"] is None

    # Nothing was persisted.
    with get_session(engine) as session:
        assert session.scalars(select(Quiz)).first() is None


def test_generate_quiz_refuses_when_sources_dont_cover_notion(engine, monkeypatch):
    # Retrieval returns non-empty chunks (e.g. a CV scoped to the wrong course),
    # but the model — the coverage judge — finds them unrelated to the notion and
    # emits the exact refusal sentence. The node must refuse, not fabricate a quiz.
    from core.answer import REFUSAL

    _patch_retrieve(monkeypatch, _make_retrieved("Work experience and education."))
    _patch_llm(monkeypatch, REFUSAL)

    result = generate_quiz("Wavelet Transform", 3, "zoe", course="CV")

    assert result["refused"] is True
    assert result["questions"] == []
    assert result["quiz_id"] is None

    # No questions were fabricated and nothing was persisted.
    with get_session(engine) as session:
        assert session.scalars(select(Quiz)).first() is None
        assert session.scalars(select(QuizQuestion)).first() is None


def test_generate_quiz_generates_when_sources_cover_notion(engine, monkeypatch):
    # The covered case still produces questions and does not refuse.
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)

    result = generate_quiz("groups", 2, "zoe")

    assert result["refused"] is False
    assert [q["problem"] for q in result["questions"]] == [
        "Prove closure.",
        "Prove identity.",
    ]


def test_generate_quiz_preserves_latex_verbatim(engine, monkeypatch):
    # The delimiter format carries LaTeX with single backslashes (\rho, \sqrt)
    # verbatim — no JSON escaping to corrupt the maths (which used to double
    # backslashes and break rendering). It must parse, not refuse, and keep the
    # LaTeX byte-for-byte.
    _patch_retrieve(monkeypatch, _make_retrieved("Portfolio variance and correlation."))
    latex_reply = (
        "### QUESTION 1\n"
        "How does $\\rho_{12}$ affect risk when $\\rho_{12} = -1$?\n"
        "### SOLUTION 1\n"
        "Portfolio variance uses $\\sqrt{w_1^2 + w_2^2}$.\n"
    )
    _patch_llm(monkeypatch, latex_reply)

    result = generate_quiz("portfolio correlation", 1, "zoe")

    assert result["refused"] is False
    assert result["questions"][0]["problem"] == (
        "How does $\\rho_{12}$ affect risk when $\\rho_{12} = -1$?"
    )


def test_generate_quiz_refuses_when_model_returns_no_question(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, "no question markers here")

    result = generate_quiz("groups", 2, "zoe")

    assert result["refused"] is True
    assert result["questions"] == []


def test_generate_quiz_caps_question_count(engine, monkeypatch):
    # The model returns three; n=2 keeps only the first two.
    three = (
        "### QUESTION 1\nQ1\n### SOLUTION 1\nS1\n"
        "### QUESTION 2\nQ2\n### SOLUTION 2\nS2\n"
        "### QUESTION 3\nQ3\n### SOLUTION 3\nS3\n"
    )
    _patch_retrieve(monkeypatch, _make_retrieved("Axioms."))
    _patch_llm(monkeypatch, three)

    result = generate_quiz("groups", 2, "zoe")
    assert [q["problem"] for q in result["questions"]] == ["Q1", "Q2"]


def test_generate_quiz_without_student_returns_unpersisted(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)

    result = generate_quiz("groups", 2, None)
    assert result["refused"] is False
    assert result["quiz_id"] is None
    assert all(q["id"] is None for q in result["questions"])

    with get_session(engine) as session:
        assert session.scalars(select(Quiz)).first() is None


def test_grade_quiz_answer_scores_and_persists(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]
    question_id = result["questions"][0]["id"]

    # Grade reuses the existing judge node; mock its LLM.
    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default", api_key=None: _FakeLLM('{"score": 90, "feedback": "Correct."}'),
    )

    verdict = grade_quiz_answer(quiz_id, question_id, "Closure holds.", "zoe")
    assert verdict == {"score": 90, "feedback": "Correct."}

    # A grade row is persisted, linked to the question (not an exercise).
    with get_session(engine) as session:
        grades = list(session.scalars(select(Grade).where(Grade.quiz_question_id == question_id)))
        assert len(grades) == 1
        assert grades[0].score == 90
        assert grades[0].exercise_id is None
        assert grades[0].answer == "Closure holds."


def test_grade_quiz_answer_uses_stored_reference(engine, monkeypatch):
    # The judge must receive the question's stored reference solution, which the
    # caller never supplies.
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]
    question_id = result["questions"][0]["id"]

    captured = {}

    class _CaptureLLM:
        def invoke(self, messages, config=None):
            captured["human"] = messages[-1][1]
            return _FakeMessage('{"score": 50, "feedback": "ok"}')

    monkeypatch.setattr(
        "agent.nodes.grade.get_llm", lambda role="default", api_key=None: _CaptureLLM()
    )

    grade_quiz_answer(quiz_id, question_id, "some answer", "zoe")
    # The stored reference solution for question 0 was "By axiom 1.".
    assert "By axiom 1." in captured["human"]


def test_grade_quiz_answer_applies_rigor_guidance(engine, monkeypatch):
    # The requested rigor must reach the shared grade judge, injecting the exact
    # per-level guidance the exercise judge uses.
    from agent.nodes.grade import _RIGOR_GUIDANCE

    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]
    question_id = result["questions"][0]["id"]

    captured = {}

    class _CaptureLLM:
        def invoke(self, messages, config=None):
            captured["human"] = messages[-1][1]
            return _FakeMessage('{"score": 50, "feedback": "ok"}')

    monkeypatch.setattr(
        "agent.nodes.grade.get_llm", lambda role="default", api_key=None: _CaptureLLM()
    )

    grade_quiz_answer(quiz_id, question_id, "answer", "zoe", "strict")
    assert _RIGOR_GUIDANCE["strict"] in captured["human"]

    # Default rigor is the balanced "standard" strictness.
    grade_quiz_answer(quiz_id, question_id, "answer", "zoe")
    assert _RIGOR_GUIDANCE["standard"] in captured["human"]


def test_summarize_quiz_threads_rigor_to_judge(engine, monkeypatch):
    from agent.nodes.grade import _RIGOR_GUIDANCE

    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]
    q0 = result["questions"][0]["id"]

    seen: list[str] = []

    class _CaptureLLM:
        def invoke(self, messages, config=None):
            seen.append(messages[-1][1])
            return _FakeMessage('{"score": 70, "feedback": "ok"}')

    monkeypatch.setattr(
        "agent.nodes.grade.get_llm", lambda role="default", api_key=None: _CaptureLLM()
    )
    monkeypatch.setattr(
        "agent.nodes.quiz_grade.get_llm", lambda role="default", api_key=None: _FakeLLM("Keep going.")
    )

    summarize_quiz(quiz_id, [{"question_id": q0, "answer": "a0"}], "zoe", "lenient")
    # The lenient guidance was applied when grading the answer.
    assert any(_RIGOR_GUIDANCE["lenient"] in human for human in seen)


def test_summarize_quiz_averages_and_recommends(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]
    q0 = result["questions"][0]["id"]
    q1 = result["questions"][1]["id"]

    # The judge (grade node) scores every answer the same; the recommendation LLM
    # (quiz node) returns a fixed study tip.
    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default", api_key=None: _FakeLLM('{"score": 80, "feedback": "Good."}'),
    )
    monkeypatch.setattr(
        "agent.nodes.quiz_grade.get_llm",
        lambda role="default", api_key=None: _FakeLLM("Revise the group axioms."),
    )

    summary = summarize_quiz(
        quiz_id,
        [{"question_id": q0, "answer": "a0"}, {"question_id": q1, "answer": "a1"}],
        "zoe",
    )

    assert summary["total"] == 80
    assert [r["question_id"] for r in summary["results"]] == [q0, q1]
    assert all(r["score"] == 80 for r in summary["results"])
    assert summary["recommendation"] == "Revise the group axioms."

    # Each answer was graded and persisted as a grade row.
    with get_session(engine) as session:
        assert len(list(session.scalars(select(Grade)))) == 2


def test_summarize_quiz_skips_unknown_questions(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]
    q0 = result["questions"][0]["id"]

    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default", api_key=None: _FakeLLM('{"score": 60, "feedback": "ok"}'),
    )
    monkeypatch.setattr(
        "agent.nodes.quiz_grade.get_llm",
        lambda role="default", api_key=None: _FakeLLM("Keep practising."),
    )

    # One valid answer plus one for a nonexistent question id: the latter is
    # skipped and the average is computed over the graded question only.
    summary = summarize_quiz(
        quiz_id,
        [{"question_id": q0, "answer": "a0"}, {"question_id": 99999, "answer": "x"}],
        "zoe",
    )

    assert summary["total"] == 60
    assert [r["question_id"] for r in summary["results"]] == [q0]


def test_summarize_quiz_without_graded_questions_has_no_recommendation(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]

    # No recommendation LLM call should be made when nothing can be graded.
    def _boom(role="default", api_key=None):
        raise AssertionError("recommendation LLM must not be called")

    monkeypatch.setattr("agent.nodes.quiz_grade.get_llm", _boom)

    summary = summarize_quiz(quiz_id, [{"question_id": 99999, "answer": "x"}], "zoe")

    assert summary == {"total": 0, "results": [], "recommendation": ""}


def test_grade_quiz_answer_unknown_question_returns_none(engine, monkeypatch):
    _patch_retrieve(monkeypatch, _make_retrieved("Group axioms."))
    _patch_llm(monkeypatch, _TWO_QUESTIONS)
    result = generate_quiz("groups", 2, "zoe")
    quiz_id = result["quiz_id"]

    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default", api_key=None: _FakeLLM('{"score": 1, "feedback": "x"}'),
    )

    # Nonexistent question id, and a real question id under the wrong quiz id.
    assert grade_quiz_answer(quiz_id, 99999, "answer", "zoe") is None
    real_qid = result["questions"][0]["id"]
    assert grade_quiz_answer(quiz_id + 999, real_qid, "answer", "zoe") is None
