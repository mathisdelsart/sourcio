"""Tests for the document inventory/management layer (``core.documents``) and
the ``/documents`` routes.

No real Qdrant, embedding model, vision LLM, or network call is made: the
``QdrantClient`` is replaced with a fake exposing only ``scroll``/``count``/
``delete``, the ingestion calls are stubbed, and the API is bound to an
in-memory SQLite database. The inventory grouping, the ingest routing, the
delete filter, and graceful handling of an empty/missing collection are all
exercised in isolation.
"""

import os
from types import SimpleNamespace

import pytest

import core.documents as documents_mod
from ingestion.schema import Page

# --- core.jobs: the background-job registry ----------------------------------


@pytest.fixture
def jobs_db():
    """Bind an in-memory SQLite database for the persisted ingestion-job helpers.

    Ingestion jobs live in the database, so these direct ``core.jobs`` tests need
    a configured session factory of their own rather than relying on another test
    having configured the engine first (which made them order-dependent).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from db.session import SessionLocal, init_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(engine)
    SessionLocal.configure(bind=engine)
    yield


def test_jobs_create_update_get_and_terminal_stamp(jobs_db):
    import core.jobs as jobs_mod

    job_id = jobs_mod.create_job("Wavelets", "Intro", "notes.pdf")
    record = jobs_mod.get_job(job_id)
    assert record is not None
    assert record["job_id"] == job_id
    assert record["status"] == "running"
    assert record["course"] == "Wavelets"
    assert record["chapter"] == "Intro"
    assert record["filename"] == "notes.pdf"
    assert record["finished_at"] is None

    jobs_mod.update_job(job_id, {"type": "progress", "done": 1, "total": 3, "indexed": 1})
    record = jobs_mod.get_job(job_id)
    assert record is not None
    assert record["done"] == 1 and record["total"] == 3
    assert record["finished_at"] is None  # still running

    jobs_mod.update_job(job_id, {"type": "done", "indexed": 3, "reason": "indexed"})
    jobs_mod.update_job(job_id, {"status": "done"})
    record = jobs_mod.get_job(job_id)
    assert record is not None
    assert record["status"] == "done"
    assert record["finished_at"] is not None

    # get returns a copy: mutating it must not leak back into the registry.
    record["indexed"] = 999
    assert jobs_mod.get_job(job_id)["indexed"] == 3


def test_jobs_update_unknown_id_is_noop(jobs_db):
    import core.jobs as jobs_mod

    jobs_mod.update_job("nope", {"status": "done"})  # must not raise
    assert jobs_mod.get_job("nope") is None


def test_jobs_prune_drops_stale_finished_jobs(jobs_db):
    from datetime import UTC, datetime, timedelta

    import core.jobs as jobs_mod
    from db.models import IngestJob
    from db.session import get_session

    old_id = jobs_mod.create_job("Old", None, "old.pdf")
    jobs_mod.update_job(old_id, {"status": "done"})
    # Backdate its completion beyond the retention window. Ingestion jobs are
    # persisted, so backdate the stored row's ``finished_at`` column (not the old
    # in-memory dict, which now only holds answer jobs).
    stale = datetime.now(UTC) - jobs_mod._RETENTION - timedelta(minutes=1)
    with get_session() as session:
        session.get(IngestJob, old_id).finished_at = stale

    # Creating a new job prunes stale finished ones.
    new_id = jobs_mod.create_job("New", None, "new.pdf")
    assert jobs_mod.get_job(old_id) is None
    assert jobs_mod.get_job(new_id) is not None


def test_openai_key_error_distinguishes_missing_vs_rejected():
    # No key supplied -> "add your key"; a key WAS supplied but rejected -> "the
    # key was rejected", so a user who pasted a bad/malformed key is not told to
    # add one they already added.
    assert documents_mod._openai_key_error(None) == documents_mod.MISSING_OPENAI_KEY_MESSAGE
    assert documents_mod._openai_key_error("") == documents_mod.MISSING_OPENAI_KEY_MESSAGE
    assert documents_mod._openai_key_error("sk-bad") == documents_mod.REJECTED_OPENAI_KEY_MESSAGE


# --- list_documents: grouping by course and chapter --------------------------


class _ScrollClient:
    """A Qdrant client returning two pages of points, then signalling the end.

    Points carry course/chapter/page payloads (some chapterless, some without a
    page) so the inventory must group, de-duplicate pages, and handle ``None``.
    """

    def __init__(self, *args, **kwargs):
        pass

    def scroll(  # noqa: ARG002
        self, *, collection_name, limit, with_payload, with_vectors, offset, scroll_filter=None
    ):
        if offset is None:
            points = [
                SimpleNamespace(payload={"course": "Wavelets", "chapter": "Intro", "page": 1}),
                SimpleNamespace(payload={"course": "Wavelets", "chapter": "Intro", "page": 2}),
                # Duplicate page must collapse to one distinct page.
                SimpleNamespace(payload={"course": "Wavelets", "chapter": "Intro", "page": 2}),
                SimpleNamespace(payload={"course": "Wavelets", "chapter": None, "page": 5}),
                SimpleNamespace(payload={}),  # no course -> ignored
            ]
            return points, "next"
        points = [
            SimpleNamespace(payload={"course": "Algebra", "chapter": "Groups", "page": 3}),
            SimpleNamespace(payload=None),
        ]
        return points, None


class _EmptyScrollClient:
    """A client whose collection is empty/missing (no points, no offset)."""

    def __init__(self, *args, **kwargs):
        pass

    def scroll(self, **kwargs):  # noqa: ARG002
        return [], None


class _RaisingScrollClient:
    """A client whose scroll raises (e.g. missing collection)."""

    def __init__(self, *args, **kwargs):
        pass

    def scroll(self, **kwargs):  # noqa: ARG002
        raise RuntimeError("collection not found")


def _use_client(monkeypatch, client_cls):
    """Patch the QdrantClient symbol used inside ``core.documents``."""
    import qdrant_client

    monkeypatch.setattr(qdrant_client, "QdrantClient", client_cls)


def test_list_documents_groups_by_course_and_chapter(monkeypatch):
    # A real caller always scopes by owner; the fake ignores the filter and returns
    # its presets, so this still exercises the grouping mechanics.
    _use_client(monkeypatch, _ScrollClient)
    inventory = documents_mod.list_documents(owner="tester")

    # Courses are sorted by name.
    assert [c["course"] for c in inventory] == ["Algebra", "Wavelets"]

    algebra = inventory[0]
    assert algebra["total_pages"] == 1
    assert algebra["chapters"] == [{"chapter": "Groups", "pages": 1}]

    wavelets = inventory[1]
    # Intro has 2 distinct pages (the duplicate collapses); the chapterless
    # group has 1. total = 3. Chapterless (None) is sorted last.
    assert wavelets["total_pages"] == 3
    assert wavelets["chapters"] == [
        {"chapter": "Intro", "pages": 2},
        {"chapter": None, "pages": 1},
    ]


def test_list_documents_empty_collection(monkeypatch):
    _use_client(monkeypatch, _EmptyScrollClient)
    assert documents_mod.list_documents(owner="tester") == []


def test_list_documents_missing_collection_degrades(monkeypatch):
    _use_client(monkeypatch, _RaisingScrollClient)
    assert documents_mod.list_documents(owner="tester") == []


def test_list_documents_fail_closed_without_owner(monkeypatch):
    # No owner -> fail closed: return [] WITHOUT scrolling (never list every
    # account's material). The client's scroll must not even be called.
    class _BoomScrollClient:
        def __init__(self, *args, **kwargs):
            pass

        def scroll(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("no Qdrant call must happen when the owner is None")

    _use_client(monkeypatch, _BoomScrollClient)
    assert documents_mod.list_documents() == []
    assert documents_mod.list_documents(owner=None) == []


# --- ingest_document: routing without touching any model ---------------------


def test_ingest_document_text_overrides_chapter(monkeypatch, tmp_path):
    path = tmp_path / "syllabus.md"
    path.write_text(" ".join(f"w{i}" for i in range(30)), encoding="utf-8")

    captured: list = []
    monkeypatch.setattr(documents_mod, "index_chunks", lambda chunks, **_: captured.extend(chunks))

    def boom_extract(*args, **kwargs):
        raise AssertionError("the PDF/vision path must not run for a text file")

    # The lazy extract import resolves to ingestion.extract.extract_pdf.
    import ingestion.extract

    monkeypatch.setattr(ingestion.extract, "extract_pdf", boom_extract)

    count = documents_mod.ingest_document(str(path), "Wavelets", "Chapter 1")

    assert count == len(captured) > 0
    # The provided chapter overrides the file-stem chapter on every chunk.
    assert all(c.course == "Wavelets" for c in captured)
    assert all(c.chapter == "Chapter 1" for c in captured)


def test_ingest_document_pdf_uses_extract(monkeypatch, tmp_path):
    path = tmp_path / "deck.pdf"
    path.write_bytes(b"%PDF-1.4 fake")

    def fake_extract(p, course, **kwargs):  # noqa: ARG001
        return [Page(course=course, page=1, text="slide one", doc_type="slides")]

    import ingestion.extract

    monkeypatch.setattr(ingestion.extract, "extract_pdf", fake_extract)

    captured: list = []
    monkeypatch.setattr(documents_mod, "index_chunks", lambda chunks, **_: captured.extend(chunks))

    count = documents_mod.ingest_document(str(path), "Wavelets")

    assert count == 1
    assert captured[0].course == "Wavelets"


def test_ingest_document_empty_file_indexes_nothing(monkeypatch, tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text("   \n\n  ", encoding="utf-8")

    def boom_index(*args, **kwargs):
        raise AssertionError("index_chunks must not run for an empty file")

    monkeypatch.setattr(documents_mod, "index_chunks", boom_index)

    assert documents_mod.ingest_document(str(path), "Wavelets") == 0


# --- stream_ingest: per-document scoping and honest 0 ------------------------


def _fake_pdf_env(monkeypatch, *, page_count, indexed):
    """Patch the PDF ingest dependencies of ``stream_ingest``.

    ``indexed`` maps a document id -> set of page numbers already in Qdrant so the
    incremental-skip check is exercised per document without a real Qdrant. The
    returned list captures the chunks handed to ``index_chunks``.
    """
    import ingestion.extract
    import ingestion.run

    monkeypatch.setattr(ingestion.run, "_pdf_page_count", lambda path: page_count)  # noqa: ARG005

    def fake_extract(path, course, *, pages=None, **kwargs):  # noqa: ARG001
        nums = pages or list(range(1, page_count + 1))
        return [Page(course=course, page=n, text=f"slide {n}", doc_type="slides") for n in nums]

    monkeypatch.setattr(ingestion.extract, "extract_pdf", fake_extract)
    monkeypatch.setattr(
        documents_mod,
        "_indexed_pages",
        lambda course, document=None, owner=None: set(indexed.get(document, set())),  # noqa: ARG005
    )

    captured: list = []
    monkeypatch.setattr(documents_mod, "index_chunks", lambda chunks, **_: captured.extend(chunks))
    return captured


def test_stream_ingest_two_documents_index_independently(monkeypatch, tmp_path):
    # Nothing indexed yet for either document: both must fully index, with
    # disjoint chunk ids so the second deck never overwrites the first.
    captured = _fake_pdf_env(monkeypatch, page_count=2, indexed={})
    a = tmp_path / "deck_a.pdf"
    a.write_bytes(b"%PDF")
    b = tmp_path / "deck_b.pdf"
    b.write_bytes(b"%PDF")

    events_a = list(documents_mod.stream_ingest(str(a), "Wavelets"))
    ids_a = {c.id for c in captured}
    captured.clear()
    events_b = list(documents_mod.stream_ingest(str(b), "Wavelets"))
    ids_b = {c.id for c in captured}

    assert events_a[-1]["indexed"] == 2
    assert events_a[-1]["reason"] == "indexed"
    assert events_b[-1]["indexed"] == 2
    assert ids_a and ids_b and ids_a.isdisjoint(ids_b)


def test_stream_ingest_same_document_skips(monkeypatch, tmp_path):
    path = tmp_path / "deck.pdf"
    path.write_bytes(b"%PDF")
    doc = documents_mod._document_id(str(path))
    captured = _fake_pdf_env(monkeypatch, page_count=2, indexed={doc: {1, 2}})

    def boom_extract(*args, **kwargs):
        raise AssertionError("extract must not run when the document is fully indexed")

    import ingestion.extract

    monkeypatch.setattr(ingestion.extract, "extract_pdf", boom_extract)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    assert captured == []
    done = events[-1]
    assert done["type"] == "done"
    assert done["indexed"] == 0
    assert done["skipped"] == 2
    assert done["reason"] == "already_indexed"


def test_stream_ingest_empty_file_reports_zero_honestly(monkeypatch, tmp_path):
    path = tmp_path / "blank.md"
    path.write_text("   \n\n  ", encoding="utf-8")

    def boom_index(*args, **kwargs):
        raise AssertionError("index_chunks must not run for an empty file")

    monkeypatch.setattr(documents_mod, "index_chunks", boom_index)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    done = events[-1]
    assert done["type"] == "done"
    assert done["indexed"] == 0
    assert done["total"] == 0
    assert done["reason"] == "empty"


def test_stream_ingest_text_decode_error_emits_error_event(monkeypatch, tmp_path):
    # A non-UTF-8 text file must surface a clean error event, not break the stream.
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff\xfe\x00 invalid utf-8")

    def boom_index(*args, **kwargs):
        raise AssertionError("index_chunks must not run when decoding fails")

    monkeypatch.setattr(documents_mod, "index_chunks", boom_index)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    assert events[-1]["type"] == "error"
    assert events[-1]["message"]


def test_stream_ingest_pdf_routes_through_hybrid(monkeypatch, tmp_path):
    # A text PDF must extract via the free PyMuPDF/hybrid route, so stream_ingest
    # is required to call extract_pdf with hybrid=True regardless of the vision
    # model. Capture the kwargs to assert the routing without any real model call.
    path = tmp_path / "letter.pdf"
    path.write_bytes(b"%PDF")

    seen: dict[str, object] = {}

    def fake_extract(p, course, *, pages=None, hybrid=False, **kwargs):  # noqa: ARG001
        seen["hybrid"] = hybrid
        nums = pages or [1]
        return [Page(course=course, page=n, text=f"text {n}", doc_type="slides") for n in nums]

    import ingestion.extract
    import ingestion.run

    monkeypatch.setattr(ingestion.run, "_pdf_page_count", lambda path: 1)  # noqa: ARG005
    monkeypatch.setattr(ingestion.extract, "extract_pdf", fake_extract)
    monkeypatch.setattr(
        documents_mod,
        "_indexed_pages",
        lambda course, document=None, owner=None: set(),  # noqa: ARG005
    )
    monkeypatch.setattr(documents_mod, "index_chunks", lambda chunks, **_: None)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    assert seen["hybrid"] is True
    assert events[-1]["type"] == "done"
    assert events[-1]["indexed"] > 0


def test_stream_ingest_pdf_forwards_extract_api_key(monkeypatch, tmp_path):
    # A visitor's own OpenAI key must reach extract_pdf's api_key argument so the
    # scanned-PDF vision call authenticates on their account, not the server's.
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF")

    seen: dict[str, object] = {}

    def fake_extract(p, course, *, pages=None, hybrid=False, api_key=None, **kwargs):  # noqa: ARG001
        seen["api_key"] = api_key
        nums = pages or [1]
        return [Page(course=course, page=n, text=f"text {n}", doc_type="slides") for n in nums]

    import ingestion.extract
    import ingestion.run

    monkeypatch.setattr(ingestion.run, "_pdf_page_count", lambda path: 1)  # noqa: ARG005
    monkeypatch.setattr(ingestion.extract, "extract_pdf", fake_extract)
    monkeypatch.setattr(
        documents_mod,
        "_indexed_pages",
        lambda course, document=None, owner=None: set(),  # noqa: ARG005
    )
    monkeypatch.setattr(documents_mod, "index_chunks", lambda chunks, **_: None)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets", extract_api_key="sk-visitor"))
    assert seen["api_key"] == "sk-visitor"
    assert events[-1]["type"] == "done"


def test_stream_ingest_md_ignores_api_key(monkeypatch, tmp_path):
    # The free .md path must index WITHOUT any key and must never touch the PDF
    # extractor (no vision, no network) even if a key is not supplied.
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome prose about wavelets.\n", encoding="utf-8")

    captured: list = []
    monkeypatch.setattr(documents_mod, "index_chunks", lambda chunks, **_: captured.extend(chunks))

    import ingestion.extract

    def boom_extract(*args, **kwargs):
        raise AssertionError("extract_pdf must not run for a .md file (free path)")

    monkeypatch.setattr(ingestion.extract, "extract_pdf", boom_extract)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    assert events[-1]["type"] == "done"
    assert events[-1]["indexed"] > 0


def test_stream_ingest_missing_openai_key_gives_clear_message(monkeypatch, tmp_path):
    # A scanned PDF whose vision call fails for missing OpenAI credentials must
    # surface the actionable "add your OpenAI key" message, not a raw SDK error.
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF")

    def fake_extract(*args, **kwargs):
        raise ValueError("Did not find openai_api_key, please add an environment variable")

    import ingestion.extract
    import ingestion.run

    monkeypatch.setattr(ingestion.run, "_pdf_page_count", lambda path: 1)  # noqa: ARG005
    monkeypatch.setattr(ingestion.extract, "extract_pdf", fake_extract)
    monkeypatch.setattr(
        documents_mod,
        "_indexed_pages",
        lambda course, document=None, owner=None: set(),  # noqa: ARG005
    )

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == documents_mod.MISSING_OPENAI_KEY_MESSAGE


def test_stream_ingest_unsupported_extension_emits_error(monkeypatch, tmp_path):
    # A clearly-unsupported file (not PDF, not .md/.txt) is reported as a clean
    # error event rather than blowing up on a raw fitz.open failure.
    path = tmp_path / "resume.docx"
    path.write_bytes(b"PK\x03\x04 not a real docx")

    def boom_count(path):  # noqa: ARG001
        raise AssertionError("the PDF page-count must not run for an unsupported file")

    import ingestion.run

    monkeypatch.setattr(ingestion.run, "_pdf_page_count", boom_count)

    events = list(documents_mod.stream_ingest(str(path), "Wavelets"))
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["message"] == documents_mod.UNSUPPORTED_FILE_MESSAGE


def test_ingest_document_unsupported_extension_raises(tmp_path):
    path = tmp_path / "slides.pptx"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ValueError, match="Unsupported file type"):
        documents_mod.ingest_document(str(path), "Wavelets")


def test_indexed_pages_scopes_to_course_and_document(monkeypatch):
    class _CapturingScroll:
        last_filter = None

        def __init__(self, *args, **kwargs):
            pass

        def scroll(self, *, scroll_filter, **kwargs):  # noqa: ARG002
            type(self).last_filter = scroll_filter
            return [SimpleNamespace(payload={"page": 1})], None

    _use_client(monkeypatch, _CapturingScroll)

    assert documents_mod._indexed_pages("Wavelets", "deck.pdf") == {1}
    # course + document -> two filter conditions.
    assert len(_CapturingScroll.last_filter.must) == 2
    # course only -> a single condition (backward-compatible).
    documents_mod._indexed_pages("Wavelets")
    assert len(_CapturingScroll.last_filter.must) == 1


# --- delete_documents: payload filter + count --------------------------------


class _DeleteClient:
    """A client recording the count/delete filters and returning a fixed count."""

    last_count_filter = None
    last_delete_selector = None

    def __init__(self, *args, **kwargs):
        pass

    def count(self, *, collection_name, count_filter, exact):  # noqa: ARG002
        type(self).last_count_filter = count_filter
        return SimpleNamespace(count=4)

    def delete(self, *, collection_name, points_selector):  # noqa: ARG002
        type(self).last_delete_selector = points_selector


def test_delete_documents_course_only(monkeypatch):
    _use_client(monkeypatch, _DeleteClient)
    deleted = documents_mod.delete_documents("Wavelets", None, "uA")
    assert deleted == 4
    # course condition + the strict owner-scope sub-filter (no chapter).
    assert len(_DeleteClient.last_count_filter.must) == 2


def test_delete_documents_course_and_chapter(monkeypatch):
    _use_client(monkeypatch, _DeleteClient)
    deleted = documents_mod.delete_documents("Wavelets", "Intro", "uA")
    assert deleted == 4
    # course + chapter + the strict owner-scope sub-filter.
    assert len(_DeleteClient.last_count_filter.must) == 3


def test_delete_documents_fail_closed_without_owner(monkeypatch):
    # No owner -> fail closed: delete nothing WITHOUT touching Qdrant (never wipe
    # every account's points for the course).
    class _BoomDeleteClient:
        def __init__(self, *args, **kwargs):
            pass

        def count(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("no Qdrant call must happen when the owner is None")

        def delete(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("no Qdrant call must happen when the owner is None")

    _use_client(monkeypatch, _BoomDeleteClient)
    assert documents_mod.delete_documents("Wavelets") == 0
    assert documents_mod.delete_documents("Wavelets", None, None) == 0


def test_delete_documents_degrades_on_error(monkeypatch):
    class _RaisingDeleteClient:
        def __init__(self, *args, **kwargs):
            pass

        def count(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("missing collection")

    _use_client(monkeypatch, _RaisingDeleteClient)
    assert documents_mod.delete_documents("Wavelets", None, "uA") == 0


# --- Per-account owner scoping -----------------------------------------------


def test_stamp_pages_sets_owner():
    pages = [
        Page(course="C", page=1, text="a", doc_type="slides"),
        Page(course="C", page=2, text="b", doc_type="slides"),
    ]
    documents_mod._stamp_pages(pages, None, "deck.pdf", "uA")
    assert all(p.owner == "uA" and p.document == "deck.pdf" for p in pages)


def test_stamp_pages_owner_none_stays_shared():
    pages = [Page(course="C", page=1, text="a", doc_type="slides")]
    documents_mod._stamp_pages(pages, None, "deck.pdf")
    assert pages[0].owner is None


def test_chunk_pages_copies_owner_and_ids_differ_per_owner():
    from ingestion.chunk import chunk_pages

    pa = Page(course="C", page=1, text="x", doc_type="slides", document="d", owner="uA")
    pb = Page(course="C", page=1, text="x", doc_type="slides", document="d", owner="uB")
    a = chunk_pages([pa])
    b = chunk_pages([pb])
    assert a[0].owner == "uA" and b[0].owner == "uB"
    # Different owners never collide on the same point id (no cross-account overwrite).
    assert a[0].id != b[0].id


def test_indexed_pages_scopes_to_owner(monkeypatch):
    class _CapturingScroll:
        last_filter = None

        def __init__(self, *args, **kwargs):
            pass

        def scroll(self, *, scroll_filter, **kwargs):  # noqa: ARG002
            type(self).last_filter = scroll_filter
            return [SimpleNamespace(payload={"page": 1})], None

    _use_client(monkeypatch, _CapturingScroll)
    documents_mod._indexed_pages("Wavelets", "deck.pdf", "uA")
    # course + document + owner -> three conditions.
    assert len(_CapturingScroll.last_filter.must) == 3


def test_list_documents_scopes_scroll_strictly_to_owner(monkeypatch):
    class _CapturingScroll:
        last_filter = "unset"

        def __init__(self, *args, **kwargs):
            pass

        def scroll(self, *, scroll_filter, **kwargs):  # noqa: ARG002
            type(self).last_filter = scroll_filter
            return [], None

    _use_client(monkeypatch, _CapturingScroll)
    documents_mod.list_documents(owner="uA")
    flt = _CapturingScroll.last_filter
    # Strict isolation: a single "owner == mine" must condition, no shared branch.
    assert flt is not None and flt.should is None and len(flt.must) == 1
    assert flt.must[0].key == "owner" and flt.must[0].match.value == "uA"


class _FilterAwareScroll:
    """A scroll client that honours the strict owner filter against canned points.

    Returns only the points whose ``owner`` matches the scroll filter's owner
    condition, so a test can assert an account's inventory contains only its own
    material (never another account's, never the owner-less legacy corpus).
    """

    points = [
        {"course": "Algebra", "chapter": None, "page": 1, "owner": "uA"},
        {"course": "Biology", "chapter": None, "page": 1, "owner": "uB"},
        {"course": "Legacy", "chapter": None, "page": 1, "owner": None},
    ]

    def __init__(self, *args, **kwargs):
        pass

    def scroll(self, *, scroll_filter, **kwargs):  # noqa: ARG002
        want = scroll_filter.must[0].match.value if scroll_filter is not None else None
        matched = [SimpleNamespace(payload=p) for p in self.points if p["owner"] == want]
        return matched, None


def test_list_documents_cross_account_isolation(monkeypatch):
    _use_client(monkeypatch, _FilterAwareScroll)
    # uA sees only its own course; never uB's, never the owner-less legacy course.
    a_courses = [c["course"] for c in documents_mod.list_documents(owner="uA")]
    b_courses = [c["course"] for c in documents_mod.list_documents(owner="uB")]
    assert a_courses == ["Algebra"]
    assert b_courses == ["Biology"]
    assert "Legacy" not in a_courses and "Legacy" not in b_courses


def test_delete_documents_owner_scopes_strictly_to_mine(monkeypatch):
    from qdrant_client.models import Filter

    _use_client(monkeypatch, _DeleteClient)
    documents_mod.delete_documents("Wavelets", None, "uA")
    conds = _DeleteClient.last_count_filter.must
    # course + a strict owner sub-filter (a nested Filter whose single `must`
    # condition is owner == mine), so the caller deletes only their own points.
    owner_filters = [c for c in conds if isinstance(c, Filter)]
    assert len(owner_filters) == 1
    assert owner_filters[0].should is None and len(owner_filters[0].must) == 1
    assert owner_filters[0].must[0].match.value == "uA"


class _FilterEvalClient:
    """A fake Qdrant client that actually evaluates delete/count filters.

    Holds a fixed set of point payloads and honours the ``course`` + strict owner
    scope built by :func:`delete_documents`, so the delete *scope* (not just the
    filter shape) can be asserted end to end.
    """

    points: list[dict] = []
    deleted: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def _cond_matches(cond, payload: dict) -> bool:
        from qdrant_client.models import FieldCondition, Filter

        if isinstance(cond, Filter):  # nested strict owner scope: all must match
            return all(_FilterEvalClient._cond_matches(c, payload) for c in (cond.must or []))
        if isinstance(cond, FieldCondition):
            return payload.get(cond.key) == cond.match.value
        return False

    @classmethod
    def _matching(cls, count_filter) -> list[dict]:
        return [
            p for p in cls.points if all(cls._cond_matches(c, p) for c in (count_filter.must or []))
        ]

    def count(self, *, collection_name, count_filter, exact):  # noqa: ARG002
        return SimpleNamespace(count=len(self._matching(count_filter)))

    def delete(self, *, collection_name, points_selector):  # noqa: ARG002
        type(self).deleted = self._matching(points_selector.filter)


def test_delete_documents_leaves_owner_less_legacy_course(monkeypatch):
    _FilterEvalClient.points = [
        {"course": "Wavelets", "owner": None},
        {"course": "Wavelets", "owner": None},
    ]
    _use_client(monkeypatch, _FilterEvalClient)
    # Strict isolation: owner-less (legacy) points are invisible, so uA cannot
    # delete them either -- nothing matches, 0 removed.
    assert documents_mod.delete_documents("Wavelets", None, "uA") == 0
    assert _FilterEvalClient.deleted == []


def test_delete_documents_removes_callers_own_course(monkeypatch):
    _FilterEvalClient.points = [
        {"course": "Wavelets", "owner": "uA"},
        {"course": "Wavelets", "owner": "uA"},
        {"course": "Wavelets", "owner": "uA"},
    ]
    _use_client(monkeypatch, _FilterEvalClient)
    assert documents_mod.delete_documents("Wavelets", None, "uA") == 3
    assert len(_FilterEvalClient.deleted) == 3


def test_delete_documents_leaves_another_accounts_owned_course(monkeypatch):
    _FilterEvalClient.points = [
        {"course": "Wavelets", "owner": "uB"},
        {"course": "Wavelets", "owner": "uB"},
    ]
    _use_client(monkeypatch, _FilterEvalClient)
    # uA must not be able to delete uB's OWNED points: nothing matches, 0 removed.
    assert documents_mod.delete_documents("Wavelets", None, "uA") == 0
    assert _FilterEvalClient.deleted == []


def test_delete_documents_only_removes_mine_when_mixed(monkeypatch):
    # A course shared (by name) across accounts: deleting as uA removes ONLY uA's
    # points, never uB's and never the owner-less legacy ones.
    _FilterEvalClient.points = [
        {"course": "Shared", "owner": "uA"},
        {"course": "Shared", "owner": "uB"},
        {"course": "Shared", "owner": None},
    ]
    _use_client(monkeypatch, _FilterEvalClient)
    assert documents_mod.delete_documents("Shared", None, "uA") == 1
    assert [p["owner"] for p in _FilterEvalClient.deleted] == ["uA"]


# --- rename_course / rename_chapter: filtered set_payload --------------------


class _SetPayloadClient:
    """Records the count/set_payload filters and payload; returns a fixed count."""

    last_count_filter = None
    last_payload = None
    last_points = None

    def __init__(self, *args, **kwargs):
        pass

    def count(self, *, collection_name, count_filter, exact):  # noqa: ARG002
        type(self).last_count_filter = count_filter
        return SimpleNamespace(count=3)

    def set_payload(self, *, collection_name, payload, points):  # noqa: ARG002
        type(self).last_payload = payload
        type(self).last_points = points


def test_rename_course_sets_payload_scoped_to_owner_and_course(monkeypatch):
    from qdrant_client.models import Filter

    _use_client(monkeypatch, _SetPayloadClient)
    assert documents_mod.rename_course("uA", "Old", "New") == 3
    assert _SetPayloadClient.last_payload == {"course": "New"}
    conds = _SetPayloadClient.last_count_filter.must
    # course condition + a strict owner sub-filter (a nested Filter whose single
    # `must` condition is owner == mine), and no chapter condition.
    assert len(conds) == 2
    owner_filters = [c for c in conds if isinstance(c, Filter)]
    assert len(owner_filters) == 1
    assert owner_filters[0].should is None and len(owner_filters[0].must) == 1
    assert owner_filters[0].must[0].key == "owner"
    assert owner_filters[0].must[0].match.value == "uA"
    # The update is scoped by that very filter, never a collection-wide set.
    assert _SetPayloadClient.last_points is _SetPayloadClient.last_count_filter


def test_rename_course_trims_new_name(monkeypatch):
    _use_client(monkeypatch, _SetPayloadClient)
    assert documents_mod.rename_course("uA", "Old", "  New  ") == 3
    assert _SetPayloadClient.last_payload == {"course": "New"}


def test_rename_chapter_sets_payload_scoped_to_owner_course_chapter(monkeypatch):
    from qdrant_client.models import Filter

    _use_client(monkeypatch, _SetPayloadClient)
    assert documents_mod.rename_chapter("uA", "Course", "Old", "New") == 3
    assert _SetPayloadClient.last_payload == {"chapter": "New"}
    conds = _SetPayloadClient.last_count_filter.must
    # course + chapter conditions + the strict owner sub-filter.
    assert len(conds) == 3
    field_keys = {c.key for c in conds if not isinstance(c, Filter)}
    assert field_keys == {"course", "chapter"}
    owner_filters = [c for c in conds if isinstance(c, Filter)]
    assert len(owner_filters) == 1 and owner_filters[0].must[0].match.value == "uA"


class _RenameBoomClient:
    """A client that must never be touched (fail-closed / no-op assertions)."""

    def __init__(self, *args, **kwargs):
        pass

    def count(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError("no Qdrant call must happen for a fail-closed/no-op rename")

    def set_payload(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError("no set_payload must happen for a fail-closed/no-op rename")


def test_rename_course_fail_closed_without_owner(monkeypatch):
    # No owner -> fail closed: rename nothing WITHOUT touching Qdrant (never a
    # collection-wide payload update).
    _use_client(monkeypatch, _RenameBoomClient)
    assert documents_mod.rename_course(None, "Old", "New") == 0
    assert documents_mod.rename_course("", "Old", "New") == 0


def test_rename_chapter_fail_closed_without_owner(monkeypatch):
    _use_client(monkeypatch, _RenameBoomClient)
    assert documents_mod.rename_chapter(None, "Course", "Old", "New") == 0
    assert documents_mod.rename_chapter("", "Course", "Old", "New") == 0


def test_rename_course_noop_leaves_qdrant_untouched(monkeypatch):
    # An empty/whitespace or unchanged new name is a no-op that never hits Qdrant.
    _use_client(monkeypatch, _RenameBoomClient)
    assert documents_mod.rename_course("uA", "Old", "   ") == 0
    assert documents_mod.rename_course("uA", "Old", "Old") == 0


def test_rename_chapter_noop_leaves_qdrant_untouched(monkeypatch):
    _use_client(monkeypatch, _RenameBoomClient)
    assert documents_mod.rename_chapter("uA", "Course", "Old", "  ") == 0
    assert documents_mod.rename_chapter("uA", "Course", "Old", "Old") == 0
    # The chapterless ("Uncategorized") group has no chapter value to match.
    assert documents_mod.rename_chapter("uA", "Course", "", "New") == 0


class _RenameEvalClient(_FilterEvalClient):
    """Evaluates the rename filter against canned points to prove the scope."""

    updated: list[dict] = []

    def set_payload(self, *, collection_name, payload, points):  # noqa: ARG002
        type(self).updated = self._matching(points)


def test_rename_course_only_updates_mine_when_mixed(monkeypatch):
    # A course shared (by name) across accounts: renaming as uA rewrites ONLY uA's
    # points, never uB's OWNED points and never the owner-less legacy ones.
    _RenameEvalClient.points = [
        {"course": "Shared", "owner": "uA"},
        {"course": "Shared", "owner": "uB"},
        {"course": "Shared", "owner": None},
    ]
    _use_client(monkeypatch, _RenameEvalClient)
    assert documents_mod.rename_course("uA", "Shared", "Renamed") == 1
    assert [p["owner"] for p in _RenameEvalClient.updated] == ["uA"]


def test_rename_course_leaves_another_accounts_owned_course(monkeypatch):
    _RenameEvalClient.points = [
        {"course": "Shared", "owner": "uB"},
        {"course": "Shared", "owner": "uB"},
    ]
    _use_client(monkeypatch, _RenameEvalClient)
    assert documents_mod.rename_course("uA", "Shared", "Renamed") == 0
    assert _RenameEvalClient.updated == []


def test_rename_documents_degrades_on_error(monkeypatch):
    class _RaisingClient:
        def __init__(self, *args, **kwargs):
            pass

        def count(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("missing collection")

    _use_client(monkeypatch, _RaisingClient)
    assert documents_mod.rename_course("uA", "Old", "New") == 0


# --- save_upload / stored_file_path / read_stored_file / list_course_files ---
# Local disk is always written (ingestion needs a real path -- see save_upload's
# docstring); R2 is an optional, best-effort DURABLE mirror activated only when
# `core.storage.configured()` is True. These tests fake `core.storage` itself
# (rather than boto3), the same seam `core.documents` calls through, matching how
# the rest of this file fakes `QdrantClient` instead of a real Qdrant server.


@pytest.fixture
def local_uploads(monkeypatch, tmp_path):
    """Point the local-disk upload root at an isolated tmp dir for this test."""
    monkeypatch.setattr(documents_mod, "UPLOADS_DIR", str(tmp_path))
    return tmp_path


def _disable_r2(monkeypatch):
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: False)


def test_save_upload_writes_local_disk_when_r2_not_configured(monkeypatch, local_uploads):
    _disable_r2(monkeypatch)
    monkeypatch.setattr(
        documents_mod.storage,
        "put_object",
        lambda *a, **k: pytest.fail("R2 must not be touched when not configured"),
    )

    path = documents_mod.save_upload(b"hello", "Wavelets", "notes.pdf")

    assert path == str(local_uploads / "Wavelets" / "notes.pdf")
    assert (local_uploads / "Wavelets" / "notes.pdf").read_bytes() == b"hello"


def test_save_upload_also_mirrors_to_r2_when_configured(monkeypatch, local_uploads):
    uploaded = {}
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)
    monkeypatch.setattr(
        documents_mod.storage, "put_object", lambda key, data: uploaded.update(key=key, data=data)
    )

    path = documents_mod.save_upload(b"hello", "Wavelets", "notes.pdf")

    # The local copy is still written unconditionally (ingestion reads it).
    assert (local_uploads / "Wavelets" / "notes.pdf").read_bytes() == b"hello"
    assert path == str(local_uploads / "Wavelets" / "notes.pdf")
    # ...and mirrored to R2 under the equivalent <course>/<file> key.
    assert uploaded == {"key": "Wavelets/notes.pdf", "data": b"hello"}


def test_save_upload_swallows_r2_failure(monkeypatch, local_uploads):
    # A durability hiccup must never fail the upload/ingest request: the local
    # copy (and thus ingestion) already succeeded.
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)

    def boom(*_a, **_k):
        raise RuntimeError("R2 unreachable")

    monkeypatch.setattr(documents_mod.storage, "put_object", boom)

    path = documents_mod.save_upload(b"hello", "Wavelets", "notes.pdf")
    assert (local_uploads / "Wavelets" / "notes.pdf").read_bytes() == b"hello"
    assert path == str(local_uploads / "Wavelets" / "notes.pdf")


def test_stored_file_path_local_lookup_and_traversal_guard(monkeypatch, local_uploads):
    (local_uploads / "Wavelets").mkdir()
    (local_uploads / "Wavelets" / "notes.pdf").write_bytes(b"hi")

    assert documents_mod.stored_file_path("Wavelets", "notes.pdf") == str(
        local_uploads / "Wavelets" / "notes.pdf"
    )
    assert documents_mod.stored_file_path("Wavelets", "missing.pdf") is None
    # A traversal attempt is sanitized by `_safe_filename` before resolution, so
    # it never escapes the course directory.
    assert documents_mod.stored_file_path("Wavelets", "../../etc/passwd") is None


@pytest.mark.parametrize("value", [".", "..", "../..", "  ..  ", "/", "///"])
def test_slug_rejects_traversal_components(value):
    # Dots survive the character filter, so a course named `.`/`..` must never
    # yield a path-traversal component; it falls back to the default like empty.
    assert documents_mod._slug(value) not in {".", ".."}
    assert documents_mod._slug("..") == "course"


@pytest.mark.parametrize("value", [".", "..", "../secret", "..\t"])
def test_safe_filename_rejects_traversal_components(value):
    assert documents_mod._safe_filename(value) not in {".", ".."}


@pytest.mark.parametrize("course", ["Wavelets", "..", "../../etc", "  ..  ", "."])
def test_course_dir_stays_inside_uploads_root(course, local_uploads):
    # The course component is validated against the fixed uploads root, so no
    # crafted course name can resolve to a sibling/parent directory.
    root = os.path.abspath(str(local_uploads))
    resolved = documents_mod._course_dir(course)
    assert os.path.commonpath([root, resolved]) == root


def test_save_upload_traversal_stays_inside_uploads_root(monkeypatch, local_uploads):
    _disable_r2(monkeypatch)
    root = os.path.abspath(str(local_uploads))

    # A course named `..` and a path-like filename must both resolve to a file
    # strictly under the uploads root -- never a sibling/parent directory.
    path = documents_mod.save_upload(b"payload", "..", "../../evil.pdf")

    resolved = os.path.abspath(path)
    assert os.path.commonpath([root, resolved]) == root
    assert os.path.isfile(resolved)


def test_read_stored_file_local_only_when_r2_not_configured(monkeypatch, local_uploads):
    _disable_r2(monkeypatch)
    (local_uploads / "Wavelets").mkdir()
    (local_uploads / "Wavelets" / "notes.pdf").write_bytes(b"hi")

    assert documents_mod.read_stored_file("Wavelets", "notes.pdf") == b"hi"
    assert documents_mod.read_stored_file("Wavelets", "missing.pdf") is None


def test_read_stored_file_prefers_r2_when_configured(monkeypatch, local_uploads):
    # Local disk also has a (stale/different) copy; R2 wins, because it is the
    # durable source of truth in production.
    (local_uploads / "Wavelets").mkdir()
    (local_uploads / "Wavelets" / "notes.pdf").write_bytes(b"stale-local-copy")
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)
    monkeypatch.setattr(
        documents_mod.storage,
        "get_object",
        lambda key: b"from-r2" if key == "Wavelets/notes.pdf" else None,
    )

    assert documents_mod.read_stored_file("Wavelets", "notes.pdf") == b"from-r2"


def test_read_stored_file_falls_back_to_local_when_r2_misses(monkeypatch, local_uploads):
    # A file uploaded before R2 was configured (or a transient R2 miss) must
    # still be viewable via the local copy.
    (local_uploads / "Wavelets").mkdir()
    (local_uploads / "Wavelets" / "notes.pdf").write_bytes(b"local-only")
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)
    monkeypatch.setattr(documents_mod.storage, "get_object", lambda key: None)

    assert documents_mod.read_stored_file("Wavelets", "notes.pdf") == b"local-only"


def test_read_stored_file_none_when_neither_backend_has_it(monkeypatch, local_uploads):
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)
    monkeypatch.setattr(documents_mod.storage, "get_object", lambda key: None)

    assert documents_mod.read_stored_file("Wavelets", "notes.pdf") is None


def test_list_course_files_local_only_when_r2_not_configured(monkeypatch, local_uploads):
    _disable_r2(monkeypatch)
    (local_uploads / "Wavelets").mkdir()
    (local_uploads / "Wavelets" / "a.pdf").write_bytes(b"1")
    (local_uploads / "Wavelets" / "b.pdf").write_bytes(b"2")

    names = documents_mod.list_course_files("Wavelets")
    assert set(names) == {"a.pdf", "b.pdf"}


def test_list_course_files_prefers_r2_and_appends_local_only_names(monkeypatch, local_uploads):
    # "r2.pdf" is only in R2, "local-only.pdf" is only on local disk (e.g.
    # uploaded before R2 was configured): both must remain visible.
    (local_uploads / "Wavelets").mkdir()
    (local_uploads / "Wavelets" / "local-only.pdf").write_bytes(b"x")
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)
    monkeypatch.setattr(documents_mod.storage, "list_keys", lambda prefix: [f"{prefix}r2.pdf"])

    names = documents_mod.list_course_files("Wavelets")
    assert "r2.pdf" in names
    assert "local-only.pdf" in names


def test_list_course_files_no_course_dir_and_r2_disabled_is_empty(monkeypatch, local_uploads):
    _disable_r2(monkeypatch)
    assert documents_mod.list_course_files("NoSuchCourse") == []


# --- _move_course_dir: local rename + R2 copy-prefix --------------------------


def test_move_course_dir_renames_local_and_copies_r2_prefix(monkeypatch, local_uploads):
    (local_uploads / "Old").mkdir()
    (local_uploads / "Old" / "notes.pdf").write_bytes(b"hi")
    calls = []
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)
    monkeypatch.setattr(
        documents_mod.storage, "copy_prefix", lambda old, new: calls.append((old, new))
    )

    documents_mod._move_course_dir("Old", "New")

    assert not (local_uploads / "Old").exists()
    assert (local_uploads / "New" / "notes.pdf").read_bytes() == b"hi"
    assert calls == [("Old/", "New/")]


def test_move_course_dir_skips_r2_copy_when_not_configured(monkeypatch, local_uploads):
    _disable_r2(monkeypatch)
    monkeypatch.setattr(
        documents_mod.storage,
        "copy_prefix",
        lambda *a, **k: pytest.fail("R2 must not be touched when not configured"),
    )
    # No local source dir either: this must stay a total no-op, never raising.
    documents_mod._move_course_dir("Old", "New")


def test_move_course_dir_never_raises_when_r2_copy_fails(monkeypatch, local_uploads):
    monkeypatch.setattr(documents_mod.storage, "configured", lambda: True)

    def boom(*_a, **_k):
        raise RuntimeError("R2 unreachable")

    monkeypatch.setattr(documents_mod.storage, "copy_prefix", boom)
    documents_mod._move_course_dir("Old", "New")  # must not raise


# --- /documents routes -------------------------------------------------------
# Gated on the optional `api` extra (FastAPI). The core tests above always run.

_HAS_API = True
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from api import runtime as api_main
    from api.main import app
except ImportError:  # pragma: no cover - exercised only without the api extra
    _HAS_API = False

requires_api = pytest.mark.skipif(not _HAS_API, reason="requires the 'api' extra (FastAPI)")


@pytest.fixture
def client():
    """Bind the API to a fresh in-memory SQLite DB and yield a test client."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    api_main.configure_engine(engine)
    with TestClient(app) as test_client:
        yield test_client
    api_main._engine = None


@requires_api
def test_documents_route_returns_inventory(client, monkeypatch):
    inventory = [
        {
            "course": "Wavelets",
            "total_pages": 3,
            "chapters": [{"chapter": "Intro", "pages": 2}, {"chapter": None, "pages": 1}],
            "files": ["notes.pdf"],
        }
    ]
    monkeypatch.setattr(api_main, "list_documents", lambda owner=None: inventory)
    response = client.get("/documents")
    assert response.status_code == 200
    assert response.json() == inventory


@requires_api
def test_documents_route_empty(client, monkeypatch):
    monkeypatch.setattr(api_main, "list_documents", lambda owner=None: [])
    response = client.get("/documents")
    assert response.status_code == 200
    assert response.json() == []


def _wait_for_job(client, job_id: str, *, timeout: float = 5.0) -> dict:
    """Poll the job endpoint until the ingest thread reaches a terminal status."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/documents/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


@requires_api
def test_upload_route_returns_job_and_finishes(client, monkeypatch):
    seen: dict = {}

    def fake_save(data, course, filename):
        seen["bytes"] = data
        seen["course"] = course
        return f"/tmp/{filename}"

    def fake_stream(path, course, chapter=None, **kwargs):  # noqa: ARG001
        seen["chapter"] = chapter
        yield {"type": "start", "total": 2, "skipped": 0}
        yield {"type": "progress", "done": 2, "total": 2, "indexed": 2, "elapsed": 0.1}
        yield {
            "type": "done",
            "indexed": 2,
            "skipped": 0,
            "total": 2,
            "reason": "indexed",
            "elapsed": 0.1,
        }

    monkeypatch.setattr(api_main, "save_upload", fake_save)
    monkeypatch.setattr(api_main, "stream_ingest", fake_stream)

    response = client.post(
        "/documents/upload",
        files={"file": ("notes.md", b"hello world", "text/markdown")},
        data={"course": "Wavelets", "chapter": "Intro", "student_id": "uA"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert isinstance(job_id, str) and job_id

    job = _wait_for_job(client, job_id)
    assert job["status"] == "done"
    assert job["indexed"] == 2
    assert job["total"] == 2
    assert job["reason"] == "indexed"
    assert job["type"] == "done"
    assert job["course"] == "Wavelets"
    assert job["filename"] == "notes.md"
    assert job["finished_at"]
    assert seen["bytes"] == b"hello world"
    assert seen["course"] == "Wavelets"
    assert seen["chapter"] == "Intro"


@requires_api
def test_upload_route_blank_chapter_becomes_null(client, monkeypatch):
    seen: dict = {}

    def fake_stream(path, course, chapter=None, **kwargs):  # noqa: ARG001
        seen["chapter"] = chapter
        yield {"type": "done", "indexed": 0, "total": 0, "reason": "empty", "elapsed": 0.0}

    monkeypatch.setattr(api_main, "save_upload", lambda *a, **k: "/tmp/x.txt")
    monkeypatch.setattr(api_main, "stream_ingest", fake_stream)
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"content", "text/plain")},
        data={"course": "Wavelets", "chapter": "   ", "student_id": "uA"},
    )
    assert response.status_code == 202
    _wait_for_job(client, response.json()["job_id"])
    assert seen["chapter"] is None


@requires_api
def test_upload_route_requires_student_id(client):
    # student_id is required so an upload is always owner-stamped (never left
    # owner-less, which strict isolation would make invisible). Missing -> 422.
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"content", "text/plain")},
        data={"course": "Wavelets"},
    )
    assert response.status_code == 422


@requires_api
def test_upload_route_stamps_owner_from_student_id(client, monkeypatch):
    seen: dict = {}

    def fake_stream(path, course, chapter=None, *, owner=None, **kwargs):  # noqa: ARG001
        seen["owner"] = owner
        yield {"type": "done", "indexed": 1, "total": 1, "reason": "indexed", "elapsed": 0.0}

    monkeypatch.setattr(api_main, "save_upload", lambda *a, **k: "/tmp/x.txt")
    monkeypatch.setattr(api_main, "stream_ingest", fake_stream)
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"content", "text/plain")},
        data={"course": "Wavelets", "student_id": "uA"},
    )
    assert response.status_code == 202
    _wait_for_job(client, response.json()["job_id"])
    assert seen["owner"] == "uA"


@requires_api
def test_upload_route_error_event_marks_job_error(client, monkeypatch):
    def fake_stream(path, course, chapter=None, **kwargs):  # noqa: ARG001
        yield {"type": "start", "total": 3, "skipped": 0}
        yield {"type": "error", "message": "boom", "done": 0, "total": 3, "indexed": 0}

    monkeypatch.setattr(api_main, "save_upload", lambda *a, **k: "/tmp/x.pdf")
    monkeypatch.setattr(api_main, "stream_ingest", fake_stream)
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
        data={"course": "Wavelets", "student_id": "uA"},
    )
    assert response.status_code == 202
    job = _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "error"
    assert job["message"] == "boom"


@requires_api
def test_job_route_unknown_id_404(client):
    response = client.get("/documents/jobs/does-not-exist")
    assert response.status_code == 404


@requires_api
def test_jobs_list_includes_started_job(client, monkeypatch):
    def fake_stream(path, course, chapter=None, **kwargs):  # noqa: ARG001
        yield {"type": "done", "indexed": 1, "total": 1, "reason": "indexed", "elapsed": 0.0}

    monkeypatch.setattr(api_main, "save_upload", lambda *a, **k: "/tmp/x.txt")
    monkeypatch.setattr(api_main, "stream_ingest", fake_stream)
    response = client.post(
        "/documents/upload",
        files={"file": ("a.txt", b"x", "text/plain")},
        data={"course": "Wavelets", "student_id": "uA"},
    )
    job_id = response.json()["job_id"]
    _wait_for_job(client, job_id)
    listed = client.get("/documents/jobs")
    assert listed.status_code == 200
    assert any(j["job_id"] == job_id for j in listed.json())


@requires_api
def test_document_file_route_serves_stored_file(client, monkeypatch):
    # The route now reads bytes via read_stored_file (R2-aware; local disk is
    # just one of its possible sources), not a raw filesystem path -- so it
    # works identically whether the bytes came from R2 or local disk.
    monkeypatch.setattr(api_main, "read_stored_file", lambda course, name: b"%PDF-1.4 fake")
    response = client.get("/documents/file", params={"course": "Wavelets", "name": "notes.pdf"})
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake"
    assert "notes.pdf" in response.headers["content-disposition"]


@requires_api
def test_document_file_route_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(api_main, "read_stored_file", lambda course, name: None)
    response = client.get("/documents/file", params={"course": "X", "name": "y.pdf"})
    assert response.status_code == 404


@requires_api
def test_delete_route_returns_count(client, monkeypatch):
    seen: dict = {}

    def fake_delete(course, chapter=None, owner=None):
        seen["course"] = course
        seen["chapter"] = chapter
        return 5

    monkeypatch.setattr(api_main, "delete_documents", fake_delete)

    response = client.delete("/documents", params={"course": "Wavelets", "chapter": "Intro"})
    assert response.status_code == 200
    assert response.json() == {"deleted": 5}
    assert seen == {"course": "Wavelets", "chapter": "Intro"}


@requires_api
def test_delete_route_requires_course(client):
    response = client.delete("/documents")
    assert response.status_code == 422


@requires_api
def test_rename_route_renames_course(client, monkeypatch):
    seen: dict = {}

    def fake_rename_course(owner, old, new):
        seen["args"] = (owner, old, new)
        return 4

    monkeypatch.setattr(api_main, "rename_course", fake_rename_course)
    response = client.post(
        "/documents/rename",
        json={"student_id": "uA", "course": "Old", "new_course": "New"},
    )
    assert response.status_code == 200
    assert response.json() == {"course_updated": 4, "chapter_updated": 0}
    assert seen["args"] == ("uA", "Old", "New")


@requires_api
def test_rename_route_renames_chapter(client, monkeypatch):
    seen: dict = {}

    def fake_rename_chapter(owner, course, old, new):
        seen["args"] = (owner, course, old, new)
        return 2

    monkeypatch.setattr(api_main, "rename_chapter", fake_rename_chapter)
    response = client.post(
        "/documents/rename",
        json={"student_id": "uA", "course": "C", "chapter": "Old", "new_chapter": "New"},
    )
    assert response.status_code == 200
    assert response.json() == {"course_updated": 0, "chapter_updated": 2}
    assert seen["args"] == ("uA", "C", "Old", "New")


@requires_api
def test_rename_route_renames_chapter_before_course(client, monkeypatch):
    # A combined rename applies the chapter first (under the ORIGINAL course name)
    # so the chapter filter still matches, then renames the course.
    order: list[str] = []

    def fake_rename_chapter(owner, course, old, new):  # noqa: ARG001
        order.append("chapter")
        return 1

    def fake_rename_course(owner, old, new):  # noqa: ARG001
        order.append("course")
        return 2

    monkeypatch.setattr(api_main, "rename_chapter", fake_rename_chapter)
    monkeypatch.setattr(api_main, "rename_course", fake_rename_course)
    response = client.post(
        "/documents/rename",
        json={
            "student_id": "uA",
            "course": "C",
            "chapter": "Old",
            "new_chapter": "NewCh",
            "new_course": "NewC",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"course_updated": 2, "chapter_updated": 1}
    assert order == ["chapter", "course"]


@requires_api
def test_rename_route_requires_a_rename(client):
    # Neither a course rename nor a full chapter rename requested -> 400.
    response = client.post("/documents/rename", json={"student_id": "uA", "course": "C"})
    assert response.status_code == 400


@requires_api
def test_rename_route_requires_student_id(client):
    response = client.post("/documents/rename", json={"course": "C", "new_course": "N"})
    assert response.status_code == 422
