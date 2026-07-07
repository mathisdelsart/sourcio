"""PDF extraction, math-aware.

The course material is slide decks where formulas are rendered as images or as
broken text that PyMuPDF cannot recover. Math/figure-heavy pages are therefore
rasterized and transcribed by a vision model into Markdown with LaTeX preserved,
which keeps the mathematics intact (the project's main grounding risk).

Two optimizations keep ingestion fast and cheap:

- Parallel vision calls: pages that need transcription are sent to the model
  concurrently (bounded by `concurrency`), while output order is preserved.
- Hybrid routing: a cheap PyMuPDF heuristic decides, per page, whether the page
  is math/figure-heavy (needs the paid vision model) or plain text (extracted
  for free with PyMuPDF). Enabled with `hybrid=True`; the default keeps the
  previous behavior of sending every page to the vision model.
"""

import base64
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from core.config import get_llm
from ingestion.schema import Page

logger = logging.getLogger(__name__)

_PROMPT = (
    "You transcribe a single course slide into clean Markdown for a study tutor.\n"
    "Rules:\n"
    "- Preserve every formula exactly, as LaTeX: inline $...$, display $$...$$.\n"
    "- Keep titles, bullet points and tables as Markdown.\n"
    "- For figures/diagrams, add a short description in [square brackets].\n"
    "- Transcribe only what is on the slide. Do not add, explain or comment.\n"
    "- Output raw Markdown directly. Do NOT wrap the whole answer in a code "
    "fence (no triple backticks around the response).\n"
    "- If the slide is empty, reply with an empty string."
)

# Characters that strongly hint at mathematical content. PyMuPDF often recovers
# these as text even when the surrounding formula is broken, so their presence
# is a cheap signal that a page is math-heavy.
_MATH_SYMBOLS = set("=±×÷∑∏∫√∞≈≠≤≥∂∇∈∉⊂⊆∪∩→←↔∀∃αβγδθλμπσφψω")
_MATH_PATTERNS = re.compile(r"\\[a-zA-Z]+|\^|_\{|\\frac|\$")

# A page with little recoverable text is suspicious: its content is probably
# rendered as images/formulas that PyMuPDF cannot read, so it needs vision.
_MIN_PLAIN_TEXT_LEN = 200


@dataclass(frozen=True)
class PageFeatures:
    """Cheap per-page signals used by the math-density heuristic."""

    image_count: int
    text_length: int
    has_math_symbols: bool


def has_math_symbols(text: str) -> bool:
    """Return whether `text` contains math-like symbols or LaTeX fragments."""
    if any(ch in _MATH_SYMBOLS for ch in text):
        return True
    return bool(_MATH_PATTERNS.search(text))


def needs_vision(features: PageFeatures) -> bool:
    """Decide whether a page is math/figure-heavy and needs vision transcription.

    Pure function over simple page features so it is unit-testable without a PDF
    or any API call. A page needs vision when either of the following holds:

    - it exposes math-like symbols, which signal formulas PyMuPDF may garble
      (math needs vision fidelity, even on an otherwise text-rich page);
    - it yields little recoverable text, suggesting image-based content -- and,
      on such a page, an embedded image confirms the content is not extractable.

    An embedded image alone does NOT force vision on a text-rich page: a
    visually designed document (e.g. a cover letter with a logo or a background
    image) still has fully recoverable text, so it is extracted for free with
    PyMuPDF rather than pushed onto the (paid, or weak/local) vision model.

    Otherwise the page is plain prose and can be extracted for free.
    """
    if features.has_math_symbols:
        return True
    # Text-rich page: recoverable by PyMuPDF for free, even with an image.
    if features.text_length >= _MIN_PLAIN_TEXT_LEN:
        return False
    # Little recoverable text: an embedded image (or a near-empty page) means
    # the content is image-based and must be transcribed by the vision model.
    return features.image_count > 0 or features.text_length < _MIN_PLAIN_TEXT_LEN


def _page_features(page) -> PageFeatures:
    """Compute the heuristic features of a PyMuPDF page."""
    text = page.get_text()
    return PageFeatures(
        image_count=len(page.get_images()),
        text_length=len(text.strip()),
        has_math_symbols=has_math_symbols(text),
    )


def _render_page(page, dpi: int) -> str:
    """Rasterize a page to a base64-encoded PNG data URI."""
    pix = page.get_pixmap(dpi=dpi)
    b64 = base64.b64encode(pix.tobytes("png")).decode()
    return f"data:image/png;base64,{b64}"


