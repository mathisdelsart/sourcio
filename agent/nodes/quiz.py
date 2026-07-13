"""quiz node: produce a grounded multi-question quiz and persist it.

A quiz is a set of practice questions on a single notion, each grounded strictly
in the course chunks retrieved for that notion and each carrying its own
reference solution. Reference solutions are stored server-side and are NEVER
returned to the caller. If nothing relevant is retrieved the node refuses rather
than inventing questions that are not in the course, mirroring the refusal
contract in ``generate.py`` and ``answer.py``.

The questions are generated in a single grounded call so they stay distinct and
share the same retrieved sources. The node also refuses when the model — acting
as the coverage judge — decides the retrieved sources are genuinely unrelated to
the requested notion, so a quiz scoped to the wrong course cannot be answered
from the model's own knowledge. Persistence is best-effort and optional: when
no ``student_id`` is given, or no database is configured, the quiz is still
returned (without ids) and nothing is written.
"""

from __future__ import annotations

import re
from typing import Any

from core.llm import get_llm
from core.prompts import REFUSAL, language_instruction
from ingestion.schema import format_numbered_sources

# Base instructions; the output-language directive is injected per request by
# ``_system_prompt`` so the quiz follows the UI language, not the source one. A
# ``{lang}`` slot sits between the bullets and the format section.
_SYSTEM = (
    "You are a course tutor who writes short practice quizzes on the requested"
    " notion using ONLY the numbered sources below.\n"
    "- Build exactly {n} distinct question(s) grounded in what the numbered sources"
    " actually STATE.\n"
    "- FORMAT and STYLE parts of the request — multiple-choice with N options,"
    " numeric-only, a length limit, 'cover both courses', 'cover every chapter' —"
    " tell you HOW to build the quiz, not WHETHER to refuse. Follow them; never"
    " refuse because of them.\n"
    "- Refuse when the request asks about a subject or a specific concept the"
    " numbered sources do NOT cover: a DIFFERENT subject or field, or a concept,"
    " method or formula they never state (they merely share notation or mention a"
    f" related idea). Then reply with exactly this sentence and nothing else: {REFUSAL}\n"
    "- CRUCIAL: if the request names one subject but the sources are about a"
    " DIFFERENT one (e.g. asked about World War II while the sources are about"
    " linguistics), REFUSE — never silently quiz on the sources' subject instead of"
    " what was asked.\n"
    "- A BROAD request for the course's OWN material ('quiz me on the course', 'the"
    " different aspects of' what the sources are about, 'covering both courses') is"
    " always coverable: build questions across the retrieved sources; do not"
    " refuse.\n"
    "- The refusal sentence stands alone as a complete reply. Never supply a"
    " concept, formula, definition or fact from your own knowledge to fill a gap in"
    " the sources; keep the course's notation.\n"
    "- Prefer questions that test UNDERSTANDING (concepts, methods, why/how,"
    " comparisons, reasoning) over trivia: do NOT ask to recall a bare number,"
    " percentage, date or single table cell verbatim. A good question can be"
    " answered by someone who understood the material, not only by someone who"
    " memorised a figure.\n"
    "- Make every question SELF-CONTAINED: never refer to 'the source', 'the"
    " slide', 'the figure', 'the provided code' or similar — if the question"
    " needs context (a snippet, a figure's content), restate it inside the"
    " question itself.\n"
    "- Unless the request asks for a specific format, VARY the question type: mix"
    " open-ended questions with the occasional single-answer multiple-choice or"
    " multiple-response question. Do NOT make every question multiple-choice.\n"
    "- BUT when the request EXPLICITLY asks for multiple-choice (or"
    " multiple-response) questions with N options, make EVERY question that type:"
    " each MUST list exactly N labelled options (A) B) C) D) …), each on its own"
    " line, and its reference solution MUST name the correct option(s). Do NOT fall"
    " back to open-ended questions in that case.\n"
    "- Keep each question COHERENT with its type. A multiple-choice or"
    " multiple-response question is answered by picking the option(s) — do NOT also"
    " ask the student to 'explain', 'justify', 'give an example' or 'describe how'"
    " in the same question. If you want reasoning or an example, make it an OPEN"
    " question and say so explicitly.\n"
    "- EXACTLY ONE option may be correct (unless the question is explicitly"
    " multiple-response). Every other option MUST be genuinely WRONG. Two options"
    " that are merely written differently but mean the SAME THING are the same"
    " option: an algebraic rearrangement of the correct formula is still the correct"
    " formula, so it cannot be a distractor. Before you commit to the options,"
    " check each one against the correct answer and reject any that is equivalent"
    " to it — a student who picks it would be marked wrong for being right.\n"
    "- When the request asks to cover several chapters or BOTH courses, SPREAD the"
    " questions across them roughly evenly. Do not draw most of them from whichever"
    " source happens to dominate the retrieved material.\n"
    "- When a question offers options, start EACH option on its own line (a line"
    " break before A), so they never run into the question text:\n"
    "  <question stem>\n  A) ...\n  B) ...\n  C) ...\n  D) ...\n"
    "- Write all mathematics in LaTeX: inline as $...$ and display as $$...$$.\n"
    "- For each question also provide a complete reference solution, grounded in"
    " the sources.\n"
    "{lang}"
    # A delimiter format (not JSON) so LaTeX backslashes pass through verbatim: a
    # model emitting $\\gamma$ or \\frac inside a JSON string produces invalid JSON
    # escapes, which used to break parsing and mangle the rendered maths.
    "Format your reply EXACTLY like this and nothing else, for each question"
    " numbered 1 to {n}:\n"
    "### QUESTION 1\n<the question>\n### SOLUTION 1\n<the reference solution>\n"
    "### QUESTION 2\n<the question>\n### SOLUTION 2\n<the reference solution>\n"
    "(continue through question {n}). Keep LaTeX exactly as written."
)


