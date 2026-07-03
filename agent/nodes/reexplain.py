"""reexplain node: re-explain the point using conversation history.

When the student did not understand, this node genuinely re-explains the last
tutor answer: different wording, more detail, a fresh angle and an example where
it helps. It reuses the conversation ``history`` instead of running retrieval
again, so the explanation stays anchored to what was already grounded.
"""

from collections.abc import Iterator

from agent.state import Level, TutorState
from core.config import get_llm
from core.obs import get_callbacks

_SYSTEM = (
    "You are a course tutor re-explaining a point the student did not grasp.\n"
    "- Genuinely RE-explain: use different wording from the previous explanation, "
    "not the same sentences.\n"
    "- Go into more detail and take a different angle; add a concrete example or "
    "analogy where it aids understanding.\n"
    "- Stay grounded in the facts of the previous explanation: do not introduce "
    "facts it does not support.\n"
    "- Keep any source citations exactly as they appear.\n"
    "- Reply in the same language as the previous explanation.\n"
    "- Output ONLY the re-explanation itself: no preamble such as 'Let me "
    "rephrase…', and no closing remark about what you did or how you rephrased it."
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
        # Skip malformed turns (e.g. a plain string) so iteration never crashes.
        if isinstance(turn, dict) and turn.get("role") == "tutor":
            return turn.get("content", "")
    return state.get("answer", "")


def _messages(state: TutorState) -> list[tuple[str, str]]:
    """Build the (system, human) chat messages for a re-explanation.

    Shared by :func:`reexplain` and :func:`stream_reexplain` so both drive the
    model with the exact same grounded prompt and per-level guidance.
    """
    previous = _previous_explanation(state)
    level: Level = state.get("level") or DEFAULT_LEVEL
    guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE[DEFAULT_LEVEL])
    human = (
        f"Previous explanation:\n{previous}\n\n"
        f"Student says: {state.get('message', '')}\n\n"
        f"Re-explain it. {guidance}"
    )
    return [("system", _SYSTEM), ("human", human)]


def reexplain(state: TutorState) -> TutorState:
    """Reformulate the previous explanation at the requested level."""
    raw = (
        get_llm("reexplain")
        .invoke(_messages(state), config={"callbacks": get_callbacks()})
        .content.strip()
    )

    history = list(state.get("history", []))
    history.append({"role": "tutor", "intent": "reexplain", "content": raw})

    return {"answer": raw, "history": history}


def stream_reexplain(state: TutorState) -> Iterator[dict]:
    """Stream a re-explanation token by token, mirroring :func:`reexplain`.

    Uses the same grounded prompt but yields incrementally so a caller can render
    the re-explanation as it types out. Re-explain runs no retrieval (it reuses
    the conversation context), so there is no "reading sources" stage — only
    token deltas followed by a single final event:

    - ``{"type": "token", "text": str}`` for each text delta the model produces.
    - ``{"type": "done", "answer": str}`` as the single final event, carrying the
      fully assembled, stripped re-explanation.
    """
    parts: list[str] = []
    for piece in get_llm("reexplain").stream(
        _messages(state), config={"callbacks": get_callbacks()}
    ):
        delta = piece.content
        if not delta:
            continue
        parts.append(delta)
        yield {"type": "token", "text": delta}
    yield {"type": "done", "answer": "".join(parts).strip()}
