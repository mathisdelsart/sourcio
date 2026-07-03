"""Shared data contract for the ingestion and retrieval pipeline.

Every feature (extract, chunk, index, retrieve, answer) is built against these
types. Fixing this contract first is what lets the features be developed
independently rather than as one sequential block.
"""

from dataclasses import dataclass


@dataclass
class Page:
    """A single extracted page, with its math preserved as Markdown + LaTeX."""

    course: str
    page: int  # 1-based page number in the source PDF
    text: str
    doc_type: str  # "slides" | "prose"
    chapter: str | None = None
    # Stable per-document identifier (usually the uploaded filename). ``None`` for
    # material ingested via the CLI, keeping chunk ids/payloads backward-compatible.
    document: str | None = None


@dataclass
class Chunk:
    """A retrievable unit of course content with citation metadata."""

    id: str
    course: str
    page: int
    text: str
    chapter: str | None = None
    # Document the chunk came from (see :class:`Page.document`). ``None`` when the
    # source document is unknown (CLI ingestion), preserving the legacy chunk id.
    document: str | None = None


@dataclass
class Retrieved:
    """A chunk returned by retrieval together with its similarity score."""

    chunk: Chunk
    score: float

    def citation(self) -> str:
        """Human-readable source label, e.g. '(Wavelet Transform, p.11)'."""
        if self.chunk.chapter:
            return f"({self.chunk.course}, {self.chunk.chapter}, p.{self.chunk.page})"
        return f"({self.chunk.course}, p.{self.chunk.page})"


def format_numbered_sources(results: list[Retrieved]) -> str:
    """Render retrieved chunks as a numbered context block for the prompt.

    Each chunk is prefixed with a 1-based index ``[n]`` so the model can cite
    sources by index without ever handling page numbers directly.
    """
    return "\n\n".join(f"[{i}] {r.chunk.text}" for i, r in enumerate(results, 1))
