"""Tests for the `python -m core.ask` CLI.

The CLI is a documented entry point (README, Makefile `make ask`), and it is the
one consumer of `core.answer.answer` that is not the API. It reads three keys off
the returned dict -- "answer", "raw", "sources" -- so a change to that shape
breaks the CLI silently: nothing else in the suite would notice. That contract is
what is pinned here.

`answer` is monkeypatched, so no LLM, vector store or network is touched. The
point is not to test argparse; it is to test that the CLI still speaks the same
language as the function behind it.
"""

import pytest

import core.ask as ask_cli

_RESULT = {
    "answer": "A piecewise constant approximation is ... (Course, p.4)",
    "raw": "A piecewise constant approximation is ... [1]",
    "sources": ["(Course, p.4)"],
}


@pytest.fixture
def fake_answer(monkeypatch):
    """Stand in for the grounded answer, capturing how the CLI called it."""
    captured = {}

    def _answer(question, *, k=5, **kwargs):
        captured["question"] = question
        captured["k"] = k
        return dict(_RESULT)

    monkeypatch.setattr(ask_cli, "answer", _answer)
    return captured


def _run(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["core.ask", *argv])
    ask_cli.main()


def test_prints_the_answer_and_its_sources(capsys, monkeypatch, fake_answer):
    _run(monkeypatch, "What is a piecewise constant approximation?")

    out = capsys.readouterr().out
    assert _RESULT["answer"] in out
    assert "(Course, p.4)" in out, "a grounded answer must show where it came from"
    # Without --raw, the pre-remapping text with its [1] markers stays hidden.
    assert "[1]" not in out


def test_forwards_the_question_and_k_to_the_grounded_answer(monkeypatch, fake_answer):
    _run(monkeypatch, "What is a wavelet?", "-k", "9")

    assert fake_answer["question"] == "What is a wavelet?"
    assert fake_answer["k"] == 9


def test_raw_flag_also_shows_the_pre_remapping_output(capsys, monkeypatch, fake_answer):
    """--raw is the debugging view: it must show the [n] markers before remapping."""
    _run(monkeypatch, "What is a wavelet?", "--raw")

    out = capsys.readouterr().out
    assert _RESULT["raw"] in out
    assert _RESULT["answer"] in out


def test_a_refusal_with_no_sources_prints_no_empty_sources_header(capsys, monkeypatch, fake_answer):
    """When the tutor refuses, there is nothing to cite -- and no dangling header."""

    def _refuse(question, *, k=5, **kwargs):
        return {"answer": "I don't know based on the course.", "raw": "", "sources": []}

    monkeypatch.setattr(ask_cli, "answer", _refuse)
    _run(monkeypatch, "What is the capital of Mars?")

    out = capsys.readouterr().out
    assert "I don't know based on the course." in out
    assert "Sources:" not in out