def _system_prompt(n: int, language: str | None) -> str:
    """Assemble the quiz system prompt with the count and language injected."""
    return _SYSTEM.format(n=n, lang=language_instruction(language, subject="the quiz"))


# Marker splitting the ``### QUESTION k`` / ``### SOLUTION k`` blocks. Tolerant of
# missing/extra ``#``, a trailing ``:`` or ``.``, and any surrounding whitespace,
# but the word must stand on its own line so an inline mention never triggers it.
_QUESTION_MARK = re.compile(r"(?im)^[ \t]*#{0,3}[ \t]*QUESTION[ \t]+\d+[ \t]*[:.]?[ \t]*$")
_SOLUTION_MARK = re.compile(r"(?im)^[ \t]*#{0,3}[ \t]*SOLUTION[ \t]+\d+[ \t]*[:.]?[ \t]*$")


def _parse_questions(raw: str, n: int) -> list[dict[str, str]]:
    """Parse the delimiter-formatted reply into ``[{"problem", "solution"}, ...]``.

    Splits on ``### QUESTION k`` / ``### SOLUTION k`` markers (see
    :data:`_QUESTION_MARK`). This format carries LaTeX verbatim, so no JSON
    escaping can corrupt the mathematics. Any preamble before the first question
    marker is ignored; a block with no solution marker keeps an empty solution. At
    most ``n`` questions are kept so an over-eager model cannot inflate the quiz.
    """
    blocks = _QUESTION_MARK.split(raw)[1:]  # drop any preamble before question 1
    questions: list[dict[str, str]] = []
    for block in blocks:
        halves = _SOLUTION_MARK.split(block, maxsplit=1)
        problem = halves[0].strip()
        solution = halves[1].strip() if len(halves) > 1 else ""
        if problem:
            questions.append({"problem": problem, "solution": solution})
        if len(questions) >= n:
            break
    return questions


