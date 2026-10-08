"""Small formatters of the report skeleton: percent, mark, data stamp, links."""

from __future__ import annotations

import pandas as pd


def pct(value, digits=1) -> str:
    """A fraction as a signed percent cell; a dash when missing."""
    return "–" if value is None or pd.isna(value) else f"{value * 100:+.{digits}f}%"


def mark(value) -> str:
    """A check or cross for a boolean; a dash when missing."""
    return "–" if value is None or pd.isna(value) else ("✅" if bool(value) else "❌")


def data_stamp(report_data: dict) -> str:
    """Hidden line recording which data a report was built from (kept when the agent fills it): as-of date, regime
    and, when report.py set it, the forecast outcome (outcome_stamp.py, issue #50)."""
    reg = report_data["regime"].iloc[0]["regime"] if not report_data["regime"].empty else "?"
    outcome = f" outcome={report_data['outcome']}" if report_data.get("outcome") else ""
    return f"<!-- report-data: as_of={report_data['as_of']} regime={reg}{outcome} -->"


def review_line(review_row: dict, link: str) -> str:
    """The one-line summary of the weekly review."""
    proposal_count = int(review_row["n_proposals"])
    return (
        f"Weekly review {review_row['week']}: {proposal_count} proposed range "
        f"change{'s' if proposal_count != 1 else ''} for a human to decide"
        f"{' (low sample)' if review_row['low_sample'] else ''} · {link}"
    )


def md_link(path: str) -> str:
    """A markdown link whose text is its target."""
    return f"[{path}]({path})"
