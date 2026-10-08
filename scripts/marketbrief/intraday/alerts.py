"""The intraday alerts feed (B9 for session B6's Slack alerts; record format in docs/ws/b9.md): per check, one
`open_trade_flagged` row per ticker with flagged open paper trades, and one `material_news_open_trade` row per
material news item first alerted on a ticker with an open trade. Deterministic, from the check's own rows and
the news stored by check_at (no look-ahead); a news item is alerted once per session and ticker. Monitoring
only: an alert never predicts or recommends a trade."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.core.calendar import prev_session, session_close_utc
from marketbrief.core.schema_intraday import INTRADAY_SCHEMAS
from marketbrief.intraday import inputs
from marketbrief.intraday.constants import (
    ALERT_MATERIAL_NEWS,
    ALERT_TRADE_FLAGGED,
    KIND_INTRADAY_ALERTS,
    TRADE_METHOD_VERSION,
)
from marketbrief.intraday.settings import alert_id

TRADE_SUMMARY_FIELDS = ("trade_id", "strategy_id", "view", "horizon_days", "flags", "band", "ret_since_entry_pct",
                        "to_target_pct")


def session_alerts(con, session_date: str, check_at, out_root: Path | None) -> list[dict]:
    """The alerts stored for this session by checks before check_at (data/ through the connection, and under
    out_root when given). A later check that was stored first (a check backfilled out of order) never counts."""
    frame = con.execute(
        "SELECT id, ticker, alert_type, trades, news_id FROM intraday_alerts WHERE session_date = ? "
        "AND check_at < ? ORDER BY id", [session_date, check_at]).df()
    rows = inputs.records(frame)
    if out_root is not None:
        for path in sorted((out_root / KIND_INTRADAY_ALERTS).glob("**/*.jsonl")):
            rows += [row for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
                     for row in [json.loads(line)] if row["session_date"] == session_date
                     and pd.Timestamp(row["check_at"]) < pd.Timestamp(check_at)]
    for row in rows:
        if isinstance(row.get("trades"), str):
            row["trades"] = json.loads(row["trades"])
    return rows


def build_alerts(ctx, earlier: list[dict]) -> list[dict]:
    """The check's alerts, given the session's earlier alerts (for `repeat` and the one-alert-per-news rule)."""
    by_ticker: dict[str, list[dict]] = {}
    for check in ctx.trade_checks:
        by_ticker.setdefault(check["ticker"], []).append(check)
    seen = {(row["trade_id"], tuple(row["flags"])) for alert in earlier if alert["alert_type"] == ALERT_TRADE_FLAGGED
            for row in alert.get("trades") or []}
    out = []
    for ticker, checks in sorted(by_ticker.items()):
        flagged = [check for check in checks if check["flagged"]]
        if not flagged:
            continue
        trades = [{**{key: check[key] for key in TRADE_SUMMARY_FIELDS}, "target_reached": check["target_reached"]}
                  for check in flagged]
        out.append({
            **_base(ctx, ticker, ALERT_TRADE_FLAGGED, alert_id(ctx.check_id, ticker, "trades")),
            "trade_ids": [check["trade_id"] for check in flagged], "trades": trades,
            "flags": sorted({flag for check in flagged for flag in check["flags"]}),
            "repeat": all((row["trade_id"], tuple(row["flags"])) in seen for row in trades),
        })
    out += news_alerts(ctx, by_ticker, earlier)
    return out


def news_alerts(ctx, by_ticker: dict[str, list[dict]], earlier: list[dict]) -> list[dict]:
    """Material news (config/intraday.yaml alerts.news_materiality, enrichment as of check_at) on tickers with an
    open trade, first seen since the previous session's close and not alerted earlier this session. Every such
    item is read (no count limit before the materiality filter), so none is dropped on a busy ticker."""
    settings = ctx.settings["alerts"]
    since = session_close_utc(ctx.cfg, prev_session(ctx.cfg, ctx.session_date, include=False))
    done = {(alert["ticker"], alert["news_id"]) for alert in earlier if alert["alert_type"] == ALERT_MATERIAL_NEWS}
    out = []
    for ticker, checks in sorted(by_ticker.items()):
        for item in inputs.news_since(ctx.con, ticker, since, ctx.check_at, None):
            if item.get("materiality") not in settings["news_materiality"] or (ticker, item["id"]) in done:
                continue
            out.append({
                **_base(ctx, ticker, ALERT_MATERIAL_NEWS, alert_id(ctx.check_id, ticker, f"news-{item['id']}")),
                "trade_ids": [check["trade_id"] for check in checks], "trades": [], "flags": [], "repeat": False,
                "news_id": item["id"], "news_title": item["title"], "news_source": item["source"],
                "news_status": item["status"], "news_materiality": item["materiality"],
                "news_first_seen_at": item["first_seen_at"].isoformat(),
            })
    return out


def _base(ctx, ticker: str, alert_type: str, ident: str) -> dict:
    """An alert's identifying columns, the rest empty."""
    return {
        **dict.fromkeys(INTRADAY_SCHEMAS[KIND_INTRADAY_ALERTS][1]), "id": ident, "check_id": ctx.check_id,
        "check_at": ctx.check_at.isoformat(), "session_date": ctx.session_date.isoformat(),
        "market": ctx.cfg[CFG_MARKET], "ticker": ticker, "alert_type": alert_type,
        "check_row_id": ctx.check_row(ticker), "method_version": TRADE_METHOD_VERSION,
        "computed_at": ctx.computed_at,
    }
