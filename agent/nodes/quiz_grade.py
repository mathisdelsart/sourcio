"""quiz grading: mark stored quiz answers and summarize a finished quiz.

Split from ``agent.nodes.quiz`` (which generates quizzes): here we grade answers
against the server-side reference solutions. ``grade_quiz_answer`` marks one
answer with the shared exercise judge (`agent.nodes.grade`) at the requested
rigor and persists the verdict; ``summarize_quiz`` grades a whole quiz and adds a
short study recommendation. Reference solutions never leave the server.
"""

from __future__ import annotations

from typing import Any

from agent.state import Rigor
from core.llm import get_llm
from core.obs import get_callbacks

# Fallback marking strictness when the caller supplies none. Mirrors the exercise
# grade node's default so quiz and exercise grading behave identically.
DEFAULT_RIGOR: Rigor = "standard"

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
    rigor: Rigor = DEFAULT_RIGOR,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Grade a whole quiz at once and return a final score plus a recommendation.

    ``answers`` is a list of ``{"question_id", "answer"}``. Each answered question
    is graded by reusing :func:`grade_quiz_answer` (so reference solutions stay
    server-side and every verdict is persisted just like one-by-one grading), at
    the requested ``rigor`` — the same marking strictness the exercise judge uses.
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
        verdict = grade_quiz_answer(quiz_id, question_id, answer, student_id, rigor, api_key)
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
        get_llm("grade", api_key=api_key)
        .invoke(
            [("system", _RECOMMEND_SYSTEM), ("human", human)],
            config={"callbacks": get_callbacks()},
        )
        .content.strip()
    )

    return {"total": total, "results": results, "recommendation": recommendation}


def grade_quiz_answer(
    quiz_id: int,
    question_id: int,
    answer: str,
    student_id: str | None,
    rigor: Rigor = DEFAULT_RIGOR,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """Grade ``answer`` against a stored quiz question's reference solution.

    Loads the question's server-side reference solution, scores the answer with
    the existing grade judge at the requested ``rigor``, and persists the verdict
    as a ``Grade`` linked to the question (best-effort). ``rigor`` is threaded
    into the shared grade node, so the exercise judge's per-level guidance
    (``agent.nodes.grade._RIGOR_GUIDANCE``) applies identically here. The
    reference solution never leaves the server.

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

            # Reuse the existing judge node with the stored reference solution,
            # passing the marking strictness so the shared rigor guidance applies.
            verdict = grade(
                {
                    "message": answer,
                    "exercise": {"solution": reference},
                    "rigor": rigor,
                    "api_key": api_key,
                }
            ).get("grade")
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
