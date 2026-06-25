"""Query-side retrieval.

Embeds the question with the same model used at indexing time, fetches the
top-k most similar chunks from Qdrant, and applies the similarity threshold.
An empty result means nothing in the course is relevant enough, which the
answer layer turns into an explicit refusal rather than a guess.

An optional cross-encoder reranker (opt-in via ``reranker_model``) can improve
precision: it fetches more candidates above the similarity threshold, rescores
each (question, chunk) pair locally, and keeps the best k. The dense threshold
still pre-filters, so an out-of-course question yields no candidates and is
refused. When disabled (the default) the dense path above is used unchanged.
"""

from collections.abc import Callable
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import Condition, FieldCondition, Filter, MatchValue

from config import get_settings
from ingestion.embed import embed_query
from ingestion.schema import Chunk, Retrieved

# A scorer maps (question, candidate texts) to one relevance score per text.
Scorer = Callable[[str, list[str]], list[float]]


def _build_filter(course: str | None, chapter: str | None) -> Filter | None:
    """Build a Qdrant payload filter, or None when no scope is requested.

    Only matching chunks are returned, so the answer stays inside the chosen
    course/chapter. With both None the query is unfiltered (full collection).
    """
    conditions: list[Condition] = []
    if course is not None:
        conditions.append(FieldCondition(key="course", match=MatchValue(value=course)))
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    if not conditions:
        return None
    return Filter(must=conditions)


@lru_cache
def _cross_encoder(model_name: str):
    """Load and cache the cross-encoder model.

    Imported lazily so that ``retrieval`` stays importable without the heavy
    ingestion dependency (sentence-transformers); the import only happens when
    a reranker is actually configured.
    """
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def _default_scorer(question: str, texts: list[str]) -> list[float]:
    """Score (question, text) pairs with the configured cross-encoder model."""
    model = _cross_encoder(get_settings().reranker_model)
    scores = model.predict([(question, text) for text in texts])
    return [float(score) for score in scores]


def rerank(
    question: str,
    candidates: list[Retrieved],
    *,
    k: int,
    scorer: Scorer,
) -> list[Retrieved]:
    """Reorder candidates by cross-encoder relevance and keep the top k.

    Pure and testable: the scoring function is injected. Each candidate's
    ``.score`` is replaced by its rerank score, so downstream consumers see the
    cross-encoder relevance rather than the original similarity. Sorting is
    stable, so equal scores preserve the incoming (similarity) order.
    """
    if not candidates:
        return []
    scores = scorer(question, [c.chunk.text for c in candidates])
    rescored = [
        Retrieved(chunk=c.chunk, score=score) for c, score in zip(candidates, scores, strict=True)
    ]
    rescored.sort(key=lambda r: r.score, reverse=True)
    return rescored[:k]


def _point_to_retrieved(point) -> Retrieved:
    """Map a Qdrant point to a :class:`Retrieved` with citation metadata."""
    payload = point.payload or {}
    chunk = Chunk(
        id=str(point.id),
        course=payload["course"],
        page=payload["page"],
        text=payload["text"],
        chapter=payload.get("chapter"),
    )
    return Retrieved(chunk=chunk, score=point.score)


def retrieve(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
    scorer: Scorer | None = None,
) -> list[Retrieved]:
    """Return up to k chunks for the question, best first.

    Default (dense) path: returns up to k chunks above the similarity threshold,
    ordered by similarity.

    Reranking path (when ``reranker_model`` is set): fetches up to
    ``rerank_candidates`` chunks *above* the similarity threshold, rescores
    them with a local cross-encoder, and returns the top k. The returned
    ``.score`` is then the cross-encoder relevance, not the dense similarity.
    Keeping the threshold preserves refusal: an out-of-course question yields
    no candidates, so the answer layer refuses instead of guessing.

    In both paths, when ``course`` and/or ``chapter`` are given retrieval is
    restricted to chunks whose payload matches them; when both are None the
    whole collection is searched. ``scorer`` is injectable for testing; when
    None the configured cross-encoder model is used.
    """
    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)
    query_filter = _build_filter(course, chapter)

    reranking = bool(settings.reranker_model)
    score_threshold = settings.similarity_threshold
    if reranking:
        # Fetch more candidates (still above the similarity threshold) so the
        # cross-encoder has room to re-order the survivors. Keeping the dense
        # pre-filter means an out-of-course question yields nothing -> refusal.
        limit = max(settings.rerank_candidates, k)
    else:
        limit = k

    response = client.query_points(
        collection_name=settings.qdrant_collection,
        query=embed_query(question),
        limit=limit,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=True,
    )

    candidates = [_point_to_retrieved(point) for point in response.points]
    if reranking:
        return rerank(question, candidates, k=k, scorer=scorer or _default_scorer)
    return candidates
