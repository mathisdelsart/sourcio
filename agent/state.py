"""Shared state for the tutor agent.

A single TypedDict is threaded through the LangGraph graph. The router fills
``intent``; each node reads the keys it needs and writes only its own output
key. Keys are ``total=False`` so a node can return a partial update without
restating the whole state, which is how LangGraph merges node outputs.
"""

from collections.abc import Sequence
from typing import Any, Literal, TypedDict

# The four intents the router can classify a message into. These labels are the
# single source of truth shared by the router prompt and the routing table.
Intent = Literal["explain", "generate", "grade", "reexplain"]

# Audience levels a re-explanation can target. Optional in the state; the
# reexplain node falls back to a sensible default when none is supplied.
Level = Literal["beginner", "intermediate", "advanced"]

# Conversation roles. ``PersistedRole`` is what the relational store records on a
# message; ``NodeRole`` is what the agent nodes read and write in the in-memory
# history. They differ deliberately: a stored ``assistant`` turn is a tutor turn
# from the agent's point of view. ``ROLE_FROM_PERSISTED`` is the single mapping
# bridging the two vocabularies, so the relabelling lives in exactly one place.
PersistedRole = Literal["user", "assistant"]
NodeRole = Literal["user", "tutor"]

ROLE_FROM_PERSISTED: dict[str, NodeRole] = {"user": "user", "assistant": "tutor"}


def to_history(rows: Sequence[Any]) -> list[dict[str, str]]:
    """Map persisted message rows to the history shape the nodes consume.

    Each row only needs ``role`` and ``content`` string attributes (e.g. a
    ``db.models.Message``). Persisted roles (``user`` / ``assistant``) are
    translated to node roles (``user`` / ``tutor``) via ``ROLE_FROM_PERSISTED``
    so the reexplain node can find the last tutor turn; unknown roles pass
    through unchanged. Chronological order is preserved. ``rows`` is typed
    loosely so this stays importable without the optional ``db`` dependency.
    """
    return [
        {"role": ROLE_FROM_PERSISTED.get(row.role, str(row.role)), "content": str(row.content)}
        for row in rows
    ]


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
