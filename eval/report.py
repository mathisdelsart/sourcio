"""Render the offline evaluation metrics as a Markdown report.

This is a presentation helper only: it turns the metrics dict produced by
``run_eval`` (the same shape written by ``--out``, e.g.
``{"refusal_accuracy": 1.0, "faithfulness_rate": 0.75, ...}``) into a titled
Markdown table plus a short pass/fail summary against the thresholds.

The core ``render_report`` function is pure (no I/O) and tolerant of missing
keys, so it works on any subset of the metrics. ``write_report`` is a thin
writer that dumps the rendered Markdown to a path; it is the only I/O here.

No scoring happens in this module and no LLM is involved.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# The rate metrics rendered as percentages, paired with their default pass
# threshold (mirrors the defaults in ``run_eval``). Order is the display order.
_RATE_METRICS: tuple[tuple[str, str, float], ...] = (
    ("refusal_accuracy", "Refusal accuracy", 1.0),
    ("faithfulness_rate", "Faithfulness", 1.0),
    ("relevance_rate", "Relevance", 1.0),
    ("retrieval_hit_rate", "Retrieval hit rate", 0.0),
)

# Plain integer counters reported below the rate table, when present.
_COUNT_METRICS: tuple[tuple[str, str], ...] = (
    ("total", "Total cases"),
    ("judged", "Judged cases"),
    ("retrieval_checked", "Retrieval checked"),
)


def _format_percent(value: Any) -> str:
    """Format a rate in ``[0, 1]`` as a whole-percent string, else ``n/a``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.0%}"
    return "n/a"


def _meets(value: Any, threshold: float) -> bool | None:
    """Whether ``value`` meets ``threshold``; ``None`` when not a number."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value >= threshold
    return None


def render_report(
    metrics: Mapping[str, Any],
    thresholds: Mapping[str, float] | None = None,
    *,
    title: str = "Offline evaluation report",
) -> str:
    """Render ``metrics`` as a Markdown report string (pure, no I/O).

    ``metrics`` mirrors the dict produced by ``run_eval`` (via ``--out``). Any
    rate or counter that is absent is simply skipped, so partial dicts render
    cleanly. ``thresholds`` overrides the per-metric pass threshold used for the
    status column and the overall verdict; missing entries fall back to the
    built-in defaults.
    """
    thresholds = thresholds or {}
    lines: list[str] = [f"# {title}", ""]

    # --- rate table ------------------------------------------------------
    lines.append("| Metric | Value | Threshold | Status |")
    lines.append("| --- | --- | --- | --- |")
    overall_ok = True
    any_rate = False
    for key, label, default_threshold in _RATE_METRICS:
        if key not in metrics:
            continue
        any_rate = True
        threshold = float(thresholds.get(key, default_threshold))
        value = metrics[key]
        meets = _meets(value, threshold)
        if meets is None:
            status = "n/a"
        elif meets:
            status = "PASS"
        else:
            status = "FAIL"
            overall_ok = False
        lines.append(f"| {label} | {_format_percent(value)} | {threshold:.0%} | {status} |")
    if not any_rate:
        lines.append("| _(no metrics)_ | n/a | n/a | n/a |")

    # --- counters --------------------------------------------------------
    counters = [(label, metrics[key]) for key, label in _COUNT_METRICS if key in metrics]
    if counters:
        lines.extend(["", "## Counts", ""])
        for label, value in counters:
            lines.append(f"- **{label}:** {value}")

    # --- failures --------------------------------------------------------
    failures = metrics.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)

    # --- verdict ---------------------------------------------------------
    lines.extend(["", "## Summary", ""])
    if not any_rate:
        lines.append("No rate metrics were provided.")
    else:
        verdict = "PASS" if overall_ok else "FAIL"
        lines.append(f"**Overall result: {verdict}** against the configured thresholds.")

    return "\n".join(lines) + "\n"


def write_report(
    metrics: Mapping[str, Any],
    path: Path,
    thresholds: Mapping[str, float] | None = None,
    *,
    title: str = "Offline evaluation report",
) -> None:
    """Render the report and write it to ``path`` (creating parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(metrics, thresholds, title=title), encoding="utf-8")


def render_report_from_file(
    metrics_path: Path,
    thresholds: Mapping[str, float] | None = None,
    *,
    title: str = "Offline evaluation report",
) -> str:
    """Load a metrics JSON file and render it as Markdown (convenience helper)."""
    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    return render_report(metrics, thresholds, title=title)
