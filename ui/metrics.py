"""Streamlit metrics dashboard for the portfolio / demo.

A small read-only page that surfaces two kinds of project signal:

* **Quality metrics** produced offline by the faithfulness evaluation
  (``eval/run_eval.py``): faithfulness, relevance, refusal accuracy and the
  retrieval hit-rate. These are never recomputed here (the live evaluation
  needs an OpenAI key); they are loaded from a JSON results file or passed in
  as a plain dict.
* **Usage stats** read from the relational store: how many students, exercises,
  grades and messages have been recorded.

All non-Streamlit logic lives in the pure helpers below so it can be unit
tested without installing the optional ``ui`` extra and without any network or
provider call. The ``main()`` entry point only wires those helpers to widgets
and imports Streamlit lazily.

Run with: ``uv run streamlit run ui/metrics.py`` (requires ``--extra ui``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Default location of the metrics produced by the offline evaluation
# (``eval/run_eval.py --out``). Resolved relative to the repository root so the
# dashboard shows the real last run out of the box. Kept as a string here and
# resolved lazily, so importing this module never touches the filesystem.
DEFAULT_RESULTS_PATH = "eval/results.json"

# Quality metrics we know how to render, in display order, with a label and
# whether the value should be shown as a percentage. Keys mirror the fields of
# ``eval.run_eval.Metrics`` plus an optional ``retrieval_hit_rate``.
_METRIC_SPECS: tuple[tuple[str, str, bool], ...] = (
    ("faithfulness_rate", "Faithfulness", True),
    ("relevance_rate", "Relevance", True),
    ("refusal_accuracy", "Refusal accuracy", True),
    ("retrieval_hit_rate", "Retrieval hit-rate", True),
)

# DB entities to count, mapping a stat key to the human label used in display.
_STAT_LABELS: tuple[tuple[str, str], ...] = (
    ("students", "Students"),
    ("exercises", "Exercises"),
    ("grades", "Grades"),
    ("messages", "Messages"),
)


@dataclass(frozen=True)
class MetricCard:
    """One quality metric rendered as a labelled card.

    ``value`` is the raw numeric value (or ``None`` when absent from the source)
    and ``display`` is the pre-formatted string shown to the user.
    """

    key: str
    label: str
    value: float | None
    display: str


def _coerce_metrics(metrics: Any) -> dict[str, Any]:
    """Return a plain dict view of a metrics source.

    Accepts a mapping or any object exposing the metric fields as attributes
    (e.g. an ``eval.run_eval.Metrics`` instance), so both can be rendered
    uniformly.
    """
    if metrics is None:
        return {}
    if isinstance(metrics, dict):
        return metrics
    return {
        key: getattr(metrics, key) for key, _label, _pct in _METRIC_SPECS if hasattr(metrics, key)
    }


def format_metric_cards(metrics: Any) -> list[MetricCard]:
    """Build the ordered list of metric cards from a metrics source.

    ``metrics`` may be a dict or a ``Metrics``-like object. Missing metrics get a
    ``None`` value and a placeholder display, so the dashboard renders even with
    a partial results file. Values are formatted as percentages.
    """
    data = _coerce_metrics(metrics)
    cards: list[MetricCard] = []
    for key, label, as_pct in _METRIC_SPECS:
        raw = data.get(key)
        value = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
        if value is None:
            display = "n/a"
        elif as_pct:
            display = f"{value:.0%}"
        else:
            display = f"{value:g}"
        cards.append(MetricCard(key=key, label=label, value=value, display=display))
    return cards


def load_metrics_file(path: str | Path) -> dict[str, Any]:
    """Load quality metrics from a JSON results file.

    Returns an empty dict when the file is missing or unreadable so the page can
    fall back to a friendly "no results yet" state instead of crashing. A JSON
    object is expected; any other top-level shape yields an empty dict.
    """
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def load_default_metrics(path: str | Path | None = None) -> dict[str, Any]:
    """Load quality metrics from the eval results file, defaulting to the last run.

    With no ``path`` the dashboard reads :data:`DEFAULT_RESULTS_PATH`
    (``eval/results.json``) so it shows the real last evaluation when one is
    present. The source stays injectable for tests and for the sidebar override,
    and a missing file gracefully yields an empty dict (no results yet).
    """
    return load_metrics_file(path if path is not None else DEFAULT_RESULTS_PATH)


def gather_db_stats(session: Any) -> dict[str, int]:
    """Count the stored entities for the usage panel.

    ``session`` is any SQLAlchemy session; it is injected so tests can pass an
    in-memory one. On any error (e.g. no database configured or missing tables)
    every count gracefully falls back to zero, keeping the page usable in a
    fresh checkout.
    """
    stats = {key: 0 for key, _label in _STAT_LABELS}
    if session is None:
        return stats

    # Imported lazily so this module stays importable without the ``api`` extra
    # (SQLAlchemy) when only the pure metric helpers are needed.
    try:
        from sqlalchemy import func, select

        from db.models import Exercise, Grade, Message, Student
    except ImportError:
        return stats

    models = {
        "students": Student,
        "exercises": Exercise,
        "grades": Grade,
        "messages": Message,
    }
    for key, model in models.items():
        try:
            stats[key] = int(session.scalar(select(func.count()).select_from(model)) or 0)
        except Exception:
            stats[key] = 0
    return stats


def format_stats(stats: dict[str, int]) -> str:
    """Render usage counts as a Markdown bullet list.

    Missing keys are treated as zero, so a partial stats dict still renders the
    full set of entities.
    """
    lines = [f"- **{label}:** {int(stats.get(key, 0))}" for key, label in _STAT_LABELS]
    return "\n".join(lines)


def _open_session_stats(database_url: str | None = None) -> dict[str, int]:
    """Open a short-lived DB session and gather stats, or zeros on failure.

    Used by the Streamlit wiring; kept here (not in ``main``) only to isolate the
    optional-import boundary. Never raises: a fresh checkout with no database
    yields all-zero counts.
    """
    try:
        from db.session import create_engine_from_settings, get_session
    except ImportError:
        return gather_db_stats(None)
    try:
        engine = create_engine_from_settings(database_url) if database_url else None
        with get_session(engine) as session:
            return gather_db_stats(session)
    except Exception:
        return gather_db_stats(None)


# --- Streamlit UI -----------------------------------------------------------


def main() -> None:  # pragma: no cover - thin UI wiring, not unit-tested
    import streamlit as st

    st.set_page_config(page_title="Grounded tutor - metrics", page_icon=":bar_chart:")
    st.title("Project metrics")
    st.caption("Quality of the grounded answers and usage of the tutor, for the demo.")

    with st.sidebar:
        st.header("Sources")
        results_path = st.text_input("Eval results JSON", value=DEFAULT_RESULTS_PATH)
        database_url = st.text_input("Database URL (optional)", value="")

    st.subheader("Quality metrics")
    metrics = load_default_metrics(results_path or None)
    cards = format_metric_cards(metrics)
    if not any(card.value is not None for card in cards):
        st.info("No evaluation results found yet. Run the offline eval to populate them.")
    columns = st.columns(len(cards))
    for column, card in zip(columns, cards, strict=True):
        column.metric(card.label, card.display)

    st.subheader("Usage")
    stats = _open_session_stats(database_url or None)
    st.markdown(format_stats(stats))


if __name__ == "__main__":  # pragma: no cover
    main()
