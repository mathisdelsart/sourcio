"""Grounded answer with citation-by-construction.

The model only ever sees numbered sources [1] [2] [3] and is told to cite those
indices. It never handles page numbers, so it cannot invent one: the code maps
each [n] back to its real source label. If retrieval finds nothing relevant,
the question is refused rather than answered from the model's own knowledge.
"""

import re
from collections.abc import Iterator

from core.config import get_llm
from core.obs import timer
from core.retrieval import retrieve
from ingestion.schema import Retrieved, format_numbered_sources

REFUSAL = "This is not covered in the course material."

_SYSTEM = (
    "You are a course tutor that answers strictly from the provided sources.\n"
    "- Use only the numbered sources below; never use outside knowledge.\n"
    "- After each claim, cite the source index it comes from, like [1] or [2].\n"
    f"- If the sources do not answer the question, reply exactly: {REFUSAL}\n"
    "- Keep the course's own notation and definitions."
)


def _remap_citations(text: str, results: list[Retrieved]) -> str:
    """Replace each [n] the model wrote with the real source label."""

    def repl(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= len(results):
            return results[n - 1].citation()
        return match.group(0)

    return re.sub(r"\[(\d+)\]", repl, text)


def _cited_indices(text: str, count: int) -> list[int]:
    """Return the valid source indices [n] the model actually cited, in order."""
    seen: list[int] = []
    for match in re.finditer(r"\[(\d+)\]", text):
        n = int(match.group(1))
        if 1 <= n <= count and n not in seen:
            seen.append(n)
    return seen


def answer(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
) -> dict:
    """Answer a question grounded in the course, or refuse if uncovered.

    Returns a dict with the remapped ``answer``, the ``refused`` flag, the
    ``sources`` actually cited in the answer (citation labels), the unmapped
    ``raw`` model output (what the LLM literally produced, with [n] markers),
    and ``retrieved``: the raw text of every retrieved chunk. The faithfulness
    judge consumes ``retrieved`` so it can verify support against the actual
    passages, not the citation labels (which carry no content). On refusal
    ``retrieved`` is an empty list, for shape consistency.

    ``course`` and ``chapter`` optionally restrict retrieval to a single course
    (and chapter); when both are None the whole collection is searched.
    """
    with timer("retrieval"):
        results = retrieve(question, k=k, course=course, chapter=chapter)
    if not results:
        return {"answer": REFUSAL, "refused": True, "sources": [], "raw": REFUSAL, "retrieved": []}

    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nQuestion: {question}"
    with timer("llm"):
        raw = get_llm("explain").invoke([("system", _SYSTEM), ("human", prompt)]).content.strip()

    if raw.strip() == REFUSAL:
        return {"answer": REFUSAL, "refused": True, "sources": [], "raw": raw, "retrieved": []}

    # Only list the sources the answer truly relies on, not every retrieved chunk.
    sources = [results[n - 1].citation() for n in _cited_indices(raw, len(results))]
    return {
        "answer": _remap_citations(raw, results),
        "refused": False,
        "sources": sources,
        "raw": raw,
        "retrieved": [r.chunk.text for r in results],
    }


def stream_answer(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
) -> Iterator[dict]:
    """Stream a grounded answer token by token, mirroring :func:`answer`.

    Runs the same retrieval, threshold/refusal and citation-by-construction
    logic as :func:`answer`, but yields incrementally so a caller can render the
    explanation as it is produced. Each yielded item is a dict tagged by
    ``type``:

    - ``{"type": "token", "text": str}`` for each raw text delta the model
      produces. Deltas carry the model's literal ``[n]`` markers; citation
      remapping is applied once, at the end, to the assembled text.
    - ``{"type": "sources", "sources": list[str], "refused": bool,
      "answer": str}`` as the single final event. ``answer`` is the fully
      remapped text (or the refusal), ``sources`` are the citation labels the
      answer actually relies on, and ``refused`` flags an uncovered question.

    On refusal (no retrieval hit, or the model emitting the exact refusal
    string) the refusal text is streamed as one token, then the final event is
    emitted with ``refused=True`` and no sources.
    """
    with timer("retrieval"):
        results = retrieve(question, k=k, course=course, chapter=chapter)
    if not results:
        yield {"type": "token", "text": REFUSAL}
        yield {"type": "sources", "sources": [], "refused": True, "answer": REFUSAL}
        return

    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nQuestion: {question}"
    parts: list[str] = []
    with timer("llm"):
        for piece in get_llm("explain").stream([("system", _SYSTEM), ("human", prompt)]):
            delta = piece.content
            if not delta:
                continue
            parts.append(delta)
            yield {"type": "token", "text": delta}

    raw = "".join(parts).strip()
    if raw == REFUSAL:
        yield {"type": "sources", "sources": [], "refused": True, "answer": REFUSAL}
        return

    sources = [results[n - 1].citation() for n in _cited_indices(raw, len(results))]
    yield {
        "type": "sources",
        "sources": sources,
        "refused": False,
        "answer": _remap_citations(raw, results),
    }