def _strip_code_fence(text: str) -> str:
    """Remove a leading Markdown code fence artifact from a transcription.

    The vision model sometimes wraps its output in a Markdown code fence (an
    opening ```markdown line and a closing ```), which pollutes the stored chunk
    and its embedding. The closing fence is not always the last line: a figure
    caption can follow it. A leading fence in a slide transcription is always an
    artifact, so when the stripped text starts with an opening fence line (```
    optionally followed by a language tag), this removes that opening line and the
    first subsequent line that is exactly a closing ```, keeping everything else
    (including any content after the closing fence).

    If the text does not start with a fence line it is returned unchanged, so
    inline backticks are never mangled. The transformation is idempotent.
    """
    stripped = text.strip()
    lines = stripped.splitlines()
    if not lines:
        return text
    # The first line must be exactly an opening fence plus an optional language
    # tag, with no other content on it.
    if not re.fullmatch(r"\s*```[A-Za-z0-9_+-]*\s*", lines[0]):
        return text
    rest = lines[1:]
    # Drop the first line that is exactly a closing fence; keep the remainder.
    for i, line in enumerate(rest):
        if line.strip() == "```":
            kept = rest[:i] + rest[i + 1 :]
            return "\n".join(kept).strip()
    # Opening fence with no closing fence: still strip the artifact opener.
    return "\n".join(rest).strip()


def _vision_transcribe(image_uri: str, llm) -> str:
    """Transcribe a rasterized page via the vision model into Markdown."""
    message = HumanMessage(
        content=[
            {"type": "text", "text": _PROMPT},
            {"type": "image_url", "image_url": {"url": image_uri}},
        ]
    )
    return llm.invoke([message]).content.strip()


# A transcriber maps a rasterized page (data URI) to its Markdown text. Injected
# so tests can pass a stub that returns canned text instead of calling the model.
Transcriber = Callable[[str], str]

# A sleeper pauses execution for the given number of seconds. Injected so tests
# run instantly with a no-op instead of waiting on real backoff delays.
Sleeper = Callable[[float], None]

