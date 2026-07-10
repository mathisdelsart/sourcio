"""Tests for `core.storage`: the optional Cloudflare R2 (S3-compatible) backend
for durable storage of uploaded course-file originals.

`boto3` is never imported here, nor required to be installed: `core.storage._client`
(the one place `boto3` would be imported, lazily) is monkeypatched wholesale with
a fake S3-shaped client exposing only the methods this module actually calls
(`put_object`/`get_object`/`list_objects_v2`/`copy_object`/`delete_object`),
matching how `tests/test_documents.py` already fakes `QdrantClient` instead of
pulling in a new test dependency like `moto`.
"""

from datetime import datetime

import pytest

import core.storage as storage_mod
from core.config import Settings

# --- test fixtures / fakes ----------------------------------------------------


def _configured_settings(**overrides) -> Settings:
    values = {
        "r2_account_id": "acct123",
        "r2_access_key_id": "key",
        "r2_secret_access_key": "secret",
        "r2_bucket": "bucket",
    }
    values.update(overrides)
    return Settings(**values)


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    """Records calls and serves objects from an in-memory dict, S3-shaped."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.mtimes: dict[str, datetime] = {}
        self.deleted: list[str] = []
        self.copies: list[tuple[str, str]] = []

    def put_object(self, *, Bucket, Key, Body):  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _FakeBody(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):  # noqa: N803, ARG002
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        contents = [
            {"Key": k, "LastModified": self.mtimes.get(k, datetime(2024, 1, 1))} for k in keys
        ]
        return {"Contents": contents, "IsTruncated": False}

    def copy_object(self, *, Bucket, CopySource, Key):  # noqa: N803
        self.copies.append((CopySource["Key"], Key))
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.deleted.append(Key)
        self.objects.pop(Key, None)


# --- configured(): the selection switch ---------------------------------------


def test_configured_true_only_when_all_four_settings_present(monkeypatch):
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    assert storage_mod.configured() is True


@pytest.mark.parametrize(
    "missing",
    ["r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"],
)
def test_configured_false_when_any_single_setting_missing(monkeypatch, missing):
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings(**{missing: ""}))
    assert storage_mod.configured() is False


def test_configured_false_by_default(monkeypatch):
    monkeypatch.setattr(storage_mod, "get_settings", lambda: Settings())
    assert storage_mod.configured() is False


# --- put_object -----------------------------------------------------------------


def test_put_object_uploads_bytes(monkeypatch):
    client = _FakeS3Client()
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    storage_mod.put_object("Wavelets/notes.pdf", b"hello")

    assert client.objects["Wavelets/notes.pdf"] == b"hello"


def test_put_object_raises_on_failure(monkeypatch):
    class BoomClient:
        def put_object(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("network down")

    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: BoomClient())

    with pytest.raises(RuntimeError):
        storage_mod.put_object("k", b"data")


# --- get_object -----------------------------------------------------------------


def test_get_object_returns_bytes(monkeypatch):
    client = _FakeS3Client()
    client.objects["Wavelets/notes.pdf"] = b"hello"
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    assert storage_mod.get_object("Wavelets/notes.pdf") == b"hello"


def test_get_object_returns_none_when_missing(monkeypatch):
    client = _FakeS3Client()
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    assert storage_mod.get_object("missing") is None


def test_get_object_returns_none_on_any_error(monkeypatch):
    class BoomClient:
        def get_object(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: BoomClient())

    assert storage_mod.get_object("k") is None


# --- list_keys --------------------------------------------------------------


def test_list_keys_newest_first(monkeypatch):
    client = _FakeS3Client()
    client.objects = {"c/a.pdf": b"1", "c/b.pdf": b"2", "other/x.pdf": b"3"}
    client.mtimes = {"c/a.pdf": datetime(2024, 1, 1), "c/b.pdf": datetime(2024, 6, 1)}
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    assert storage_mod.list_keys("c/") == ["c/b.pdf", "c/a.pdf"]


def test_list_keys_paginates_through_truncated_results(monkeypatch):
    class PagedClient:
        def __init__(self):
            self.tokens_seen: list[str | None] = []

        def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):  # noqa: N803, ARG002
            self.tokens_seen.append(ContinuationToken)
            if ContinuationToken is None:
                return {
                    "Contents": [{"Key": "c/a.pdf", "LastModified": datetime(2024, 1, 1)}],
                    "IsTruncated": True,
                    "NextContinuationToken": "page2",
                }
            return {
                "Contents": [{"Key": "c/b.pdf", "LastModified": datetime(2024, 2, 1)}],
                "IsTruncated": False,
            }

    client = PagedClient()
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    assert storage_mod.list_keys("c/") == ["c/b.pdf", "c/a.pdf"]
    assert client.tokens_seen == [None, "page2"]


def test_list_keys_degrades_to_empty_on_error(monkeypatch):
    class BoomClient:
        def list_objects_v2(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: BoomClient())

    assert storage_mod.list_keys("c/") == []


# --- copy_prefix ------------------------------------------------------------


def test_copy_prefix_copies_then_deletes_every_object(monkeypatch):
    client = _FakeS3Client()
    client.objects = {"old/a.pdf": b"1", "old/b.pdf": b"2"}
    client.mtimes = {"old/a.pdf": datetime(2024, 1, 1), "old/b.pdf": datetime(2024, 1, 2)}
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    storage_mod.copy_prefix("old/", "new/")

    assert client.objects.get("new/a.pdf") == b"1"
    assert client.objects.get("new/b.pdf") == b"2"
    assert "old/a.pdf" not in client.objects
    assert "old/b.pdf" not in client.objects
    assert set(client.deleted) == {"old/a.pdf", "old/b.pdf"}


def test_copy_prefix_no_objects_is_a_silent_no_op(monkeypatch):
    client = _FakeS3Client()
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    storage_mod.copy_prefix("old/", "new/")  # must not raise

    assert client.copies == []
    assert client.deleted == []


def test_copy_prefix_never_raises_when_listing_fails(monkeypatch):
    class BoomClient:
        def list_objects_v2(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: BoomClient())

    storage_mod.copy_prefix("old/", "new/")  # must not raise


def test_copy_prefix_never_raises_when_a_single_copy_fails(monkeypatch):
    client = _FakeS3Client()
    client.objects = {"old/a.pdf": b"1"}
    client.mtimes = {"old/a.pdf": datetime(2024, 1, 1)}

    def boom_copy(*, Bucket, CopySource, Key):  # noqa: N803, ARG001
        raise RuntimeError("copy failed")

    client.copy_object = boom_copy
    monkeypatch.setattr(storage_mod, "get_settings", lambda: _configured_settings())
    monkeypatch.setattr(storage_mod, "_client", lambda: client)

    storage_mod.copy_prefix("old/", "new/")  # must not raise despite the mid-loop failure
