"""Tests for math-aware extraction. Run without the ingestion extra or any API.

The heuristic and the hybrid router are exercised through pure features and a
stub transcriber. The PDF layer is replaced by a fake `fitz` module injected via
`sys.modules`, so no real PyMuPDF and no vision/API call is ever made.
"""

import sys
import time
import types

import pytest

from ingestion import extract
from ingestion.extract import (
    PageFeatures,
    _strip_code_fence,
    has_math_symbols,
    needs_vision,
)

# --- _strip_code_fence: pure helper ------------------------------------------


def test_strip_code_fence_with_language_tag():
    text = "```markdown\n# Piecewise constant approximation\n$f(x) = c$\n```"
    assert _strip_code_fence(text) == "# Piecewise constant approximation\n$f(x) = c$"


def test_strip_code_fence_without_language_tag():
    text = "```\n# Title\nbody\n```"
    assert _strip_code_fence(text) == "# Title\nbody"


def test_strip_code_fence_with_trailing_content_after_close():
    # Real case: a figure caption follows the closing fence. Both fence lines
    # must go, the inner content and the trailing caption must stay.
    text = (
        "```markdown\n"
        "# Piecewise constant approximation\n"
        "- One fundamental element\n"
        "```\n"
        "[Figure]: A graph showing the piecewise constant approximation"
    )
    expected = (
        "# Piecewise constant approximation\n"
        "- One fundamental element\n"
        "[Figure]: A graph showing the piecewise constant approximation"
    )
    result = _strip_code_fence(text)
    assert result == expected
    assert "```" not in result


def test_strip_code_fence_no_fence_passthrough():
    text = "# Title\nplain markdown content with no fence."
    assert _strip_code_fence(text) == text


def test_strip_code_fence_leaves_inline_backticks_intact():
    text = "Use the `print()` function and a ``` literal somewhere in prose."
    assert _strip_code_fence(text) == text


def test_strip_code_fence_is_idempotent():
    once = _strip_code_fence("```markdown\n# Title\nbody\n```\n[Figure]: caption after fence")
    assert _strip_code_fence(once) == once


# --- Heuristic: needs_vision over synthetic features -------------------------


def test_has_math_symbols_detects_symbols_and_latex():
    assert has_math_symbols(r"the integral $\int_0^1 x\,dx$")
    assert has_math_symbols("energy E = mc^2")
    assert has_math_symbols("α + β ≤ γ")
    assert not has_math_symbols("A plain prose sentence about history.")


def test_needs_vision_when_page_has_images():
    feats = PageFeatures(image_count=2, text_length=5000, has_math_symbols=False)
    assert needs_vision(feats) is True


def test_needs_vision_when_page_has_math_symbols():
    feats = PageFeatures(image_count=0, text_length=5000, has_math_symbols=True)
    assert needs_vision(feats) is True


def test_needs_vision_when_text_too_short():
    feats = PageFeatures(image_count=0, text_length=10, has_math_symbols=False)
    assert needs_vision(feats) is True


def test_plain_text_page_does_not_need_vision():
    feats = PageFeatures(image_count=0, text_length=5000, has_math_symbols=False)
    assert needs_vision(feats) is False


# --- Fake PyMuPDF layer ------------------------------------------------------


class _FakePage:
    def __init__(self, text: str, images: int):
        self._text = text
        self._images = images

    def get_text(self) -> str:
        return self._text

    def get_images(self):
        return [object()] * self._images

    def get_pixmap(self, dpi: int):
        page = self

        class _Pix:
            def tobytes(self, _fmt: str) -> bytes:
                return f"PNG:{page._text[:8]}".encode()

        return _Pix()


class _FakeDoc:
    def __init__(self, pages):
        self._pages = pages
        self.closed = False

    def __iter__(self):
        return iter(self._pages)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_fitz(monkeypatch):
    """Install a fake `fitz` module whose `open` returns a configurable doc."""
    holder: dict[str, _FakeDoc] = {}

    def _open(_path):
        return holder["doc"]

    module = types.ModuleType("fitz")
    module.open = _open
    monkeypatch.setitem(sys.modules, "fitz", module)

    def _set(pages):
        holder["doc"] = _FakeDoc(pages)
        return holder["doc"]

    return _set


