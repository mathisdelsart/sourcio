"""Shared state for the tutor agent.

A single TypedDict is threaded through the LangGraph graph. The router fills
``intent``; each node reads the keys it needs and writes only its own output
key. Keys are ``total=False`` so a node can return a partial update without
restating the whole state, which is how LangGraph merges node outputs.
"""

from typing import Any, Literal, TypedDict

# The four intents the router can classify a message into. These labels are the
# single source of truth shared by the router prompt and the routing table.
Intent = Literal["explain", "generate", "grade", "reexplain"]

# Audience levels a re-explanation can target. Optional in the state; the
# reexplain node falls back to a sensible default when none is supplied.
Level = Literal["beginner", "intermediate", "advanced"]


class TutorState(TypedDict, total=False):
    """State passed between graph nodes."""

    student_id: str
    message: str
    intent: Intent  # explain | generate | grade | reexplain
    level: Level  # optional audience level for re-explanation
    retrieved: list[Any]  # citations/sources backing the last explanation
    answer: str  # grounded explanation (explain / reexplain output)
    exercise: dict[str, Any]  # generated exercise + reference solution
    grade: dict[str, Any]  # score + feedback from the judge
    history: list[Any]  # prior turns, used to keep memory across re-explanations
