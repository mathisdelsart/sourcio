"""Streamlit demo UI for the grounded course tutor.

Thin presentation layer over the FastAPI service: it calls the HTTP endpoints
(``/ask``, ``/reexplain``, ``/exercise``, ``/grade``, ``/history``) rather than
importing the library functions directly, so the UI and server share one
contract. All non-Streamlit logic lives in the pure helpers and the
``TutorClient`` wrapper below so they can be unit-tested without installing the
optional ``ui`` extra and without any real network call.

Run with: ``uv run streamlit run ui/app.py`` (requires ``--extra ui``).
Configure the backend via ``API_BASE_URL`` (default ``http://localhost:8000``).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API_BASE_URL = "http://localhost:8000"

# Audience levels offered by the "re-explain" control, mirroring the agent's
# ``Level`` literal. Kept here so the widget and the helper share one list.
LEVELS = ("beginner", "intermediate", "advanced")

HOW_IT_WORKS = (
    "This tutor answers **only** from your indexed course material. Every claim "
    "is backed by a numbered source, and if a question is not covered the tutor "
    "refuses rather than guessing. Use **Re-explain** to hear the last answer "
    "again at a simpler or more advanced level."
)


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

    def health(self) -> bool:
        """Return True when the backend ``/health`` probe responds OK.

        Any transport or HTTP error is swallowed and reported as ``False`` so the
        sidebar can show a connection indicator without raising.
        """
        try:
            response = self._client.get("/health")
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return response.json().get("status") == "ok"

    def ask(
        self,
        student_id: str,
        question: str,
        k: int = 5,
        *,
        course: str | None = None,
        chapter: str | None = None,
    ) -> dict[str, Any]:
        """Ask a grounded question and return ``{answer, refused, sources}``.

        ``course``/``chapter`` are only sent when set, so the request stays
        backward compatible with the unfiltered whole-collection search.
        """
        payload: dict[str, Any] = {"student_id": student_id, "question": question, "k": k}
        if course:
            payload["course"] = course
        if chapter:
            payload["chapter"] = chapter
        return self._post("/ask", payload)

    def reexplain(self, student_id: str, level: str) -> dict[str, Any]:
        """Rephrase the student's last tutor answer at ``level`` -> ``{answer}``."""
        return self._post("/reexplain", {"student_id": student_id, "level": level})

    def exercise(self, student_id: str, notion: str) -> dict[str, Any]:
        """Generate an exercise and return ``{problem, refused, id}``.

        The ``id`` is the server-side exercise id (``None`` when the exercise was
        refused or not persisted). It must be carried back into ``grade`` so the
        recorded grade links to its exercise.
        """
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


def health_label(ok: bool) -> str:
    """Render the sidebar connection indicator for a health-check result."""
    return "🟢 Connected" if ok else "🔴 Not reachable"


def format_sources(sources: list[str]) -> str:
    """Render cited source labels as a Markdown bullet list.

    Returns a friendly note when no source is cited rather than an empty list.
    """
    if not sources:
        return "_No sources cited._"
    return "\n".join(f"- {label}" for label in sources)


def render_refusal(result: dict[str, Any]) -> str:
    """Render the refusal banner shown when the course does not cover a question.

    Kept distinct so the North-Star "not covered" behaviour stays visible and
    can be surfaced with a dedicated Streamlit warning callout.
    """
    body = (result.get("answer") or "").strip()
    return f"**Not covered in the course.** {body}".strip()


def is_refused(result: dict[str, Any]) -> bool:
    """Return True when an ``/ask`` (or exercise) result was refused."""
    return bool(result.get("refused"))


def render_answer(result: dict[str, Any]) -> str:
    """Build the Markdown block shown for an ``/ask`` result.

    Surfaces the refusal message clearly when ``refused`` is True; otherwise the
    grounded answer followed by its cited sources. LaTeX in the answer body is
    passed through untouched so Streamlit's Markdown renders ``$...$`` math.
    """
    if is_refused(result):
        return render_refusal(result)

    body = (result.get("answer") or "").strip()
    sources = result.get("sources") or []
    return f"{body}\n\n**Sources**\n\n{format_sources(sources)}"


