"""Opt-in hardening middleware: security response headers and rate limiting.

Both pieces are pure-stdlib (no third-party dependency) and safe by default:

* Security headers are always added and never change response bodies or status
  codes, so existing behavior is preserved.
* Rate limiting is disabled unless ``Settings.rate_limit_per_minute`` is a
  positive value, so the default configuration (and the test suite) is never
  throttled.

The middleware reads settings through ``core.config.get_settings`` at request
time, so a deployment toggles either feature with an environment variable and no
code change.
"""

import threading
import time
from collections import deque

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from core.config import get_settings

# One rolling window is 60 seconds wide; the limit is expressed per minute.
_WINDOW_SECONDS = 60.0

# Prune idle clients only occasionally so the bookkeeping stays O(1)-ish per
# request instead of scanning every known client on every call.
_PRUNE_EVERY_SECONDS = 300.0


class SecurityHeadersMiddleware:
    """Add a conservative set of security headers to every response.

    The headers are defensive defaults that do not affect API clients or the
    interactive ``/docs`` page:

    * ``X-Content-Type-Options: nosniff`` — disable MIME sniffing.
    * ``X-Frame-Options: DENY`` — forbid framing (clickjacking).
    * ``Referrer-Policy: no-referrer`` — never leak URLs in the Referer header.
    * ``X-XSS-Protection: 0`` — disable the legacy, buggy XSS auditor (modern
      best practice is to turn it off rather than enable it).
    * ``Permissions-Policy`` — deny powerful browser features the API never uses.

    ``Strict-Transport-Security`` is added only when ``enable_hsts`` is set, as
    HSTS is meaningful only behind TLS and would be incorrect on plain HTTP.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                for name, value in self._headers():
                    headers.append((name.encode("latin-1"), value.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    def _headers() -> list[tuple[str, str]]:
        headers = [
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", "DENY"),
            ("referrer-policy", "no-referrer"),
            ("x-xss-protection", "0"),
            ("permissions-policy", "geolocation=(), microphone=(), camera=()"),
        ]
        if get_settings().enable_hsts:
            headers.append(("strict-transport-security", "max-age=31536000; includeSubDomains"))
        return headers


class _FixedWindowCounter:
    """Per-client sliding-window request counter, thread/async-safe in-process.

    Each client (keyed by IP) keeps a deque of recent request timestamps. On each
    hit, timestamps older than the window are evicted from the left; the request
    is allowed when fewer than ``limit`` remain. This is O(1) amortized per
    request and bounds memory by pruning idle clients periodically.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        # Seeded so the first prune is driven by the first observed timestamp,
        # which keeps the counter usable with synthetic clocks in tests.
        self._last_prune: float | None = None

    def check(self, key: str, limit: int, now: float) -> tuple[bool, float]:
        """Record a hit for ``key`` and report whether it is allowed.

        Returns ``(allowed, retry_after_seconds)``. When allowed, the retry hint
        is 0. When throttled, it is how long the caller should wait before the
        oldest in-window request ages out.
        """
        with self._lock:
            self._maybe_prune(now)
            window_start = now - _WINDOW_SECONDS
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] <= window_start:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(0.0, bucket[0] + _WINDOW_SECONDS - now)
                return False, retry_after
            bucket.append(now)
            return True, 0.0

    def _maybe_prune(self, now: float) -> None:
        """Drop clients with no in-window hits so memory cannot grow unbounded."""
        if self._last_prune is None:
            self._last_prune = now
            return
        if now - self._last_prune < _PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        window_start = now - _WINDOW_SECONDS
        stale = [
            key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= window_start
        ]
        for key in stale:
            del self._hits[key]


class RateLimitMiddleware:
    """Throttle each client IP to ``rate_limit_per_minute`` requests per minute.

    Disabled (pass-through) when the configured limit is not positive, which is
    the default. When enabled and the limit is exceeded, the request is rejected
    with HTTP 429 and a ``Retry-After`` header, without invoking the route.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._counter = _FixedWindowCounter()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = get_settings().rate_limit_per_minute
        if limit <= 0:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        key = request.client.host if request.client else "unknown"
        allowed, retry_after = self._counter.check(key, limit, time.monotonic())
        if allowed:
            await self.app(scope, receive, send)
            return

        response: Response = JSONResponse(
            {"detail": "Rate limit exceeded. Try again later."},
            status_code=429,
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )
        await response(scope, receive, send)
