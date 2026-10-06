"""Citable evidence ids of a replay root and their context-pack section."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from marketbrief.core.database import connect
from marketbrief.constants.ai_replay import EVIDENCE_DAYS, EVIDENCE_KINDS
from marketbrief.replay.ai_replay.roots import data_root


def evidence(market: str, root: Path, cutoff: datetime, days: int = EVIDENCE_DAYS) -> tuple[pd.DataFrame, dict]:
    """Citable ids in root (news, SEC filings, NSE announcements), with when each became public."""
    with data_root(root):
        con = connect(market)
        frames = []
        for kind, sql in (
            ("news", "SELECT id, array_to_string(tickers, ',') AS ticker, 'news' AS form, "
                     "coalesce(published_at, first_seen_at) AS public_at, title AS text FROM news ORDER BY ALL"),
            ("filings", "SELECT id, ticker, form, coalesce(accepted_at, CAST(filing_date + 1 AS TIMESTAMPTZ)) AS public_at, "
                        "description AS text FROM filings ORDER BY ALL"),
            ("announcements", "SELECT id, ticker, category AS form, coalesce(published_at, first_seen_at) AS public_at, "
                              "subject AS text FROM announcements ORDER BY ALL"),
        ):
            df = con.execute(sql).df()
            df["kind"] = kind
            frames.append(df)
    ev_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    ev_df = ev_df.drop_duplicates("id")
    since = pd.Timestamp(cutoff) - pd.Timedelta(days=days)
    pub = pd.to_datetime(ev_df["public_at"], utc=True)
    recent = ev_df[pub >= since]
    counts = {"total": int(len(ev_df)), f"last_{days}d": int(len(recent)),
              "by_kind_total": {k: int((ev_df["kind"] == k).sum()) for k in EVIDENCE_KINDS},
              f"by_kind_last_{days}d": {k: int((recent["kind"] == k).sum()) for k in EVIDENCE_KINDS},
              "tickers_with_recent_ids": int(recent["ticker"].replace("", np.nan).dropna().nunique()),
              f"by_form_last_{days}d": {str(k): int(v) for k, v in recent["form"].fillna("").value_counts().items()}}
    return ev_df, counts


def evidence_section(ev_df: pd.DataFrame, cutoff: datetime, days: int = EVIDENCE_DAYS, limit: int = 200) -> str:
    since = pd.Timestamp(cutoff) - pd.Timedelta(days=days)
    df = ev_df.assign(public_at=pd.to_datetime(ev_df["public_at"], utc=True))
    df = df[df["public_at"] >= since].sort_values(["public_at", "id"], ascending=[False, True])
    head = (f"## Citable evidence ids (as-of replay; public in the {days} days before {cutoff.isoformat()})\n\n"
            "Only these kinds of ids may go in `evidence_ids` (news, SEC filings, NSE announcements). There is no "
            "stored news before live collection began, so in a replay only filings or announcements can be cited.\n\n")
    if df.empty:
        return head + "_none: no citable ids in this window, so every call must be an abstention_\n"
    lines = ["| id | kind | ticker | form | public_utc | text |", "|---|---|---|---|---|---|"]
    for r in df.head(limit).itertuples():
        txt = str(r.text or "").replace("|", "/").replace("\n", " ")[:120]
        lines.append(f"| {r.id} | {r.kind} | {r.ticker or ''} | {r.form or ''} | {str(r.public_at)[:16]} | {txt} |")
    more = f"\n{len(df) - limit} more in this window (query DuckDB in the replay root).\n" if len(df) > limit else "\n"
    return head + "\n".join(lines) + "\n" + more
