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
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from config import get_llm
from ingestion.schema import Page

_PROMPT = (
    "You transcribe a single course slide into clean Markdown for a study tutor.\n"
    "Rules:\n"
    "- Preserve every formula exactly, as LaTeX: inline $...$, display $$...$$.\n"
    "- Keep titles, bullet points and tables as Markdown.\n"
    "- For figures/diagrams, add a short description in [square brackets].\n"
    "- Transcribe only what is on the slide. Do not add, explain or comment.\n"
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
    or any API call. A page needs vision when any of the following holds:

    - it embeds one or more images (figures/diagrams or rendered formulas);
    - it exposes math-like symbols, which signal formulas PyMuPDF may garble;
    - it yields very little recoverable text, suggesting image-based content.

    Otherwise the page is plain prose and can be extracted for free.
    """
    if features.image_count > 0:
        return True
    if features.has_math_symbols:
        return True
    return features.text_length < _MIN_PLAIN_TEXT_LEN


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


def extract_pdf(
    path: str,
    course: str,
    *,
    dpi: int = 150,
    max_pages: int | None = None,
    pages: list[int] | None = None,
    hybrid: bool = False,
    concurrency: int = 8,
    transcriber: Transcriber | None = None,
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
            pass a stub to avoid any API call.

    Returns:
        One Page per selected slide, in document order, with math preserved as
        LaTeX for vision-transcribed pages.
    """
    import fitz  # PyMuPDF, imported lazily so non-ingestion code can import this module.

    if transcriber is None:
        llm = get_llm("extract")

        def transcriber(image_uri: str) -> str:
            return _vision_transcribe(image_uri, llm)

    doc = fitz.open(path)
    selected = set(pages) if pages else None

    # First pass: select pages, classify them, and resolve plain-text pages for
    # free. Vision pages are recorded as pending jobs to run concurrently.
    plain: dict[int, str] = {}
    vision_jobs: list[tuple[int, str]] = []
    order: list[int] = []

    for i, page in enumerate(doc):
        page_no = i + 1
        if selected is not None and page_no not in selected:
            continue
        if max_pages is not None and len(order) >= max_pages:
            break
        order.append(page_no)

        if hybrid and not needs_vision(_page_features(page)):
            plain[page_no] = page.get_text().strip()
        else:
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
                transcribed[futures[future]] = future.result()

    result: list[Page] = []
    for page_no in order:
        text = plain[page_no] if page_no in plain else transcribed[page_no]
        result.append(Page(course=course, page=page_no, text=text, doc_type="slides"))
    return result
