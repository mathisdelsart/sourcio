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
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import HumanMessage

from core.config import get_settings
from core.llm import get_llm
from ingestion.mathdetect import _page_features, needs_vision
from ingestion.retry import Sleeper, Transcriber, with_rate_limit_retry
from ingestion.schema import Page

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

    # Whether the vision transcriber can actually run. When it cannot — no
    # visitor key, no process OPENAI_API_KEY, and not a local Ollama vision model
    # — routing a page to vision would only fail with an auth error. In that case
    # hybrid mode extracts EVERY page for free with PyMuPDF instead: a math-heavy
    # but text-based PDF (e.g. a thesis) still imports, just with lower-fidelity
    # math, and the visitor can re-import with a key for full fidelity. An
    # injected transcriber (tests) always counts as available.
    settings = get_settings()
    vision_available = (
        transcriber is not None
        or bool(api_key)
        or bool(os.getenv("OPENAI_API_KEY"))
        or settings.llm_provider.strip().lower() == "ollama"
        or (os.getenv("LLM_EXTRACT") or "").startswith("ollama:")
    )

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
        # Keep a page on the free PyMuPDF path when it is plain text OR when
        # vision is not available at all, so a math/scanned page never fails the
        # import for lack of a working key — it is imported as best-effort text.
        if hybrid and (not vision_available or not needs_vision(_page_features(page))):
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
