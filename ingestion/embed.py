"""Local multilingual embeddings (bge-m3).

Shared by indexing (documents) and retrieval (queries) so both sides use the
same vector space. The model is loaded once and cached. Vectors are L2
normalized, which makes cosine similarity equal to the dot product.
"""

from functools import lru_cache

from core.config import get_settings


@lru_cache
def _model():
    # Imported lazily so modules that only reach the pure logic (e.g. tests,
    # retrieval helpers) do not require the heavy ingestion dependency.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)


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
