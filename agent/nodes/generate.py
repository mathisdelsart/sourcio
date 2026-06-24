"""generate node: produce an exercise and its reference solution.

The reference solution is stored server-side and is never returned by /exercise.
The exercise is calibrated to the course's own notation. The reference solution
is generated alongside it and stored so the grade node can mark a student's
answer against it later.
"""

from agent.state import TutorState
from config import get_llm

_SYSTEM = (
    "You are a course tutor who writes practice exercises.\n"
    "- Produce one exercise on the requested notion, using the course's notation.\n"
    "- Then provide a complete reference solution.\n"
    "Format your reply exactly as:\n"
    "EXERCISE:\n<the exercise>\n\nSOLUTION:\n<the reference solution>"
)


def _split(raw: str) -> tuple[str, str]:
    """Split the model output into (exercise, reference solution)."""
    marker = "SOLUTION:"
    if marker in raw:
        head, _, tail = raw.partition(marker)
        problem = head.replace("EXERCISE:", "", 1).strip()
        return problem, tail.strip()
    # Fallback: keep the whole text as the exercise, no parsed solution.
    return raw.replace("EXERCISE:", "", 1).strip(), ""


def generate(state: TutorState) -> TutorState:
    """Generate an exercise + reference solution for ``state['message']``."""
    prompt = f"Notion: {state['message']}"
    raw = get_llm("generate").invoke([("system", _SYSTEM), ("human", prompt)]).content.strip()

    problem, solution = _split(raw)
    return {"exercise": {"problem": problem, "solution": solution, "raw": raw}}
