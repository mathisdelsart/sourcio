"""Rate-limit (HTTP 429) retry with exponential backoff for provider calls.

Used by ``ingestion.extract`` to keep a vision-transcription run alive through
the provider's per-minute token budget. Rate-limit detection is duck-typed (no
provider SDK import) and the sleep is injectable, so tests run instantly.
"""

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# A transcriber maps a rasterized page (data URI) to its Markdown text. Injected
# so tests can pass a stub that returns canned text instead of calling the model.
Transcriber = Callable[[str], str]

# A sleeper pauses execution for the given number of seconds. Injected so tests
# run instantly with a no-op instead of waiting on real backoff delays.
Sleeper = Callable[[float], None]

# Default backoff schedule for rate-limit retries. The provider enforces a
# per-minute token budget, so waits are on the order of tens of seconds.
_DEFAULT_MAX_RETRIES = 6
_DEFAULT_BASE_DELAY = 2.0
_DEFAULT_MAX_DELAY = 60.0


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return whether `exc` looks like an API rate-limit (HTTP 429) error.

    Detection is by exception class name and message so the OpenAI SDK never has
    to be imported here: any error whose type name or text mentions a 429 status
    or a rate limit is treated as transient and worth retrying. Unrelated errors
    return False and must be re-raised immediately so real bugs are not masked.
    """
    haystack = f"{type(exc).__name__} {exc}".lower()
    return "ratelimit" in haystack or "rate limit" in haystack or "429" in haystack


def with_rate_limit_retry(
    transcriber: Transcriber,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
    max_delay: float = _DEFAULT_MAX_DELAY,
    sleep: Sleeper = time.sleep,
) -> Transcriber:
    """Wrap a transcriber so rate-limit failures retry with exponential backoff.

    Only rate-limit (HTTP 429) errors are retried; any other exception is
    re-raised immediately so genuine bugs surface instead of being silently
    retried. Between attempts the wrapper sleeps `base_delay * 2**attempt`,
    capped at `max_delay`. The sleep function is injectable so tests can pass a
    no-op and run without any real waiting. After `max_retries` exhausted
    retries the last rate-limit error propagates.
    """

    def wrapped(image_uri: str) -> str:
        attempt = 0
        while True:
            try:
                return transcriber(image_uri)
            except Exception as exc:  # noqa: BLE001 - re-raised below unless 429
                if not is_rate_limit_error(exc):
                    raise
                if attempt >= max_retries:
                    logger.warning("rate limit: giving up after %d retries", attempt)
                    raise
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "rate limit hit; backing off %.1fs before retry %d/%d",
                    delay,
                    attempt + 1,
                    max_retries,
                )
                sleep(delay)
                attempt += 1

    return wrapped
