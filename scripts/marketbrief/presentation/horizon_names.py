"""Horizons on the reader's pages (HTML report, charts, dashboard, report and Slack; core/horizons.py, docs/SPEC.md
decision 37): their names, the trading days to a range's target close, the horizon an overview shows, and rows grouped
by horizon and horizon label. An N+k row and a row of an old window (legacy_cc, legacy_5d_d4) never share a name and
are never pooled."""
from __future__ import annotations

import pandas as pd

from marketbrief.constants.horizon_names import (
    NAME_LEGACY_DAY,
    NAME_N_PLUS_K,
    PHRASE_LEGACY,
    PHRASE_N_PLUS_K,
    WHEN_LEGACY,
    WHEN_N_PLUS_K,
)
from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.core.horizons import horizons


def days_to_target(h: int, label: str | None) -> int:
    """Trading days from the as-of close to a range's target close: k + 1 for N+k (the close of D+k); h for an old
    range (legacy_cc: the 1-day range targeted D's close, the 5-day one D+4's)."""
    return int(h) + 1 if label == LABEL_N_PLUS_K else int(h)


def horizon_name(h: int, label: str | None, n_plus_k: str = NAME_N_PLUS_K, legacy: tuple = NAME_LEGACY_DAY) -> str:
    """The `n_plus_k` template for an N+k row; for a row of an old window its old wording, `legacy` = (names of
    particular horizons, template of the others)."""
    days = days_to_target(h, label)
    if label == LABEL_N_PLUS_K:
        return n_plus_k.format(h=int(h), days=days)
    named, other = legacy
    return named.get(int(h), other.format(h=int(h), days=days))


def range_texts(h: int, label: str | None) -> dict:
    """A range's name, its trading days to the target close (`ahead`), the card text (`when`) and the chart title
    phrase (`phrase`)."""
    return {"name": horizon_name(h, label), "ahead": days_to_target(h, label),
            "when": horizon_name(h, label, WHEN_N_PLUS_K, WHEN_LEGACY),
            "phrase": horizon_name(h, label, PHRASE_N_PLUS_K, PHRASE_LEGACY)}


def horizon_order(h: int, label: str | None) -> tuple:
    """Sort key: by horizon, an N+k row before an old window's."""
    return (int(h), label != LABEL_N_PLUS_K, label or "")


def by_horizon(frame: pd.DataFrame, horizon: str = "horizon_days", label: str = "horizon_label") -> list:
    """The rows of a frame per horizon and horizon label, never pooled, in horizon_order: [((h, label), rows)]."""
    if frame.empty:
        return []
    groups = frame.groupby([horizon, label], sort=False)
    return sorted((((int(h), lab), rows) for (h, lab), rows in groups), key=lambda item: horizon_order(*item[0]))


def primary_horizon(view: dict) -> int:
    """The horizon an overview shows: the shortest one with a range that is not late; when every range is late, the
    longest one published; with no range at all, the longest configured horizon (config/strategies.yaml)."""
    ranges = [r for c in view["companies"] for r in c["ranges"]]
    on_time = sorted({r["h"] for r in ranges if not r["late"]})
    if on_time:
        return on_time[0]
    return max((r["h"] for r in ranges), default=horizons()[-1])
