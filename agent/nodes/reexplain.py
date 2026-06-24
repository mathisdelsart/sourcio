"""reexplain node: rephrase the explanation using conversation history.

When the student did not understand, this node reformulates the last tutor
answer more simply. It reuses the conversation ``history`` instead of running
retrieval again, so the explanation stays anchored to what was already grounded.
"""

from agent.state import TutorState
from config import get_llm

_SYSTEM = (
    "You are a course tutor re-explaining a point the student did not grasp.\n"
    "- Rephrase the previous explanation more simply, with the same content.\n"
    "- Do not introduce facts beyond the previous explanation.\n"
    "- Keep any source citations exactly as they appear."
)


def _previous_explanation(state: TutorState) -> str:
    """Return the most recent tutor explanation, or the last answer field."""
    for turn in reversed(state.get("history", [])):
        if turn.get("role") == "tutor":
            return turn.get("content", "")
    return state.get("answer", "")


def reexplain(state: TutorState) -> TutorState:
    """Reformulate the previous explanation and append it to memory."""
    previous = _previous_explanation(state)
    human = (
        f"Previous explanation:\n{previous}\n\n"
        f"Student says: {state['message']}\n\nRe-explain it more simply."
    )
    raw = get_llm("reexplain").invoke([("system", _SYSTEM), ("human", human)]).content.strip()

    history = list(state.get("history", []))
    history.append({"role": "tutor", "intent": "reexplain", "content": raw})

    return {"answer": raw, "history": history}
