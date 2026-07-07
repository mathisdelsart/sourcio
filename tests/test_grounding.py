"""Tests for the grounding guarantees that do not need a model or Qdrant."""

from types import SimpleNamespace

import core.answer as answer_mod
from core.answer import _citations, _cited_indices, _strip_filler_lead_ins
from ingestion.chunk import chunk_pages
from ingestion.schema import Chunk, Page, Retrieved


def _retrieved(page: int, score: float = 0.9, text: str = "...") -> Retrieved:
    chunk = Chunk(id=f"id{page}", course="Wavelet Transform", page=page, text=text)
    return Retrieved(chunk=chunk, score=score)


def test_citation_label_without_chapter():
    assert _retrieved(11).citation() == "(Wavelet Transform, p.11)"


def test_citations_carry_marker_number_id_and_label_ascending():
    # The legend pairs each inline [n] with its number, chunk id and label,
    # ordered by ascending n even when the answer cites them out of order.
    results = [_retrieved(11), _retrieved(12), _retrieved(13)]
    cites = _citations("First [3] then [1].", results)
    assert cites == [
        {"n": 1, "id": "id11", "label": "(Wavelet Transform, p.11)"},
        {"n": 3, "id": "id13", "label": "(Wavelet Transform, p.13)"},
    ]


def test_cited_indices_returns_only_used_sources_in_order():
    # Two chunks retrieved, but the answer only cites the first one.
    assert _cited_indices("Defined by formula [1].", count=2) == [1]
    # De-duplicates and ignores out-of-range indices.
    assert _cited_indices("[2] then [2] and bogus [9]", count=2) == [2]


def test_answer_includes_retrieved_chunk_texts(monkeypatch):
    # With retrieve and the LLM mocked (no Qdrant, no API), answer() must expose
    # the raw retrieved passages so the faithfulness judge can verify support.
    results = [
        _retrieved(11, text="A wavelet is a localized oscillation."),
        _retrieved(12, text="Multiresolution analysis decomposes a signal."),
    ]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    reply = SimpleNamespace(content="A wavelet is X [1].")
    fake_llm = SimpleNamespace(invoke=lambda messages, config=None: reply)
    monkeypatch.setattr(answer_mod, "get_llm", lambda role: fake_llm)

    out = answer_mod.answer("what is a wavelet?")

    assert out["refused"] is False
    assert out["retrieved"] == [
        "A wavelet is a localized oscillation.",
        "Multiresolution analysis decomposes a signal.",
    ]
    # The answer keeps the inline [n] marker (no remapping) so the UI can pair it
    # with the numbered legend.
    assert out["answer"] == "A wavelet is X [1]."
    # ``sources`` stays the citation labels, distinct from the chunk texts.
    assert out["sources"] == ["(Wavelet Transform, p.11)"]
    assert out["citations"] == [{"n": 1, "id": "id11", "label": "(Wavelet Transform, p.11)"}]


def test_answer_strips_trailing_refusal_appended_after_real_answer(monkeypatch):
    # The model answered, then wrongly tacked the refusal onto the end. The
    # answer must stand and the contradictory refusal line must be removed.
    results = [_retrieved(11, text="A wavelet is a localized oscillation.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    reply = SimpleNamespace(
        content=f"A wavelet is a localized oscillation [1].\n\n{answer_mod.REFUSAL}"
    )
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: SimpleNamespace(invoke=lambda messages, config=None: reply),
    )

    out = answer_mod.answer("what is a wavelet?")

    assert out["refused"] is False
    assert answer_mod.REFUSAL not in out["answer"]
    # The [n] marker is preserved (remapping was removed).
    assert out["answer"] == "A wavelet is a localized oscillation [1]."


def test_strip_filler_lead_ins_removes_standalone_lines():
    # A filler lead-in on its own line is dropped; real content is untouched.
    text = "La réponse finale est donc :\nA wavelet is localized [1]."
    assert _strip_filler_lead_ins(text) == "A wavelet is localized [1]."
    # An English filler line is removed too.
    assert _strip_filler_lead_ins("The final answer is:\nBody [1].") == "Body [1]."
    # A line that merely starts with a filler phrase but carries content stays.
    kept = "In summary the transform is linear [1]."
    assert _strip_filler_lead_ins(kept) == kept


def test_answer_strips_filler_lead_in_line(monkeypatch):
    # The model prepended an announcing line despite the prompt; it is stripped
    # while the real, cited answer is preserved with its [n] marker.
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    reply = SimpleNamespace(content="The final answer is:\nA wavelet is localized [1].")
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: SimpleNamespace(invoke=lambda messages, config=None: reply),
    )

    out = answer_mod.answer("what is a wavelet?")

    assert out["refused"] is False
    assert out["answer"] == "A wavelet is localized [1]."


def test_answer_refuses_when_whole_output_is_refusal(monkeypatch):
    # Retrieval hit, but the model's entire output is exactly the refusal.
    results = [_retrieved(11)]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    reply = SimpleNamespace(content=answer_mod.REFUSAL)
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: SimpleNamespace(invoke=lambda messages, config=None: reply),
    )

    out = answer_mod.answer("uncovered topic")

    assert out["refused"] is True
    assert out["answer"] == answer_mod.REFUSAL


def test_answer_refuses_when_model_answers_without_any_citation(monkeypatch):
    # Retrieval hit, but the model wrote a plausible answer with zero [n] markers
    # (e.g. answered from its own knowledge on an uncovered topic). The grounding
    # guard must convert this into a refusal so no ungrounded answer leaks.
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    reply = SimpleNamespace(content="The Wavelet Transform decomposes a signal into scales.")
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: SimpleNamespace(invoke=lambda messages, config=None: reply),
    )

    out = answer_mod.answer("what is the wavelet transform?")

    assert out["refused"] is True
    assert out["answer"] == answer_mod.REFUSAL
    assert out["citations"] == []
    assert out["sources"] == []
    assert out["retrieved"] == []


