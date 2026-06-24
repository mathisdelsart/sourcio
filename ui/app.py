"""Streamlit demo UI for the grounded course tutor.

Thin presentation layer over the library functions: ``answer.answer`` for
grounded questions, the ``generate`` node for exercises and the ``grade`` node
for marking. All non-Streamlit logic lives in the pure helpers below so it can
be unit-tested without installing the optional ``ui`` extra.

Run with: ``uv run streamlit run ui/app.py`` (requires ``--extra ui``).
"""

from __future__ import annotations

from typing import Any

# --- Pure helpers (no Streamlit import; unit-tested in tests/test_ui.py) -----


def format_sources(sources: list[str]) -> str:
    """Render cited source labels as a Markdown bullet list.

    Returns a friendly note when no source is cited rather than an empty list.
    """
    if not sources:
        return "_No sources cited._"
    return "\n".join(f"- {label}" for label in sources)


def render_answer(result: dict[str, Any]) -> str:
    """Build the Markdown block shown for an ``answer.answer`` result.

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


# --- Streamlit UI -----------------------------------------------------------


def main() -> None:  # pragma: no cover - thin UI wiring, not unit-tested
    import streamlit as st

    from agent.nodes.generate import generate
    from agent.nodes.grade import grade
    from answer import answer

    st.set_page_config(page_title="Grounded course tutor", page_icon=":books:")
    st.title("Grounded course tutor")
    st.caption("Answers strictly from your course material, with citations.")

    ask_tab, exercise_tab, grade_tab = st.tabs(["Ask", "Exercise", "Grade"])

    with ask_tab:
        question = st.text_area("Question", key="ask_question", height=120)
        k = st.slider("Sources to retrieve", min_value=1, max_value=10, value=5)
        if st.button("Ask", key="ask_button") and question.strip():
            with st.spinner("Retrieving and answering..."):
                result = answer(question, k=k)
            st.markdown(render_answer(result))

    with exercise_tab:
        notion = st.text_input("Notion to practice", key="exercise_notion")
        if st.button("Generate exercise", key="exercise_button") and notion.strip():
            with st.spinner("Building a course-grounded exercise..."):
                out = generate({"message": notion})
            st.session_state["last_exercise"] = out.get("exercise", {})
            st.markdown(render_exercise(st.session_state["last_exercise"]))

    with grade_tab:
        last = st.session_state.get("last_exercise")
        if last and not last.get("refused"):
            st.markdown(render_exercise(last))
        student_answer = st.text_area("Your answer", key="grade_answer", height=160)
        if st.button("Grade", key="grade_button") and student_answer.strip():
            with st.spinner("Grading your answer..."):
                state = {"message": student_answer}
                if last:
                    state["exercise"] = last
                out = grade(state)
            st.markdown(render_grade(out.get("grade", {})))


if __name__ == "__main__":  # pragma: no cover
    main()
