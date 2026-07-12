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

An optional neighbor-chunk context expansion (opt-in via ``neighbor_expansion``)
runs *after* the thresholded (and optionally reranked) top results are chosen:
for each result it pulls adjacent slides/windows (same course and chapter, page
within +/- ``neighbor_window``, excluding the page itself) with a payload-only
``scroll`` -- no similarity threshold, since these are context, not matches.
Neighbors are de-duplicated against the originals and appended after them.
Expansion never runs on an empty retrieval, so the refusal guard is untouched,
and any neighbor-fetch error degrades to the un-expanded results.
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
    Range,
    SparseVector,
)

from core.config import get_settings
from core.qdrant import client_from_settings
from core.query import expand_query, hyde_passage
from ingestion.embed import embed_query
from ingestion.index import DENSE_VECTOR_NAME
from ingestion.schema import Chunk, Retrieved

# A scorer maps (question, candidate texts) to one relevance score per text.
Scorer = Callable[[str, list[str]], list[float]]

# Upper bound on how many neighbor chunks are fetched in total per ``retrieve``
# call, so a large k with a wide window can never balloon the context block or
# the number of scroll calls without bound.
_MAX_NEIGHBORS = 20


def owner_scope_filter(owner: str) -> Filter:
    """Sub-filter matching *only* material owned by ``owner`` (strict isolation).

    A single ``must`` condition ``owner == owner`` — no shared/legacy branch. An
    account sees strictly its own material: owner-less points (the legacy / CLI
    corpus ingested before per-account scoping) are *not* matched and are
    therefore invisible to every account. Nesting this ``Filter`` inside another
    filter's ``must`` requires the owner to match, so it scopes reads, deletes and
    single-source lookups to the caller's own points and nothing else. This closes
    the cross-tenant leak where an owner-less chunk was visible to everyone.
    """
    return Filter(must=[FieldCondition(key="owner", match=MatchValue(value=owner))])


def _build_filter(
    course: str | None, chapter: str | None, owner: str | None = None
) -> Filter | None:
    """Build a Qdrant payload filter, or None when no scope is requested.

    Only matching chunks are returned, so the answer stays inside the chosen
    course/chapter. When ``owner`` is given, the results are strictly scoped to the
    caller's *own* material via :func:`owner_scope_filter` (no shared/legacy
    branch). ``owner`` is None only on the offline/CLI/eval path (the API always
    supplies the caller's id, which is required on ``AskRequest``); in that case
    the query is not owner-scoped. With course, chapter and owner all None the
    query is unfiltered (full collection), which is the offline behaviour.
    """
    conditions: list[Condition] = []
    if course is not None:
        conditions.append(FieldCondition(key="course", match=MatchValue(value=course)))
    if chapter is not None:
        conditions.append(FieldCondition(key="chapter", match=MatchValue(value=chapter)))
    if owner is not None:
        conditions.append(owner_scope_filter(owner))
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


