"""quiz node: produce a grounded multi-question quiz and persist it.

A quiz is a set of practice questions on a single notion, each grounded strictly
in the course chunks retrieved for that notion and each carrying its own
reference solution. Reference solutions are stored server-side and are NEVER
returned to the caller. If nothing relevant is retrieved the node refuses rather
than inventing questions that are not in the course, mirroring the refusal
contract in ``generate.py`` and ``answer.py``.

The questions are generated in a single grounded call so they stay distinct and
share the same retrieved sources. Persistence is best-effort and optional: when
no ``student_id`` is given, or no database is configured, the quiz is still
returned (without ids) and nothing is written.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.config import get_llm
from core.obs import get_callbacks
from ingestion.schema import format_numbered_sources

_SYSTEM = (
    "You are a course tutor who writes short practice quizzes.\n"
    "- Build exactly {n} distinct question(s) on the requested notion using ONLY"
    " the numbered sources below.\n"
    "- Never introduce material that is not in the sources; keep the course's"
    " notation.\n"
    "- Make every question SELF-CONTAINED: never refer to 'the source', 'the"
    " slide', 'the figure', 'the provided code' or similar — if the question"
    " needs context (a snippet, a figure's content), restate it inside the"
    " question itself.\n"
    "- Write all mathematics in LaTeX: inline as $...$ and display as $$...$$.\n"
    "- For each question also provide a complete reference solution, grounded in"
    " the sources.\n"
    "Reply with JSON only: a list of objects "
    '[{{"problem": "<question>", "solution": "<reference solution>"}}, ...] '
    "with {n} item(s)."
)


def _parse_questions(raw: str, n: int) -> list[dict[str, str]]:
    """Parse the model output into ``[{"problem", "solution"}, ...]``.

    Tolerates text surrounding the JSON array. Each item is coerced to a
    problem/solution pair; malformed items are skipped. At most ``n`` questions
    are kept so an over-eager model cannot inflate the quiz.
    """
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []

    questions: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        problem = str(item.get("problem", "")).strip()
        solution = str(item.get("solution", "")).strip()
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
) -> dict[str, Any]:
    """Generate a course-grounded quiz of ``n`` questions on ``notion``.

    Retrieves chunks for ``notion`` and builds the questions only from them.
    ``course`` and ``chapter`` optionally scope retrieval to a single course
    (and chapter) so the quiz stays on the requested material; when both are
    None the whole collection is searched. Returns a refusal (``refused=True``,
    empty ``questions``) when nothing relevant is found or the model produces no
    usable question, never inventing content. On success the quiz and its
    questions are persisted (best-effort) and the return exposes problems only —
    reference solutions stay server-side.

    Returns ``{"quiz_id", "notion", "questions": [{"id", "problem"}], "refused"}``.
    """
    from core.retrieval import retrieve

    n = max(1, int(n))
    results = retrieve(notion, course=course, chapter=chapter)
    if not results:
        return {"quiz_id": None, "notion": notion, "questions": [], "refused": True}

    system = _SYSTEM.format(n=n)
    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nNotion: {notion}"
    raw = get_llm("generate").invoke([("system", system), ("human", prompt)]).content.strip()

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


_RECOMMEND_SYSTEM = (
    "You are a supportive tutor writing a short study recommendation for a student"
    " who has just finished a quiz.\n"
    "- Base your advice ONLY on the per-question feedback provided below.\n"
    "- Give concrete, actionable study advice: which topics to revisit and the"
    " recurring gaps to fix (weak vocabulary, missing rigour, calculation slips,"
    " incomplete reasoning).\n"
    "- Write the recommendation in the SAME LANGUAGE as the student's answers.\n"
    "- Keep it to a few sentences of Markdown; do not restate every detail."
)


def summarize_quiz(
    quiz_id: int,
    answers: list[dict[str, Any]],
    student_id: str | None = None,
) -> dict[str, Any]:
    """Grade a whole quiz at once and return a final score plus a recommendation.

    ``answers`` is a list of ``{"question_id", "answer"}``. Each answered question
    is graded by reusing :func:`grade_quiz_answer` (so reference solutions stay
    server-side and every verdict is persisted just like one-by-one grading).
    Items whose question cannot be resolved — unknown id, or one not belonging to
    ``quiz_id`` — are skipped. ``total`` is the average per-question score over the
    graded questions (0 when none could be graded).

    A short study ``recommendation`` is then produced by the grade LLM from all the
    per-question feedback, in the same language as the student's answers. The call
    is skipped (empty recommendation) when nothing could be graded.

    Returns ``{"total", "results": [{"question_id", "score", "feedback"}],
    "recommendation"}``.
    """
    results: list[dict[str, Any]] = []
    scores: list[int] = []
    answer_by_id: dict[int, str] = {}
    for item in answers:
        raw_id = item.get("question_id")
        if raw_id is None:
            continue
        question_id = int(raw_id)
        answer = str(item.get("answer", ""))
        answer_by_id[question_id] = answer
        verdict = grade_quiz_answer(quiz_id, question_id, answer, student_id)
        if verdict is None:
            continue
        results.append(
            {
                "question_id": question_id,
                "score": verdict["score"],
                "feedback": verdict["feedback"],
            }
        )
        scores.append(verdict["score"])

    total = round(sum(scores) / len(scores)) if scores else 0

    if not results:
        return {"total": total, "results": results, "recommendation": ""}

    blocks = [
        f"Question {r['question_id']} — score {r['score']}/100\n"
        f"Student answer: {answer_by_id.get(r['question_id'], '')}\n"
        f"Feedback: {r['feedback']}"
        for r in results
    ]
    human = f"Overall score: {total}/100.\n\n" + "\n\n".join(blocks)
    recommendation = (
        get_llm("grade")
        .invoke(
            [("system", _RECOMMEND_SYSTEM), ("human", human)],
            config={"callbacks": get_callbacks()},
        )
        .content.strip()
    )

    return {"total": total, "results": results, "recommendation": recommendation}


def grade_quiz_answer(
    quiz_id: int, question_id: int, answer: str, student_id: str | None
) -> dict[str, Any] | None:
    """Grade ``answer`` against a stored quiz question's reference solution.

    Loads the question's server-side reference solution, scores the answer with
    the existing grade judge, and persists the verdict as a ``Grade`` linked to
    the question (best-effort). The reference solution never leaves the server.

    Returns ``{"score", "feedback"}``, or ``None`` when the question does not
    exist (or belongs to another quiz), so the API can surface a 404. When no
    database is available the question cannot be resolved and ``None`` is
    returned as well.
    """
    from agent.nodes.grade import grade

    try:
        from db.models import Grade, QuizQuestion
        from db.session import get_or_create_student, get_session
    except Exception:
        return None

    try:
        with get_session() as session:
            question = session.get(QuizQuestion, question_id)
            if question is None or question.quiz_id != quiz_id:
                return None
            reference = question.reference_solution

            # Reuse the existing judge node with the stored reference solution.
            verdict = grade({"message": answer, "exercise": {"solution": reference}}).get("grade")
            assert verdict is not None

            if student_id:
                student = get_or_create_student(session, student_id)
                session.add(
                    Grade(
                        quiz_question_id=question.id,
                        student_id=student.id,
                        answer=answer,
                        score=verdict["score"],
                        feedback=verdict["feedback"],
                    )
                )
            return {"score": verdict["score"], "feedback": verdict["feedback"]}
    except Exception:
        return None
