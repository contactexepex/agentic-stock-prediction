"""Intraday alerts in the day's thread (SPEC F9 (2)): a flagged open paper trade, or material news on a company
with an open trade. Input: B9's alerts feed. Until B9 merges, the record format is W1's (`trade_checks` rows,
design/catalogue/trade_check.json) plus the news alert record of docs/ws/b6.md. Monitoring only: nothing is
traded."""
from __future__ import annotations

from marketbrief.alerts import text as fmt
from marketbrief.alerts.constants import BAND_TEXT, FLAG_TEXT, MSG_FOOTER, PAPER

NEWS_ALERT = "news"


def check_time(rows: list[dict]) -> str:
    """The newest check time of the rows, as 'HH:MM UTC'."""
    newest = max(str(r.get("check_at") or "") for r in rows)
    return f"{newest[11:16]} UTC" if len(newest) >= 16 else "the latest check"


def trade_alert_line(row: dict, names: dict, currency: str) -> str:
    """One flagged trade check: price vs entry, band, target, flags."""
    flags = ", ".join(FLAG_TEXT.get(f, f) for f in row.get("flags") or [])
    band = BAND_TEXT.get(row.get("band"), row.get("band") or "band unknown")
    to_target = row.get("to_target_pct")
    if fmt.missing(to_target):
        target = f"target {fmt.money(currency, row.get('target_price'))}"
    elif to_target < 0:
        target = f"target {fmt.money(currency, row.get('target_price'))} already passed ({fmt.pct(to_target)})"
    else:
        target = f"{fmt.pct(to_target)} left to target {fmt.money(currency, row.get('target_price'))}"
    last = fmt.money(currency, row.get("last_price"))
    return (f"• *{row['ticker']}* {fmt.horizon(row['horizon_days'])}, {fmt.who(row['strategy_id'], names)}"
            f" ({row['view']}, session {row.get('session_number')} of the trade): {last},"
            f" {fmt.pct(row.get('ret_since_entry_pct'))} since entry at {fmt.money(currency, row.get('entry_price'))};"
            f" {band} ({fmt.money(currency, row.get('lo80'))}–{fmt.money(currency, row.get('hi80'))}); {target}."
            f" Flags: {flags or 'none'}. {PAPER}")


def news_alert_line(row: dict) -> str:
    """One material news item on a company with open paper trades."""
    trades = len(row.get("trade_ids") or [])
    return (f"• *{row['ticker']}* news ({row.get('status') or 'status unknown'}, materiality"
            f" {row.get('materiality') or 'unknown'}): \"{row.get('title', '')}\" [{row.get('news_id')}];"
            f" {trades} open paper trade{'s' if trades != 1 else ''} on it. {PAPER}")


def build_alerts(market: str, rows: list[dict], names: dict | None = None, currency: str | None = None) -> str | None:
    """The alert message of one check run: flagged trade checks, then news alerts. None when nothing is
    flagged (no post)."""
    names = names or {}
    flagged = [r for r in rows if r.get("kind") != NEWS_ALERT and r.get("flagged")]
    news = [r for r in rows if r.get("kind") == NEWS_ALERT]
    if not flagged and not news:
        return None
    currency = currency or fmt.MARKET_CURRENCY.get(market, "")
    lines = [f"*{fmt.market_label(market)} — intraday check at {check_time(flagged + news)}: "
             f"{len(flagged)} flagged open paper trade{'s' if len(flagged) != 1 else ''}"
             f"{f', {len(news)} news alert' + ('s' if len(news) != 1 else '') if news else ''}* (monitoring only)"]
    for row in sorted(flagged, key=lambda r: (r["ticker"], r["horizon_days"], r["strategy_id"], r["view"])):
        lines.append(trade_alert_line(row, names, currency))
    for row in sorted(news, key=lambda r: (r["ticker"], str(r.get("news_id")))):
        lines.append(news_alert_line(row))
    lines.append(MSG_FOOTER)
    return "\n".join(lines) + "\n"
