"""The weekly review's intraday section (WS5 learning loop): how the deviations the explainer described turned out
by the session's close, counted held / reversed / faded / pending, for the review week and since start, overall and
per attribution (marketbrief/intraday/outcomes.py). Notes and closes count only once stored by the review's clock
(MB_NOW-aware). Context only: a note describes a move, it is never a call and is not scored."""

from __future__ import annotations

from datetime import date

from marketbrief.core.clock import clock
from marketbrief.intraday.constants import OUTCOME_FADED, OUTCOME_HELD, OUTCOME_PENDING, OUTCOME_REVERSED
from marketbrief.intraday.outcomes import explanation_outcomes, outcome_summary
from marketbrief.intraday.settings import intraday_config_or_default

OUTCOMES = (OUTCOME_HELD, OUTCOME_REVERSED, OUTCOME_FADED, OUTCOME_PENDING)


def intraday_outcomes(con, start: date, end: date) -> dict:
    """{week, all}: outcome_summary of the explained deviations with session dates in the review week and up to its
    end, as stored by the clock."""
    settings = intraday_config_or_default()
    if not has_view(con):   # a connection without the views of sql/views.sql (some tests build a bare one)
        empty = outcome_summary([])
        return {"week": empty, "all": empty, "hold_fraction": settings["outcome"]["hold_fraction"]}
    as_of = clock()
    return {
        "week": outcome_summary(explanation_outcomes(con, settings, start, end, as_of)),
        "all": outcome_summary(explanation_outcomes(con, settings, None, end, as_of)),
        "hold_fraction": settings["outcome"]["hold_fraction"],
    }


def has_view(con) -> bool:
    """The connection has the learning loop's view."""
    found = con.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = 'intraday_explanation_close'")
    return bool(found.fetchone()[0])


def count_row(name: str, counts: dict) -> str:
    """One table row: n and the count of each outcome."""
    total = sum(counts.values())
    return f"| {name} | {total} | " + " | ".join(str(counts.get(outcome, 0)) for outcome in OUTCOMES) + " |"


def markdown_lines(intraday: dict, win_names: dict) -> list[str]:
    """The review section."""
    lines = ["## Intraday deviations: held or reversed by the close", ""]
    if not intraday["all"]["n"]:
        return lines + ["_No explained intraday deviation stored yet (`scripts/intraday_check.py`)._", ""]
    lines += [
        f"Each note of the deviation explainer, paired with the session's stored close: **held** = the move since "
        f"the open kept its sign and at least {intraday['hold_fraction']:g} of its size, **reversed** = the sign "
        "flipped, **faded** = otherwise, **pending** = no close stored yet. Context only: a note is never a call.",
        "",
        "| Window · attribution | n | held | reversed | faded | pending |",
        "|---|---|---|---|---|---|",
    ]
    for window in ("week", "all"):
        summary = intraday[window]
        lines.append(count_row(win_names[window], summary["outcomes"]))
        lines += [count_row(f"{win_names[window]} · {name}", counts)
                  for name, counts in summary["by_attribution"].items()]
    return lines + [""]