def _persist_quiz(
    student_external_id: str | None,
    *,
    notion: str,
    questions: list[dict[str, str]],
) -> tuple[int | None, list[int | None]]:
    """Persist a quiz and its questions; return ``(quiz_id, question_ids)``.

    Skips silently when there is no ``student_external_id`` or no database is
    available, returning ``(None, [None, ...])`` so the node works without a
    store. Question ids are returned in question order so the caller can expose
    them without ever exposing the reference solutions.
    """
    skipped: tuple[int | None, list[int | None]] = (None, [None] * len(questions))
    if not student_external_id:
        return skipped

    try:
        from db.models import Quiz, QuizQuestion
        from db.session import get_or_create_student, get_session
    except Exception:
        return skipped

    try:
        with get_session() as session:
            student = get_or_create_student(session, student_external_id)
            quiz = Quiz(student_id=student.id, notion=notion)
            session.add(quiz)
            session.flush()
            question_ids: list[int | None] = []
            for position, q in enumerate(questions):
                row = QuizQuestion(
                    quiz_id=quiz.id,
                    problem=q["problem"],
                    reference_solution=q["solution"],
                    position=position,
                )
                session.add(row)
                session.flush()
                question_ids.append(row.id)
            return quiz.id, question_ids
    except Exception:
        # No engine bound / connection failure: return the quiz unpersisted.
        return skipped


def generate_quiz(
    notion: str,
    n: int,
    student_id: str | None,
    *,
    course: str | None = None,
    chapter: str | None = None,
    language: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate a course-grounded quiz of ``n`` questions on ``notion``.

    Retrieves chunks for ``notion`` and builds the questions only from them.
    ``course`` and ``chapter`` optionally scope retrieval to a single course
    (and chapter) so the quiz stays on the requested material; when both are
    None the whole collection is searched. ``language`` (a locale code) forces
    the quiz's prose into that language regardless of the source language.
    ``api_key`` is an optional per-request OpenAI key: when set, generation runs
    on the visitor's own OpenAI model instead of the free default.
    Returns a refusal (``refused=True``,
    empty ``questions``) when nothing relevant is found or the model produces no
    usable question, never inventing content. On success the quiz and its
    questions are persisted (best-effort) and the return exposes problems only —
    reference solutions stay server-side.

    Returns ``{"quiz_id", "notion", "questions": [{"id", "problem"}], "refused"}``.
    """
    from core.retrieval import retrieve

    n = max(1, int(n))
    # Strictly scope to the requesting student's own material so a quiz is never
    # built from another account's uploads (nor the owner-less legacy corpus).
    results = retrieve(notion, course=course, chapter=chapter, owner=student_id, api_key=api_key)
    if not results:
        return {"quiz_id": None, "notion": notion, "questions": [], "refused": True}

    system = _system_prompt(n, language)
    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nNotion: {notion}"
    raw = (
        get_llm("generate", api_key=api_key)
        .invoke([("system", system), ("human", prompt)])
        .content.strip()
    )

    # The model is the coverage judge: when the retrieved sources do not actually
    # cover the requested notion (e.g. the quiz was scoped to the wrong course, or
    # only matched a chunk mentioning the topic in passing), it emits the exact
    # refusal sentence. Mirror answer.py/generate.py: detect it and refuse rather
    # than fabricating questions from the model's own knowledge. REFUSAL carries no
    # '[' or ']', so it never collides with the JSON-array regex in _parse_questions.
    if raw == REFUSAL:
        return {"quiz_id": None, "notion": notion, "questions": [], "refused": True}

    questions = _parse_questions(raw, n)
    if not questions:
        # The course was retrieved but no usable question came back: refuse
        # rather than surface an empty or fabricated quiz.
        return {"quiz_id": None, "notion": notion, "questions": [], "refused": True}

    quiz_id, question_ids = _persist_quiz(student_id, notion=notion, questions=questions)

    # Expose problems only. Reference solutions are never placed in the return.
    exposed = [
        {"id": qid, "problem": q["problem"]} for qid, q in zip(question_ids, questions, strict=True)
    ]
    return {"quiz_id": quiz_id, "notion": notion, "questions": exposed, "refused": False}
