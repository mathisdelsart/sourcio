"""Optional LangFuse tracing and per-stage latency instrumentation.

Two independent, fully opt-in concerns live here:

* **Tracing** (LangFuse): activates only when LangFuse credentials are present
  in the environment. The `langfuse` package is imported lazily inside the
  helpers, so importing this module never requires the optional `obs` extra.
* **Latency**: a tiny in-process timing utility (a context manager plus a
  percentile aggregator) used to record how long each pipeline stage
  (retrieval, LLM call, judge) takes. Recording is opt-in via the
  `LATENCY_ENABLED` environment variable and is zero-overhead when disabled, so
  wiring a timer around a stage never changes behavior or adds a paid call.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Credentials that signal LangFuse should be enabled. Both keys are required.
_REQUIRED_ENV_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


def tracing_enabled() -> bool:
    """Return True when LangFuse is configured via environment variables."""
    return all(os.getenv(var) for var in _REQUIRED_ENV_VARS)


def get_callbacks() -> list:
    """Return LangChain callbacks for tracing, or an empty list when disabled.

    The `langfuse` import is deferred so this module stays importable without the
    optional extra. When LangFuse is not configured, no import is attempted.
    """
    if not tracing_enabled():
        return []

    # Lazy import: only reached when tracing is explicitly enabled. The handler
    # moved across LangFuse major versions, so try both known locations.
    try:
        from langfuse.langchain import CallbackHandler  # langfuse >= 3
    except ImportError:  # pragma: no cover - depends on installed version
        from langfuse.callback import CallbackHandler  # langfuse < 3

    # The handler reads LangFuse credentials from the environment.
    return [CallbackHandler()]


# --- Per-stage latency instrumentation --------------------------------------

# Environment flag that switches latency recording on. Recording is off by
# default so that the timer context manager is a no-op (zero overhead) in
# production paths unless explicitly enabled.
_LATENCY_ENV_VAR = "LATENCY_ENABLED"

# Default location the recorded samples are flushed to and the dashboard reads
# from. Resolved relative to the repository root, mirroring the eval results
# file. Kept as a string and resolved lazily so importing never touches disk.
DEFAULT_LATENCY_PATH = "eval/latency.json"


@dataclass(frozen=True)
class LatencySample:
    """A single timed observation: how long one stage took, in milliseconds."""

    stage: str
    duration_ms: float


@dataclass(frozen=True)
class StageStats:
    """Aggregated latency for one stage."""

    stage: str
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float


# Process-wide sink for recorded samples. A module-level list keeps the timer
# dependency-free; tests and callers can pass an explicit sink instead.
_SAMPLES: list[LatencySample] = []


def latency_enabled() -> bool:
    """Return True when latency recording is switched on via the environment.

    Any non-empty, non-"0"/"false" value enables it, so the common shell idiom
    ``LATENCY_ENABLED=1`` works.
    """
    value = os.getenv(_LATENCY_ENV_VAR, "").strip().lower()
    return value not in ("", "0", "false", "no")


def reset_samples() -> None:
    """Clear the process-wide sample sink. Mainly for tests and fresh runs."""
    _SAMPLES.clear()


def get_samples() -> list[LatencySample]:
    """Return a copy of the samples recorded so far in the default sink."""
    return list(_SAMPLES)


def record_sample(
    stage: str,
    duration_ms: float,
    sink: list[LatencySample] | None = None,
) -> None:
    """Append one ``{stage, duration_ms}`` record to a sink.

    Defaults to the process-wide sink; ``sink`` is injectable so tests and
    callers can collect into their own list.
    """
    target = _SAMPLES if sink is None else sink
    target.append(LatencySample(stage=stage, duration_ms=float(duration_ms)))


@contextmanager
def timer(
    stage: str,
    *,
    sink: list[LatencySample] | None = None,
    enabled: bool | None = None,
) -> Iterator[None]:
    """Time the wrapped block and record its duration for ``stage``.

    Opt-in and zero-overhead by default: when latency recording is disabled
    (``enabled`` is None and :func:`latency_enabled` is False) nothing is timed
    or stored, so wrapping a stage never changes behavior. Pass ``enabled=True``
    to force recording (used by tests) or ``sink`` to collect elsewhere than the
    process-wide sink. The duration is measured with a monotonic clock and stored
    in milliseconds even if the block raises.
    """
    active = latency_enabled() if enabled is None else enabled
    if not active:
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        record_sample(stage, duration_ms, sink=sink)


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Return the ``fraction`` percentile of already-sorted values.

    Uses nearest-rank: the smallest value whose rank covers the requested
    fraction. ``fraction`` is in [0, 1] (e.g. 0.5 for p50, 0.95 for p95). The
    input must be sorted ascending and non-empty.
    """
    if not sorted_values:
        raise ValueError("percentile of an empty sequence is undefined")
    n = len(sorted_values)
    # Nearest-rank: rank = ceil(fraction * n), clamped to [1, n], 1-indexed.
    rank = max(1, min(n, _ceil(fraction * n)))
    return sorted_values[rank - 1]


def _ceil(value: float) -> int:
    """Integer ceiling without importing math (kept dependency-light)."""
    truncated = int(value)
    return truncated + 1 if value > truncated else truncated


def latency_stats(samples: Iterable[LatencySample]) -> list[StageStats]:
    """Aggregate samples into per-stage count/mean/p50/p95, sorted by stage.

    Pure helper (no I/O). Stages with no samples are simply absent from the
    result. Percentiles use nearest-rank (:func:`percentile`).
    """
    by_stage: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        by_stage[sample.stage].append(sample.duration_ms)

    stats: list[StageStats] = []
    for stage in sorted(by_stage):
        values = sorted(by_stage[stage])
        count = len(values)
        stats.append(
            StageStats(
                stage=stage,
                count=count,
                mean_ms=sum(values) / count,
                p50_ms=percentile(values, 0.5),
                p95_ms=percentile(values, 0.95),
            )
        )
    return stats


def stats_to_dict(stats: Iterable[StageStats]) -> dict[str, dict[str, float]]:
    """Return a JSON-serializable ``{stage: {count, mean_ms, p50_ms, p95_ms}}`` map.

    Pure helper so the result is JSON-serializable and feeds the metrics
    dashboard (via :func:`write_latency`).
    """
    return {
        s.stage: {
            "count": s.count,
            "mean_ms": s.mean_ms,
            "p50_ms": s.p50_ms,
            "p95_ms": s.p95_ms,
        }
        for s in stats
    }


def write_latency(
    samples: Iterable[LatencySample],
    path: str | Path = DEFAULT_LATENCY_PATH,
) -> dict[str, dict[str, float]]:
    """Aggregate ``samples`` and write the per-stage stats to ``path`` as JSON.

    Creates parent directories as needed and returns the written mapping. The
    file is a build/run artifact consumed by the metrics dashboard; it is not
    committed.
    """
    payload = stats_to_dict(latency_stats(samples))
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
