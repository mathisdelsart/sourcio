"""LangGraph graph: intent router and nodes.

The router classifies the intent and dispatches to explain, generate, grade or
reexplain. ``langgraph`` is imported lazily inside ``build_graph`` so the
router, the routing table, and the nodes stay importable (and unit-testable)
without the optional ``agent`` extra installed.
"""

import re
from typing import get_args

from agent.nodes.explain import explain
from agent.nodes.generate import generate
from agent.nodes.grade import grade
from agent.nodes.reexplain import reexplain
from agent.state import Intent, TutorState
from config import get_llm

# Every valid intent label, derived from the Intent type so the two cannot drift.
INTENTS: tuple[str, ...] = get_args(Intent)
DEFAULT_INTENT: Intent = "explain"

# Cheap, deterministic fallback used when the model output is unusable. Order
# matters: a "don't understand / again / rephrase / simpler" signal is the
# strongest re-explain cue, so reexplain is checked before generate and grade
# (otherwise "I don't understand this problem again" would match "problem" and
# mis-route to generate). The catch-all explain stays last.
_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    "reexplain": ("again", "rephrase", "simpler", "don't understand", "do not understand"),
    "generate": ("exercise", "exercice", "practice", "problem", "quiz"),
    "grade": ("grade", "correct", "my answer", "is this right", "evaluate", "mark"),
}


def _contains_cue(text: str, cue: str) -> bool:
    """Match a cue on word boundaries to avoid spurious substring hits."""
    return re.search(rf"\b{re.escape(cue)}\b", text) is not None


_ROUTER_SYSTEM = (
    "You classify a student's message into exactly one intent.\n"
    "Reply with a single word, one of: " + ", ".join(INTENTS) + ".\n"
    "- explain: a question to answer from the course.\n"
    "- generate: a request to create an exercise on a notion.\n"
    "- grade: a request to mark the student's own answer.\n"
    "- reexplain: a request to rephrase the previous explanation."
)


def _keyword_intent(message: str) -> Intent:
    """Deterministic fallback classification based on keywords."""
    text = message.lower()
    for intent, words in _KEYWORDS.items():
        if any(_contains_cue(text, word) for word in words):
            return intent
    return DEFAULT_INTENT


def classify_intent(message: str) -> Intent:
    """Classify a message into one intent label.

    The primary path asks ``get_llm('router')``; any answer outside the known
    labels falls back to a keyword heuristic, so the router never emits an
    invalid route.
    """
    try:
        raw = get_llm("router").invoke([("system", _ROUTER_SYSTEM), ("human", message)]).content
        label = raw.strip().lower()
        if label in INTENTS:
            return label  # type: ignore[return-value]
    except Exception:
        # Any model/transport error degrades gracefully to the heuristic.
        pass
    return _keyword_intent(message)


def router(state: TutorState) -> TutorState:
    """Entry node: write the classified intent into the state."""
    return {"intent": classify_intent(state.get("message", ""))}


def route(state: TutorState) -> Intent:
    """Map the state's intent to the name of the node to run next."""
    intent = state.get("intent", DEFAULT_INTENT)
    return intent if intent in INTENTS else DEFAULT_INTENT


def build_graph():
    """Build and compile the tutor StateGraph.

    entry router -> conditional routing to one node -> END.
    """
    from langgraph.graph import END, StateGraph

    builder = StateGraph(TutorState)
    builder.add_node("router", router)
    builder.add_node("explain", explain)
    builder.add_node("generate", generate)
    builder.add_node("grade", grade)
    builder.add_node("reexplain", reexplain)

    builder.set_entry_point("router")
    builder.add_conditional_edges(
        "router",
        route,
        {intent: intent for intent in INTENTS},
    )
    for intent in INTENTS:
        builder.add_edge(intent, END)

    return builder.compile()
