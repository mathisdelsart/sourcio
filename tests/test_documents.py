"""Tests for the document inventory/management layer (``core.documents``) and
the ``/documents`` routes.

No real Qdrant, embedding model, vision LLM, or network call is made: the
``QdrantClient`` is replaced with a fake exposing only ``scroll``/``count``/
``delete``, the ingestion calls are stubbed, and the API is bound to an
in-memory SQLite database. The inventory grouping, the ingest routing, the
delete filter, and graceful handling of an empty/missing collection are all
exercised in isolation.
"""

from types import SimpleNamespace

import pytest

import core.documents as documents_mod
from ingestion.schema import Page

# --- core.jobs: the in-memory background-job registry ------------------------


def test_jobs_create_update_get_and_terminal_stamp():
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


def test_jobs_update_unknown_id_is_noop():
    import core.jobs as jobs_mod

    jobs_mod.update_job("nope", {"status": "done"})  # must not raise
    assert jobs_mod.get_job("nope") is None


def test_jobs_prune_drops_stale_finished_jobs(monkeypatch):
    from datetime import UTC, datetime, timedelta

    import core.jobs as jobs_mod

    old_id = jobs_mod.create_job("Old", None, "old.pdf")
    jobs_mod.update_job(old_id, {"status": "done"})
    # Backdate its completion beyond the retention window.
    stale = datetime.now(UTC) - jobs_mod._RETENTION - timedelta(minutes=1)
    with jobs_mod._lock:
        jobs_mod._jobs[old_id]["finished_at"] = stale.isoformat()

    # Creating a new job prunes stale finished ones.
    new_id = jobs_mod.create_job("New", None, "new.pdf")
    assert jobs_mod.get_job(old_id) is None
    assert jobs_mod.get_job(new_id) is not None


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
    _use_client(monkeypatch, _ScrollClient)
    inventory = documents_mod.list_documents()

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
    assert documents_mod.list_documents() == []


def test_list_documents_missing_collection_degrades(monkeypatch):
    _use_client(monkeypatch, _RaisingScrollClient)
    assert documents_mod.list_documents() == []


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
    deleted = documents_mod.delete_documents("Wavelets")
    assert deleted == 4
    # One condition (course) when no chapter is given.
    assert len(_DeleteClient.last_count_filter.must) == 1


def test_delete_documents_course_and_chapter(monkeypatch):
    _use_client(monkeypatch, _DeleteClient)
    deleted = documents_mod.delete_documents("Wavelets", "Intro")
    assert deleted == 4
    # Two conditions (course + chapter) when a chapter is given.
    assert len(_DeleteClient.last_count_filter.must) == 2


def test_delete_documents_degrades_on_error(monkeypatch):
    class _RaisingDeleteClient:
        def __init__(self, *args, **kwargs):
            pass

        def count(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("missing collection")

    _use_client(monkeypatch, _RaisingDeleteClient)
    assert documents_mod.delete_documents("Wavelets") == 0


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


def test_list_documents_scopes_scroll_by_owner(monkeypatch):
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
    # The owner-scope sub-filter is "mine OR unset" (a should of two conditions).
    assert flt is not None and len(flt.should) == 2

    # Without an owner the scroll stays unscoped (global), unchanged.
    documents_mod.list_documents()
    assert _CapturingScroll.last_filter is None


def test_delete_documents_owner_is_mine_only(monkeypatch):
    from qdrant_client.models import FieldCondition, Filter

    _use_client(monkeypatch, _DeleteClient)
    documents_mod.delete_documents("Wavelets", None, "uA")
    conds = _DeleteClient.last_count_filter.must
    # course + a MINE-ONLY owner condition: an exact FieldCondition match, never
    # a nested shared/legacy OR filter, so shared/other points are never deleted.
    owner_conds = [c for c in conds if isinstance(c, FieldCondition) and c.key == "owner"]
    assert len(owner_conds) == 1 and owner_conds[0].match.value == "uA"
    assert all(not isinstance(c, Filter) for c in conds)


# --- /documents routes -------------------------------------------------------
# Gated on the optional `api` extra (FastAPI). The core tests above always run.

_HAS_API = True
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    import api.main as api_main
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
        data={"course": "Wavelets", "chapter": "Intro"},
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
        data={"course": "Wavelets", "chapter": "   "},
    )
    assert response.status_code == 202
    _wait_for_job(client, response.json()["job_id"])
    assert seen["chapter"] is None


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
        data={"course": "Wavelets"},
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
        data={"course": "Wavelets"},
    )
    job_id = response.json()["job_id"]
    _wait_for_job(client, job_id)
    listed = client.get("/documents/jobs")
    assert listed.status_code == 200
    assert any(j["job_id"] == job_id for j in listed.json())


@requires_api
def test_document_file_route_serves_stored_file(client, monkeypatch, tmp_path):
    stored = tmp_path / "notes.pdf"
    stored.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(api_main, "stored_file_path", lambda course, name: str(stored))
    response = client.get("/documents/file", params={"course": "Wavelets", "name": "notes.pdf"})
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake"


@requires_api
def test_document_file_route_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(api_main, "stored_file_path", lambda course, name: None)
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
