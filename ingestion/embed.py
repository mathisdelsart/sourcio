"""Local multilingual embeddings (bge-m3).

Shared by indexing (documents) and retrieval (queries) so both sides use the
same vector space. The model is loaded once and cached. Vectors are L2
normalized, which makes cosine similarity equal to the dot product.

bge-m3 also produces lexical (sparse) weights, used by the opt-in hybrid
retrieval path. Those weights are exposed via :class:`SparseEmbedding`
(``indices``/``values``) and computed by a separate ``FlagEmbedding`` model so
the dense path above stays untouched and the heavy dependency stays optional.
"""

from dataclasses import dataclass
from functools import lru_cache

from core.config import get_settings


@dataclass(frozen=True)
class SparseEmbedding:
    """A sparse (lexical) vector as parallel ``indices``/``values`` lists.

    Mirrors Qdrant's sparse-vector wire format: ``indices`` are the active
    vocabulary token ids and ``values`` their (non-negative) lexical weights.
    """

    indices: list[int]
    values: list[float]


@lru_cache
def _model():
    # Imported lazily so modules that only reach the pure logic (e.g. tests,
    # retrieval helpers) do not require the heavy ingestion dependency.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)


@lru_cache
def _sparse_model():
    """Load and cache the bge-m3 model that exposes lexical (sparse) weights.

    Uses ``FlagEmbedding.BGEM3FlagModel`` because it returns the lexical token
    weights bge-m3 was trained to produce, which the ``SentenceTransformer``
    wrapper does not surface. Imported lazily so the dense path and tests never
    require this heavy optional dependency.
    """
    from FlagEmbedding import BGEM3FlagModel

    return BGEM3FlagModel(get_settings().embedding_model, use_fp16=False)


def _to_sparse(lexical_weights: dict) -> SparseEmbedding:
    """Convert bge-m3 ``lexical_weights`` (token id -> weight) to a sparse vector.

    Token ids arrive as strings from ``FlagEmbedding``; they are cast to int for
    Qdrant. Zero-weight entries are dropped so the stored vector stays sparse.
    """
    indices: list[int] = []
    values: list[float] = []
    for token, weight in lexical_weights.items():
        value = float(weight)
        if value == 0.0:
            continue
        indices.append(int(token))
        values.append(value)
    return SparseEmbedding(indices=indices, values=values)


def embed_sparse_texts(texts: list[str]) -> list[SparseEmbedding]:
    """Compute bge-m3 lexical (sparse) vectors for a batch of document texts."""
    output = _sparse_model().encode(
        texts, return_dense=False, return_sparse=True, return_colbert_vecs=False
    )
    return [_to_sparse(weights) for weights in output["lexical_weights"]]


def embed_sparse_query(text: str) -> SparseEmbedding:
    """Compute the bge-m3 lexical (sparse) vector for a single query."""
    return embed_sparse_texts([text])[0]


def embedding_dim() -> int:
    """Dimension of the embedding vectors (1024 for bge-m3)."""
    model = _model()
    # Method was renamed in recent sentence-transformers; support both.
    if hasattr(model, "get_embedding_dimension"):
        return model.get_embedding_dimension()
    return model.get_sentence_embedding_dimension()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of document texts."""
    vectors = _model().encode(texts, normalize_embeddings=True)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a single query. bge-m3 needs no special query prefix."""
    return embed_texts([text])[0]
