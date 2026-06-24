"""generate node: produce an exercise and its reference solution.

The reference solution is stored server-side and is never returned by /exercise.
The exercise is grounded in the course: it is built strictly from chunks
retrieved for the requested notion, using the course's own notation. If nothing
relevant is retrieved, the node refuses rather than inventing content that is
not in the course (mirroring the refusal contract in ``answer.py``).
"""

from agent.persistence import persist_exercise
from agent.state import TutorState
from answer import REFUSAL
from config import get_llm
from ingestion.schema import Retrieved

_SYSTEM = (
    "You are a course tutor who writes practice exercises.\n"
    "- Build one exercise on the requested notion using ONLY the numbered sources below.\n"
    "- Never introduce material that is not in the sources; keep the course's notation.\n"
    "- Then provide a complete reference solution, also grounded in the sources.\n"
    "Format your reply exactly as:\n"
    "EXERCISE:\n<the exercise>\n\nSOLUTION:\n<the reference solution>"
)


def _format_sources(results: list[Retrieved]) -> str:
    return "\n\n".join(f"[{i}] {r.chunk.text}" for i, r in enumerate(results, 1))


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
    """Generate a course-grounded exercise + reference solution.

    Retrieves chunks for ``state['message']`` and builds the exercise only from
    them. Returns a refusal when nothing relevant is found. When an exercise is
    produced (not refused) it is persisted for the student via the optional
    persistence layer, which is a no-op without a student or database.
    """
    from retrieval import retrieve

    results = retrieve(state["message"])
    if not results:
        return {
            "exercise": {"problem": REFUSAL, "solution": "", "refused": True},
            "retrieved": [],
        }

    prompt = f"Sources:\n{_format_sources(results)}\n\nNotion: {state['message']}"
    raw = get_llm("generate").invoke([("system", _SYSTEM), ("human", prompt)]).content.strip()

    problem, solution = _split(raw)
    # The notion is the request itself; the course comes from the retrieved
    # chunks so the stored exercise stays attributed to its source course.
    notion = state["message"]
    course = results[0].chunk.course
    exercise_id = persist_exercise(
        state.get("student_id"),
        course=course,
        notion=notion,
        problem=problem,
        reference_solution=solution,
    )
    exercise: dict = {
        "problem": problem,
        "solution": solution,
        "refused": False,
        "course": course,
        "notion": notion,
    }
    # Surface the stored id so a later grade can link back to this exercise.
    if exercise_id is not None:
        exercise["id"] = exercise_id
    return {
        "exercise": exercise,
        "retrieved": [r.citation() for r in results],
    }
