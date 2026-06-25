"""Tests for the grounding guarantees that do not need a model or Qdrant."""

from types import SimpleNamespace

import core.answer as answer_mod
from core.answer import _cited_indices, _remap_citations
from ingestion.chunk import chunk_pages
from ingestion.schema import Chunk, Page, Retrieved


def _retrieved(page: int, score: float = 0.9, text: str = "...") -> Retrieved:
    chunk = Chunk(id=f"id{page}", course="Wavelet Transform", page=page, text=text)
    return Retrieved(chunk=chunk, score=score)


def test_citation_label_without_chapter():
    assert _retrieved(11).citation() == "(Wavelet Transform, p.11)"


def test_remap_replaces_indices_with_real_sources():
    results = [_retrieved(11), _retrieved(12)]
    out = _remap_citations("Defined here [1] and extended there [2].", results)
    assert out == (
        "Defined here (Wavelet Transform, p.11) and extended there (Wavelet Transform, p.12)."
    )


def test_remap_leaves_out_of_range_indices_untouched():
    # The model cannot fabricate a page: an unknown index is left as-is.
    results = [_retrieved(11)]
    assert _remap_citations("Bogus [7]", results) == "Bogus [7]"


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
    fake_llm = SimpleNamespace(invoke=lambda messages: reply)
    monkeypatch.setattr(answer_mod, "get_llm", lambda role: fake_llm)

    out = answer_mod.answer("what is a wavelet?")

    assert out["refused"] is False
    assert out["retrieved"] == [
        "A wavelet is a localized oscillation.",
        "Multiresolution analysis decomposes a signal.",
    ]
    # ``sources`` stays the citation labels, distinct from the chunk texts.
    assert out["sources"] == ["(Wavelet Transform, p.11)"]


def test_answer_retrieved_is_empty_on_refusal(monkeypatch):
    # No retrieval hit -> refusal, and ``retrieved`` is an empty list (shape).
    monkeypatch.setattr(answer_mod, "retrieve", lambda *a, **k: [])
    out = answer_mod.answer("off-topic question")
    assert out["refused"] is True
    assert out["retrieved"] == []


def test_chunk_pages_one_slide_one_chunk_drops_empty():
    pages = [
        Page(course="C", page=1, text="slide one", doc_type="slides"),
        Page(course="C", page=2, text="   ", doc_type="slides"),  # empty -> dropped
        Page(course="C", page=3, text="slide three", doc_type="slides"),
    ]
    chunks = chunk_pages(pages)
    assert [c.page for c in chunks] == [1, 3]
    assert len({c.id for c in chunks}) == 2  # stable, unique ids
