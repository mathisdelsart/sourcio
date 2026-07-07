"""Grounded answer with citation-by-construction.

The model only ever sees numbered sources [1] [2] [3] and is told to cite those
indices. It never handles page numbers, so it cannot invent one: the code maps
each [n] back to its real source label. If retrieval finds nothing relevant,
the question is refused rather than answered from the model's own knowledge.
"""

import re
from collections.abc import Iterator

from core.config import get_llm, get_settings
from core.obs import get_callbacks, timer
from core.retrieval import retrieve, retrieve_multi
from ingestion.schema import Retrieved, format_numbered_sources

REFUSAL = "This is not covered in the course material."

# Locale codes the UI sends, mapped to the language name used in the prompt.
_LANGUAGE_NAMES = {"en": "English", "fr": "French", "nl": "Dutch"}


def _language_instruction(language: str | None, *, subject: str = "the answer") -> str:
    """Build the output-language directive for a grounding system prompt.

    ``subject`` names what must be written ("the answer", "the exercise", "the
    quiz"), so the same directive is reusable across the answer, exercise and
    quiz prompts. With no explicit ``language`` we keep the original behavior:
    write in the request's own language. With a locale code ('en'/'fr'/'nl') we
    make that language the strong default that overrides the sources' language,
    while still deferring to an explicit request for another language. The
    wording is deliberately forceful so a weak local model does not default to
    the (usually English) source language.
    """
    if language is None:
        return (
            f"- Write {subject} in the same language as the request, unless it "
            "explicitly asks for another language.\n"
        )
    name = _LANGUAGE_NAMES.get(language, "English")
    return (
        f"- Write {subject} in {name}, even if the sources are written in another "
        "language, unless the request explicitly asks for another language. Only "
        "the prose is translated: keep all mathematics, notation and symbols "
        "exactly as they appear in the sources.\n"
    )


def _system_prompt(language: str | None = None) -> str:
    """Assemble the grounding system prompt, with the language directive injected."""
    return (
        "You are a course tutor that answers strictly from the provided sources.\n"
        "- Use only the numbered sources below; never use outside knowledge.\n"
        + _language_instruction(language)
        + "- After each claim, cite the source index it comes from, like [1] or [2].\n"
        "- You are the judge of whether the course covers the question: answer as long "
        "as the numbered sources contain the information needed, even partially. Only "
        "if the sources genuinely do not contain the answer (they merely mention the "
        "topic in passing, or are unrelated), reply with exactly this sentence and "
        f"nothing else: {REFUSAL}\n"
        "- The refusal sentence stands alone as a complete answer: never append it "
        "after a real answer. Once you have answered, do not add it.\n"
        "- Give the answer once: do not repeat it or append a restatement such as "
        "'The complete answer is…'.\n"
        "- State the answer directly. Do not open with an announcing or filler "
        "lead-in such as 'The final answer is', 'La réponse finale est donc' or "
        "'In summary'.\n"
        "- Keep the course's own notation and definitions."
    )


def _strip_trailing_refusal(text: str) -> str:
    """Drop a refusal sentence the model wrongly appended after a real answer.

    The model is told to emit the refusal alone, but occasionally tacks it onto
    the end of a genuine answer. When the text ends with the refusal (optionally
    after a lead-in like 'Réponse :' the model may add), remove it and keep the
    real answer.
    """
    stripped = text.rstrip()
    if stripped.endswith(REFUSAL):
        stripped = stripped[: -len(REFUSAL)].rstrip()
        # Remove a dangling lead-in the model may have left before the refusal.
        stripped = re.sub(r"(?i)\b(r[ée]ponse|answer)\s*:?\s*$", "", stripped).rstrip()
    return stripped


# Filler lead-in lines the model sometimes prepends to its answer despite the
# prompt (e.g. "The final answer is:"). Stripped only when the phrase stands
# alone on its own line (optionally ending with a colon or period), so real
# content is never cut. Covers the three UI locales (en/fr/nl).
_FILLER_LINE = re.compile(
    r"(?im)^\s*(?:the final answer is|here is the final answer|in summary|to summarize|"
    r"la r[ée]ponse finale est(?: donc)?|en r[ée]sum[ée]|pour r[ée]sumer|"
    r"het (?:uiteindelijke |eind)antwoord is|samengevat)\s*[:.]?\s*$"
)


