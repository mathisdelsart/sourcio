"""Tests for plain-text (Markdown / text) ingestion. No model, no network.

Markdown and text course files are read straight from disk, split into prose
windows, and chunked through the existing prose path. These tests assert the
windows, the citation metadata and the CLI routing without ever calling an
embedding model, the vision model or Qdrant (indexing is monkeypatched to
capture the chunks instead).
"""

from ingestion import run
from ingestion.chunk import chunk_pages
from ingestion.load import is_text_file, load_text_file, split_prose
from ingestion.schema import Page

# --- Extension detection -----------------------------------------------------


def test_is_text_file_detects_md_and_txt():
    assert is_text_file("notes.md")
    assert is_text_file("summary.txt")
    assert is_text_file("/abs/path/Notes.MD")  # case-insensitive
    assert not is_text_file("course.pdf")
    assert not is_text_file("deck.PDF")
    assert not is_text_file("noextension")


# --- Prose windowing ---------------------------------------------------------


def test_split_prose_single_window_when_short():
    assert split_prose("a few words here") == ["a few words here"]


def test_split_prose_windows_overlap():
    text = " ".join(str(i) for i in range(10))
    windows = split_prose(text, window_words=4, overlap_words=2)
    # step = window - overlap = 2 -> starts at 0, 2, 4, 6
    assert windows == ["0 1 2 3", "2 3 4 5", "4 5 6 7", "6 7 8 9"]


def test_split_prose_empty_and_whitespace():
    assert split_prose("") == []
    assert split_prose("   \n\t  ") == []


def test_split_prose_rejects_overlap_ge_window():
    import pytest

    with pytest.raises(ValueError):
        split_prose("a b c", window_words=3, overlap_words=3)


# --- load_text_file: prose Pages with citation metadata ----------------------


def test_load_md_file_produces_prose_pages(tmp_path):
    path = tmp_path / "wavelets.md"
    path.write_text("# Heading\n" + " ".join(f"w{i}" for i in range(20)), encoding="utf-8")

    pages = load_text_file(str(path), "Wavelet Transform", window_words=8, overlap_words=2)

    assert pages, "expected at least one prose page"
    assert all(p.doc_type == "prose" for p in pages)
    assert all(p.course == "Wavelet Transform" for p in pages)
    # chapter is the file stem; page is a running 1-based window index.
    assert all(p.chapter == "wavelets" for p in pages)
    assert [p.page for p in pages] == list(range(1, len(pages) + 1))


def test_load_txt_file_reads_utf8(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("transformee en ondelettes deja vu", encoding="utf-8")

    pages = load_text_file(str(path), "Course")

    assert len(pages) == 1
    assert pages[0].text == "transformee en ondelettes deja vu"
    assert pages[0].chapter == "resume"
    assert pages[0].doc_type == "prose"


def test_load_empty_file_yields_no_pages(tmp_path):
    path = tmp_path / "blank.md"
    path.write_text("   \n\n  ", encoding="utf-8")

    assert load_text_file(str(path), "Course") == []


# --- Prose chunking: one chunk per window, stable distinct ids ---------------


def test_chunk_pages_handles_prose():
    pages = [
        Page(course="C", page=1, text="first window", doc_type="prose", chapter="notes"),
        Page(course="C", page=2, text="second window", doc_type="prose", chapter="notes"),
    ]
    chunks = chunk_pages(pages)

    assert [c.text for c in chunks] == ["first window", "second window"]
    assert [c.page for c in chunks] == [1, 2]
    assert all(c.chapter == "notes" for c in chunks)
    assert len({c.id for c in chunks}) == 2  # distinct ids per window


def test_prose_chunk_ids_distinct_across_documents():
    # Same course and window index but different documents must not collide.
    a = chunk_pages([Page(course="C", page=1, text="x", doc_type="prose", chapter="doc_a")])
    b = chunk_pages([Page(course="C", page=1, text="y", doc_type="prose", chapter="doc_b")])
    assert a[0].id != b[0].id


def test_slide_chunk_ids_unchanged():
    # Slides (chapter is None) keep the original course-only key, byte-identical.
    import uuid

    chunks = chunk_pages([Page(course="C", page=7, text="slide", doc_type="slides")])
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "C-p7"))
    assert chunks[0].id == expected


def test_slide_chunk_ids_distinct_across_documents():
    # Two decks in the same course share page numbers 1..N; folding the document
    # identity into the id keeps their chunks distinct (no overwrite).
    a = chunk_pages([Page(course="C", page=1, text="a", doc_type="slides", document="deck_a.pdf")])
    b = chunk_pages([Page(course="C", page=1, text="b", doc_type="slides", document="deck_b.pdf")])
    assert a[0].id != b[0].id
    # And the document identity is carried through onto the chunk.
    assert a[0].document == "deck_a.pdf"


# --- CLI routing: text files indexed without touching the PDF path -----------


def test_run_routes_text_file_and_indexes_chunks(tmp_path, monkeypatch):
    path = tmp_path / "syllabus.md"
    path.write_text(" ".join(f"t{i}" for i in range(30)), encoding="utf-8")

    captured: list = []

    def fake_index(chunks, *, sparse=False):
        captured.extend(chunks)

    # Capture indexing; fail loudly if the PDF/vision path is ever reached.
    monkeypatch.setattr(run, "index_chunks", fake_index)

    def boom_extract(*args, **kwargs):
        raise AssertionError("extract_pdf must not be called for a text file")

    monkeypatch.setattr(run, "extract_pdf", boom_extract)

    monkeypatch.setattr(
        run.argparse.ArgumentParser,
        "parse_args",
        lambda self: run.argparse.Namespace(
            pdf=str(path),
            course="Wavelet Transform",
            max_pages=None,
            pages=None,
            dpi=150,
            hybrid=False,
            concurrency=4,
            sparse=False,
            batch_size=10,
        ),
    )

    run.main()

    assert captured, "expected chunks to be indexed"
    assert all(c.course == "Wavelet Transform" for c in captured)
    assert all(c.chapter == "syllabus" for c in captured)
