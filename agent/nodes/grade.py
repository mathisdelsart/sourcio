"""grade node: LLM-as-a-judge correcting the student's answer.

Compares the student's answer to the reference solution and returns a score plus
a *detailed* correction (what is right, what to fix, and a complete model answer).
Distinct from the system-evaluation judge (faithfulness) under eval/.

This is judge #1 (the product feature). It marks the student's answer, ideally
against the reference solution of a previously generated exercise, and returns a
numeric score together with an actionable, grounded correction.
"""

import json
import re

from agent.persistence import persist_grade
from agent.state import Rigor, TutorState
from core.config import get_llm
from core.obs import get_callbacks

_SYSTEM = (
    "You are a supportive but rigorous tutor correcting a student's answer.\n"
    "- Grade ONLY against what the question actually asked: never penalise "
    "information the question did not request.\n"
    "- If the question asks only for a final value or answer, a correct final "
    "answer earns full (or near-full) credit. Do NOT deduct for missing "
    "derivations, formulas, units, or intermediate steps unless the question "
    "text explicitly asks the student to 'show your work', 'derive', 'explain' "
    "or 'justify'. The reference solution may show extra steps for context; do "
    "not require the student to reproduce them when the question did not ask.\n"
    "- Compare the student's answer to the reference solution when one is given, "
    "and reward any correct method and the course's notation.\n"
    "- Be encouraging, but judge factual correctness, not just coverage: a "
    "statement that is wrong, or that gives one item's property to another "
    "(swapping or confusing two concepts), is an ERROR — say plainly that it is "
    "incorrect and deduct real credit; never soften a wrong statement into 'a bit "
    "vague' or 'could be clearer'. An item the question explicitly asked for that "
    "is missing or left blank earns NO credit for that item.\n"
    "- When the question explicitly asks for several specific items or parts, let "
    "the total score roughly reflect how many the student got RIGHT (correct AND "
    "present) out of those asked, before minor adjustments: about half of them "
    "correct is about half credit, not a passing 70. Do not round generosity up.\n"
    "- Read the student's answer carefully before listing anything to fix. Only "
    "list something under 'What to fix or add' if the student's answer genuinely "
    "gets it wrong or genuinely omits something the question asked for. NEVER "
    "ask for something the answer already contains, and never restate a value or "
    "step the student already gave correctly as if it were an error or an "
    "improvement. A critique that merely repeats the student's own correct work "
    "in different words is not allowed.\n"
    "- For a multiple-choice or multiple-response question, choosing the correct "
    "option(s) IS a correct answer: award the credit and do NOT require a separate "
    "written justification, example or explanation unless the question explicitly "
    "asks for one.\n"
    "- If the answer is fully correct and complete, say so plainly: put a short "
    "confirmation under 'What to fix or add' (e.g. 'Nothing to fix — the answer "
    "is complete and correct.') and award full or near-full credit. Do not "
    "manufacture criticism to look thorough.\n"
    "- Keep your Model answer internally consistent: do not state a relationship "
    "or value one way and then restate it inverted or differently.\n"
    "- Write the whole correction in the SAME LANGUAGE as the student's answer.\n"
    "\n"
    "Reply in EXACTLY this format and nothing else:\n"
    "SCORE: <integer 0-100>\n"
    "---\n"
    "<a detailed correction in Markdown, translating these headings into the "
    "student's language>:\n"
    "**What you got right** — what the answer covers correctly.\n"
    "**What to fix or add** — a point-by-point list of real errors and anything "
    "the question asked for that is missing.\n"
    "**Model answer** — a complete, correct answer grounded in the reference and "
    "the course's notation."
)

# Sensible fallback when the state carries no explicit marking strictness.
DEFAULT_RIGOR: Rigor = "standard"

# Per-rigor guidance appended to the prompt so the same answer is marked at the
# requested strictness. Every level still grades strictly against what the
# question asked and tolerates accessory differences unless strict. Keys mirror
# the ``Rigor`` literal.
_RIGOR_GUIDANCE: dict[Rigor, str] = {
    "lenient": (
        "Grade leniently: award full or near-full credit when the substance is "
        "correct. When the question asks only for a final value, a correct final "
        "value alone earns full credit — do not deduct for missing steps, "
        "formulas or units the question never requested. Ignore typos, ordering, "
        "phrasing and minor numeric rounding that do not change the meaning; "
        "deduct only for content that is genuinely wrong or that the question "
        "asked for and is missing."
    ),
    "standard": (
        "Grade with balance: reward the correct method and substance, note real "
        "errors, and do not penalise unrequested details or trivial slips. When "
        "the question asks only for a final value, a correct final value alone "
        "earns full credit — do not require derivations, formulas, units or "
        "intermediate steps the question did not explicitly ask for."
    ),
    "strict": (
        "Grade strictly: expect exact notation and full completeness of what the "
        "question asked. You may expect the working to be shown, but ONLY when "
        "the question actually asked the student to show, derive, explain or "
        "justify it; if the question asks only for a final value, do not deduct "
        "for steps it never requested. Deduct for imprecision, but still only "
        "for content the question actually required. Give NO benefit of the doubt "
        "on correctness: a wrong or inverted statement scores as wrong, and an "
        "item the question asked for that is missing or blank scores as absent — "
        "award partial credit strictly for what is actually correct and present."
    ),
}

