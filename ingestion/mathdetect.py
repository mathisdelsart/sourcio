"""Math-density heuristic for PDF pages.

A cheap, PyMuPDF-only signal used by ``ingestion.extract`` to decide, per page,
whether a slide is math/figure-heavy (needs the paid vision model) or plain text
(extracted for free). Pure functions over simple page features, so they are
unit-testable without a PDF or any API call.
"""

import re
from dataclasses import dataclass

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
