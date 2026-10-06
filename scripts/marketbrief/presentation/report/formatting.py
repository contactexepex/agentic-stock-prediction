"""Small formatters of the report skeleton: percent, mark, data stamp, links."""
from __future__ import annotations

import pandas as pd


def pct(v, digits=1) -> str:
    return "–" if v is None or pd.isna(v) else f"{v * 100:+.{digits}f}%"


def mark(v) -> str:
    return "–" if v is None or pd.isna(v) else ("✅" if bool(v) else "❌")


def data_stamp(d: dict) -> str:
    """Hidden line recording which data a report was built from (kept when the agent fills it)."""
    reg = d["regime"].iloc[0]["regime"] if not d["regime"].empty else "?"
    return f"<!-- report-data: as_of={d['as_of']} regime={reg} -->"


def review_line(rv: dict, link: str) -> str:
    n = int(rv["n_proposals"])
    return (f"Weekly review {rv['week']}: {n} proposed range change{'s' if n != 1 else ''} for a human to decide"
            f"{' (low sample)' if rv['low_sample'] else ''} · {link}")


def md_link(path: str) -> str:
    return f"[{path}]({path})"
