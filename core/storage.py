"""Durable object storage for uploaded course-file originals (Cloudflare R2).

Uploaded PDFs/``.md``/``.txt`` originals are saved to local disk by
``core.documents`` so the "view original file" feature can re-open them later.
That works for local development, but the production API runs inside an
ephemeral container (Hugging Face Spaces, see ``docs/DEPLOY-API.md``): every
redeploy or free-tier sleep/wake cycle wipes the filesystem, silently losing
every stored original. The *indexed* content survives fine (chunks + embeddings
live in Qdrant Cloud, a genuinely persistent external service) -- only the raw
original file, which was never durably stored anywhere, is lost.

This module is a thin, optional S3-compatible object-storage backend for
Cloudflare R2 (R2 speaks the S3 API, so the AWS SDK ``boto3`` talks to it
directly via a custom ``endpoint_url`` -- no separate R2 SDK is needed). It
activates automatically, and only, when all of the ``R2_*`` settings are
present (see ``core.config.Settings``); with any of them empty (the default),
:func:`configured` returns False and ``core.documents`` keeps behaving exactly
as it did before R2 existed (local disk only, zero setup -- the project's
default posture, matching the BYO-LLM-key "optional upgrade path, sane free
default" pattern described in CLAUDE.md).

``boto3`` is imported lazily inside :func:`_client`, so importing this module
unconditionally (as ``core.documents`` now does) never requires the optional
``storage`` extra to be installed when R2 is not configured -- e.g. every local
dev run and most of the test suite.

Every function that touches the network degrades gracefully rather than
raising into a caller that only wanted a secondary/best-effort operation:
:func:`get_object` and :func:`list_keys` return ``None``/``[]`` on any error,
and :func:`copy_prefix` never raises. :func:`put_object` is the one exception
-- it raises on failure so ``core.documents.save_upload`` can decide (and
currently does) to swallow it itself, keeping that policy decision visible at
the call site instead of hidden in this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.config import get_settings


def configured() -> bool:
    """Return whether all four R2 settings are present, selecting the R2 backend.

    Presence (not truthiness of any single value) of the account id, access key,
    secret key and bucket is what switches ``core.documents`` from local-disk-only
    to R2-backed storage; any missing field keeps the local-disk fallback active.
    """
    settings = get_settings()
    return bool(
        settings.r2_account_id
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and settings.r2_bucket
    )


def _client() -> Any:
    """Build a boto3 S3 client pointed at the account's R2 endpoint.

    Cloudflare R2's S3-compatible endpoint is derived from the account id
    (``https://<account_id>.r2.cloudflarestorage.com``), so no separate endpoint
    setting is needed. ``region_name="auto"`` is R2's documented convention (R2
    has no AWS-style regions). Imported lazily so ``boto3`` is only ever required
    when R2 is actually configured.
    """
    import boto3

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def put_object(key: str, data: bytes) -> None:
    """Upload ``data`` to R2 under ``key``, overwriting any existing object.

    Raises on failure (network error, bad credentials, missing bucket, ...): the
    caller is expected to decide whether that failure should be swallowed (see
    ``core.documents.save_upload``, which treats this as best-effort so a
    durability hiccup never fails the upload/ingest request that already
    succeeded locally).
    """
    settings = get_settings()
    _client().put_object(Bucket=settings.r2_bucket, Key=key, Body=data)


def get_object(key: str) -> bytes | None:
    """Download the object at ``key`` from R2, or ``None`` if missing or on any error.

    Never raises: a missing key, a transient network error, or a misconfigured
    bucket are all treated the same way by callers -- "not found here, fall back
    to the next source" -- so this stays a pure lookup with no exception contract
    to thread through ``core.documents``.
    """
    settings = get_settings()
    try:
        response = _client().get_object(Bucket=settings.r2_bucket, Key=key)
        return response["Body"].read()
    except Exception:
        return None


def list_keys(prefix: str) -> list[str]:
    """List object keys under ``prefix``, newest first by ``LastModified``.

    Paginates through ``list_objects_v2`` (R2/S3 caps a single page at 1000
    keys), so a course with many stored files is still listed completely. Any
    error (missing bucket, network issue, ...) degrades to an empty list rather
    than raising, matching ``core.documents.list_course_files``'s existing
    graceful-degradation contract for a missing local directory.
    """
    settings = get_settings()
    client = _client()
    items: list[tuple[str, datetime]] = []
    continuation_token: str | None = None
    try:
        while True:
            kwargs: dict[str, Any] = {"Bucket": settings.r2_bucket, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**kwargs)
            for obj in response.get("Contents", []):
                items.append((obj["Key"], obj["LastModified"]))
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
    except Exception:
        return []
    items.sort(key=lambda pair: pair[1], reverse=True)
    return [key for key, _ in items]


def copy_prefix(old_prefix: str, new_prefix: str) -> None:
    """Best-effort move of every object under ``old_prefix`` to ``new_prefix``.

    S3/R2 has no atomic rename, so this is the standard copy-then-delete
    pattern: each key under ``old_prefix`` is copied to the same relative key
    under ``new_prefix`` (e.g. ``old/notes.pdf`` -> ``new/notes.pdf``), then the
    original is deleted. Mirrors ``core.documents._move_course_dir``'s contract
    exactly: never raises, so a failure here can never fail the Qdrant payload
    rename that already succeeded. A destination key that already exists is
    overwritten by ``copy_object``, matching a course-name merge being
    acceptable (same as the local-disk rename).
    """
    try:
        settings = get_settings()
        client = _client()
        bucket = settings.r2_bucket
        for key in list_keys(old_prefix):
            if not key.startswith(old_prefix):
                continue  # defensive: list_keys is already scoped to the prefix
            new_key = new_prefix + key[len(old_prefix) :]
            client.copy_object(
                Bucket=bucket, CopySource={"Bucket": bucket, "Key": key}, Key=new_key
            )
            client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass
