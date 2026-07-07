"""Tests for math-aware extraction. Run without the ingestion extra or any API.

The heuristic and the hybrid router are exercised through pure features and a
stub transcriber. The PDF layer is replaced by a fake `fitz` module injected via
`sys.modules`, so no real PyMuPDF and no vision/API call is ever made.
"""

import base64
import sys
import time
import types

import pytest

from ingestion import extract
from ingestion.extract import (
    PageFeatures,
    _strip_code_fence,
    has_math_symbols,
    is_rate_limit_error,
    needs_vision,
    with_rate_limit_retry,
)


class _FakeRateLimitError(Exception):
    """Stand-in for the OpenAI SDK's RateLimitError, by class name only."""


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


def test_needs_vision_when_image_only_page_has_little_text():
    # An image with little recoverable text is image-based content: needs vision.
    feats = PageFeatures(image_count=2, text_length=10, has_math_symbols=False)
    assert needs_vision(feats) is True


def test_text_rich_page_with_image_does_not_need_vision():
    # A designed but text-heavy page (e.g. a cover letter with a logo) is fully
    # recoverable by PyMuPDF: an embedded image alone must not force vision.
    feats = PageFeatures(image_count=1, text_length=5000, has_math_symbols=False)
    assert needs_vision(feats) is False


def test_math_on_text_rich_page_still_needs_vision():
    # Math needs vision fidelity even when the page is otherwise text-rich.
    feats = PageFeatures(image_count=1, text_length=5000, has_math_symbols=True)
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

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def __getitem__(self, index):
        return self._pages[index]

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
    figure = _FakePage("Fig. 1", images=1)  # image + little text -> vision
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


def test_text_rich_page_with_image_extracts_via_pymupdf(fake_fitz):
    # A designed page (embedded image) that is text-heavy must be extracted for
    # free with PyMuPDF, never sent to the vision model.
    designed = _FakePage("word " * 100, images=1)
    fake_fitz([designed])

    calls = {"n": 0}

    def stub(_uri: str) -> str:
        calls["n"] += 1
        return "VISION"

    result = extract.extract_pdf("x.pdf", "Course", hybrid=True, transcriber=stub)

    assert calls["n"] == 0  # vision never called
    assert result[0].text == ("word " * 100).strip()


def test_empty_vision_transcription_falls_back_to_pymupdf_text(fake_fitz):
    # A page routed to vision (math symbols) whose transcription comes back empty
    # (weak/absent local model) must fall back to the PyMuPDF text so the
    # text-bearing page still indexes instead of being dropped as empty.
    body = "E = mc^2 " + "word " * 100  # math -> vision, but full of real text
    page = _FakePage(body, images=1)
    fake_fitz([page])

    result = extract.extract_pdf("x.pdf", "Course", hybrid=True, transcriber=lambda _uri: "")

    assert result[0].text == body.strip()
    assert result[0].text != ""


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


def test_explicit_pages_honor_requested_order(fake_fitz):
    # Each page transcribes to a marker carrying its 1-based page number, so the
    # output order can be checked end to end against the requested order.
    pages = [_FakePage(f"page-{i + 1}!", images=1) for i in range(8)]
    fake_fitz(pages)

    def stub(image_uri: str) -> str:
        # The rasterized PNG encodes the page text ("PNG:page-N!"); decode the
        # data URI back to it so the marker is tied to the source page.
        b64 = image_uri.split(",", 1)[1]
        return base64.b64decode(b64).decode()

    result = extract.extract_pdf("x.pdf", "Course", pages=[5, 3, 8], transcriber=stub)

    # Page numbers follow the requested order, not document order.
    assert [p.page for p in result] == [5, 3, 8]
    # And the transcribed text is tied to the matching page (no off-by-one mix-up).
    assert [p.text for p in result] == ["PNG:page-5!", "PNG:page-3!", "PNG:page-8!"]


# --- Rate-limit detection helper ---------------------------------------------


def test_is_rate_limit_error_recognizes_429_and_rate_limit_messages():
    assert is_rate_limit_error(_FakeRateLimitError("boom"))  # matched by class name
    assert is_rate_limit_error(Exception("Error code: 429 - too many tokens"))
    assert is_rate_limit_error(Exception("Rate limit reached for org"))
    assert is_rate_limit_error(RuntimeError("RATELIMIT exceeded"))


