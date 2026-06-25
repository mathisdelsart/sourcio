"""explain node: retrieval-augmented, sourced explanation.

Retrieves chunks above the similarity threshold, refuses when nothing is relevant,
and cites sources via remapped indices mapped back to (chapter, page).

This node owns no RAG logic of its own. It delegates to ``answer.answer``, the
single place where retrieval, the similarity threshold, refusal, and
citation-by-construction live, so the grounding guarantees cannot drift.
"""

from agent.state import TutorState


def explain(state: TutorState) -> TutorState:
    """Answer ``state['message']`` from the course and record it in memory."""
    from core.answer import answer

    result = answer(state.get("message", ""))

    history = list(state.get("history", []))
    history.append({"role": "tutor", "intent": "explain", "content": result["answer"]})

    return {
        "answer": result["answer"],
        "retrieved": result["sources"],
        "history": history,
    }
