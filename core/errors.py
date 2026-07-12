"""Turn opaque LLM-provider capacity errors into an actionable message.

The free-tier default model (Groq) enforces small per-minute token budgets: a
long question, a large retrieved context, or a chatty history can trip it well
below any limit a paid model would handle without complaint. Left alone, the
raw provider error (``Error code: 413 - {'error': {...}}``) leaks straight to
the user with no indication of what to do about it. This module recognizes
that error shape and swaps in a message that tells the user to add their own
OpenAI/Anthropic key for requests like this.
"""

from fastapi import HTTPException, status

# Statuses the OpenAI-compatible provider SDKs (openai, groq, anthropic) use
# for "request too large" (413) and "rate limited" (429). Both mean the same
# thing for the free tier: this request exceeds what it can serve right now.
_CAPACITY_STATUS_CODES = (413, 429)

FREE_TIER_CAPACITY_MESSAGE = (
    "This request is too large for the free model. Add your own OpenAI or Anthropic "
    "API key (account menu) for requests like this -- it then runs on your own "
    "model, billed to your account."
)

OWN_KEY_CAPACITY_MESSAGE = (
    "Your API key hit its provider's rate or size limit for this request. Wait a "
    "moment and try again, or check your account's usage limits."
)

# Client-safe fallback for a non-capacity error, mirroring the global 500 handler.
# Never carries the raw exception text, so an unexpected error cannot leak a stack
# trace or internal detail through a streamed ``error`` event.
GENERIC_ERROR_MESSAGE = "An internal error occurred. Please retry later."


def describe_capacity_error(exc: Exception, *, used_own_key: bool) -> str | None:
    """Return a friendly message when `exc` is a provider capacity error, else None.

    Duck-typed on `status_code` rather than importing every provider SDK's
    exception classes, so this works regardless of which optional provider
    extras (e.g. `groq`) are installed in the running process.
    """
    if getattr(exc, "status_code", None) not in _CAPACITY_STATUS_CODES:
        return None
    return OWN_KEY_CAPACITY_MESSAGE if used_own_key else FREE_TIER_CAPACITY_MESSAGE


def friendly_llm_error_message(exc: Exception, *, used_own_key: bool) -> str:
    """Client-safe message for a streamed ``error`` event.

    Returns the actionable capacity message when ``exc`` is a provider capacity
    error, otherwise a generic message that never exposes the raw exception text.
    A streaming response cannot raise an ``HTTPException`` once the body has begun,
    so SSE handlers emit this instead of ``str(exc)`` (and log the real error
    server-side).
    """
    return describe_capacity_error(exc, used_own_key=used_own_key) or GENERIC_ERROR_MESSAGE


def raise_friendly_llm_error(exc: Exception, *, used_own_key: bool) -> None:
    """Re-raise `exc` as a clear 413 when it is a provider capacity error.

    Does nothing for any other exception, so callers write
    ``raise_friendly_llm_error(exc, used_own_key=...); raise`` to fall back to
    their existing handling (the global 500 handler) unchanged.
    """
    message = describe_capacity_error(exc, used_own_key=used_own_key)
    if message is not None:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=message) from exc


# --- OpenAI vision-extraction credential errors (used by document ingestion) ---
# A scanned/image PDF needs the vision model. These recognize a missing/invalid
# OpenAI credential and produce the right guidance for the uploader.

# No OpenAI key available (neither the visitor's nor a server env key). Text PDFs
# and .md/.txt import for free with local embeddings, so this only applies to
# image-based pages; it guides the UI to prompt the visitor for their own key.
MISSING_OPENAI_KEY_MESSAGE = (
    "This looks like a scanned or image-based PDF, which needs a vision model to "
    "read. Add your OpenAI API key to import it — text PDFs and .md/.txt files "
    "import for free without a key."
)

# The visitor DID supply a key that the provider rejected (wrong value, no credit,
# or no vision-model access). A common cause is pasting a whole `OPENAI_API_KEY=...`
# line instead of just the key, so the message says so.
REJECTED_OPENAI_KEY_MESSAGE = (
    "The API key was rejected. Check that it is valid — that it has credit and "
    "access to a vision model, and that you pasted only the key itself (e.g. "
    "sk-…), not a whole 'OPENAI_API_KEY=…' line."
)


def _openai_key_error(extract_api_key: str | None) -> str:
    """Pick the missing-key vs rejected-key message by whether a key was supplied."""
    return REJECTED_OPENAI_KEY_MESSAGE if extract_api_key else MISSING_OPENAI_KEY_MESSAGE


def _is_missing_openai_credentials(exc: BaseException) -> bool:
    """Return whether ``exc`` is an OpenAI missing/invalid-credentials error.

    Detection is by exception class name and message so the OpenAI SDK never has
    to be imported here. Covers both LangChain's "Did not find openai_api_key"
    startup ValueError and the SDK's ``AuthenticationError`` (HTTP 401), which is
    what a scanned PDF hits when no key (visitor's or env) is available for the
    vision fallback. Unrelated errors return False and keep their own message.
    """
    haystack = f"{type(exc).__name__} {exc}".lower()
    return (
        "openai_api_key" in haystack
        or "authenticationerror" in haystack
        or "api_key client option must be set" in haystack
        or ("api key" in haystack and "openai" in haystack)
    )
