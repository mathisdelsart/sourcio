"""Query-side retrieval.

Embeds the question with the same model used at indexing time, fetches the
top-k most similar chunks from Qdrant, and applies the similarity threshold.
An empty result means nothing in the course is relevant enough, which the
answer layer turns into an explicit refusal rather than a guess.
"""

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import get_settings
from ingestion.embed import embed_query
from ingestion.schema import Chunk, Retrieved


def _build_filter(course: str | None, chapter: str | None) -> Filter | None:
    """Build a Qdrant payload filter, or None when no scope is requested.

    Only matching chunks are returned, so the answer stays inside the chosen
    course/chapter. With both None the query is unfiltered (full collection).
    """
    conditions: list[FieldCondition] = []
    if course is not None:
        conditions.append(FieldCondition(key="course", match=MatchValue(value=course)))
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    if not conditions:
        return None
    return Filter(must=conditions)


def retrieve(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
) -> list[Retrieved]:
    """Return up to k chunks above the similarity threshold, best first.

    When ``course`` and/or ``chapter`` are given, retrieval is restricted to
    chunks whose payload matches them. When both are None the behavior is
    unchanged and the whole collection is searched.
    """
    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)

    response = client.query_points(
        collection_name=settings.qdrant_collection,
        query=embed_query(question),
        limit=k,
        score_threshold=settings.similarity_threshold,
        query_filter=_build_filter(course, chapter),
        with_payload=True,
    )

    results: list[Retrieved] = []
    for point in response.points:
        payload = point.payload or {}
        chunk = Chunk(
            id=str(point.id),
            course=payload["course"],
            page=payload["page"],
            text=payload["text"],
            chapter=payload.get("chapter"),
        )
        results.append(Retrieved(chunk=chunk, score=point.score))
    return results
