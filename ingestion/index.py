"""Embeddings and Qdrant upsert.

Each chunk is embedded with the local multilingual model and stored in Qdrant
as {vector, payload}. The payload keeps the chunk text and its citation
metadata so retrieval can both rank and cite without a second lookup.
"""

import logging

from qdrant_client import QdrantClient, models

from core.config import get_settings
from ingestion.embed import embed_texts, embedding_dim
from ingestion.schema import Chunk

logger = logging.getLogger(__name__)


def _client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


def _ensure_collection(client: QdrantClient, name: str) -> None:
    """Create the collection (cosine distance) if it does not exist yet."""
    if client.collection_exists(name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(
            size=embedding_dim(),
            distance=models.Distance.COSINE,
        ),
    )


def index_chunks(chunks: list[Chunk]) -> None:
    """Embed and upsert chunks into the configured Qdrant collection."""
    if not chunks:
        logger.warning("index_chunks called with no chunks")
        return

    settings = get_settings()
    client = _client()
    _ensure_collection(client, settings.qdrant_collection)

    vectors = embed_texts([c.text for c in chunks])
    points = [
        models.PointStruct(
            id=c.id,
            vector=vector,
            payload={
                "text": c.text,
                "course": c.course,
                "chapter": c.chapter,
                "page": c.page,
            },
        )
        for c, vector in zip(chunks, vectors, strict=True)
    ]
    client.upsert(collection_name=settings.qdrant_collection, points=points)
    logger.info("upserted %d chunks into %r", len(points), settings.qdrant_collection)
