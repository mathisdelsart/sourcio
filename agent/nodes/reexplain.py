"""reexplain node: rephrase the explanation using conversation history.

When the student did not understand, this node reformulates the last tutor
answer more simply. It reuses the conversation ``history`` instead of running
retrieval again, so the explanation stays anchored to what was already grounded.
"""

from agent.state import Level, TutorState
from config import get_llm

_SYSTEM = (
    "You are a course tutor re-explaining a point the student did not grasp.\n"
    "- Rephrase the previous explanation with the same content.\n"
    "- Do not introduce facts beyond the previous explanation.\n"
    "- Keep any source citations exactly as they appear."
)

# Sensible fallback when the state carries no explicit audience level.
DEFAULT_LEVEL: Level = "beginner"

# Per-level guidance appended to the prompt so the same grounded content is
# re-pitched at the requested audience. Keys mirror the ``Level`` literal.
_LEVEL_GUIDANCE: dict[Level, str] = {
    "beginner": (
        "Explain as to a beginner: use simple, everyday language and concrete "
        "analogies, and avoid jargon."
    ),
    "intermediate": (
        "Explain at an intermediate level: keep the core technical terms but "
        "clarify them, balancing rigour and accessibility."
    ),
    "advanced": (
        "Explain at an advanced level: be precise, formal and concise, using "
        "the proper technical vocabulary."
    ),
}


def _previous_explanation(state: TutorState) -> str:
    """Return the most recent tutor explanation, or the last answer field."""
    for turn in reversed(state.get("history", [])):
        if turn.get("role") == "tutor":
            return turn.get("content", "")
    return state.get("answer", "")


def reexplain(state: TutorState) -> TutorState:
    """Reformulate the previous explanation at the requested level."""
    previous = _previous_explanation(state)
    level: Level = state.get("level") or DEFAULT_LEVEL
    guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE[DEFAULT_LEVEL])
    human = (
        f"Previous explanation:\n{previous}\n\n"
        f"Student says: {state['message']}\n\n"
        f"Re-explain it. {guidance}"
    )
    raw = get_llm("reexplain").invoke([("system", _SYSTEM), ("human", human)]).content.strip()

    history = list(state.get("history", []))
    history.append({"role": "tutor", "intent": "reexplain", "content": raw})

    return {"answer": raw, "history": history}
