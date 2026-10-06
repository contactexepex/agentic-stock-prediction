"""Citable evidence ids of a replay root and their context-pack section."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from marketbrief.constants.ai_replay import EVIDENCE_DAYS, EVIDENCE_KINDS
from marketbrief.core.database import connect
from marketbrief.replay.ai_replay.roots import data_root


def evidence(market: str, root: Path, cutoff: datetime, days: int = EVIDENCE_DAYS) -> tuple[pd.DataFrame, dict]:
    """Citable ids in root (news, SEC filings, NSE announcements), with when each became public."""
    with data_root(root):
        con = connect(market)
        frames = []
        for kind, sql in (
            (
                "news",
                "SELECT id, array_to_string(tickers, ',') AS ticker, 'news' AS form, "
                "coalesce(published_at, first_seen_at) AS public_at, title AS text FROM news ORDER BY ALL",
            ),
            (
                "filings",
                "SELECT id, ticker, form, coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) AS public_at, "
                "description AS text FROM filings ORDER BY ALL",
            ),
            (
                "announcements",
                "SELECT id, ticker, category AS form, coalesce(published_at, first_seen_at) AS public_at, "
                "subject AS text FROM announcements ORDER BY ALL",
            ),
        ):
            frame = con.execute(sql).df()
            frame["kind"] = kind
            frames.append(frame)
    evidence_frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    evidence_frame = evidence_frame.drop_duplicates("id")
    since = pd.Timestamp(cutoff) - pd.Timedelta(days=days)
    pub = pd.to_datetime(evidence_frame["public_at"], utc=True)
    recent = evidence_frame[pub >= since]
    counts = {
        "total": int(len(evidence_frame)),
        f"last_{days}d": int(len(recent)),
        "by_kind_total": {key: int((evidence_frame["kind"] == key).sum()) for key in EVIDENCE_KINDS},
        f"by_kind_last_{days}d": {key: int((recent["kind"] == key).sum()) for key in EVIDENCE_KINDS},
        "tickers_with_recent_ids": int(recent["ticker"].replace("", np.nan).dropna().nunique()),
        f"by_form_last_{days}d": {
            str(key): int(count) for key, count in recent["form"].fillna("").value_counts().items()
        },
    }
    return evidence_frame, counts


def evidence_section(
    evidence_frame: pd.DataFrame, cutoff: datetime, days: int = EVIDENCE_DAYS, limit: int = 200
) -> str:
    """The context pack's section listing the citable ids public before the cutoff."""
    since = pd.Timestamp(cutoff) - pd.Timedelta(days=days)
    frame = evidence_frame.assign(public_at=pd.to_datetime(evidence_frame["public_at"], utc=True))
    frame = frame[frame["public_at"] >= since].sort_values(["public_at", "id"], ascending=[False, True])
    head = (
        f"## Citable evidence ids (as-of replay; public in the {days} days before {cutoff.isoformat()})\n\n"
        "Only these kinds of ids may go in `evidence_ids` (news, SEC filings, NSE announcements). There is no "
        "stored news before live collection began, so in a replay only filings or announcements can be cited.\n\n"
    )
    if frame.empty:
        return head + "_none: no citable ids in this window, so every call must be an abstention_\n"
    lines = ["| id | kind | ticker | form | public_utc | text |", "|---|---|---|---|---|---|"]
    for row in frame.head(limit).itertuples():
        row_text = str(row.text or "").replace("|", "/").replace("\n", " ")[:120]
        lines.append(
            f"| {row.id} | {row.kind} | {row.ticker or ''} | {row.form or ''} | {str(row.public_at)[:16]} | "
            f"{row_text} |"
        )
    more = (
        f"\n{len(frame) - limit} more in this window (query DuckDB in the replay root).\n"
        if len(frame) > limit
        else "\n"
    )
    return head + "\n".join(lines) + "\n" + more
