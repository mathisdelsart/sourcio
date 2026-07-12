"""Central configuration: the `Settings` model and its cached accessor.

All tunables (LLM roles/provider, Qdrant, database, auth, retrieval flags, cache,
budget) are read from the environment into `Settings`. The model-agnostic LLM
factory that consumes these settings lives in `core.llm` (`get_llm`).
"""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load `.env` into the process environment so provider SDKs (e.g. OpenAI) can
# read OPENAI_API_KEY directly. pydantic-settings only populates Settings fields.
load_dotenv()


class Settings(BaseSettings):
    """Application settings, overridable via `.env` or environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    qdrant_url: str = "http://localhost:6333"
    # API key for a managed Qdrant (e.g. Qdrant Cloud). None for a local,
    # unauthenticated instance, so the default local setup is unchanged.
    qdrant_api_key: str | None = None
    qdrant_collection: str = "courses"

    # Comma-separated CORS origins allowed to call the API from a browser.
    # Defaults to local dev origins so the `web/` frontend works out of the box
    # locally; in production set CORS_ORIGINS to the deployed frontend URL
    # (e.g. the Vercel domain). Empty disables CORS entirely.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Multilingual embeddings (documents and questions are in French).
    embedding_model: str = "BAAI/bge-m3"

    # Retrieval threshold on the dense (bge-m3 cosine) score — the precision/recall
    # dial for grounding. It is genuinely a trade-off, not a magic value:
    #   - too HIGH (e.g. 0.5) and short/vaguely-phrased but legitimate in-course
    #     questions (e.g. "Where is Faktion located?" against a cover letter) score
    #     below it and get wrongly refused;
    #   - too LOW (e.g. 0.25) and clearly off-course questions retrieve loosely
    #     related chunks that a weak local model may answer from.
    # Calibration on the original course found in-course ~0.57-0.68 vs out-of-course
    # ~0.28-0.43, but real, heterogeneous personal documents blur that gap. We keep
    # a moderate floor (0.35) that favours recall on real content, and rely on the
    # LLM coverage refusal + the no-citation guard as the semantic backstops. For
    # reliable grounding on dense/technical material use a stronger LLM (OpenAI);
    # embeddings/Qdrant stay local. Tune with SIMILARITY_THRESHOLD, or re-run
    # `python -m eval.calibrate` on your own corpus to pick a value with data.
    similarity_threshold: float = 0.35

    # Cross-encoder reranker (opt-in precision boost, no re-ingestion needed).
    # "" disables it (dense path unchanged); a model name (e.g.
    # "cross-encoder/ms-marco-MiniLM-L-6-v2") enables reranking. It needs the
    # `ingestion` extra (sentence-transformers) and runs locally.
    reranker_model: str = ""

    # When the reranker is enabled, how many candidates to fetch from Qdrant
    # before reranking and truncating back to k. Ignored when disabled.
    rerank_candidates: int = 20

    # Name of the named sparse vector in Qdrant (bge-m3 lexical weights). Used by
    # both sparse indexing (--sparse) and the hybrid query path.
    sparse_vector_name: str = "sparse"

    # Opt-in hybrid dense + sparse (BM25-style) retrieval with RRF fusion. False
    # keeps the dense-only path unchanged. When True, hybrid is used only if the
    # collection actually carries the sparse vector; otherwise retrieval falls
    # back to dense gracefully (no crash). Requires a collection ingested with
    # the `--sparse` flag.
    hybrid_retrieval: bool = False

    # When hybrid is active, how many candidates each branch (dense kNN and
    # sparse) prefetches before RRF fusion truncates back to the requested k
    # (or to rerank_candidates when the reranker is also enabled).
    hybrid_prefetch: int = 50

    # Opt-in multi-query retrieval expansion (query rewriting). False keeps the
    # single-query dense/hybrid path byte-identical. When True, the question is
    # rewritten into a few diverse sub-queries (see `multi_query_n`); retrieval
    # runs for each and the candidate lists are fused before the SAME similarity
    # threshold, refusal and optional reranker are applied. It only widens recall
    # and never weakens the refusal guard.
    multi_query: bool = False

    # When multi-query is active, how many LLM-generated rewrites to request in
    # addition to the original question. Ignored when `multi_query` is False.
    multi_query_n: int = 3

    # Opt-in HyDE (Hypothetical Document Embeddings) retrieval. False keeps the
    # dense/hybrid path byte-identical. When True, a short hypothetical answer is
    # generated and embedded instead of the bare question for the dense branch,
    # which often lands closer to the indexed chunks. The similarity threshold,
    # refusal guard and optional reranker are applied unchanged. `multi_query`
    # takes precedence when both are set (multi-query never embeds a HyDE probe).
    hyde: bool = False

    # Opt-in neighbor-chunk context expansion. False keeps retrieval
    # byte-identical (no extra Qdrant calls). When True, after the thresholded
    # (and optionally reranked) top results are chosen, adjacent slides/windows
    # are pulled for each result -- same course and chapter, with `page` within
    # +/- `neighbor_window` of the result's page (excluding the page itself) --
    # so the model sees fuller surrounding context. Neighbors are fetched with
    # no similarity threshold (they are context, not matches) and are appended
    # after the ranked results. Expansion never runs on an empty retrieval, so
    # the refusal guard is untouched.
    neighbor_expansion: bool = False

    # Half-width of the neighbor page window when `neighbor_expansion` is on:
    # for a result on page p, pages in [p - window, p + window] (excluding p)
    # are pulled as context. Ignored when expansion is disabled.
    neighbor_window: int = 1

    # Relational store (SQLite in development, PostgreSQL later).
    database_url: str = "sqlite:///./app.db"

    # LLM response cache (opt-in cost saver). "" disables it; "memory" uses an
    # in-process cache; "sqlite" persists to disk across runs.
    llm_cache: str = ""

    # Token budget cap for the LLM factory (opt-in guard). 0 disables it; a
    # positive value stops generation once accumulated usage exceeds the cap.
    llm_budget_tokens: int = 0

    # API-key authentication (opt-in). "" leaves the API fully open; a non-empty
    # value requires clients to send a matching `X-API-Key` header on the
    # mutating endpoints and `/history`. `/health` is always open.
    api_key: str = ""

    # In-process rate limit. 0 (the default) means "auto": the effective limit is
    # derived from `require_auth` via `effective_rate_limit_per_minute` below, so
    # a public deployment is throttled by default while local dev stays open. A
    # positive value is an explicit operator override that always wins (set a very
    # high number to effectively disable throttling in public mode). When active,
    # each client (by IP) is capped to that many requests per rolling 60-second
    # window; once exceeded the request is rejected with 429 and a `Retry-After`
    # header. The limiter is per-process (a single Uvicorn worker); it is not a
    # substitute for an edge rate limiter in a multi-replica deployment.
    rate_limit_per_minute: int = 0

    # Maximum size, in megabytes, accepted by the document upload endpoint. Guards
    # the public deployment against oversized/abusive uploads; a file larger than
    # this is rejected with HTTP 413 before ingestion. Override via MAX_UPLOAD_MB.
    max_upload_mb: int = 100

    # Document-ingestion parallelism. A PDF is imported by transcribing pages
    # through the vision model concurrently and indexing them in batches; larger
    # values import a big PDF much faster (the old 4/3 defaults meant a 123-page
    # thesis crawled through ~41 near-serial rounds). The rate-limit retry/backoff
    # absorbs any 429s, so a high concurrency self-throttles to the provider's
    # limit rather than failing. Override via INGEST_CONCURRENCY / INGEST_BATCH_SIZE.
    ingest_concurrency: int = 12
    ingest_batch_size: int = 16

    # Send HTTP Strict-Transport-Security on every response. Off by default
    # because HSTS only makes sense behind HTTPS/TLS; enabling it on a plain-HTTP
    # local setup would be wrong. Enable it only when the API is served over TLS.
    enable_hsts: bool = False

    # Root logging level for the JSON structured logger configured on API
    # startup. A standard level name ("DEBUG", "INFO", "WARNING", "ERROR"); an
    # unknown value falls back to "INFO" so a typo never crashes startup. Default
    # "INFO" keeps the test suite quiet (DEBUG would be noisy).
    log_level: str = "INFO"

    # Enforced multi-user mode (opt-in). When OFF (the default) the API stays
    # anonymous: callers are keyed by a device `student_id` and authentication is
    # optional, exactly as in the MVP. When ON, every data endpoint requires a
    # valid bearer token (401 otherwise) and enforces per-user student ownership,
    # so a caller can only touch students that belong to their own account (true
    # tenant isolation). This is independent of `api_key`; the two guards coexist.
    require_auth: bool = False

    # Secret used to sign user JWTs (HS256). The default is an insecure
    # placeholder for local development only and MUST be overridden in
    # production via `JWT_SECRET` (or `.env`); leaking it lets anyone forge a
    # valid access token. User authentication is additive and independent of
    # `api_key` above; the two guards coexist.
    jwt_secret: str = "dev-insecure-change-me"

    # Lifetime of an issued access token, in minutes. After it elapses the token
    # is rejected and the user must log in again.
    jwt_expire_minutes: int = 60

    # Global LLM provider switch. "" keeps the default OpenAI provider; "ollama"
    # routes every role to a local Ollama chat model; "groq" routes every non-vision
    # role to a free-tier Groq-hosted model (see `get_llm`). Per-role `LLM_<ROLE>`
    # values may still carry their own `provider:model` prefix, which always wins
    # over this global default.
    llm_provider: str = ""

    # Default Groq chat model used when `llm_provider="groq"` and a role has no
    # explicit `LLM_<ROLE>` override. Groq serves this on its free tier via an
    # OpenAI-style API; langchain-groq reads GROQ_API_KEY from the environment, so
    # no base_url is needed. Groq has no vision model, so the `extract` (vision)
    # role falls back to the OpenAI default — ingestion is a one-time offline step
    # and is never run on the deployed API.
    groq_chat_model: str = "llama-3.3-70b-versatile"

    # Base URL of the local Ollama server, used only when the Ollama provider is
    # active. The default matches Ollama's out-of-the-box bind address.
    ollama_base_url: str = "http://localhost:11434"

    # Default Ollama model ids used when `llm_provider="ollama"` and a role has no
    # explicit `LLM_<ROLE>` override. The extract role needs a multimodal model to
    # transcribe rasterized slides; the others use a general chat model.
    ollama_chat_model: str = "llama3.1"
    ollama_vision_model: str = "llama3.2-vision"

    # Default Anthropic chat model used when a caller supplies their own Anthropic
    # key (prefix `sk-ant-`) and the role has no explicit Anthropic `LLM_<ROLE>`
    # override. A current, cost-effective Claude model; override via
    # ANTHROPIC_CHAT_MODEL. langchain-anthropic reads the per-call key from the
    # `api_key` passed to `init_chat_model` (see `get_llm`).
    anthropic_chat_model: str = "claude-haiku-4-5"

    # Durable object storage for uploaded course-file originals (Cloudflare R2,
    # optional). All four must be set to activate it (see `core.storage.configured`);
    # any left empty (the default) keeps the local-disk fallback used everywhere
    # today. R2 is what makes an uploaded PDF's "view original" survive a
    # container restart in production (HF Spaces' filesystem is ephemeral); local
    # dev needs none of this. `r2_account_id` also derives the R2 S3-compatible
    # endpoint (`https://<account_id>.r2.cloudflarestorage.com`), so no separate
    # endpoint setting is needed. See docs/DEPLOY.md for the Cloudflare
    # dashboard setup steps.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    @property
    def effective_rate_limit_per_minute(self) -> int:
        """Resolve the rate limit actually enforced by the middleware.

        Selection order:

        1. An explicit positive `rate_limit_per_minute` always wins (operator
           override): the deployment throttles at exactly that value.
        2. Otherwise (`rate_limit_per_minute == 0`, the "auto" default) the limit
           follows the deployment mode: **60** requests/minute when
           `require_auth` is True (public mode gets a sane default throttle) and
           **0** (off) when `require_auth` is False (local dev stays unthrottled,
           so the test suite is never tripped).

        To truly disable throttling in public mode, an operator sets a very high
        explicit `rate_limit_per_minute` rather than 0.
        """
        if self.rate_limit_per_minute > 0:
            return self.rate_limit_per_minute
        return 60 if self.require_auth else 0


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
