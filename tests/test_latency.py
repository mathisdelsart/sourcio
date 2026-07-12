"""Tests for the per-stage latency instrumentation in ``obs``.

Everything runs offline with synthetic durations: no network, no LLM, no API
call. The timer is exercised with ``enabled=True`` and its own sink so it never
touches the process-wide sink or any environment-driven behavior, and the
percentile math is asserted directly on hand-built samples.
"""

from __future__ import annotations

import json

import pytest

from core.obs import (
    LatencySample,
    StageStats,
    latency_enabled,
    latency_stats,
    percentile,
    record_sample,
    reset_samples,
    stats_to_dict,
    timer,
    write_latency,
)

# --- percentile (nearest-rank) ----------------------------------------------


def test_percentile_empty_raises():
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_percentile_single_sample_returns_that_value():
    assert percentile([42.0], 0.5) == 42.0
    assert percentile([42.0], 0.95) == 42.0


def test_percentile_p50_and_p95_on_ten_values():
    values = [float(x) for x in range(1, 11)]  # 1..10, sorted
    # Nearest-rank: p50 -> ceil(0.5*10)=5 -> values[4] == 5.
    assert percentile(values, 0.5) == 5.0
    # p95 -> ceil(0.95*10)=10 -> values[9] == 10.
    assert percentile(values, 0.95) == 10.0


def test_percentile_p0_and_p100_are_min_and_max():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.0) == 1.0  # clamped to rank 1
    assert percentile(values, 1.0) == 4.0  # rank n


def test_percentile_two_values():
    values = [10.0, 20.0]
    assert percentile(values, 0.5) == 10.0  # ceil(1.0)=1 -> first
    assert percentile(values, 0.95) == 20.0  # ceil(1.9)=2 -> second


# --- latency_stats aggregation ----------------------------------------------


def test_latency_stats_empty_returns_no_rows():
    assert latency_stats([]) == []


def test_latency_stats_single_sample_per_stage():
    samples = [LatencySample("retrieval", 12.0)]
    [stat] = latency_stats(samples)
    assert stat == StageStats(stage="retrieval", count=1, mean_ms=12.0, p50_ms=12.0, p95_ms=12.0)


def test_latency_stats_groups_by_stage_and_sorts():
    samples = [
        LatencySample("llm", 100.0),
        LatencySample("retrieval", 10.0),
        LatencySample("llm", 200.0),
        LatencySample("retrieval", 30.0),
        LatencySample("retrieval", 20.0),
    ]
    stats = latency_stats(samples)
    # Stages are returned sorted alphabetically.
    assert [s.stage for s in stats] == ["llm", "retrieval"]
    by_stage = {s.stage: s for s in stats}

    llm = by_stage["llm"]
    assert llm.count == 2
    assert llm.mean_ms == 150.0
    assert llm.p50_ms == 100.0  # ceil(0.5*2)=1 -> first of [100, 200]
    assert llm.p95_ms == 200.0  # ceil(0.95*2)=2 -> second

    ret = by_stage["retrieval"]
    assert ret.count == 3
    assert ret.mean_ms == 20.0
    assert ret.p50_ms == 20.0  # ceil(1.5)=2 -> middle of [10, 20, 30]
    assert ret.p95_ms == 30.0  # ceil(2.85)=3 -> last


def test_latency_stats_is_order_independent_for_percentiles():
    ascending = [LatencySample("s", float(x)) for x in range(1, 6)]
    descending = [LatencySample("s", float(x)) for x in range(5, 0, -1)]
    assert latency_stats(ascending) == latency_stats(descending)


# --- timer context manager --------------------------------------------------


def test_timer_records_into_sink_when_enabled():
    sink: list[LatencySample] = []
    with timer("retrieval", sink=sink, enabled=True):
        pass
    assert len(sink) == 1
    assert sink[0].stage == "retrieval"
    assert sink[0].duration_ms >= 0.0


def test_timer_is_noop_when_disabled():
    sink: list[LatencySample] = []
    with timer("retrieval", sink=sink, enabled=False):
        pass
    assert sink == []


def test_timer_records_even_when_block_raises():
    sink: list[LatencySample] = []
    with pytest.raises(RuntimeError):
        with timer("llm", sink=sink, enabled=True):
            raise RuntimeError("boom")
    # The duration is recorded in the finally block despite the exception.
    assert len(sink) == 1
    assert sink[0].stage == "llm"


def test_timer_uses_process_sink_by_default(monkeypatch):
    reset_samples()
    monkeypatch.setenv("LATENCY_ENABLED", "1")
    with timer("judge"):
        pass
    from core.obs import get_samples

    samples = get_samples()
    assert [s.stage for s in samples] == ["judge"]
    reset_samples()


def test_latency_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("LATENCY_ENABLED", raising=False)
    assert latency_enabled() is False
    monkeypatch.setenv("LATENCY_ENABLED", "1")
    assert latency_enabled() is True
    monkeypatch.setenv("LATENCY_ENABLED", "0")
    assert latency_enabled() is False
    monkeypatch.setenv("LATENCY_ENABLED", "false")
    assert latency_enabled() is False
    monkeypatch.setenv("LATENCY_ENABLED", "true")
    assert latency_enabled() is True


def test_record_sample_appends_to_explicit_sink():
    sink: list[LatencySample] = []
    record_sample("retrieval", 5.0, sink=sink)
    record_sample("retrieval", 7, sink=sink)
    assert [s.duration_ms for s in sink] == [5.0, 7.0]
    assert all(isinstance(s.duration_ms, float) for s in sink)


# --- serialization round-trip -----------------------------------------------


def test_stats_to_dict_shape():
    samples = [LatencySample("retrieval", 10.0), LatencySample("retrieval", 30.0)]
    payload = stats_to_dict(latency_stats(samples))
    assert payload == {"retrieval": {"count": 2, "mean_ms": 20.0, "p50_ms": 10.0, "p95_ms": 30.0}}


def test_write_and_load_latency_round_trip(tmp_path):
    samples = [
        LatencySample("retrieval", 10.0),
        LatencySample("retrieval", 20.0),
        LatencySample("llm", 100.0),
    ]
    path = tmp_path / "latency.json"
    written = write_latency(samples, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == written
    assert loaded["llm"]["p50_ms"] == 100.0


def test_write_latency_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "latency.json"
    write_latency([LatencySample("judge", 1.0)], path)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["judge"]["count"] == 1