def test_is_rate_limit_error_rejects_unrelated_errors():
    assert not is_rate_limit_error(ValueError("bad argument"))
    assert not is_rate_limit_error(KeyError("missing"))
    assert not is_rate_limit_error(Exception("connection refused"))


# --- Retry wrapper: backoff on 429, immediate re-raise otherwise -------------


def test_with_rate_limit_retry_retries_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def flaky(_uri: str) -> str:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _FakeRateLimitError("429 too many requests")
        return "OK"

    wrapped = with_rate_limit_retry(flaky, sleep=slept.append)
    assert wrapped("uri") == "OK"
    assert calls["n"] == 3  # two failures + one success
    assert len(slept) == 2  # one backoff per retry
    assert slept[0] < slept[1]  # exponential growth


def test_with_rate_limit_retry_reraises_non_rate_limit_immediately():
    calls = {"n": 0}

    def boom(_uri: str) -> str:
        calls["n"] += 1
        raise ValueError("genuine application bug")

    wrapped = with_rate_limit_retry(boom, sleep=lambda _s: None)
    with pytest.raises(ValueError, match="genuine application bug"):
        wrapped("uri")
    assert calls["n"] == 1  # no retry on non-rate-limit errors


def test_with_rate_limit_retry_gives_up_after_max_retries():
    calls = {"n": 0}

    def always_429(_uri: str) -> str:
        calls["n"] += 1
        raise _FakeRateLimitError("rate limit")

    wrapped = with_rate_limit_retry(always_429, max_retries=3, sleep=lambda _s: None)
    with pytest.raises(_FakeRateLimitError):
        wrapped("uri")
    assert calls["n"] == 4  # initial attempt + 3 retries


# --- extract_pdf integrates the retry wrapper --------------------------------


def test_extract_pdf_retries_rate_limited_page(fake_fitz):
    # Distinct text per page so each rasterizes to a distinct data URI.
    pages = [_FakePage(f"page-{i} E = mc^2", images=1) for i in range(2)]
    fake_fitz(pages)

    attempts: dict[str, int] = {}
    slept: list[float] = []

    def stub(uri: str) -> str:
        attempts[uri] = attempts.get(uri, 0) + 1
        if attempts[uri] == 1:
            raise _FakeRateLimitError("429 rate limit, retry")
        return "VISION"

    result = extract.extract_pdf(
        "x.pdf", "Course", concurrency=2, transcriber=stub, sleep=slept.append
    )

    assert [p.page for p in result] == [1, 2]
    assert all(p.text == "VISION" for p in result)
    # Each page failed once then succeeded -> two attempts per unique page.
    assert all(c == 2 for c in attempts.values())
    assert len(slept) == 2  # one backoff per page (no real waiting occurred)


def test_extract_pdf_propagates_non_rate_limit_error(fake_fitz):
    pages = [_FakePage("E = mc^2", images=1)]
    fake_fitz(pages)

    def stub(_uri: str) -> str:
        raise ValueError("genuine application bug")

    with pytest.raises(ValueError, match="genuine application bug"):
        extract.extract_pdf("x.pdf", "Course", transcriber=stub, sleep=lambda _s: None)


def test_extract_pdf_forwards_api_key_to_get_llm(fake_fitz, monkeypatch):
    # With no injected transcriber, extract_pdf must build the vision model via
    # get_llm and forward the caller's api_key so a visitor's own key pays for the
    # scanned-PDF ingestion. The model is stubbed so no network/LLM is hit.
    pages = [_FakePage("E = mc^2", images=1)]
    fake_fitz(pages)

    captured: dict[str, object] = {}

    class _FakeLLM:
        def invoke(self, _messages):
            class _Msg:
                content = "VISION"

            return _Msg()

    def fake_get_llm(role, api_key=None):
        captured["role"] = role
        captured["api_key"] = api_key
        return _FakeLLM()

    monkeypatch.setattr(extract, "get_llm", fake_get_llm)
    result = extract.extract_pdf("x.pdf", "Course", api_key="sk-visitor", sleep=lambda _s: None)

    assert captured["role"] == "extract"
    assert captured["api_key"] == "sk-visitor"
    assert [p.text for p in result] == ["VISION"]
