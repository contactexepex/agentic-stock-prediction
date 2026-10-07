"""Intraday alerts in the day's thread (SPEC F9 (2)) from B9's alerts feed (`intraday_alerts`, view
`intraday_alerts_feed`; format in docs/ws/b9.md "The alerts feed"): per check run, one `open_trade_flagged` row per
ticker with flagged open paper trades, and one `material_news_open_trade` row per material news item on a ticker
with an open trade. A trade alert already posted with the same flags earlier in the session (`repeat`) is not
posted again; every news alert is. A trade alert quotes the deviation explainer's note on its check row when the
note was written by the clock.
Monitoring only: nothing is traded."""
from __future__ import annotations

from marketbrief.alerts import text as fmt
from marketbrief.alerts.constants import BAND_TEXT, FLAG_TEXT, LABEL_PAPER_ONLY, MSG_FOOTER, PAPER

TRADE_ALERT = "open_trade_flagged"
NEWS_ALERT = "material_news_open_trade"


def check_time(rows: list[dict]) -> str:
    """The newest check time of the rows, as 'HH:MM UTC'."""
    newest = max(str(r.get("check_at") or "") for r in rows)
    return f"{newest[11:16]} UTC" if len(newest) >= 16 else "the latest check"


def trade_text(trade: dict, names: dict) -> str:
    """One flagged trade of a trade alert: who, horizon, move since entry, band, target, flags."""
    to_target = trade.get("to_target_pct")
    if trade.get("target_reached") or (not fmt.missing(to_target) and to_target < 0):
        target = "target already reached"
    elif fmt.missing(to_target):
        target = "target distance unknown"
    else:
        target = f"{fmt.pct(to_target)} left to target"
    flags = ", ".join(FLAG_TEXT.get(f, f) for f in trade.get("flags") or []) or "none"
    band = BAND_TEXT.get(trade.get("band"), trade.get("band") or "band unknown")
    return (f"{fmt.horizon(trade['horizon_days'])} {fmt.who(trade['strategy_id'], names)} ({trade.get('view')}):"
            f" {fmt.pct(trade.get('ret_since_entry_pct'))} since entry, {band}, {target}; flags: {flags}")


def note_line(row: dict) -> list[str]:
    """The deviation explainer's note on the check row, when one exists (the reader drops later notes)."""
    if not row.get("explanation"):
        return []
    cited = ", ".join(row.get("cited_ids") or [])
    return [f"   Note ({row.get('attribution') or 'unexplained'}): {row['explanation']}"
            + (f" [{cited}]" if cited else "")]


def trade_alert_lines(row: dict, names: dict) -> list[str]:
    """A ticker's flagged open trades, one line each, then the explainer's note."""
    trades = sorted(row.get("trades") or [], key=lambda t: (t["horizon_days"], t["strategy_id"], str(t.get("view"))))
    lines = [f"• *{row['ticker']}* {len(trades)} flagged open paper trade{'s' if len(trades) != 1 else ''}: {PAPER}"]
    lines += [f"   – {trade_text(t, names)} {PAPER}" for t in trades]
    return lines + note_line(row)


def news_alert_line(row: dict) -> str:
    """One material news item on a company with open paper trades."""
    trades = len(row.get("trade_ids") or [])
    source = f" ({row['news_source']})" if row.get("news_source") else ""
    return (f"• *{row['ticker']}* news ({row.get('news_status') or 'status unknown'}, materiality"
            f" {row.get('news_materiality') or 'unknown'}): \"{row.get('news_title') or ''}\"{source}"
            f" [{row.get('news_id')}]; {trades} open paper trade{'s' if trades != 1 else ''} on it. {PAPER}")


def build_alerts(market: str, rows: list[dict], names: dict | None = None) -> str | None:
    """The alert message of one check run: new trade alerts (repeat false), then news alerts. None when there is
    nothing new to post."""
    names = names or {}
    trades = [r for r in rows if r.get("alert_type") == TRADE_ALERT and not r.get("repeat")]
    news = [r for r in rows if r.get("alert_type") == NEWS_ALERT]
    if not trades and not news:
        return None
    lines = [f"*{fmt.market_label(market)} — intraday check at {check_time(trades + news)}: {len(trades)}"
             f" compan{'ies' if len(trades) != 1 else 'y'} with newly flagged open paper trades"
             f"{f', {len(news)} news alert' + ('s' if len(news) != 1 else '') if news else ''}* (monitoring only)",
             LABEL_PAPER_ONLY]
    for row in sorted(trades, key=lambda r: r["ticker"]):
        lines += trade_alert_lines(row, names)
    for row in sorted(news, key=lambda r: (r["ticker"], str(r.get("news_id")))):
        lines.append(news_alert_line(row))
    lines.append(MSG_FOOTER)
    return "\n".join(lines) + "\n"
