"""Embeddings and Qdrant upsert.

Each chunk is embedded with the local multilingual model and stored in Qdrant
as {vector, payload}. The payload keeps the chunk text and its citation
metadata so retrieval can both rank and cite without a second lookup.

Sparse indexing is opt-in (``sparse=True``). When enabled, the collection is
created with Qdrant *named* vectors -- the dense vector under
``DENSE_VECTOR_NAME`` plus a named sparse vector (bge-m3 lexical weights) -- and
each point carries both. The default dense-only path is unchanged, so existing
ingestion and the live dense-only collection keep working.
"""

import logging

from qdrant_client import QdrantClient, models

from core.config import get_settings
from ingestion.embed import embed_sparse_texts, embed_texts, embedding_dim
from ingestion.schema import Chunk

logger = logging.getLogger(__name__)

# Name of the dense vector when the collection uses named vectors (sparse mode).
# Dense-only collections keep Qdrant's unnamed default vector, so the live demo
# index is untouched.
DENSE_VECTOR_NAME = "dense"


def _client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def _ensure_collection(client: QdrantClient, name: str, *, sparse: bool) -> None:
    """Create the collection if it does not exist yet.

    Dense-only (default): a single unnamed cosine vector, exactly as before.
    Sparse mode: named vectors -- a dense cosine vector under
    ``DENSE_VECTOR_NAME`` and a named sparse vector for the bge-m3 lexical
    weights -- so the Query API can prefetch and RRF-fuse both branches.
    """
    if client.collection_exists(name):
        _ensure_payload_indexes(client, name)
        return

    dense_params = models.VectorParams(
        size=embedding_dim(),
        distance=models.Distance.COSINE,
    )
    if not sparse:
        client.create_collection(collection_name=name, vectors_config=dense_params)
    else:
        settings = get_settings()
        client.create_collection(
            collection_name=name,
            vectors_config={DENSE_VECTOR_NAME: dense_params},
            sparse_vectors_config={settings.sparse_vector_name: models.SparseVectorParams()},
        )
    _ensure_payload_indexes(client, name)


def _ensure_payload_indexes(client: QdrantClient, name: str) -> None:
    """Ensure keyword payload indexes exist on ``course`` and ``document``.

    A keyword index on ``course`` lets Qdrant's facet API aggregate distinct
    courses server-side (otherwise it 400s and callers fall back to a scroll),
    and an index on ``document`` keeps per-document filtering fast. Both calls are
    idempotent and best-effort: creating an index that already exists, or a client
    that lacks the method, is swallowed so indexing never fails over this.
    """
    create = getattr(client, "create_payload_index", None)
    if create is None:
        return
    for field in ("course", "document"):
        try:
            create(
                collection_name=name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            # Already indexed, or the server/client does not support it: harmless.
            logger.debug("payload index on %r not created (may already exist)", field)


def index_chunks(chunks: list[Chunk], *, sparse: bool = False) -> None:
    """Embed and upsert chunks into the configured Qdrant collection.

    ``sparse=False`` (default): dense-only, unnamed vector -- unchanged behavior.
    ``sparse=True``: also compute the bge-m3 lexical weights and store both a
    named dense vector and a named sparse vector per point, enabling the opt-in
    hybrid retrieval path. Choose one mode per collection (the vector schema is
    fixed at creation time).
    """
    if not chunks:
        logger.warning("index_chunks called with no chunks")
        return

    settings = get_settings()
    client = _client()
    _ensure_collection(client, settings.qdrant_collection, sparse=sparse)

    dense_vectors = embed_texts([c.text for c in chunks])
    payloads = [
        {
            "text": c.text,
            "course": c.course,
            "chapter": c.chapter,
            "page": c.page,
            "document": c.document,
        }
        for c in chunks
    ]

    if not sparse:
        points = [
            models.PointStruct(id=c.id, vector=vector, payload=payload)
            for c, vector, payload in zip(chunks, dense_vectors, payloads, strict=True)
        ]
    else:
        sparse_vectors = embed_sparse_texts([c.text for c in chunks])
        points = [
            models.PointStruct(
                id=c.id,
                vector={
                    DENSE_VECTOR_NAME: dense,
                    settings.sparse_vector_name: models.SparseVector(
                        indices=sv.indices, values=sv.values
                    ),
                },
                payload=payload,
            )
            for c, dense, sv, payload in zip(
                chunks, dense_vectors, sparse_vectors, payloads, strict=True
            )
        ]

    client.upsert(collection_name=settings.qdrant_collection, points=points)
    logger.info(
        "upserted %d chunks into %r (sparse=%s)",
        len(points),
        settings.qdrant_collection,
        sparse,
    )
