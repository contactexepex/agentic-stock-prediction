"""Cell formatters and table rows of the weekly review's markdown report."""

from __future__ import annotations

import math
from marketbrief.analytics import scoring


def fpct(value, digits: int = 0) -> str:
    return scoring.percent(value, digits)


def fnum(value, digits: int = 3) -> str:
    return "–" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.{digits}f}"


def fval(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {item}" for key, item in value.items()) + "}"
    return str(value)


def flag(count: int, review_config: dict) -> str:
    return "low n" if count < review_config["min_n"] else ""


def range_row(label: list, summary: dict, review_config: dict) -> list:
    return [
        *label,
        summary["n"],
        fpct(summary.get("cover50")),
        fpct(summary.get("cover80")),
        fpct(summary.get("naive_cover50")),
        fpct(summary.get("naive_cover80")),
        fnum(summary.get("width80_pct"), 2),
        fnum(summary.get("naive_width80_pct"), 2),
        fnum(summary.get("score80_pct")),
        fnum(summary.get("naive_score80_pct")),
        flag(summary["n"], review_config),
    ]


def ablation_rows(ablation: dict) -> list[list]:
    rows = []
    for variant in ablation.get("variants") or []:
        horizons = list(variant["by_h"])
        join = lambda key, formatter: (
            " / ".join(formatter(variant["by_h"][horizon].get(key)) for horizon in horizons) or "–"
        )  # noqa: E731
        rel = (variant.get("vs_current") or {}).get("rel_score")
        rows.append(
            [
                variant["name"],
                variant["n"],
                join("cover50", fpct),
                join("cover80", fpct),
                join("width80_pct", lambda value: fnum(value, 2)),
                join("score80_pct", fnum),
                "–" if rel is None else f"{rel:+.1%}",
                variant.get("verdict", ""),
            ]
        )
    return rows
