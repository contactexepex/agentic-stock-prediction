"""Correction replies (owner, 2026-10-07): when a trade listed in a day's close results is re-settled after the
post (a new `paper_trades_settled` row with `supersedes`, F1.5), one reply in that day's thread states the new
and the old numbers. The original post stays as posted."""
from __future__ import annotations

from datetime import datetime, timedelta

from marketbrief.alerts import text as fmt
from marketbrief.alerts.close import trade_head
from marketbrief.alerts.constants import LABEL_PAPER_ONLY, MSG_FOOTER, PAPER, POST_CLOSE, POST_CORRECTION
from marketbrief.alerts.ledger import Ledger


def correction_text(row: dict, names: dict, currency: str) -> str:
    """'Correction: NVDA N+1, Model + news (rule.model_news.v1) (accuracy) is now net +$3.10 (+0.31%), was +$4.60
    (+0.46%); re-settled 2026-10-02T03:00:00+00:00 (flags: split_in_window, resettled). [Paper]'."""
    flags = f" (flags: {', '.join(row['flags'])})" if row.get("flags") else ""
    now_text = (f"net {fmt.signed_money(currency, row.get('net_pnl'))} ({fmt.pct(row.get('return_pct'))})"
                if row.get("status") == "settled" else str(row.get("status")))
    line = (f"Correction: {trade_head(row, names)} is now {now_text}, was"
            f" {fmt.signed_money(currency, row.get('was_net_pnl'))} ({fmt.pct(row.get('was_return_pct'))});"
            f" re-settled {row.get('settled_at')}{flags}. {PAPER}")
    return "\n".join([line, LABEL_PAPER_ONLY, MSG_FOOTER]) + "\n"


def close_posts(ledger: Ledger, now: datetime, days: int) -> list[dict]:
    """The first part of each close post of the market posted within `days` days before `now`, oldest first."""
    since = now - timedelta(days=days)
    rows = [r for r in ledger.rows() if r.get("kind") == POST_CLOSE and int(r.get("part", 0)) == 1
            and since <= datetime.fromisoformat(r["posted_at"].replace("Z", "+00:00")) <= now]
    return sorted(rows, key=lambda r: r["posted_at"])


def correction_key(market: str, row: dict) -> str:
    """One reply per re-settlement row."""
    return f"{POST_CORRECTION}:{market}:{row['id']}"


def session_of(post: dict) -> str:
    """The session date of a close post (the last part of close:<market>:<D>)."""
    return post["post_key"].rsplit(":", 1)[1]
