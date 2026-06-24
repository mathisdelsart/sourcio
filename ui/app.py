"""Streamlit demo UI for the grounded course tutor.

Thin presentation layer over the FastAPI service: it calls the HTTP endpoints
(``/ask``, ``/exercise``, ``/grade``, ``/history``) rather than importing the
library functions directly, so the UI and server share one contract. All
non-Streamlit logic lives in the pure helpers and the ``TutorClient`` wrapper
below so they can be unit-tested without installing the optional ``ui`` extra
and without any real network call.

Run with: ``uv run streamlit run ui/app.py`` (requires ``--extra ui``).
Configure the backend via ``API_BASE_URL`` (default ``http://localhost:8000``).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API_BASE_URL = "http://localhost:8000"


def get_api_base_url() -> str:
    """Return the configured backend base URL, trimming any trailing slash."""
    return os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")


class TutorClient:
    """Typed wrapper over the FastAPI endpoints.

    The HTTP transport is injectable so tests can drive it with a mocked
    ``httpx`` transport instead of a live server.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or get_api_base_url()).rstrip("/")
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def ask(self, student_id: str, question: str, k: int = 5) -> dict[str, Any]:
        """Ask a grounded question and return ``{answer, refused, sources}``."""
        return self._post("/ask", {"student_id": student_id, "question": question, "k": k})

    def exercise(self, student_id: str, notion: str) -> dict[str, Any]:
        """Generate an exercise and return ``{problem, refused}``."""
        return self._post("/exercise", {"student_id": student_id, "notion": notion})

    def grade(
        self, student_id: str, message: str, exercise: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Grade an answer and return ``{score, feedback}``."""
        payload: dict[str, Any] = {"student_id": student_id, "message": message}
        if exercise is not None:
            payload["exercise"] = exercise
        return self._post("/grade", payload)

    def history(self, student_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return the student's recent turns, chronological."""
        response = self._client.get(f"/history/{student_id}", params={"limit": limit})
        response.raise_for_status()
        return response.json()


# --- Pure helpers (no Streamlit import; unit-tested in tests/test_ui.py) -----


def format_sources(sources: list[str]) -> str:
    """Render cited source labels as a Markdown bullet list.

    Returns a friendly note when no source is cited rather than an empty list.
    """
    if not sources:
        return "_No sources cited._"
    return "\n".join(f"- {label}" for label in sources)


def render_answer(result: dict[str, Any]) -> str:
    """Build the Markdown block shown for an ``/ask`` result.

    Surfaces the refusal message clearly when ``refused`` is True; otherwise the
    grounded answer followed by its cited sources.
    """
    if result.get("refused"):
        return f"**Refused.** {result.get('answer', '').strip()}"

    body = (result.get("answer") or "").strip()
    sources = result.get("sources") or []
    return f"{body}\n\n**Sources**\n\n{format_sources(sources)}"


def render_exercise(exercise: dict[str, Any]) -> str:
    """Build the Markdown block shown for a generated exercise.

    The reference solution is intentionally omitted: it is kept server-side and
    used only for grading, never revealed in the exercise view.
    """
    if exercise.get("refused"):
        return f"**Refused.** {exercise.get('problem', '').strip()}"
    return (exercise.get("problem") or "").strip()


def render_grade(grade: dict[str, Any]) -> str:
    """Build the Markdown block shown for a grading verdict."""
    score = grade.get("score", 0)
    feedback = (grade.get("feedback") or "").strip()
    return f"**Score: {score}/100**\n\n{feedback}"


def render_history(history: list[dict[str, Any]]) -> str:
    """Render conversation history as a chronological Markdown transcript.

    Each turn is labelled by role; an empty history yields a friendly note.
    """
    if not history:
        return "_No history yet._"
    lines = []
    for turn in history:
        role = str(turn.get("role", "")).strip().capitalize() or "Unknown"
        content = str(turn.get("content", "")).strip()
        lines.append(f"**{role}:** {content}")
    return "\n\n".join(lines)


# --- Streamlit UI -----------------------------------------------------------


def main() -> None:  # pragma: no cover - thin UI wiring, not unit-tested
    import streamlit as st

    st.set_page_config(page_title="Grounded course tutor", page_icon=":books:")
    st.title("Grounded course tutor")
    st.caption("Answers strictly from your course material, with citations.")

    with st.sidebar:
        st.header("Settings")
        base_url = st.text_input("API base URL", value=get_api_base_url())
        student_id = st.text_input("Student id", value="demo-student")

    client = TutorClient(base_url)

    ask_tab, exercise_tab, grade_tab, history_tab = st.tabs(["Ask", "Exercise", "Grade", "History"])

    with ask_tab:
        question = st.text_area("Question", key="ask_question", height=120)
        k = st.slider("Sources to retrieve", min_value=1, max_value=10, value=5)
        if st.button("Ask", key="ask_button") and question.strip():
            with st.spinner("Retrieving and answering..."):
                result = client.ask(student_id, question, k=k)
            st.markdown(render_answer(result))

    with exercise_tab:
        notion = st.text_input("Notion to practice", key="exercise_notion")
        if st.button("Generate exercise", key="exercise_button") and notion.strip():
            with st.spinner("Building a course-grounded exercise..."):
                out = client.exercise(student_id, notion)
            st.session_state["last_exercise"] = out
            st.markdown(render_exercise(out))

    with grade_tab:
        last = st.session_state.get("last_exercise")
        if last and not last.get("refused"):
            st.markdown(render_exercise(last))
        student_answer = st.text_area("Your answer", key="grade_answer", height=160)
        if st.button("Grade", key="grade_button") and student_answer.strip():
            with st.spinner("Grading your answer..."):
                out = client.grade(student_id, student_answer, exercise=last or None)
            st.markdown(render_grade(out))

    with history_tab:
        if st.button("Refresh history", key="history_button"):
            with st.spinner("Loading history..."):
                turns = client.history(student_id)
            st.markdown(render_history(turns))


if __name__ == "__main__":  # pragma: no cover
    main()