def test_answer_keeps_grounded_answer_with_citation(monkeypatch):
    # A citation-bearing answer is unaffected by the grounding guard.
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    reply = SimpleNamespace(content="A wavelet is localized [1].")
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: SimpleNamespace(invoke=lambda messages, config=None: reply),
    )

    out = answer_mod.answer("what is a wavelet?")

    assert out["refused"] is False
    assert out["answer"] == "A wavelet is localized [1]."
    assert out["sources"] == ["(Wavelet Transform, p.11)"]


def test_stream_answer_refuses_when_no_citation(monkeypatch):
    # Streaming path: the model streamed a plausible but uncited answer; the final
    # event must be a refusal so the UI shows the refusal, not the streamed text.
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: _fake_stream_llm(["The Wavelet Transform ", "decomposes a signal."]),
    )

    events = list(answer_mod.stream_answer("what is the wavelet transform?"))
    final = events[-1]

    assert final["type"] == "sources"
    assert final["refused"] is True
    assert final["answer"] == answer_mod.REFUSAL
    assert final["sources"] == []
    assert final["citations"] == []


def test_answer_language_injects_french_instruction(monkeypatch):
    # language='fr' must put the French default-language directive in the prompt.
    captured: list = []
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)

    def _invoke(messages, config=None):
        captured.append(messages)
        return SimpleNamespace(content="Une ondelette est localisée [1].")

    monkeypatch.setattr(answer_mod, "get_llm", lambda role: SimpleNamespace(invoke=_invoke))

    answer_mod.answer("qu'est-ce qu'une ondelette ?", language="fr")

    system_prompt = captured[0][0][1]
    assert "Write the answer in French" in system_prompt
    assert "even if the sources are written in another language" in system_prompt


def test_stream_answer_strips_trailing_refusal(monkeypatch):
    # The streamed final answer must not include a refusal appended after a body.
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    monkeypatch.setattr(
        answer_mod,
        "get_llm",
        lambda role: _fake_stream_llm(["A wavelet is X [1].\n\n", answer_mod.REFUSAL]),
    )

    events = list(answer_mod.stream_answer("what is a wavelet?"))
    final = events[-1]
    assert final["refused"] is False
    assert answer_mod.REFUSAL not in final["answer"]
    assert final["answer"] == "A wavelet is X [1]."


def test_answer_retrieved_is_empty_on_refusal(monkeypatch):
    # No retrieval hit -> refusal, and ``retrieved`` is an empty list (shape).
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: [])
    out = answer_mod.answer("off-topic question")
    assert out["refused"] is True
    assert out["retrieved"] == []


class _FakeChunk:
    """Minimal stand-in for a streamed chat-model chunk, exposing ``.content``."""

    def __init__(self, content: str) -> None:
        self.content = content


def _fake_stream_llm(deltas):
    """Return an object whose ``.stream(messages)`` yields the given deltas."""
    return SimpleNamespace(stream=lambda messages, config=None: (_FakeChunk(d) for d in deltas))


def test_stream_answer_yields_tokens_then_sources(monkeypatch):
    # retrieve and the LLM's .stream() are mocked: no Qdrant, no API call.
    results = [_retrieved(11, text="A wavelet is localized.")]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    monkeypatch.setattr(
        answer_mod, "get_llm", lambda role: _fake_stream_llm(["A wavelet ", "is X ", "[1]."])
    )

    events = list(answer_mod.stream_answer("what is a wavelet?"))

    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert tokens == ["A wavelet ", "is X ", "[1]."]

    final = events[-1]
    assert final["type"] == "sources"
    assert final["refused"] is False
    # The assembled answer keeps its [n] markers; the model only ever emitted [1].
    assert final["answer"] == "A wavelet is X [1]."
    assert final["sources"] == ["(Wavelet Transform, p.11)"]
    assert final["citations"] == [{"n": 1, "id": "id11", "label": "(Wavelet Transform, p.11)"}]


def test_stream_answer_refuses_when_no_retrieval(monkeypatch):
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: [])
    events = list(answer_mod.stream_answer("off-topic"))

    # The first event is the (real) retrieving stage, then the refusal token.
    assert events[0] == {"type": "stage", "stage": "retrieving"}
    assert events[1] == {"type": "token", "text": answer_mod.REFUSAL}
    final = events[-1]
    assert final["type"] == "sources"
    assert final["refused"] is True
    assert final["sources"] == []
    assert final["answer"] == answer_mod.REFUSAL


def test_stream_answer_refuses_when_model_emits_refusal(monkeypatch):
    results = [_retrieved(11)]
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: results)
    monkeypatch.setattr(answer_mod, "get_llm", lambda role: _fake_stream_llm([answer_mod.REFUSAL]))

    events = list(answer_mod.stream_answer("uncovered"))
    final = events[-1]
    assert final["type"] == "sources"
    assert final["refused"] is True
    assert final["sources"] == []


def test_chunk_pages_one_slide_one_chunk_drops_empty():
    pages = [
        Page(course="C", page=1, text="slide one", doc_type="slides"),
        Page(course="C", page=2, text="   ", doc_type="slides"),  # empty -> dropped
        Page(course="C", page=3, text="slide three", doc_type="slides"),
    ]
    chunks = chunk_pages(pages)
    assert [c.page for c in chunks] == [1, 3]
    assert len({c.id for c in chunks}) == 2  # stable, unique ids
