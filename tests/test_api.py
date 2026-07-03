"""Tests for the FastAPI service.

No real LLM, vector store, or network call is made: the underlying grounded
function and graph nodes are monkeypatched in the ``api.main`` namespace, and the
service is bound to an in-memory SQLite database, so the routes are exercised in
isolation. The module is skipped when the optional ``api`` extra (FastAPI) is not
installed, so CI without extras collects cleanly.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.main as api_main  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture
def client():
    """Bind the API to a fresh in-memory SQLite DB and yield a test client.

    A single shared in-memory connection (``StaticPool``) is used so every
    request sees the same database for the duration of the test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    # The app's lifespan would otherwise overwrite the engine; pre-binding above
    # leaves ``_engine`` set, so the lifespan no-ops and our in-memory DB is used.
    with TestClient(app) as test_client:
        yield test_client
    api_main._engine = None


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_returns_grounded_answer_and_sources(client, monkeypatch):
    captured = {}

    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        captured["question"] = question
        captured["k"] = k
        return {
            "answer": "A wavelet is ... (Course, p.11)",
            "refused": False,
            "sources": ["(Course, p.11)"],
            "raw": "A wavelet is ... [1]",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post(
        "/ask", json={"student_id": "s1", "question": "What is a wavelet?", "k": 3}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "answer": "A wavelet is ... (Course, p.11)",
        "refused": False,
        "sources": ["(Course, p.11)"],
        "citations": [],
    }
    # The request reached the grounded function with its parameters intact.
    assert captured == {"question": "What is a wavelet?", "k": 3}
    # The internal raw model output is not exposed by the API.
    assert "raw" not in body


def test_ask_threads_course_and_chapter_to_answer(client, monkeypatch):
    captured = {}

    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        captured["course"] = course
        captured["chapter"] = chapter
        return {"answer": "ok (Course, p.1)", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post(
        "/ask",
        json={
            "student_id": "s1",
            "question": "What is X?",
            "course": "Algebra",
            "chapter": "Ch.2",
        },
    )
    assert response.status_code == 200
    # The course/chapter filter reached the grounded function as kwargs.
    assert captured == {"course": "Algebra", "chapter": "Ch.2"}


def test_ask_defaults_course_and_chapter_to_none(client, monkeypatch):
    captured = {}

    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        captured["course"] = course
        captured["chapter"] = chapter
        return {"answer": "ok", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post("/ask", json={"student_id": "s1", "question": "anything"})
    assert response.status_code == 200
    # Backward compatible: omitting the filter searches the whole collection.
    assert captured == {"course": None, "chapter": None}


def test_ask_uses_default_k(client, monkeypatch):
    captured = {}

    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        captured["k"] = k
        return {"answer": "ok", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post("/ask", json={"student_id": "s1", "question": "anything"})
    assert response.status_code == 200
    assert captured["k"] == 5


def test_ask_surfaces_refusal(client, monkeypatch):
    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        return {
            "answer": "This is not covered in the course material.",
            "refused": True,
            "sources": [],
            "raw": "This is not covered in the course material.",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    response = client.post("/ask", json={"student_id": "s1", "question": "off-topic"})
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["sources"] == []


def test_ask_persists_user_and_assistant_messages(client, monkeypatch):
    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        return {
            "answer": "Grounded reply (Course, p.3)",
            "refused": False,
            "sources": ["(Course, p.3)"],
            "raw": "Grounded reply [1]",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "alice", "question": "Define X?"})

    history = client.get("/history/alice").json()
    assert [(t["role"], t["content"]) for t in history] == [
        ("user", "Define X?"),
        ("assistant", "Grounded reply (Course, p.3)"),
    ]


def test_history_is_chronological_across_turns(client, monkeypatch):
    counter = {"n": 0}

    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        counter["n"] += 1
        return {
            "answer": f"answer-{counter['n']}",
            "refused": False,
            "sources": [],
            "raw": f"answer-{counter['n']}",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "bob", "question": "first"})
    client.post("/ask", json={"student_id": "bob", "question": "second"})

    history = client.get("/history/bob").json()
    contents = [t["content"] for t in history]
    assert contents == ["first", "answer-1", "second", "answer-2"]
    # created_at is surfaced as an ISO string for each turn.
    assert all(isinstance(t["created_at"], str) for t in history)


def test_history_respects_limit(client, monkeypatch):
    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        return {"answer": "a", "refused": False, "sources": [], "raw": "a"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "carol", "question": "q1"})
    client.post("/ask", json={"student_id": "carol", "question": "q2"})

    # Each /ask writes two rows; limit=2 returns only the most recent two.
    limited = client.get("/history/carol", params={"limit": 2}).json()
    assert [t["content"] for t in limited] == ["q2", "a"]


def test_history_unknown_student_is_empty(client):
    assert client.get("/history/nobody").json() == []


def test_clear_history_removes_all_turns(client, monkeypatch):
    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        return {"answer": "a", "refused": False, "sources": [], "raw": "a"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    client.post("/ask", json={"student_id": "dave", "question": "q1"})
    client.post("/ask", json={"student_id": "dave", "question": "q2"})

    resp = client.delete("/history/dave")
    assert resp.status_code == 200
    # Two /ask calls write two rows each.
    assert resp.json() == {"deleted": 4}
    assert client.get("/history/dave").json() == []


def test_student_get_or_create_reuses_same_student(client, monkeypatch):
    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        return {"answer": "ok", "refused": False, "sources": [], "raw": "ok"}

    monkeypatch.setattr(api_main, "answer", fake_answer)

    # Two asks for the same external id must accumulate into one history,
    # proving the student is reused rather than duplicated.
    client.post("/ask", json={"student_id": "dave", "question": "one"})
    client.post("/ask", json={"student_id": "dave", "question": "two"})

    history = client.get("/history/dave").json()
    user_turns = [t["content"] for t in history if t["role"] == "user"]
    assert user_turns == ["one", "two"]


def test_exercise_returns_problem_without_solution(client, monkeypatch):
    captured = {}

    def fake_generate(state):
        captured["message"] = state["message"]
        captured["state"] = state
        return {
            "exercise": {"problem": "Compute X.", "solution": "X = 42.", "refused": False},
            "retrieved": ["(Course, p.7)"],
        }

    monkeypatch.setattr(api_main, "generate", fake_generate)

    response = client.post(
        "/exercise",
        json={
            "student_id": "s1",
            "notion": "integrals",
            "course": "Algebra",
            "chapter": "Ch.2",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"problem": "Compute X.", "refused": False, "id": None}
    assert captured["message"] == "integrals"
    # The student id is threaded to the node so it can persist the exercise.
    assert captured["state"]["student_id"] == "s1"
    # The course/chapter scope is threaded into the node's state for retrieval.
    assert captured["state"]["course"] == "Algebra"
    assert captured["state"]["chapter"] == "Ch.2"
    # The reference solution must never leak to the client.
    assert "solution" not in body


def test_exercise_surfaces_refusal(client, monkeypatch):
    def fake_generate(state):
        return {
            "exercise": {
                "problem": "This is not covered in the course material.",
                "solution": "",
                "refused": True,
            },
            "retrieved": [],
        }

    monkeypatch.setattr(api_main, "generate", fake_generate)

    response = client.post("/exercise", json={"student_id": "s1", "notion": "off-topic"})
    assert response.status_code == 200
    assert response.json()["refused"] is True


def test_exercise_does_not_write_to_history(client, monkeypatch):
    # Exercises are persisted by the agent node, not by the API: /exercise must
    # not create assistant/user Message rows.
    def fake_generate(state):
        return {
            "exercise": {"problem": "Compute X.", "solution": "s", "refused": False},
            "retrieved": [],
        }

    monkeypatch.setattr(api_main, "generate", fake_generate)

    client.post("/exercise", json={"student_id": "erin", "notion": "limits"})
    assert client.get("/history/erin").json() == []


def test_grade_returns_score_and_feedback(client, monkeypatch):
    captured = {}

    def fake_grade(state):
        captured["state"] = state
        return {"grade": {"score": 80, "feedback": "Good method."}}

    monkeypatch.setattr(api_main, "grade", fake_grade)

    response = client.post(
        "/grade",
        json={"student_id": "s1", "message": "X = 42", "exercise": {"solution": "X = 42"}},
    )
    assert response.status_code == 200
    assert response.json() == {"score": 80, "feedback": "Good method."}
    # Both the answer and the optional reference exercise reached the node.
    assert captured["state"]["message"] == "X = 42"
    assert captured["state"]["exercise"] == {"solution": "X = 42"}


def test_grade_without_exercise(client, monkeypatch):
    captured = {}

    def fake_grade(state):
        captured["state"] = state
        return {"grade": {"score": 0, "feedback": "No reference provided."}}

    monkeypatch.setattr(api_main, "grade", fake_grade)

    response = client.post("/grade", json={"student_id": "s1", "message": "X = 42"})
    assert response.status_code == 200
    assert response.json()["feedback"] == "No reference provided."
    # No exercise key is forwarded when the request omits it.
    assert "exercise" not in captured["state"]


def test_grade_does_not_write_to_history(client, monkeypatch):
    def fake_grade(state):
        return {"grade": {"score": 50, "feedback": "ok"}}

    monkeypatch.setattr(api_main, "grade", fake_grade)

    client.post("/grade", json={"student_id": "frank", "message": "answer"})
    assert client.get("/history/frank").json() == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/ask", {}),
        ("/ask", {"question": "no student"}),
        ("/ask", {"student_id": "s1"}),
        ("/exercise", {}),
        ("/exercise", {"notion": "no student"}),
        ("/grade", {}),
        ("/grade", {"message": "no student"}),
    ],
)
def test_missing_required_field_is_422(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422


# --- /ask/stream (SSE) -------------------------------------------------------


def _parse_sse(text):
    """Parse an SSE body into a list of decoded JSON ``data:`` payloads."""
    import json

    events = []
    for block in text.strip().split("\n\n"):
        data = "".join(
            line[len("data:") :].strip() for line in block.splitlines() if line.startswith("data:")
        )
        if data:
            events.append(json.loads(data))
    return events


def test_ask_stream_streams_tokens_then_sources(client, monkeypatch):
    captured = {}

    def fake_stream_answer(question, *, k=5, course=None, chapter=None, language=None):
        captured["question"] = question
        captured["k"] = k
        yield {"type": "token", "text": "A wavelet "}
        yield {"type": "token", "text": "is X [1]."}
        yield {
            "type": "sources",
            "sources": ["(Course, p.11)"],
            "refused": False,
            "answer": "A wavelet is X (Course, p.11).",
        }

    monkeypatch.setattr(api_main, "stream_answer", fake_stream_answer)

    response = client.post(
        "/ask/stream", json={"student_id": "s1", "question": "What is a wavelet?", "k": 3}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    assert events[0] == {"type": "token", "text": "A wavelet "}
    assert events[1] == {"type": "token", "text": "is X [1]."}
    # The final sources event forwards the server-cleaned assembled answer so
    # the client can replace the raw token buffer with it.
    assert events[-1] == {
        "type": "sources",
        "sources": ["(Course, p.11)"],
        "citations": [],
        "refused": False,
        "answer": "A wavelet is X (Course, p.11).",
    }
    assert captured == {"question": "What is a wavelet?", "k": 3}


def test_ask_stream_persists_history_after_completion(client, monkeypatch):
    def fake_stream_answer(question, *, k=5, course=None, chapter=None, language=None):
        yield {"type": "token", "text": "Grounded reply "}
        yield {"type": "token", "text": "[1]"}
        yield {
            "type": "sources",
            "sources": ["(Course, p.3)"],
            "refused": False,
            "answer": "Grounded reply (Course, p.3)",
        }

    monkeypatch.setattr(api_main, "stream_answer", fake_stream_answer)

    response = client.post("/ask/stream", json={"student_id": "alice", "question": "Define X?"})
    assert response.status_code == 200
    # Drain the stream so the generator's completion (and persistence) runs.
    _ = response.text

    history = client.get("/history/alice").json()
    assert [(t["role"], t["content"]) for t in history] == [
        ("user", "Define X?"),
        ("assistant", "Grounded reply (Course, p.3)"),
    ]


def test_ask_stream_surfaces_refusal(client, monkeypatch):
    refusal = "This is not covered in the course material."

    def fake_stream_answer(question, *, k=5, course=None, chapter=None, language=None):
        yield {"type": "token", "text": refusal}
        yield {"type": "sources", "sources": [], "refused": True, "answer": refusal}

    monkeypatch.setattr(api_main, "stream_answer", fake_stream_answer)

    response = client.post("/ask/stream", json={"student_id": "s1", "question": "off-topic"})
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0] == {"type": "token", "text": refusal}
    assert events[-1] == {
        "type": "sources",
        "sources": [],
        "citations": [],
        "refused": True,
        "answer": refusal,
    }

    # The refusal text is persisted as the assistant turn.
    history = client.get("/history/s1").json()
    assert history[-1]["content"] == refusal


def test_ask_stream_threads_course_and_chapter(client, monkeypatch):
    captured = {}

    def fake_stream_answer(question, *, k=5, course=None, chapter=None, language=None):
        captured["course"] = course
        captured["chapter"] = chapter
        yield {"type": "sources", "sources": [], "refused": False, "answer": "ok"}

    monkeypatch.setattr(api_main, "stream_answer", fake_stream_answer)

    response = client.post(
        "/ask/stream",
        json={
            "student_id": "s1",
            "question": "What is X?",
            "course": "Algebra",
            "chapter": "Ch.2",
        },
    )
    assert response.status_code == 200
    _ = response.text
    assert captured == {"course": "Algebra", "chapter": "Ch.2"}


# --- /reexplain --------------------------------------------------------------


def _seed_conversation(client, monkeypatch, student_id, question="Define X?"):
    """Run one /ask so the student has a prior tutor answer to re-explain."""

    def fake_answer(question, *, k=5, course=None, chapter=None, language=None):
        return {
            "answer": "X is a formal structure (Course, p.3)",
            "refused": False,
            "sources": ["(Course, p.3)"],
            "raw": "X is a formal structure [1]",
        }

    monkeypatch.setattr(api_main, "answer", fake_answer)
    client.post("/ask", json={"student_id": student_id, "question": question})


def test_reexplain_rebuilds_history_and_returns_rephrased(client, monkeypatch):
    _seed_conversation(client, monkeypatch, "rex")

    captured = {}

    def fake_reexplain(state):
        # The node receives the rebuilt conversation history (assistant turns
        # relabelled to ``tutor``) and the requested level.
        captured["state"] = state
        return {"answer": "X is simply a set of rules, in plain words."}

    monkeypatch.setattr(api_main, "reexplain", fake_reexplain)

    response = client.post("/reexplain", json={"student_id": "rex", "level": "beginner"})
    assert response.status_code == 200
    assert response.json() == {"answer": "X is simply a set of rules, in plain words."}

    state = captured["state"]
    assert state["level"] == "beginner"
    # History is rebuilt from the DB with the tutor answer present, so the node
    # has something to rephrase.
    roles = [t["role"] for t in state["history"]]
    assert "tutor" in roles
    contents = [t["content"] for t in state["history"]]
    assert "X is a formal structure (Course, p.3)" in contents


def test_reexplain_persists_assistant_message(client, monkeypatch):
    _seed_conversation(client, monkeypatch, "rex2")
    monkeypatch.setattr(api_main, "reexplain", lambda state: {"answer": "Plainer explanation."})

    client.post("/reexplain", json={"student_id": "rex2", "level": "beginner"})

    history = client.get("/history/rex2").json()
    # The new explanation is appended as an assistant turn after the original.
    assert [(t["role"], t["content"]) for t in history][-1] == (
        "assistant",
        "Plainer explanation.",
    )


def test_reexplain_without_prior_answer_is_graceful(client, monkeypatch):
    # A brand-new student has no prior tutor answer: a friendly message is
    # returned and the node is never invoked (no crash).
    called = {"node": False}

    def fake_reexplain(state):
        called["node"] = True
        return {"answer": "should not happen"}

    monkeypatch.setattr(api_main, "reexplain", fake_reexplain)

    response = client.post("/reexplain", json={"student_id": "newcomer", "level": "beginner"})
    assert response.status_code == 200
    assert "no previous answer" in response.json()["answer"].lower()
    assert called["node"] is False


def test_reexplain_defaults_level_to_beginner(client, monkeypatch):
    _seed_conversation(client, monkeypatch, "rex3")
    captured = {}

    def fake_reexplain(state):
        captured["level"] = state["level"]
        return {"answer": "ok"}

    monkeypatch.setattr(api_main, "reexplain", fake_reexplain)

    response = client.post("/reexplain", json={"student_id": "rex3"})
    assert response.status_code == 200
    assert captured["level"] == "beginner"


def test_reexplain_rejects_invalid_level(client):
    response = client.post("/reexplain", json={"student_id": "s1", "level": "expert"})
    assert response.status_code == 422


# --- End-to-end persistence (real generate/grade nodes, no LLM/network) ------


class _FakeMessage:
    """Minimal stand-in for a chat model reply, exposing ``.content``."""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """A chat model whose ``invoke`` returns a fixed reply, no network."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    def invoke(self, _messages, config=None):
        return _FakeMessage(self._reply)


def _make_retrieved(text: str):
    """Build a single retrieval result so the real nodes do not refuse."""
    from ingestion.schema import Chunk, Retrieved

    chunk = Chunk(id="1", course="Algebra", page=7, text=text, chapter="Ch.2")
    return [Retrieved(chunk=chunk, score=0.9)]


def test_exercise_then_grade_persist_and_link(client, monkeypatch):
    # Exercise the REAL generate/grade nodes end to end: only the LLM and the
    # vector retrieval are mocked, so no OpenAI call and no Qdrant are needed.
    # ``generate`` does ``from retrieval import retrieve`` lazily, so the source
    # module is patched; the nodes import ``get_llm`` at module load.
    monkeypatch.setattr("core.retrieval.retrieve", lambda *a, **k: _make_retrieved("Group axioms."))
    monkeypatch.setattr(
        "agent.nodes.generate.get_llm",
        lambda role="default": _FakeLLM("EXERCISE:\nProve closure.\n\nSOLUTION:\nBy axiom 1."),
    )
    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default": _FakeLLM('{"score": 90, "feedback": "Correct."}'),
    )

    # 1) Generate an exercise. It must be persisted and its id surfaced.
    ex_response = client.post("/exercise", json={"student_id": "zoe", "notion": "groups"})
    assert ex_response.status_code == 200
    ex_body = ex_response.json()
    assert ex_body["refused"] is False
    exercise_id = ex_body["id"]
    assert isinstance(exercise_id, int)

    # The exercise row exists, with its reference solution stored server-side.
    from db.models import Exercise, Grade
    from db.session import get_session

    with get_session(api_main._engine) as session:
        exercise = session.get(Exercise, exercise_id)
        assert exercise is not None
        assert exercise.problem == "Prove closure."
        assert exercise.reference_solution == "By axiom 1."

    # 2) Grade an answer, round-tripping the exercise id back to /grade.
    grade_response = client.post(
        "/grade",
        json={
            "student_id": "zoe",
            "message": "Closure holds by axiom 1.",
            "exercise": {"id": exercise_id, "solution": "By axiom 1."},
        },
    )
    assert grade_response.status_code == 200
    assert grade_response.json() == {"score": 90, "feedback": "Correct."}

    # The grade row exists and links back to the persisted exercise.
    with get_session(api_main._engine) as session:
        grades = list(session.scalars(select(Grade).where(Grade.exercise_id == exercise_id)))
        assert len(grades) == 1
        assert grades[0].exercise_id == exercise_id
        assert grades[0].score == 90


def test_grade_without_exercise_id_is_not_persisted(client, monkeypatch):
    # Without an exercise id to link to, the grade node must not write a row
    # (persist_grade skips), even though the verdict is still returned.
    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default": _FakeLLM('{"score": 10, "feedback": "No reference."}'),
    )

    response = client.post("/grade", json={"student_id": "ivan", "message": "guess"})
    assert response.status_code == 200
    assert response.json()["score"] == 10

    from db.models import Grade
    from db.session import get_session

    with get_session(api_main._engine) as session:
        assert session.scalars(select(Grade)).first() is None


# --- /quiz and /quiz/{id}/grade ----------------------------------------------


def test_quiz_returns_questions_without_solutions(client, monkeypatch):
    captured = {}

    def fake_generate_quiz(notion, n, student_id, *, course=None, chapter=None):
        captured["args"] = (notion, n, student_id)
        captured["scope"] = (course, chapter)
        return {
            "quiz_id": 1,
            "notion": notion,
            "questions": [
                {"id": 10, "problem": "Q1?"},
                {"id": 11, "problem": "Q2?"},
            ],
            "refused": False,
        }

    monkeypatch.setattr(api_main, "generate_quiz", fake_generate_quiz)

    response = client.post(
        "/quiz",
        json={
            "student_id": "s1",
            "notion": "groups",
            "n": 2,
            "course": "Algebra",
            "chapter": "Ch.2",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "quiz_id": 1,
        "notion": "groups",
        "questions": [{"id": 10, "problem": "Q1?"}, {"id": 11, "problem": "Q2?"}],
        "refused": False,
    }
    # The notion, count and student id reached the node.
    assert captured["args"] == ("groups", 2, "s1")
    # The course/chapter scope was threaded through to retrieval.
    assert captured["scope"] == ("Algebra", "Ch.2")
    # No reference solution field is present on any question.
    assert all("solution" not in q for q in body["questions"])


def test_quiz_defaults_question_count(client, monkeypatch):
    captured = {}

    def fake_generate_quiz(notion, n, student_id, *, course=None, chapter=None):
        captured["n"] = n
        return {"quiz_id": 1, "notion": notion, "questions": [], "refused": False}

    monkeypatch.setattr(api_main, "generate_quiz", fake_generate_quiz)

    client.post("/quiz", json={"student_id": "s1", "notion": "groups"})
    assert captured["n"] == 3


def test_quiz_surfaces_refusal(client, monkeypatch):
    monkeypatch.setattr(
        api_main,
        "generate_quiz",
        lambda notion, n, student_id, *, course=None, chapter=None: {
            "quiz_id": None,
            "notion": notion,
            "questions": [],
            "refused": True,
        },
    )

    response = client.post("/quiz", json={"student_id": "s1", "notion": "off-topic"})
    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["questions"] == []


def test_quiz_rejects_out_of_range_count(client):
    response = client.post("/quiz", json={"student_id": "s1", "notion": "n", "n": 0})
    assert response.status_code == 422
    response = client.post("/quiz", json={"student_id": "s1", "notion": "n", "n": 99})
    assert response.status_code == 422


def test_quiz_grade_returns_score_and_feedback(client, monkeypatch):
    captured = {}

    def fake_grade_quiz_answer(quiz_id, question_id, answer, student_id):
        captured["args"] = (quiz_id, question_id, answer, student_id)
        return {"score": 80, "feedback": "Good."}

    monkeypatch.setattr(api_main, "grade_quiz_answer", fake_grade_quiz_answer)

    response = client.post(
        "/quiz/5/grade",
        json={"student_id": "s1", "question_id": 10, "answer": "my answer"},
    )
    assert response.status_code == 200
    assert response.json() == {"score": 80, "feedback": "Good."}
    assert captured["args"] == (5, 10, "my answer", "s1")


def test_quiz_grade_unknown_question_is_404(client, monkeypatch):
    monkeypatch.setattr(
        api_main, "grade_quiz_answer", lambda quiz_id, question_id, answer, student_id: None
    )

    response = client.post(
        "/quiz/5/grade", json={"student_id": "s1", "question_id": 999, "answer": "a"}
    )
    assert response.status_code == 404


def test_quiz_grade_missing_field_is_422(client):
    response = client.post("/quiz/5/grade", json={"student_id": "s1", "answer": "a"})
    assert response.status_code == 422


def test_quiz_then_grade_end_to_end(client, monkeypatch):
    # Exercise the REAL quiz/grade nodes end to end: only the LLM and retrieval
    # are mocked, so no OpenAI call and no Qdrant are needed.
    monkeypatch.setattr("core.retrieval.retrieve", lambda *a, **k: _make_retrieved("Group axioms."))
    monkeypatch.setattr(
        "agent.nodes.quiz.get_llm",
        lambda role="default": _FakeLLM(
            '[{"problem": "Prove closure.", "solution": "By axiom 1."},'
            ' {"problem": "Prove identity.", "solution": "Element e."}]'
        ),
    )
    monkeypatch.setattr(
        "agent.nodes.grade.get_llm",
        lambda role="default": _FakeLLM('{"score": 90, "feedback": "Correct."}'),
    )

    quiz_response = client.post("/quiz", json={"student_id": "zed", "notion": "groups", "n": 2})
    assert quiz_response.status_code == 200
    quiz_body = quiz_response.json()
    assert quiz_body["refused"] is False
    quiz_id = quiz_body["quiz_id"]
    assert isinstance(quiz_id, int)
    question_id = quiz_body["questions"][0]["id"]
    # No reference solution is exposed by the quiz response.
    assert "By axiom 1." not in quiz_response.text

    # The quiz and its questions exist, with reference solutions server-side.
    from db.models import Grade, Quiz, QuizQuestion
    from db.session import get_session

    with get_session(api_main._engine) as session:
        quiz = session.get(Quiz, quiz_id)
        assert quiz is not None
        questions = list(
            session.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))
        )
        assert {q.reference_solution for q in questions} == {"By axiom 1.", "Element e."}

    grade_response = client.post(
        f"/quiz/{quiz_id}/grade",
        json={"student_id": "zed", "question_id": question_id, "answer": "Closure holds."},
    )
    assert grade_response.status_code == 200
    assert grade_response.json() == {"score": 90, "feedback": "Correct."}

    # The grade row links to the quiz question, not an exercise.
    with get_session(api_main._engine) as session:
        grades = list(session.scalars(select(Grade).where(Grade.quiz_question_id == question_id)))
        assert len(grades) == 1
        assert grades[0].exercise_id is None
        assert grades[0].score == 90


# --- API-key authentication --------------------------------------------------

_API_KEY = "secret-key"


def _set_api_key(monkeypatch, key):
    """Override the API key the auth dependency reads, with everything mocked.

    The dependency calls ``get_settings()`` from the ``api.main`` namespace, so
    replacing it there lets us drive the configured key without touching the
    process environment or the lru-cached real settings.
    """
    from core.config import Settings

    settings = Settings(api_key=key)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)


def _stub_nodes(monkeypatch):
    """Mock the grounded function and graph nodes so no LLM or network is hit."""
    monkeypatch.setattr(
        api_main,
        "answer",
        lambda question, *, k=5, course=None, chapter=None, language=None: {
            "answer": "ok",
            "refused": False,
            "sources": [],
            "raw": "ok",
        },
    )

    def _fake_stream_answer(question, *, k=5, course=None, chapter=None, language=None):
        yield {"type": "sources", "sources": [], "refused": False, "answer": "ok"}

    monkeypatch.setattr(api_main, "stream_answer", _fake_stream_answer)
    monkeypatch.setattr(
        api_main,
        "generate",
        lambda state: {
            "exercise": {"problem": "p", "solution": "s", "refused": False},
            "retrieved": [],
        },
    )
    monkeypatch.setattr(
        api_main,
        "grade",
        lambda state: {"grade": {"score": 50, "feedback": "ok"}},
    )
    monkeypatch.setattr(
        api_main,
        "reexplain",
        lambda state: {"answer": "rephrased"},
    )
    monkeypatch.setattr(
        api_main,
        "generate_quiz",
        lambda notion, n, student_id, *, course=None, chapter=None: {
            "quiz_id": 1,
            "notion": notion,
            "questions": [{"id": 1, "problem": "Q?"}],
            "refused": False,
        },
    )
    monkeypatch.setattr(
        api_main,
        "grade_quiz_answer",
        lambda quiz_id, question_id, answer, student_id: {"score": 50, "feedback": "ok"},
    )


def test_health_open_without_api_key(client, monkeypatch):
    # /health stays open even when a key is configured (container healthchecks).
    _set_api_key(monkeypatch, _API_KEY)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/ask", {"student_id": "s1", "question": "q"}),
        ("post", "/ask/stream", {"student_id": "s1", "question": "q"}),
        ("post", "/reexplain", {"student_id": "s1", "level": "beginner"}),
        ("post", "/exercise", {"student_id": "s1", "notion": "n"}),
        ("post", "/grade", {"student_id": "s1", "message": "m"}),
        ("post", "/quiz", {"student_id": "s1", "notion": "n"}),
        ("post", "/quiz/1/grade", {"student_id": "s1", "question_id": 1, "answer": "a"}),
        ("get", "/history/s1", None),
    ],
)
def test_protected_endpoint_rejects_missing_key(client, monkeypatch, method, path, body):
    _set_api_key(monkeypatch, _API_KEY)
    _stub_nodes(monkeypatch)
    response = client.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/ask", {"student_id": "s1", "question": "q"}),
        ("post", "/ask/stream", {"student_id": "s1", "question": "q"}),
        ("post", "/reexplain", {"student_id": "s1", "level": "beginner"}),
        ("post", "/exercise", {"student_id": "s1", "notion": "n"}),
        ("post", "/grade", {"student_id": "s1", "message": "m"}),
        ("post", "/quiz", {"student_id": "s1", "notion": "n"}),
        ("post", "/quiz/1/grade", {"student_id": "s1", "question_id": 1, "answer": "a"}),
        ("get", "/history/s1", None),
    ],
)
def test_protected_endpoint_rejects_wrong_key(client, monkeypatch, method, path, body):
    _set_api_key(monkeypatch, _API_KEY)
    _stub_nodes(monkeypatch)
    response = client.request(method, path, json=body, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/ask", {"student_id": "s1", "question": "q"}),
        ("post", "/ask/stream", {"student_id": "s1", "question": "q"}),
        ("post", "/reexplain", {"student_id": "s1", "level": "beginner"}),
        ("post", "/exercise", {"student_id": "s1", "notion": "n"}),
        ("post", "/grade", {"student_id": "s1", "message": "m"}),
        ("post", "/quiz", {"student_id": "s1", "notion": "n"}),
        ("post", "/quiz/1/grade", {"student_id": "s1", "question_id": 1, "answer": "a"}),
        ("get", "/history/s1", None),
    ],
)
def test_protected_endpoint_accepts_correct_key(client, monkeypatch, method, path, body):
    _set_api_key(monkeypatch, _API_KEY)
    _stub_nodes(monkeypatch)
    response = client.request(method, path, json=body, headers={"X-API-Key": _API_KEY})
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/ask", {"student_id": "s1", "question": "q"}),
        ("post", "/ask/stream", {"student_id": "s1", "question": "q"}),
        ("post", "/reexplain", {"student_id": "s1", "level": "beginner"}),
        ("post", "/exercise", {"student_id": "s1", "notion": "n"}),
        ("post", "/grade", {"student_id": "s1", "message": "m"}),
        ("post", "/quiz", {"student_id": "s1", "notion": "n"}),
        ("post", "/quiz/1/grade", {"student_id": "s1", "question_id": 1, "answer": "a"}),
        ("get", "/history/s1", None),
    ],
)
def test_endpoints_open_when_no_key_configured(client, monkeypatch, method, path, body):
    # Default (empty) key: the API is fully open, no header required.
    _set_api_key(monkeypatch, "")
    _stub_nodes(monkeypatch)
    response = client.request(method, path, json=body)
    assert response.status_code == 200


def test_enqueue_review_makes_notion_due_immediately(client):
    """A notion added via /reviews/enqueue appears at once in /reviews/due."""
    enqueue = client.post("/reviews/enqueue", json={"student_id": "s1", "notion": "wavelets"})
    assert enqueue.status_code == 200
    payload = enqueue.json()
    assert payload["notion"] == "wavelets"
    # No SM-2 step is applied, so the notion is seeded at the defaults.
    assert payload["interval_days"] == 0
    assert payload["ease"] == 2.5

    due = client.get("/reviews/due", params={"student_id": "s1"})
    assert due.status_code == 200
    notions = [item["notion"] for item in due.json()]
    assert "wavelets" in notions


def test_enqueue_review_resets_existing_notion_to_due(client):
    """Enqueuing a previously rated notion resets it so it is due again now."""
    # Rate it well first: this schedules it into the future, off the due list.
    rated = client.post("/reviews", json={"student_id": "s1", "notion": "wavelets", "quality": 5})
    assert rated.status_code == 200
    assert rated.json()["interval_days"] == 1
    before = client.get("/reviews/due", params={"student_id": "s1"})
    assert "wavelets" not in [item["notion"] for item in before.json()]

    # Enqueue resets it back to due-now without duplicating the row.
    enqueue = client.post("/reviews/enqueue", json={"student_id": "s1", "notion": "wavelets"})
    assert enqueue.status_code == 200
    assert enqueue.json()["interval_days"] == 0

    after = client.get("/reviews/due", params={"student_id": "s1"})
    assert "wavelets" in [item["notion"] for item in after.json()]