# Default backoff schedule for rate-limit retries. The provider enforces a
# per-minute token budget, so waits are on the order of tens of seconds.
_DEFAULT_MAX_RETRIES = 6
_DEFAULT_BASE_DELAY = 2.0
_DEFAULT_MAX_DELAY = 60.0


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return whether `exc` looks like an API rate-limit (HTTP 429) error.

    Detection is by exception class name and message so the OpenAI SDK never has
    to be imported here: any error whose type name or text mentions a 429 status
    or a rate limit is treated as transient and worth retrying. Unrelated errors
    return False and must be re-raised immediately so real bugs are not masked.
    """
    haystack = f"{type(exc).__name__} {exc}".lower()
    return "ratelimit" in haystack or "rate limit" in haystack or "429" in haystack


def with_rate_limit_retry(
    transcriber: Transcriber,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
    sleep: Sleeper = time.sleep,
) -> Transcriber:
    """Wrap a transcriber so rate-limit failures retry with exponential backoff.

    Only rate-limit (HTTP 429) errors are retried; any other exception is
    re-raised immediately so genuine bugs surface instead of being silently
    retried. Between attempts the wrapper sleeps `base_delay * 2**attempt`,
    capped at `max_delay`. The sleep function is injectable so tests can pass a
    no-op and run without any real waiting. After `max_retries` exhausted
    retries the last rate-limit error propagates.
    """

    def wrapped(image_uri: str) -> str:
        attempt = 0
        while True:
            try:
                return transcriber(image_uri)
            except Exception as exc:  # noqa: BLE001 - re-raised below unless 429
                if not is_rate_limit_error(exc):
                    raise
                if attempt >= max_retries:
                    logger.warning("rate limit: giving up after %d retries", attempt)
                    raise
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "rate limit hit; backing off %.1fs before retry %d/%d",
                    delay,
                    attempt + 1,
                    max_retries,
                )
                sleep(delay)
                attempt += 1

    return wrapped


def extract_pdf(
    path: str,
    course: str,
    *,
    dpi: int = 150,
    max_pages: int | None = None,
    pages: list[int] | None = None,
    hybrid: bool = False,
    concurrency: int = 4,
    transcriber: Transcriber | None = None,
    sleep: Sleeper = time.sleep,
    api_key: str | None = None,
) -> list[Page]:
    """Extract a slide-deck PDF into per-slide Pages.

    Math/figure-heavy pages are transcribed by a vision model (preserving LaTeX);
    in hybrid mode, plain-text pages are extracted for free with PyMuPDF. Vision
    calls run concurrently while output order follows the page number.

    Args:
        path: Path to the PDF file.
        course: Course name stored on every page for citations.
        dpi: Rasterization resolution; higher is sharper but larger.
        max_pages: Optional cap on the first N selected pages, to keep cost low.
        pages: Optional explicit 1-based page numbers to extract (overrides the
            natural order filter); useful to spend API calls only on math-heavy
            slides while validating.
        hybrid: If True, route plain-text pages to free PyMuPDF text extraction
            and only math/figure-heavy pages to the vision model. If False (the
            default), every selected page is sent to the vision model.
        concurrency: Maximum number of vision transcriptions running at once.
        transcriber: Optional injected function mapping a rasterized page (PNG
            data URI) to its Markdown text. Defaults to the vision model; tests
            pass a stub to avoid any API call. The transcriber (default or
            injected) is wrapped with rate-limit retry/backoff.
        sleep: Sleep function used by the rate-limit backoff; tests pass a no-op
            so retries do not actually wait.
        api_key: Optional OpenAI key authenticating the vision model for this
            extraction only (a visitor importing a scanned/image PDF with their
            own key so the app owner is not billed). Forwarded to
            ``get_llm("extract", api_key=...)`` and used transiently; it is never
            stored or logged. Ignored when a ``transcriber`` is injected (tests)
            or when the resolved extract model is not an OpenAI one.

    Returns:
        One Page per selected slide, with math preserved as LaTeX for
        vision-transcribed pages. When explicit `pages` are given the output
        follows that requested order; otherwise pages are in document order.
    """
    import fitz  # PyMuPDF, imported lazily so non-ingestion code can import this module.

    if transcriber is None:
        llm = get_llm("extract", api_key=api_key)

        def _default_transcriber(image_uri: str) -> str:
            return _vision_transcribe(image_uri, llm)

        transcriber = _default_transcriber

    # Back off and retry on rate-limit (429) errors instead of crashing the run.
    transcriber = with_rate_limit_retry(transcriber, sleep=sleep)

    doc = fitz.open(path)
    page_count = doc.page_count

    # Resolve the output order. Explicit `pages` take priority in the given order
    # (de-duplicated, keeping first occurrence, and dropping out-of-range values);
    # otherwise pages follow natural document order. `max_pages` then caps the
    # first N selected pages in whichever order was chosen.
    if pages:
        seen: set[int] = set()
        order = [p for p in pages if 1 <= p <= page_count and not (p in seen or seen.add(p))]
    else:
        order = list(range(1, page_count + 1))
    if max_pages is not None:
        order = order[:max_pages]

    # First pass: classify the selected pages and resolve plain-text pages for
    # free. Vision pages are recorded as pending jobs to run concurrently. The
    # dicts are keyed by page number so the requested order is honored later.
    # For every vision page we also capture whatever text PyMuPDF can recover,
    # to use as a fallback if the vision transcription comes back empty.
    plain: dict[int, str] = {}
    vision_jobs: list[tuple[int, str]] = []
    vision_fallback: dict[int, str] = {}

    for page_no in order:
        page = doc[page_no - 1]
        # Default mode returns a str; guard keeps the type checker honest
        # against PyMuPDF's broad get_text() overloads.
        raw = page.get_text()
        text = (raw if isinstance(raw, str) else "").strip()
        if hybrid and not needs_vision(_page_features(page)):
            plain[page_no] = text
        else:
            vision_fallback[page_no] = text
            vision_jobs.append((page_no, _render_page(page, dpi)))

    doc.close()

    # Second pass: transcribe vision pages concurrently, preserving order below.
    transcribed: dict[int, str] = {}
    if vision_jobs:
        workers = max(1, min(concurrency, len(vision_jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(transcriber, image_uri): page_no for page_no, image_uri in vision_jobs
            }
            for future in futures:
                # The vision model sometimes wraps its whole answer in a code
                # fence; strip it before the text reaches a Page. The plain-text
                # PyMuPDF path is left untouched.
                transcribed[futures[future]] = _strip_code_fence(future.result())

    result: list[Page] = []
    for page_no in order:
        if page_no in plain:
            text = plain[page_no]
        else:
            text = transcribed[page_no]
            # Fallback: if the vision model returned nothing (a weak/absent
            # local model, or a page it could not read) but PyMuPDF recovered
            # text on this page, keep that text so a text-bearing page still
            # indexes instead of being dropped as empty downstream.
            if not text and vision_fallback.get(page_no):
                text = vision_fallback[page_no]
        result.append(Page(course=course, page=page_no, text=text, doc_type="slides"))
    return result
