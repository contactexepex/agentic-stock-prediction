"""Paper-trade status of the reader's report, once any strategy is live (config/strategies.yaml live_from): the open
paper trades (B4's shared Open-trade records, rm_common.open_trades) summed per company and per strategy, and WS4's
signal tiers in lean words. Everything is labelled SIMULATED: a paper trade is a record, never an order."""
from __future__ import annotations

from marketbrief.constants import reader as text
from marketbrief.lab import registry
from marketbrief.portfolio import signals
from marketbrief.portfolio.settings import load_portfolio_config
from marketbrief.presentation.reader.forecasts import day_label
from marketbrief.warehouse import rm_common
from marketbrief.warehouse.rm_registry import BuildContext


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def trade_summary(trades: list[dict]) -> dict:
    """{n, avg_pct (unrealised, percent), best, worst} of a list of open trades."""
    pcts = [t["unrealised_pct"] for t in trades if t.get("unrealised_pct") is not None]
    return {"n": len(trades), "avg_pct": mean(pcts), "best": max(pcts) if pcts else None,
            "worst": min(pcts) if pcts else None}


def tier_rows(ctx: BuildContext, active: set[str]) -> dict[str, dict[str, str]]:
    """ticker -> {horizon: tier in lean words} of the active companies at READER_HORIZONS."""
    payload = signals.cockpit_payload(ctx.con, ctx.cutoff_time, ctx.market, load_portfolio_config())
    out: dict[str, dict[str, str]] = {}
    for row in payload["tiers"]:
        if row["ticker"] in active and row["horizon_days"] in text.READER_HORIZONS:
            out.setdefault(row["ticker"], {})[str(row["horizon_days"])] = text.TIER_WORDS.get(row["tier"], row["tier"])
    return out


def paper_status(ctx: BuildContext, session_date: str, active: set[str]) -> dict:
    """{live, live_from, note, label, open (summary), by_ticker, by_strategy, tiers} as of the cut-off; `live` = any
    registry strategy is live on the session being predicted (lab/registry.is_live)."""
    specs = registry.strategies()
    starts = sorted(str(s["live_from"]) for s in specs if s.get("live_from") is not None)
    live = any(registry.is_live(spec, session_date) for spec in specs)
    out = {"live": live, "live_from": starts[0] if starts else None, "label": text.SIMULATED,
           "note": None if live else (text.PAPER_NOT_LIVE.format(day=day_label(starts[0])) if starts
                                      else text.PAPER_NO_START)}
    if not live:
        return out
    trades = [t for t in rm_common.open_trades(ctx) if t["ticker"] in active]
    by_ticker: dict[str, list[dict]] = {}
    by_strategy: dict[str, list[dict]] = {}
    for trade in trades:
        by_ticker.setdefault(trade["ticker"], []).append(trade)
        by_strategy.setdefault(trade["strategy_id"], []).append(trade)
    names = {spec["id"]: spec.get("name") or spec["id"] for spec in specs}
    out.update(
        open=trade_summary(trades),
        by_ticker={ticker: trade_summary(rows) for ticker, rows in sorted(by_ticker.items())},
        by_strategy=[{"id": key, "name": names.get(key, key), **trade_summary(rows)}
                     for key, rows in sorted(by_strategy.items())],
        tiers=tier_rows(ctx, active),
    )
    return out
