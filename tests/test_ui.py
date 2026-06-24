"""Unit tests for the pure UI helpers.

These exercise the Streamlit-free rendering logic in ``ui/app.py`` with
synthetic data: no Streamlit import, no model and no Qdrant. They make no API
calls. Tests importing Streamlit itself are guarded with ``importorskip`` so CI
running ``uv sync --group dev`` (without the ``ui`` extra) simply skips them.
"""

from ui.app import (
    format_sources,
    render_answer,
    render_exercise,
    render_grade,
)


def test_format_sources_renders_bullet_list():
    out = format_sources(["(Course, p.11)", "(Course, p.12)"])
    assert out == "- (Course, p.11)\n- (Course, p.12)"


def test_format_sources_handles_no_sources():
    assert format_sources([]) == "_No sources cited._"


def test_render_answer_grounded_includes_body_and_sources():
    result = {
        "answer": "Defined in (Course, p.11).",
        "refused": False,
        "sources": ["(Course, p.11)"],
    }
    out = render_answer(result)
    assert "Defined in (Course, p.11)." in out
    assert "**Sources**" in out
    assert "- (Course, p.11)" in out


def test_render_answer_shows_refusal_clearly():
    result = {
        "answer": "This is not covered in the course material.",
        "refused": True,
        "sources": [],
    }
    out = render_answer(result)
    assert out.startswith("**Refused.**")
    assert "This is not covered in the course material." in out


def test_render_exercise_omits_solution():
    exercise = {
        "problem": "Compute the Fourier transform of f.",
        "solution": "secret reference solution",
        "refused": False,
    }
    out = render_exercise(exercise)
    assert "Compute the Fourier transform of f." in out
    assert "secret reference solution" not in out


def test_render_exercise_shows_refusal():
    exercise = {"problem": "This is not covered in the course material.", "refused": True}
    out = render_exercise(exercise)
    assert out.startswith("**Refused.**")


def test_render_grade_includes_score_and_feedback():
    out = render_grade({"score": 80, "feedback": "Correct method, minor slip."})
    assert "**Score: 80/100**" in out
    assert "Correct method, minor slip." in out


def test_app_module_imports_without_streamlit():
    # The module must be importable without the optional ``ui`` extra; only
    # ``main`` touches Streamlit, and it is never called here.
    import ui.app as app

    assert callable(app.main)
