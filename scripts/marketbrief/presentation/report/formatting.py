"""Small formatters of the report skeleton: percent, mark, data stamp, links."""

from __future__ import annotations

import pandas as pd


def pct(value, digits=1) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:+.{digits}f}%"


def mark(value) -> str:
    return "–" if value is None or pd.isna(value) else ("✅" if bool(value) else "❌")


def data_stamp(report_data: dict) -> str:
    """Hidden line recording which data a report was built from (kept when the agent fills it)."""
    reg = report_data["regime"].iloc[0]["regime"] if not report_data["regime"].empty else "?"
    return f"<!-- report-data: as_of={report_data['as_of']} regime={reg} -->"


def review_line(review_config: dict, link: str) -> str:
    proposal_count = int(review_config["n_proposals"])
    return (
        f"Weekly review {review_config['week']}: {proposal_count} proposed range "
        f"change{'s' if proposal_count != 1 else ''} for a human to decide"
        f"{' (low sample)' if review_config['low_sample'] else ''} · {link}"
    )


def md_link(path: str) -> str:
    return f"[{path}]({path})"