def render_exercise(exercise: dict[str, Any]) -> str:
    """Build the Markdown block shown for a generated exercise.

    The reference solution is intentionally omitted: it is kept server-side and
    used only for grading, never revealed in the exercise view.
    """
    if exercise.get("refused"):
        return render_refusal({"answer": exercise.get("problem", "")})
    return (exercise.get("problem") or "").strip()


def exercise_for_grading(exercise: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build the exercise payload sent to ``/grade`` from a generated exercise.

    Returns ``None`` when there is no usable exercise (missing or refused) so the
    answer is graded on its own. Otherwise the generated exercise dict is passed
    through unchanged, crucially preserving its server-side ``id`` so the grade
    links back to the stored exercise (``persist_grade`` skips without it).
    """
    if not exercise or exercise.get("refused"):
        return None
    return exercise


def grade_score(grade: dict[str, Any]) -> int:
    """Clamp a grading score into the 0..100 range for the progress widget."""
    try:
        score = int(grade.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def render_grade(grade: dict[str, Any]) -> str:
    """Build the Markdown block shown for a grading verdict."""
    score = grade_score(grade)
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
        student_id = st.text_input("Student id", value="demo-student")
        course = st.text_input("Course filter (optional)", value="")
        base_url = st.text_input("API base URL", value=get_api_base_url())
        client = TutorClient(base_url)
        st.markdown(f"**Backend:** {health_label(client.health())}")
        st.divider()
        st.subheader("How it works")
        st.markdown(HOW_IT_WORKS)

    course_filter = course.strip() or None

    ask_tab, exercise_tab, grade_tab, history_tab = st.tabs(["Ask", "Exercise", "Grade", "History"])

    with ask_tab:
        question = st.text_area("Question", key="ask_question", height=120)
        k = st.slider("Sources to retrieve", min_value=1, max_value=10, value=5)
        if st.button("Ask", key="ask_button") and question.strip():
            with st.spinner("Retrieving and answering..."):
                result = client.ask(student_id, question, k=k, course=course_filter)
            st.session_state["last_answer"] = result

        result = st.session_state.get("last_answer")
        if result is not None:
            if is_refused(result):
                st.warning(render_refusal(result))
            else:
                st.markdown((result.get("answer") or "").strip())
                st.markdown("**Sources**")
                st.markdown(format_sources(result.get("sources") or []))

            st.divider()
            st.markdown("**Did not get it? Re-explain at a level:**")
            level = st.radio(
                "Level",
                LEVELS,
                horizontal=True,
                key="reexplain_level",
                label_visibility="collapsed",
            )
            if st.button("Re-explain", key="reexplain_button"):
                with st.spinner("Re-explaining..."):
                    again = client.reexplain(student_id, level)
                st.markdown((again.get("answer") or "").strip())

    with exercise_tab:
        notion = st.text_input("Notion to practice", key="exercise_notion")
        if st.button("Generate exercise", key="exercise_button") and notion.strip():
            with st.spinner("Building a course-grounded exercise..."):
                out = client.exercise(student_id, notion)
            st.session_state["last_exercise"] = out

        ex = st.session_state.get("last_exercise")
        if ex is not None:
            if ex.get("refused"):
                st.warning(render_refusal({"answer": ex.get("problem", "")}))
            else:
                st.markdown(render_exercise(ex))

    with grade_tab:
        last = st.session_state.get("last_exercise")
        gradable = exercise_for_grading(last)
        if gradable is not None:
            st.info(f"Grading against generated exercise #{gradable.get('id', '?')}.")
            st.markdown(render_exercise(last))
        student_answer = st.text_area("Your answer", key="grade_answer", height=160)
        if st.button("Grade", key="grade_button") and student_answer.strip():
            with st.spinner("Grading your answer..."):
                out = client.grade(student_id, student_answer, exercise=gradable)
            st.progress(grade_score(out) / 100.0)
            st.metric("Score", f"{grade_score(out)}/100")
            st.markdown((out.get("feedback") or "").strip())

    with history_tab:
        if st.button("Refresh history", key="history_button"):
            with st.spinner("Loading history..."):
                turns = client.history(student_id)
            for turn in turns:
                role = str(turn.get("role", "user"))
                with st.chat_message("user" if role == "user" else "assistant"):
                    st.markdown((turn.get("content") or "").strip())
            if not turns:
                st.markdown(render_history(turns))


if __name__ == "__main__":  # pragma: no cover
    main()
