"""Tests for the routers' error and edge-case branches.

The happy paths live in test_api.py. What is exercised here is what happens when
the LLM call behind an endpoint *fails*, and the "nothing to work with" branches
the client can reach with a perfectly valid request. These are real paths -- a
free-tier provider trips its per-minute budget constantly -- and they were the
untested half of every router.

Two failure shapes matter, and they are handled differently:

* a **capacity** error (the provider SDKs duck-type it with `status_code` 413 or
  429) is translated into a 413 carrying an actionable message, and
* any **other** exception falls through to the global 500 handler, whose body
  must never carry the raw exception text.

Streaming endpoints cannot raise once the response body has begun, so they emit
an SSE `error` event instead. Both are covered.

As in test_api.py, no LLM, vector store or network is touched: the runtime nodes
are monkeypatched and the service is bound to an in-memory SQLite database.
"""

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from api import runtime as api_runtime  # noqa: E402
from api.main import app  # noqa: E402
from api.routers.reexplain import NOTHING_TO_REEXPLAIN  # noqa: E402
from core.errors import (  # noqa: E402
    FREE_TIER_CAPACITY_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    OWN_KEY_CAPACITY_MESSAGE,
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_runtime.configure_engine(engine)
    with TestClient(app) as test_client:
        yield test_client
    api_runtime._engine = None


@pytest.fixture
def failing_client():
    """A client that lets the app return its own 500 instead of re-raising.

    TestClient re-raises unhandled server exceptions by default, which would skip
    the global handler -- exactly the code these tests are here to pin down.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_runtime.configure_engine(engine)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    api_runtime._engine = None


class _CapacityError(Exception):
    """Mimics a provider SDK's "request too large" / "rate limited" error.

    core.errors duck-types on `status_code` rather than importing each SDK's
    exception classes, so this is all a capacity error needs to look like.
    """

    def __init__(self, status_code: int = 429) -> None:
        super().__init__("provider capacity exceeded")
        self.status_code = status_code


def _boom(exc: Exception):
    """Build a node stand-in that raises `exc` whatever it is called with."""

    def _raise(*args, **kwargs):
        raise exc

    return _raise


# Every non-streaming endpoint that sits in front of an LLM call, with the
# runtime node it delegates to and a minimal valid payload. Parametrizing keeps
# the capacity/generic pair honest: a new LLM-backed route that forgets to
# translate its provider errors shows up here as a failure, not as a gap.
_LLM_ROUTES = (
    ("/ask", "answer", {"question": "What is a wavelet?", "student_id": "s1"}),
    ("/exercise", "generate", {"notion": "wavelets", "student_id": "s1"}),
    ("/grade", "grade", {"message": "my answer", "student_id": "s1"}),
    ("/quiz", "generate_quiz", {"notion": "wavelets", "n": 3, "student_id": "s1"}),
)


@pytest.mark.parametrize(("path", "node", "payload"), _LLM_ROUTES)
def test_capacity_error_becomes_413_with_actionable_message(
    client, monkeypatch, path, node, payload
):
    """A provider capacity error is translated, not leaked."""
    monkeypatch.setattr(api_runtime, node, _boom(_CapacityError(429)))

    response = client.post(path, json=payload)

    assert response.status_code == 413
    # The free-tier message is the one that tells the user what to actually do:
    # bring their own key. Without a caller-supplied key, that is the branch.
    assert response.json()["detail"] == FREE_TIER_CAPACITY_MESSAGE


@pytest.mark.parametrize(("path", "node", "payload"), _LLM_ROUTES)
def test_non_capacity_error_becomes_500_without_leaking_the_exception(
    failing_client, monkeypatch, path, node, payload
):
    """Any other failure falls through to the global handler and leaks nothing."""
    monkeypatch.setattr(api_runtime, node, _boom(RuntimeError("qdrant socket exploded")))

    response = failing_client.post(path, json=payload)

    assert response.status_code == 500
    assert "qdrant socket exploded" not in response.text


def test_capacity_error_with_own_key_says_check_your_own_limits(client, monkeypatch):
    """A visitor using their own key gets the 'your key hit its limit' variant.

    The two messages are not interchangeable: telling someone who already added
    a key to "add your own key" is the bug this guards.
    """
    monkeypatch.setattr(api_runtime, "answer", _boom(_CapacityError(413)))

    response = client.post(
        "/ask",
        json={"question": "What is a wavelet?", "student_id": "s1"},
        headers={"X-OpenAI-Key": "sk-visitor-key"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == OWN_KEY_CAPACITY_MESSAGE


def test_quiz_grade_capacity_error_becomes_413(client, monkeypatch):
    """/quiz/grade goes through a different node than /grade."""
    monkeypatch.setattr(api_runtime, "grade_quiz_answer", _boom(_CapacityError(429)))

    response = client.post(
        "/quiz/1/grade",
        json={"question_id": 1, "answer": "42", "student_id": "s1"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == FREE_TIER_CAPACITY_MESSAGE


def test_quiz_grade_non_capacity_error_becomes_500(failing_client, monkeypatch):
    """And a non-capacity failure there still leaks nothing to the client."""
    monkeypatch.setattr(
        api_runtime, "grade_quiz_answer", _boom(RuntimeError("judge prompt blew up"))
    )

    response = failing_client.post(
        "/quiz/1/grade",
        json={"question_id": 1, "answer": "42", "student_id": "s1"},
    )

    assert response.status_code == 500
    assert "judge prompt blew up" not in response.text


# --- /reexplain: the "nothing to re-explain" branches -------------------------
# Re-explaining needs a previous tutor answer. Both the unknown-student case and
# the known-student-with-no-tutor-turn case must answer politely rather than 500.


def test_reexplain_without_any_history_refuses_politely(client, monkeypatch):
    """An unknown student has no prior answer: say so, do not call the LLM."""
    called = False

    def _should_not_run(*args, **kwargs):
        nonlocal called
        called = True
        return {"answer": "should never be produced"}

    monkeypatch.setattr(api_runtime, "reexplain", _should_not_run)

    response = client.post("/reexplain", json={"student_id": "ghost"})

    assert response.status_code == 200
    assert response.json()["answer"] == NOTHING_TO_REEXPLAIN
    assert called is False, "reexplain must not reach the LLM with nothing to re-explain"


def test_reexplain_for_a_known_student_with_no_tutor_turn_refuses_politely(client, monkeypatch):
    """A student who exists but has never been answered has nothing to re-explain.

    Distinct from the unknown-student case above: that one exits on `student is
    None`, this one gets past it and must still be caught by the "no tutor turn
    yet" guard. Creating a session registers the student without producing a
    tutor answer.
    """
    called = False

    def _should_not_run(*args, **kwargs):
        nonlocal called
        called = True
        return {"answer": "should never be produced"}

    monkeypatch.setattr(api_runtime, "reexplain", _should_not_run)
    client.post("/sessions", json={"student_id": "s1"})

    response = client.post("/reexplain", json={"student_id": "s1"})

    assert response.status_code == 200
    assert response.json()["answer"] == NOTHING_TO_REEXPLAIN
    assert called is False


def test_reexplain_stream_for_a_known_student_with_no_tutor_turn_refuses_politely(client):
    """The streaming path duplicates that guard; it must not drift from it."""
    client.post("/sessions", json={"student_id": "s1"})

    response = client.post("/reexplain/stream", json={"student_id": "s1"})

    assert response.status_code == 200
    events = _sse_events(response)
    assert any(NOTHING_TO_REEXPLAIN in str(event.values()) for event in events), events


def test_reexplain_non_capacity_error_becomes_500(failing_client, monkeypatch):
    """A non-capacity failure re-raises into the global handler, leaking nothing."""
    monkeypatch.setattr(
        api_runtime,
        "answer",
        lambda *a, **k: {"answer": "A wavelet is ...", "refused": False, "sources": []},
    )
    failing_client.post("/ask", json={"question": "What is a wavelet?", "student_id": "s1"})

    monkeypatch.setattr(api_runtime, "reexplain", _boom(RuntimeError("model host vanished")))
    response = failing_client.post("/reexplain", json={"student_id": "s1"})

    assert response.status_code == 500
    assert "model host vanished" not in response.text


def test_reexplain_capacity_error_becomes_413(client, monkeypatch):
    """With a real prior answer, a failing re-explain is still translated."""
    monkeypatch.setattr(
        api_runtime,
        "answer",
        lambda *a, **k: {"answer": "A wavelet is ...", "refused": False, "sources": []},
    )
    client.post("/ask", json={"question": "What is a wavelet?", "student_id": "s1"})

    monkeypatch.setattr(api_runtime, "reexplain", _boom(_CapacityError(429)))
    response = client.post("/reexplain", json={"student_id": "s1"})

    assert response.status_code == 413
    assert response.json()["detail"] == FREE_TIER_CAPACITY_MESSAGE


# --- Streaming: errors become SSE events, never exceptions --------------------


def _sse_events(response) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_ask_stream_emits_an_error_event_instead_of_raising(client, monkeypatch):
    """A mid-stream failure is reported in-band and never leaks the raw error."""
    monkeypatch.setattr(api_runtime, "stream_answer", _boom(RuntimeError("socket died")))

    response = client.post(
        "/ask/stream", json={"question": "What is a wavelet?", "student_id": "s1"}
    )

    # The stream itself succeeded; the failure is carried inside it.
    assert response.status_code == 200
    events = _sse_events(response)
    assert events, "the stream must not be silently empty on failure"
    assert events[-1] == {"type": "error", "message": GENERIC_ERROR_MESSAGE}
    assert "socket died" not in response.text


def test_ask_stream_error_event_carries_the_capacity_message(client, monkeypatch):
    """A capacity failure mid-stream still gets the actionable message."""
    monkeypatch.setattr(api_runtime, "stream_answer", _boom(_CapacityError(413)))

    response = client.post(
        "/ask/stream", json={"question": "What is a wavelet?", "student_id": "s1"}
    )

    assert _sse_events(response)[-1] == {
        "type": "error",
        "message": FREE_TIER_CAPACITY_MESSAGE,
    }


def test_reexplain_stream_without_history_refuses_politely(client):
    """The streaming variant has its own no-history guard; it must agree."""
    response = client.post("/reexplain/stream", json={"student_id": "ghost"})

    assert response.status_code == 200
    events = _sse_events(response)
    assert any(NOTHING_TO_REEXPLAIN in str(event.values()) for event in events), events


def test_reexplain_stream_emits_an_error_event(client, monkeypatch):
    """A failing re-explain stream reports in-band rather than raising."""
    monkeypatch.setattr(
        api_runtime,
        "answer",
        lambda *a, **k: {"answer": "A wavelet is ...", "refused": False, "sources": []},
    )
    client.post("/ask", json={"question": "What is a wavelet?", "student_id": "s1"})

    monkeypatch.setattr(api_runtime, "stream_reexplain", _boom(RuntimeError("socket died")))
    response = client.post("/reexplain/stream", json={"student_id": "s1"})

    assert response.status_code == 200
    assert _sse_events(response)[-1] == {"type": "error", "message": GENERIC_ERROR_MESSAGE}
    assert "socket died" not in response.text


# --- Non-LLM edge cases -------------------------------------------------------


def test_ready_returns_503_when_no_engine_is_bound():
    """/ready is the orchestrator's probe: it must fail while the DB is unbound.

    Deliberately does not use the `client` fixture, which binds an engine.
    """
    api_runtime._engine = None
    with TestClient(app) as unbound:
        # The lifespan binds an engine on startup, so clear it again to simulate
        # a process that has not finished wiring up.
        api_runtime._engine = None
        response = unbound.get("/ready")

    assert response.status_code == 503
    assert "not ready" in response.json()["detail"].lower()


def test_delete_history_for_a_thread_the_student_does_not_own_reports_zero(client):
    """Deleting someone else's thread is a no-op, not an error -- and not a leak.

    The student must exist for this to be meaningful: an unknown student would
    bail out one guard earlier and never reach the ownership check.
    """
    client.post("/sessions", json={"student_id": "s1"})

    response = client.request("DELETE", "/history/s1", params={"session_id": 999})

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


def test_delete_documents_scopes_the_purge_to_the_caller(client, monkeypatch):
    """Passing student_id must scope the delete to that owner, never globally.

    A regression here would let one user's purge wipe another's course, so the
    owner argument is asserted explicitly rather than just the returned count.
    """
    captured = {}

    def fake_delete(course, chapter, owner):
        captured["course"] = course
        captured["owner"] = owner
        return 7

    monkeypatch.setattr(api_runtime, "delete_documents", fake_delete)

    response = client.request(
        "DELETE", "/documents", params={"course": "Signals", "student_id": "s1"}
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 7}
    assert captured["owner"] == "s1", "the purge must be scoped to the caller"