def _strip_filler_lead_ins(text: str) -> str:
    """Drop standalone filler lead-in lines the model may add despite the prompt.

    A defensive complement to the prompt instruction: the model occasionally
    still writes a line such as 'The final answer is:' on its own. Only whole
    lines that are nothing but such a phrase are removed, so answer content is
    left intact.
    """
    kept = [line for line in text.split("\n") if not _FILLER_LINE.match(line)]
    return "\n".join(kept).strip()


def _citations(raw: str, results: list[Retrieved]) -> list[dict]:
    """Structured list of the sources the answer cites: number, chunk id, label.

    ``n`` is the 1-based index exactly as written inline in the answer (``[n]``),
    so a UI can render a numbered legend that matches the markers. The chunk id
    lets a UI resolve each citation to its exact source excerpt via
    ``GET /source/{id}``; the label is the human-readable ``(course, p.n)`` text.
    Entries are ordered by ascending ``n``.
    """
    return [
        {"n": n, "id": results[n - 1].chunk.id, "label": results[n - 1].citation()}
        for n in sorted(_cited_indices(raw, len(results)))
    ]


def _retrieve(question: str, *, k: int, course: str | None, chapter: str | None) -> list[Retrieved]:
    """Dispatch to single-, multi-query or HyDE retrieval based on settings.

    With both ``multi_query`` and ``hyde`` off (the default) this calls
    :func:`retrieve` exactly as before, so the default path is byte-identical.

    Precedence when more than one is enabled: ``multi_query`` wins. Multi-query
    already expands into several sub-queries and fuses them, a different recall
    strategy from embedding a single HyDE probe; rather than nesting the two we
    keep it simple and let multi-query take over. Otherwise, when only ``hyde``
    is set, :func:`retrieve` runs with ``hyde=True``. In every case the
    threshold/refusal and reranker behave identically.
    """
    settings = get_settings()
    if settings.multi_query:
        return retrieve_multi(question, k=k, course=course, chapter=chapter)
    if settings.hyde:
        return retrieve(question, k=k, course=course, chapter=chapter, hyde=True)
    return retrieve(question, k=k, course=course, chapter=chapter)


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
    language: str | None = None,
) -> dict:
    """Answer a question grounded in the course, or refuse if uncovered.

    Returns a dict with the ``answer`` (keeping the model's inline ``[n]``
    markers so a UI can pair them with a numbered source legend), the ``refused``
    flag, the ``sources`` actually cited in the answer (citation labels), the
    ``citations`` (number + chunk id + label, ascending by number), the ``raw``
    model output, and ``retrieved``: the raw text of every retrieved chunk. The
    faithfulness
    judge consumes ``retrieved`` so it can verify support against the actual
    passages, not the citation labels (which carry no content). On refusal
    ``retrieved`` is an empty list, for shape consistency.

    ``course`` and ``chapter`` optionally restrict retrieval to a single course
    (and chapter); when both are None the whole collection is searched.
    ``language`` (a locale code) sets the default answer language; when None the
    model answers in the question's own language.
    """
    with timer("retrieval"):
        results = _retrieve(question, k=k, course=course, chapter=chapter)
    if not results:
        return {
            "answer": REFUSAL,
            "refused": True,
            "sources": [],
            "citations": [],
            "raw": REFUSAL,
            "retrieved": [],
        }

    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nQuestion: {question}"
    with timer("llm"):
        raw = (
            get_llm("explain")
            .invoke(
                [("system", _system_prompt(language)), ("human", prompt)],
                config={"callbacks": get_callbacks()},
            )
            .content.strip()
        )

    if raw == REFUSAL:
        return {
            "answer": REFUSAL,
            "refused": True,
            "sources": [],
            "citations": [],
            "raw": raw,
            "retrieved": [],
        }

    # Guard against the model appending the refusal after a genuine answer, and
    # drop any standalone filler lead-in line it may have added.
    cleaned = _strip_filler_lead_ins(_strip_trailing_refusal(raw))
    # Only list the sources the answer truly relies on, not every retrieved chunk.
    citations = _citations(cleaned, results)
    # Grounding guard (citation-by-construction): a non-refusal answer that cites
    # zero sources is not defensible from the course material, so a weak model may
    # have answered from its own knowledge. Refuse rather than leak an ungrounded
    # answer. A genuine refusal is already returned above (raw == REFUSAL), so this
    # only ever converts a NON-refusal, no-citation answer.
    if not citations:
        return {
            "answer": REFUSAL,
            "refused": True,
            "sources": [],
            "citations": [],
            "raw": raw,
            "retrieved": [],
        }
    return {
        # Keep the inline [n] markers: the UI pairs them with the numbered legend.
        "answer": cleaned,
        "refused": False,
        "sources": [c["label"] for c in citations],
        "citations": citations,
        "raw": raw,
        "retrieved": [r.chunk.text for r in results],
    }