# "SCORE: 60" — requires the colon, so a legacy JSON `"score": 60` (quote before
# the colon) does not match here and instead falls through to the JSON branch.
_SCORE_RE = re.compile(r"score\s*:\s*(-?\d+)", re.IGNORECASE)

# A "**Heading** —" section marker (a bold span followed by a dash). Matched
# regardless of the heading's language so the three sections each begin their
# own paragraph. Any whitespace already before the marker is consumed so the
# rewrite never accumulates blank lines across repeated grading.
_SECTION_RE = re.compile(r"[ \t]*\n?[ \t]*(\*\*[^*\n]+\*\*[ \t]*[—–-])")


def _paragraphize_sections(feedback: str) -> str:
    """Put each ``**Heading** —`` section on its own paragraph.

    Markdown collapses single newlines, so the three bold section headings the
    grader emits would otherwise render run together inline. Insert a blank line
    before each heading (except a leading one) so they render as separate blocks,
    keying on the ``**...** —`` shape rather than the heading text so it works in
    any language.
    """
    spaced = _SECTION_RE.sub(r"\n\n\1", feedback).strip()
    # Collapse any run of 3+ newlines the substitution may have created.
    return re.sub(r"\n{3,}", "\n\n", spaced)


def _clamp(value: object) -> int:
    """Clamp a model-supplied score to the documented 0-100 range."""
    try:
        return max(0, min(100, int(value)))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0


def _parse(raw: str) -> dict:
    """Parse the verdict, preferring the ``SCORE:`` + Markdown format.

    A detailed correction is many lines of Markdown, which models routinely break
    when asked to embed it in a JSON string, so the primary format keeps the score
    on its own line and the correction as free Markdown after a ``---`` divider.
    A legacy ``{"score", "feedback"}`` JSON verdict is still accepted as a
    fallback so older prompts (and the test suite) keep working.
    """
    text = raw.strip()

    score_match = _SCORE_RE.search(text)
    if score_match:
        if "---" in text:
            feedback = text.split("---", 1)[1].strip()
        else:
            feedback = text[score_match.end() :].strip()
        if feedback:
            return {
                "score": _clamp(score_match.group(1)),
                "feedback": _paragraphize_sections(feedback),
            }

    # Fallback: a legacy JSON verdict, tolerating extra surrounding text.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return {
                "score": _clamp(data.get("score", 0)),
                "feedback": str(data.get("feedback", "")).strip(),
            }
        except (ValueError, TypeError):
            pass

    # Unparseable: surface the raw reply as feedback rather than guess a score.
    return {"score": 0, "feedback": text}


def grade(state: TutorState) -> TutorState:
    """Grade ``state['message']`` (the student's answer) and return a verdict.

    When the answer is graded against a stored exercise (``state['exercise']``
    carries its id) the verdict is persisted for the student via the optional
    persistence layer, which is a no-op without a student, exercise or database.
    """
    exercise = state.get("exercise") or {}
    reference = exercise.get("solution", "")
    problem = exercise.get("problem", "")
    message = state.get("message", "")
    rigor: Rigor = state.get("rigor") or DEFAULT_RIGOR
    guidance = _RIGOR_GUIDANCE.get(rigor, _RIGOR_GUIDANCE[DEFAULT_RIGOR])

    # The question is given first so the judge marks against what was actually
    # asked rather than demanding unrequested detail from the reference.
    human = (
        f"Question/Exercise:\n{problem}\n\n"
        f"Reference solution:\n{reference}\n\n"
        f"Student answer:\n{message}\n\n"
        f"{guidance}"
    )
    raw = (
        get_llm("grade", api_key=state.get("api_key"))
        .invoke(
            [("system", _SYSTEM), ("human", human)],
            config={"callbacks": get_callbacks()},
        )
        .content.strip()
    )

    # Keep raw parsing internal; the node returns only the clean verdict.
    verdict = _parse(raw)

    persist_grade(
        state.get("student_id"),
        exercise_id=exercise.get("id"),
        answer=message,
        score=verdict["score"],
        feedback=verdict["feedback"],
    )

    return {"grade": verdict}
