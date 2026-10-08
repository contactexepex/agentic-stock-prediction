"""Intraday alerts (B9's feed for the Slack alerts and the Home page's alerts) as EXAMPLES, built with B9's engine
code (marketbrief/intraday/alerts.build_alerts) from the example trade checks of trade_check.json and the news stored
by each check's time: a trade alert per ticker with flagged open trades, and a news alert per high-materiality item
(config/intraday.yaml alerts.news_materiality) first seen since the previous session's close on a ticker with an open
trade. Each check is the first of its session, so no alert is a repeat."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from marketbrief.core.database import connect
from marketbrief.core.market_config import load_market
from marketbrief.intraday.alerts import build_alerts
from marketbrief.intraday.settings import load_intraday_config, row_id


def check_alerts(checks: list[dict]) -> list[dict]:
    """The alerts of one check, given its trade_checks rows (one market, one check_id)."""
    first = checks[0]
    market, check_id, check_at = first["market"], first["check_id"], datetime.fromisoformat(first["check_at"])
    ctx = SimpleNamespace(trade_checks=checks, check_id=check_id, check_at=check_at,
                          session_date=date.fromisoformat(first["session_date"]), cfg=load_market(market),
                          con=connect(market), settings=load_intraday_config(),
                          check_row=lambda ticker: row_id(check_id, ticker), computed_at=first["computed_at"])
    return build_alerts(ctx, [])


def intraday_alerts(trade_checks: list[dict]) -> list[dict]:
    by_check: dict[str, list[dict]] = {}
    for check in trade_checks:
        by_check.setdefault(check["check_id"], []).append(check)
    alerts = [alert for check_id in sorted(by_check, reverse=True) for alert in check_alerts(by_check[check_id])]
    for alert in alerts:   # the catalogue writes times as ...Z (the engine's isoformat writes +00:00)
        for key in ("check_at", "news_first_seen_at"):
            if alert[key]:
                alert[key] = alert[key].replace("+00:00", "Z")
    return alerts