def _to_retrieved(item, score: float) -> Retrieved:
    """Map a Qdrant point/record to a :class:`Retrieved` with citation metadata.

    ``item`` is either a search point (carries ``.score``) or a scroll record
    (no score). The caller supplies ``score``: the point's similarity for a
    ranked hit, or ``0.0`` for a neighbor pulled as surrounding context (never a
    ranked match, so it sorts after the real hits).
    """
    payload = item.payload or {}
    chunk = Chunk(
        id=str(item.id),
        course=payload["course"],
        page=payload["page"],
        text=payload["text"],
        chapter=payload.get("chapter"),
    )
    return Retrieved(chunk=chunk, score=score)


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
    dense_text: str,
    limit: int,
    score_threshold: float,
    query_filter: Filter | None,
    using: str | None = None,
):
    """Run the dense-only query.

    ``dense_text`` is the text embedded for the dense kNN lookup. On the plain
    path it is the question; on the HyDE path it is the hypothetical answer
    passage, so the probe vector resembles the indexed material more closely.
    The similarity threshold is unchanged either way, so refusal is preserved.

    ``using`` names the dense vector for collections built with named vectors
    (sparse-enabled collections have no default vector, so the dense query must
    name it). It stays None for a plain dense-only collection that stores a
    single unnamed vector (``using=None`` selects that default vector).
    """
    response = client.query_points(
        collection_name=collection,
        query=embed_query(dense_text),
        using=using,
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
    dense_text: str,
    limit: int,
    score_threshold: float,
    query_filter: Filter | None,
):
    """Run a dense+sparse query fused with RRF via the Qdrant Query API.

    Two prefetch branches feed the fusion: a dense kNN branch (named dense
    vector, keeping the similarity threshold so refusal is preserved) and a
    sparse lexical branch (bge-m3 weights). RRF merges their ranks; the outer
    query truncates to ``limit``. The reranker, when enabled, runs on top.

    ``dense_text`` is embedded for the dense branch (the hypothetical passage on
    the HyDE path, the question otherwise). The sparse lexical branch always
    embeds the original ``question``: HyDE helps semantic matching, whereas
    lexical overlap is best judged on the student's actual wording.
    """
    from ingestion.embed import embed_sparse_query

    settings = get_settings()
    sparse = embed_sparse_query(question)
    prefetch = [
        Prefetch(
            query=embed_query(dense_text),
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


def _fetch_candidates(
    client: QdrantClient,
    *,
    settings,
    question: str,
    limit: int,
    score_threshold: float,
    query_filter: Filter | None,
    dense_text: str | None = None,
) -> list[Retrieved]:
    """Fetch threshold-filtered candidates for one query (dense or hybrid).

    Chooses the hybrid RRF path when ``hybrid_retrieval`` is set and the
    collection carries the sparse vector, otherwise the plain dense path. In
    both cases the dense similarity threshold pre-filters, so an out-of-course
    query yields no candidates. Reranking is intentionally *not* applied here:
    on the multi-query path it must run once over the fused pool.

    ``dense_text`` overrides the text embedded for the dense branch (the HyDE
    hypothetical passage); when None it defaults to ``question``, so the plain
    path is unchanged. The sparse lexical branch always uses ``question``.
    """
    dense_query = dense_text if dense_text is not None else question
    has_sparse = _collection_has_sparse(
        client, settings.qdrant_collection, settings.sparse_vector_name
    )
    if settings.hybrid_retrieval and has_sparse:
        points = _hybrid_points(
            client,
            collection=settings.qdrant_collection,
            question=question,
            dense_text=dense_query,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
    else:
        # A sparse-enabled collection uses named vectors (no default vector), so
        # the dense query must name the dense vector; a plain dense-only
        # collection stores one unnamed vector (using=None).
        points = _dense_points(
            client,
            collection=settings.qdrant_collection,
            dense_text=dense_query,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
            using=DENSE_VECTOR_NAME if has_sparse else None,
        )
    return [_to_retrieved(point, point.score) for point in points]


def _neighbor_filter(result: Retrieved, window: int, owner: str | None = None) -> Filter:
    """Build the payload filter selecting a result's page-window neighbors.

    Same course and (when present) chapter as the result, with ``page`` in
    ``[page - window, page + window]`` and the result's own page excluded. This
    keeps neighbors inside the same course/chapter so expansion never pulls in
    unrelated material. When ``owner`` is given the neighbors are strictly scoped
    to the caller's *own* material (via :func:`owner_scope_filter`, no shared/legacy
    branch), so expansion never leaks another account's adjacent slides.
    """
    page = result.chunk.page
    must: list[Condition] = [
        FieldCondition(key="course", match=MatchValue(value=result.chunk.course)),
        FieldCondition(key="page", range=Range(gte=page - window, lte=page + window)),
    ]
    if result.chunk.chapter is not None:
        must.append(FieldCondition(key="chapter", match=MatchValue(value=result.chunk.chapter)))
    if owner is not None:
        must.append(owner_scope_filter(owner))
    must_not: list[Condition] = [
        FieldCondition(key="page", match=MatchValue(value=page)),
    ]
    return Filter(must=must, must_not=must_not)


def _fetch_neighbors(
    client: QdrantClient,
    *,
    collection: str,
    result: Retrieved,
    window: int,
    limit: int,
    owner: str | None = None,
) -> list[Retrieved]:
    """Scroll the page-window neighbors of one result (no similarity threshold).

    Uses a payload-only ``scroll`` with the neighbor filter; ``limit`` caps how
    many records are pulled. Returns context-only :class:`Retrieved` (score 0).
    ``owner`` strictly scopes the neighbors to the caller's own material.
    """
    records, _ = client.scroll(
        collection_name=collection,
        scroll_filter=_neighbor_filter(result, window, owner),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return [_to_retrieved(record, 0.0) for record in records]


def _expand_with_neighbors(
    client: QdrantClient,
    results: list[Retrieved],
    *,
    collection: str,
    window: int,
    owner: str | None = None,
) -> list[Retrieved]:
    """Append page-window neighbors of each result, de-duped and bounded.

    The original ranked ``results`` are kept first and in order; neighbors are
    appended after them, de-duplicated by chunk id (against the originals and
    among themselves), and capped at ``_MAX_NEIGHBORS`` in total. Refusal is
    decided before this runs: an empty ``results`` is returned untouched (no
    scroll is issued). Any neighbor-fetch error degrades to the un-expanded
    ``results`` rather than raising -- expansion is best-effort context.
    """
    if not results or window < 1:
        return results

    seen: set[str] = {r.chunk.id for r in results}
    neighbors: list[Retrieved] = []
    try:
        for result in results:
            if len(neighbors) >= _MAX_NEIGHBORS:
                break
            remaining = _MAX_NEIGHBORS - len(neighbors)
            fetched = _fetch_neighbors(
                client,
                collection=collection,
                result=result,
                window=window,
                limit=remaining,
                owner=owner,
            )
            for neighbor in fetched:
                if neighbor.chunk.id in seen:
                    continue
                seen.add(neighbor.chunk.id)
                neighbors.append(neighbor)
                if len(neighbors) >= _MAX_NEIGHBORS:
                    break
    except Exception:
        # Best-effort context: any failure leaves the ranked results intact.
        return results

    return results + neighbors


def _fuse(candidate_lists: list[list[Retrieved]]) -> list[Retrieved]:
    """Fuse per-query candidate lists by chunk id, keeping the best score.

    De-duplicates across sub-queries: a chunk surfaced by several rewrites is
    kept once, with its highest similarity score, and the fused pool is sorted
    by score (best first). This preserves the score semantics the threshold and
    reranker downstream expect, while widening coverage across rewrites.
    """
    best: dict[str, Retrieved] = {}
    for candidates in candidate_lists:
        for cand in candidates:
            current = best.get(cand.chunk.id)
            if current is None or cand.score > current.score:
                best[cand.chunk.id] = cand
    fused = list(best.values())
    fused.sort(key=lambda r: r.score, reverse=True)
    return fused


def retrieve(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
    owner: str | None = None,
    scorer: Scorer | None = None,
    hyde: bool = False,
    expand_neighbors: bool | None = None,
    api_key: str | None = None,
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

    HyDE path (when ``hyde`` is True): a short hypothetical answer passage is
    generated (see ``core.query.hyde_passage``) and embedded *instead of the
    question* for the dense branch, on the theory that an answer sits closer to
    the indexed chunks than a question does. The similarity threshold is applied
    unchanged to that probe, so an out-of-course question still clears nothing
    and is refused; the sparse lexical branch (hybrid) still uses the original
    question. HyDE composes with the dense, hybrid and reranking paths.

    Reranking path (when ``reranker_model`` is set): fetches up to
    ``rerank_candidates`` candidates, rescores them with a local cross-encoder,
    and returns the top k. The returned ``.score`` is then the cross-encoder
    relevance. Reranking composes with either base path (dense or hybrid). The
    cross-encoder always scores against the original ``question``, not the HyDE
    passage, so relevance is judged on what the student asked.

    Neighbor expansion path (when ``expand_neighbors`` is True, or None and
    ``neighbor_expansion`` is set): after the thresholded (and optionally
    reranked) top results are chosen, each result's adjacent slides/windows are
    pulled (same course and chapter, page within +/- ``neighbor_window``,
    excluding the page itself) and appended after the ranked results, de-duped
    by chunk id and capped in total. Neighbors carry no similarity score and
    never trigger or suppress refusal: an empty thresholded retrieval is
    returned untouched, with no neighbor fetch attempted. Any neighbor-fetch
    error degrades to the un-expanded results. When disabled (the default) no
    extra Qdrant call is made and behavior is byte-identical.

    In all paths, when ``course`` and/or ``chapter`` are given retrieval is
    restricted to chunks whose payload matches them; when both are None the
    whole collection is searched. When ``owner`` is given, retrieval is strictly
    scoped to the caller's *own* material (no shared/legacy visibility). ``owner``
    is None only on the offline/CLI/eval path; the API always passes the caller's
    id (required on ``AskRequest``), so a user read is always owner-scoped.
    ``scorer`` is injectable for testing; when None the configured cross-encoder
    model is used. ``api_key`` is an optional per-request OpenAI key forwarded to
    the HyDE probe LLM (see :func:`core.query.hyde_passage`); it does not affect
    the dense/sparse search itself and defaults to the free model when None.
    """
    settings = get_settings()
    client = client_from_settings()
    query_filter = _build_filter(course, chapter, owner)

    reranking = bool(settings.reranker_model)
    score_threshold = settings.similarity_threshold
    if reranking:
        # Fetch more candidates (still above the similarity threshold) so the
        # cross-encoder has room to re-order the survivors. Keeping the dense
        # pre-filter means an out-of-course question yields nothing -> refusal.
        limit = max(settings.rerank_candidates, k)
    else:
        limit = k

    # On the HyDE path, embed a hypothetical answer passage for the dense branch
    # instead of the bare question. hyde_passage() never raises and falls back to
    # the question, so HyDE degrades to a plain dense query on any LLM error.
    dense_text = hyde_passage(question, api_key=api_key) if hyde else None

    candidates = _fetch_candidates(
        client,
        settings=settings,
        question=question,
        limit=limit,
        score_threshold=score_threshold,
        query_filter=query_filter,
        dense_text=dense_text,
    )
    if reranking:
        results = rerank(question, candidates, k=k, scorer=scorer or _default_scorer)
    else:
        results = candidates

    # Refusal is decided above (empty -> empty). Only an in-course, non-empty
    # result set is ever expanded with neighbors, and only when opted in. The
    # settings are read defensively so a minimal stub without the fields keeps
    # expansion off.
    if expand_neighbors is None:
        expand = bool(getattr(settings, "neighbor_expansion", False))
    else:
        expand = expand_neighbors
    if expand and results:
        return _expand_with_neighbors(
            client,
            results,
            collection=settings.qdrant_collection,
            window=int(getattr(settings, "neighbor_window", 1)),
            owner=owner,
        )
    return results


def retrieve_multi(
    question: str,
    *,
    k: int = 5,
    course: str | None = None,
    chapter: str | None = None,
    owner: str | None = None,
    scorer: Scorer | None = None,
    api_key: str | None = None,
) -> list[Retrieved]:
    """Multi-query retrieval: expand the question, retrieve per query, then fuse.

    The question is rewritten into a few diverse sub-queries (see
    ``core.query.expand_query``); ``retrieve`` runs for each, and the candidate
    lists are fused by chunk id keeping the best score. The SAME machinery as
    the single-query path is preserved:

    - Every sub-query is fetched with the dense similarity threshold, so an
      out-of-course question contributes nothing from any rewrite and the fused
      pool is empty -> the answer layer refuses. Multi-query only widens recall;
      it never relaxes the refusal guard.
    - The optional cross-encoder reranker, when configured, runs once over the
      fused pool and truncates to k, exactly as in the single-query path.
    - When the reranker is off, the fused pool is sorted by similarity and
      truncated to k.

    With ``multi_query`` disabled this wrapper is never reached; the default
    callers keep using :func:`retrieve` unchanged.
    """
    settings = get_settings()
    queries = expand_query(question, n=settings.multi_query_n, api_key=api_key)

    client = client_from_settings()
    query_filter = _build_filter(course, chapter, owner)

    reranking = bool(settings.reranker_model)
    score_threshold = settings.similarity_threshold
    # Each sub-query fetches enough room for fusion/reranking to choose from.
    per_query_limit = max(settings.rerank_candidates, k) if reranking else k

    candidate_lists = [
        _fetch_candidates(
            client,
            settings=settings,
            question=q,
            limit=per_query_limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )
        for q in queries
    ]
    fused = _fuse(candidate_lists)

    if reranking:
        # Rerank against the original question, not a rewrite, so relevance is
        # judged on what the student actually asked.
        return rerank(question, fused, k=k, scorer=scorer or _default_scorer)
    return fused[:k]
