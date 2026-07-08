"""generate node: produce an exercise and its reference solution.

The reference solution is stored server-side and is never returned by /exercise.
The exercise is grounded in the course: it is built strictly from the chunks
retrieved for the requested topic — a worked problem when the material is
mathematical, or recall / short-answer questions when it is factual or prose.
The node refuses rather than inventing content that is not in the course
(mirroring the permissive refusal contract in ``answer.py``), in two cases: when
nothing is retrieved at all, and when the model — acting as the coverage judge —
decides the retrieved sources are genuinely unrelated to the request. It does
NOT refuse merely because the material is non-mathematical.
"""

from agent.persistence import persist_exercise
from agent.state import TutorState
from core.answer import REFUSAL, _language_instruction
from core.config import get_llm
from core.obs import get_callbacks
from ingestion.schema import format_numbered_sources

# Base instructions; the output-language directive is injected per request by
# ``_system_prompt`` so an exercise follows the UI language, not the source one.
_SYSTEM_HEAD = (
    "You are a course tutor who writes practice exercises on the requested topic "
    "using ONLY the numbered sources below.\n"
    "- Build an exercise as long as the numbered sources contain information "
    "relevant to the request, even partially. The material may be of any kind: a "
    "worked problem when it is mathematical, or recall / short-answer / Q&A "
    "questions when it is factual, biographical or prose. Never refuse merely "
    "because the material is non-mathematical or has no formulas.\n"
    "- You are the judge of coverage. Only if the sources are genuinely unrelated "
    "to the request (a truly off-topic notion — they merely mention it in passing, "
    "or are about a different subject) reply with exactly this sentence and nothing "
    f"else: {REFUSAL}\n"
    "- The refusal sentence stands alone as a complete reply; never invent an "
    "exercise on unrelated material just because some source was retrieved.\n"
    "- Never introduce material that is not in the sources. When the material uses "
    "the course's notation, keep that notation.\n"
    "- Prefer an exercise that tests UNDERSTANDING (applying a concept or method, "
    "reasoning, comparing) over trivia; avoid asking to recall a bare number, "
    "percentage or single table cell verbatim.\n"
    "- Make the exercise SELF-CONTAINED: never refer to 'the source', 'the slide',"
    " 'the figure' or 'the provided code' — restate any needed context inside it.\n"
    "- When the material is mathematical, write mathematics in LaTeX: inline as "
    "$...$ and display as $$...$$.\n"
    "- Then provide a complete reference solution, also grounded in the sources.\n"
)

_SYSTEM_FORMAT = (
    "Format your reply exactly as:\n"
    "EXERCISE:\n<the exercise>\n\nSOLUTION:\n<the reference solution>"
)


def _system_prompt(language: str | None = None) -> str:
    """Assemble the exercise system prompt with the language directive injected."""
    return _SYSTEM_HEAD + _language_instruction(language, subject="the exercise") + _SYSTEM_FORMAT


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
    from core.retrieval import retrieve

    message = state.get("message", "")
    # Scope retrieval to the requested course/chapter when given, so the exercise
    # is built from the right material rather than whatever matched globally.
    course_filter = state.get("course")
    chapter_filter = state.get("chapter")
    # Strictly scope to the requesting student's own material so an exercise is
    # never built from another account's uploads (nor the owner-less legacy corpus).
    api_key = state.get("api_key")
    results = retrieve(
        message,
        course=course_filter,
        chapter=chapter_filter,
        owner=state.get("student_id"),
        api_key=api_key,
    )
    if not results:
        return {
            "exercise": {"problem": REFUSAL, "solution": "", "refused": True},
            "retrieved": [],
        }

    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nNotion: {message}"
    raw = (
        get_llm("generate", api_key=api_key)
        .invoke(
            [("system", _system_prompt(state.get("language"))), ("human", prompt)],
            config={"callbacks": get_callbacks()},
        )
        .content.strip()
    )

    # The model is the coverage judge: when the retrieved sources do not actually
    # cover the requested notion (e.g. the request was scoped to the wrong course,
    # or only matched a chunk mentioning the topic in passing), it emits the exact
    # refusal sentence. Mirror answer.py: detect that and refuse instead of parsing
    # an off-topic exercise out of unrelated material.
    if raw == REFUSAL:
        return {
            "exercise": {"problem": REFUSAL, "solution": "", "refused": True},
            "retrieved": [],
        }

    problem, solution = _split(raw)
    # The notion is the request itself. The explicitly requested course wins as
    # the stored attribution; otherwise fall back to the retrieved chunk's course.
    notion = message
    course = course_filter or results[0].chunk.course
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