def stream_answer(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
    language: str | None = None,
) -> Iterator[dict]:
    """Stream a grounded answer token by token, mirroring :func:`answer`.

    Runs the same retrieval, threshold/refusal and citation-by-construction
    logic as :func:`answer`, but yields incrementally so a caller can render the
    explanation as it is produced. Each yielded item is a dict tagged by
    ``type``:

    - ``{"type": "token", "text": str}`` for each raw text delta the model
      produces. Deltas carry the model's literal ``[n]`` markers, which the final
      answer keeps so a UI can pair them with a numbered source legend.
    - ``{"type": "sources", "sources": list[str], "citations": list[dict],
      "refused": bool, "answer": str}`` as the single final event. ``answer`` is
      the cleaned text with its ``[n]`` markers preserved (or the refusal),
      ``sources`` are the citation labels the answer actually relies on,
      ``citations`` carries each marker's number + chunk id + label, and
      ``refused`` flags an uncovered question.

    On refusal (no retrieval hit, or the model emitting the exact refusal
    string) the refusal text is streamed as one token, then the final event is
    emitted with ``refused=True`` and no sources.
    """
    # Real progress stages (consumed by the UI): retrieving runs the embedding +
    # vector search; generating starts once sources are found and the model is
    # about to write. These reflect actual work, not a timer.
    yield {"type": "stage", "stage": "retrieving"}
    with timer("retrieval"):
        results = _retrieve(question, k=k, course=course, chapter=chapter)
    if not results:
        yield {"type": "token", "text": REFUSAL}
        yield {
            "type": "sources",
            "sources": [],
            "citations": [],
            "refused": True,
            "answer": REFUSAL,
        }
        return

    yield {"type": "stage", "stage": "reading", "sources": len(results)}
    prompt = f"Sources:\n{format_numbered_sources(results)}\n\nQuestion: {question}"
    parts: list[str] = []
    with timer("llm"):
        for piece in get_llm("explain").stream(
            [("system", _system_prompt(language)), ("human", prompt)],
            config={"callbacks": get_callbacks()},
        ):
            delta = piece.content
            if not delta:
                continue
            parts.append(delta)
            yield {"type": "token", "text": delta}

    raw = "".join(parts).strip()
    if raw == REFUSAL:
        yield {
            "type": "sources",
            "sources": [],
            "citations": [],
            "refused": True,
            "answer": REFUSAL,
        }
        return

    # Tokens were streamed verbatim; the final assembled answer drops a refusal
    # sentence the model may have appended and any standalone filler lead-in,
    # while keeping the inline [n] markers for the numbered legend.
    cleaned = _strip_filler_lead_ins(_strip_trailing_refusal(raw))
    citations = _citations(cleaned, results)
    # Grounding guard (same as answer()): if the assembled answer cites no source
    # yet was not an explicit refusal, it is ungrounded — emit the refusal as the
    # final event so the UI shows the refusal, not the streamed ungrounded text.
    if not citations:
        yield {
            "type": "sources",
            "sources": [],
            "citations": [],
            "refused": True,
            "answer": REFUSAL,
        }
        return
    yield {
        "type": "sources",
        "sources": [c["label"] for c in citations],
        "citations": citations,
        "refused": False,
        "answer": cleaned,
    }