# --- Hybrid router: vision vs plain-text per page ----------------------------


def test_hybrid_routes_plain_and_vision_pages(fake_fitz):
    plain = _FakePage("word " * 100, images=0)  # long, no math, no image
    mathy = _FakePage("E = mc^2", images=0)  # math symbols -> vision
    figure = _FakePage("word " * 100, images=1)  # has image -> vision
    fake_fitz([plain, mathy, figure])

    seen: list[str] = []

    def stub(image_uri: str) -> str:
        seen.append(image_uri)
        return "VISION"

    result = extract.extract_pdf("x.pdf", "Course", hybrid=True, transcriber=stub)

    assert [p.page for p in result] == [1, 2, 3]
    # Page 1 is plain text (free, untouched by the stub).
    assert result[0].text == ("word " * 100).strip()
    # Pages 2 and 3 went through the vision stub.
    assert result[1].text == "VISION"
    assert result[2].text == "VISION"
    assert len(seen) == 2


def test_default_mode_sends_every_page_to_vision(fake_fitz):
    pages = [_FakePage("word " * 100, images=0) for _ in range(3)]
    fake_fitz(pages)

    calls = {"n": 0}

    def stub(_image_uri: str) -> str:
        calls["n"] += 1
        return "VISION"

    result = extract.extract_pdf("x.pdf", "Course", transcriber=stub)

    assert [p.page for p in result] == [1, 2, 3]
    assert all(p.text == "VISION" for p in result)
    assert calls["n"] == 3  # hybrid disabled: every page uses vision


# --- Parallel extraction: order preserved, one call per vision page ----------


def test_parallel_preserves_order_and_calls_once_per_page(fake_fitz):
    n = 6
    # Each page rasterizes to a unique data URI (its text is encoded in the PNG),
    # so the stub can echo back a marker tied to that page.
    pages = [_FakePage(f"page-{i}!", images=1) for i in range(n)]
    fake_fitz(pages)

    counts: dict[str, int] = {}
    first_uri: dict[str, str] = {}

    def stub(image_uri: str) -> str:
        counts[image_uri] = counts.get(image_uri, 0) + 1
        # Make the first-submitted job finish last to prove output order is not
        # completion order.
        first_uri.setdefault("v", image_uri)
        if image_uri == first_uri["v"]:
            time.sleep(0.03)
        return image_uri

    result = extract.extract_pdf("x.pdf", "Course", concurrency=4, transcriber=stub)

    # Pages come back strictly in document order regardless of completion order.
    assert [p.page for p in result] == list(range(1, n + 1))
    # Each page's text is the unique URI produced for that page: order is end to end.
    assert len(set(p.text for p in result)) == n
    # Exactly one transcription per vision-selected page.
    assert len(counts) == n
    assert all(c == 1 for c in counts.values())


def test_extract_strips_fence_on_vision_pages_only(fake_fitz):
    mathy = _FakePage("E = mc^2", images=1)  # vision page
    plain = _FakePage("```not code``` " + "word " * 100, images=0)  # plain page
    fake_fitz([mathy, plain])

    def stub(_uri: str) -> str:
        return "```markdown\n# Slide\n$E=mc^2$\n```"

    result = extract.extract_pdf("x.pdf", "Course", hybrid=True, transcriber=stub)

    # Vision page: surrounding fence removed.
    assert result[0].text == "# Slide\n$E=mc^2$"
    # Plain-text page: PyMuPDF output is left exactly as-is, fences and all.
    assert result[1].text == ("```not code``` " + "word " * 100).strip()


def test_max_pages_caps_selection(fake_fitz):
    pages = [_FakePage("E = mc^2", images=0) for _ in range(5)]
    fake_fitz(pages)
    result = extract.extract_pdf("x.pdf", "Course", max_pages=2, transcriber=lambda uri: "V")
    assert [p.page for p in result] == [1, 2]


def test_explicit_pages_override_order(fake_fitz):
    pages = [_FakePage("E = mc^2", images=0) for _ in range(5)]
    fake_fitz(pages)
    result = extract.extract_pdf("x.pdf", "Course", pages=[2, 4], transcriber=lambda uri: "V")
    assert [p.page for p in result] == [2, 4]
