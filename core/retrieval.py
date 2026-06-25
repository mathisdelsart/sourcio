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

An optional hybrid dense + sparse (BM25-style) path (opt-in via
``hybrid_retrieval``) fuses a dense kNN branch and a bge-m3 lexical (sparse)
branch with Reciprocal Rank Fusion (RRF) using the Qdrant Query API. It engages
only when the collection actually carries the named sparse vector; otherwise it
falls back to the dense path gracefully. The dense branch keeps the similarity
threshold, so refusal semantics are preserved, and the optional reranker is
applied on top exactly as in the dense path.
"""

from collections.abc import Callable
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Condition,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
    SparseVector,
)

from core.config import get_settings
from ingestion.embed import embed_query
from ingestion.index import DENSE_VECTOR_NAME
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


def _collection_has_sparse(client: QdrantClient, collection: str, sparse_name: str) -> bool:
    """Return True when ``collection`` carries the named sparse vector.

    Lets the hybrid path fall back to dense gracefully against a dense-only
    collection (e.g. the live demo index) instead of crashing. Any error while
    inspecting the collection is treated as "no sparse vector".
    """
    try:
        info = client.get_collection(collection)
        sparse_config = info.config.params.sparse_vectors
    except Exception:
        return False
    return bool(sparse_config) and sparse_name in sparse_config


def _dense_points(
    client: QdrantClient,
    *,
    collection: str,
    question: str,
    limit: int,
    score_threshold: float,
    query_filter: Filter | None,
):
    """Run the dense-only query against the (unnamed-vector) collection."""
    response = client.query_points(
        collection_name=collection,
        query=embed_query(question),
        limit=limit,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=True,
    )
    return response.points


def _hybrid_points(
    client: QdrantClient,
    *,
    collection: str,
    question: str,
    limit: int,
    score_threshold: float,
    query_filter: Filter | None,
):
    """Run a dense+sparse query fused with RRF via the Qdrant Query API.

    Two prefetch branches feed the fusion: a dense kNN branch (named dense
    vector, keeping the similarity threshold so refusal is preserved) and a
    sparse lexical branch (bge-m3 weights). RRF merges their ranks; the outer
    query truncates to ``limit``. The reranker, when enabled, runs on top.
    """
    from ingestion.embed import embed_sparse_query

    settings = get_settings()
    sparse = embed_sparse_query(question)
    prefetch = [
        Prefetch(
            query=embed_query(question),
            using=DENSE_VECTOR_NAME,
            limit=settings.hybrid_prefetch,
            score_threshold=score_threshold,
            filter=query_filter,
        ),
        Prefetch(
            query=SparseVector(indices=sparse.indices, values=sparse.values),
            using=settings.sparse_vector_name,
            limit=settings.hybrid_prefetch,
            filter=query_filter,
        ),
    ]
    response = client.query_points(
        collection_name=collection,
        prefetch=prefetch,
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
    )
    return response.points


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

    Hybrid path (when ``hybrid_retrieval`` is set *and* the collection carries
    the named sparse vector): fuses a dense kNN branch and a bge-m3 lexical
    (sparse) branch with RRF. The dense branch keeps the similarity threshold so
    an out-of-course question still yields nothing (refusal). If hybrid is
    requested but the collection has no sparse vector, retrieval falls back to
    the dense path gracefully.

    Reranking path (when ``reranker_model`` is set): fetches up to
    ``rerank_candidates`` candidates, rescores them with a local cross-encoder,
    and returns the top k. The returned ``.score`` is then the cross-encoder
    relevance. Reranking composes with either base path (dense or hybrid).

    In all paths, when ``course`` and/or ``chapter`` are given retrieval is
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

    use_hybrid = settings.hybrid_retrieval and _collection_has_sparse(
        client, settings.qdrant_collection, settings.sparse_vector_name
    )
    if use_hybrid:
        points = _hybrid_points(
            client,
            collection=settings.qdrant_collection,
            question=question,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
    else:
        points = _dense_points(
            client,
            collection=settings.qdrant_collection,
            question=question,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )

    candidates = [_point_to_retrieved(point) for point in points]
    if reranking:
        return rerank(question, candidates, k=k, scorer=scorer or _default_scorer)
    return candidates
