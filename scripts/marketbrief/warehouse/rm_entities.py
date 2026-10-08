"""The derived records several pages share (docs/DATA_CATALOGUE.md, "derived for pages, B4"; docs/ws/b4.md), each
computed once per build through BuildContext.shared, as of the cut-off. rm_common re-exports the three readers.

  agreement(ctx)    {"1".."5": Agreement rows by rank}: per horizon and active company, how many strategies' newest
                    predictions qualify as a trade (`buy`) of those that predicted it (`of`), by family, with the
                    buyers' average P(up). The predictions are the newest batch made by the cut-off (the newest
                    `session_date` among the strategy_predictions rows with made_at at or before it; each id's first
                    stored row). Rank: most buyers, then the higher average probability, then the ticker.
  open_trades(ctx)  the Open-trade records: B9's open trades as of the cut-off (intraday/trades.open_trades: every
                    qualifying prediction and picked head-to-head pick made before D's open, without a settlement
                    row by the cut-off, for at most `trades.max_sessions_past_exit` sessions past its exit), that have
                    entered (D's open stored by the cut-off) and buy at least one share (F1.4), valued at the newest
                    stored close: unrealised profit before costs on today's price basis (splits and bonuses since D).
  companies(ctx)    the Company records, active and inactive (never deleted), active first, then by ticker: B1's
                    accessor, the newest two raw closes collected by the cut-off, agreement_n1 (active companies) and
                    the open-trade count (exactly the records of open_trades).

live_rows(rows, day_key) (Wave 5 go-live) keeps the rows of strategies live on their D (lab/registry.is_live); the
page modules apply it to the predictions, picks and trade checks they read themselves.

Drafted from session B11's agreement.py and company_records.latest_closes (build/b11-market-pages 3f6b4df)."""

from __future__ import annotations

import statistics
from datetime import date

import pandas as pd

from marketbrief.contracts.strategies import FAMILIES
from marketbrief.intraday import trades as intraday_trades
from marketbrief.intraday.settings import load_intraday_config
from marketbrief.lab import registry
from marketbrief.lab.sizing import quantity as trade_quantity
from marketbrief.utils.numbers import json_safe_float
from marketbrief.warehouse.rm_registry import BuildContext

STATE_ACTIVE = "active"
MONEY, PCT, PROB = 2, 2, 4
PREDICTIONS_SQL = """
WITH p AS (SELECT DISTINCT ON (id) * FROM strategy_predictions WHERE made_at <= ?::TIMESTAMPTZ ORDER BY id, made_at)
SELECT id, strategy_id, family, ticker, as_of_date, session_date, horizon_days, prob_up, qualifies FROM p
WHERE session_date = (SELECT max(session_date) FROM p) ORDER BY ticker, horizon_days, strategy_id"""
# each ticker's raw bars collected by the cut-off, newest collection per day, sessions of the market only
RAW_BARS = """WITH p AS (SELECT DISTINCT ON (ticker, date) ticker, date, open, close FROM prices
WHERE collected_at <= ?::TIMESTAMPTZ AND date <= ?::DATE AND list_contains(?, ticker)
ORDER BY ticker, date, collected_at DESC)
SELECT * FROM p WHERE NOT EXISTS (SELECT 1 FROM own_closed_days c WHERE c.ticker = p.ticker AND c.date = p.date)"""
CLOSES_SQL = f"""SELECT ticker, date, close FROM (SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY date DESC)
AS n FROM ({RAW_BARS}) WHERE close IS NOT NULL) WHERE n <= 2 ORDER BY ticker, n"""
OPENS_SQL = f"SELECT ticker, date, open FROM ({RAW_BARS}) WHERE open IS NOT NULL"
OPEN_TRADE_KEYS = ("trade_id", "view", "prediction_id", "strategy_id", "family", "ticker", "horizon_days")
PREDICTED_KEYS = ("target_price", "lo80", "lo50", "hi50", "hi80")
COMPANY_KEYS = (
    "market",
    "ticker",
    "name",
    "exchange",
    "sector",
    "state",
    "state_since",
    "added_at",
    "amount",
    "amount_overridden",
    "currency",
    "yahoo",
    "nse_symbol",
    "cik",
)


def iso_day(value) -> str | None:
    """A stored date or time as YYYY-MM-DD, or None."""
    return None if value is None or pd.isna(value) else pd.Timestamp(value).date().isoformat()


def iso_time(value) -> str | None:
    """An aware time as ISO UTC with a Z, or None."""
    return (
        None
        if value is None or pd.isna(value)
        else pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    )


# ---------- live strategies (Wave 5 go-live; lab/registry.is_live) ----------
def live(strategy_id: str, session_date) -> bool:
    """Whether a strategy trades for real on D = session_date: its live_from is set and on or before D."""
    return registry.is_live(strategy_id, iso_day(session_date))


def earliest_live_from() -> str | None:
    """The earliest live_from of the registry, or None while no strategy is live."""
    days = [str(spec["live_from"]) for spec in registry.strategies() if spec.get("live_from") is not None]
    return min(days) if days else None


def live_rows(rows: list[dict], day_key: str) -> list[dict]:
    """The rows of live strategies on their D (`day_key`: session_date of a prediction or pick, entry_date of a
    trade or check); rows of a strategy before its live_from (rehearsal runs) are never shown, nor rows without a
    day. A row without a strategy (a head-to-head pick with status no_candidate: no strategy of its family
    qualified) is kept when some strategy of its family is live on its D (a live pick run's answer), and dropped
    otherwise (a rehearsal run)."""
    kept = []
    for row in rows:
        day = row.get(day_key)
        if day is None or pd.isna(day):
            continue
        if row.get("strategy_id"):
            keep = live(row["strategy_id"], day)
        else:
            keep = any(live(spec["id"], day) for spec in registry.strategies(family=row.get("family")))
        if keep:
            kept.append(row)
    return kept


def newest_batch(rows: list[dict]) -> list[dict]:
    """The rows of the newest session_date among them."""
    newest = max((iso_day(row["session_date"]) for row in rows), default=None)
    return [row for row in rows if iso_day(row["session_date"]) == newest]


# ---------- agreement ----------
def tally(predictions: list[dict]) -> dict:
    """buy, of, by_family and avg_prob_up of one company's predictions at one horizon."""
    buys = [p for p in predictions if p["qualifies"] is True]
    probabilities = [p["prob_up"] for p in buys if p["prob_up"] is not None and not pd.isna(p["prob_up"])]
    return {
        "buy": len(buys),
        "of": len(predictions),
        "by_family": {
            family: {
                "buy": sum(p["family"] == family for p in buys),
                "of": sum(p["family"] == family for p in predictions),
            }
            for family in FAMILIES
        },
        "avg_prob_up": round(statistics.mean(probabilities), PROB) if probabilities else None,
    }


def agreement_rows(predictions: list[dict], companies: list[dict], market: str) -> dict[str, list[dict]]:
    """horizon ("1".."5") -> the companies' Agreement records by rank (`companies`: active ones, ticker and name)."""
    as_of = iso_day(predictions[0]["as_of_date"]) if predictions else None
    session = iso_day(predictions[0]["session_date"]) if predictions else None
    out = {}
    for k in registry.horizons():
        rows = []
        for company in companies:
            mine = [p for p in predictions if p["ticker"] == company["ticker"] and int(p["horizon_days"]) == k]
            counts = tally(mine)
            label = f"{company['name']}: {counts['buy']} of {counts['of']} strategies buy at N+{k}"
            rows.append(
                {
                    "market": market,
                    "as_of_date": as_of,
                    "session_date": session,
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "horizon_days": k,
                    **counts,
                    "label": label,
                    "paper": True,
                }
            )
        rows.sort(key=lambda row: (-row["buy"], -(row["avg_prob_up"] or 0), row["ticker"]))
        out[str(k)] = [{**row, "rank": rank} for rank, row in enumerate(rows, 1)]
    return out


def agreement(ctx: BuildContext) -> dict[str, list[dict]]:
    """The market's Agreement records per horizon (active companies), from the newest predictions by the cut-off."""

    def compute() -> dict[str, list[dict]]:
        frame = ctx.con.execute(PREDICTIONS_SQL, [ctx.cutoff]).df()
        predictions = [row for row in frame.to_dict("records") if row["ticker"] in ctx.active]
        active = [company for company in ctx.companies if company["state"] == STATE_ACTIVE]
        return agreement_rows(predictions, sorted(active, key=lambda c: c["ticker"]), ctx.market)

    return ctx.shared("agreement", compute)


# ---------- open trades ----------
def open_trade_record(trade: dict, market: str, currency: str, prices: dict) -> dict | None:
    """One Open-trade record from B9's trade and `prices` = {entry, last, last_date, factor, target_factor}:
    `factor` turns a price of D (the entry) into today's basis and `target_factor` a price of the as-of date (the
    target), as intraday/trade_rows does (intraday/trades.factor_after). None when no whole share is bought (F1.4)."""
    entry, last, factor = prices["entry"], prices["last"], prices["factor"]
    shares = trade_quantity(market, float(trade["amount"]), entry)
    if not shares:
        return None
    target = json_safe_float(trade["target_price"])
    return {
        **{key: trade[key] for key in OPEN_TRADE_KEYS},
        "market": market,
        "entry_date": trade["entry_date"].isoformat(),
        "exit_date": trade["exit_date"].isoformat(),
        "entry_price": json_safe_float(entry),
        "quantity": float(shares),
        "amount": json_safe_float(trade["amount"]),
        "currency": currency,
        **{key: json_safe_float(trade[key]) for key in PREDICTED_KEYS},
        "last_price": json_safe_float(last),
        "last_price_date": prices["last_date"],
        "unrealised_pnl": round(shares * (last / factor - entry), MONEY),
        "unrealised_pct": round((last / (entry * factor) - 1) * 100, PCT),
        "to_target_pct": None if target is None else round((target * prices["target_factor"] / last - 1) * 100, PCT),
        "paper": True,
    }


def raw_bars(ctx: BuildContext, sql: str, tickers: list[str]) -> list[tuple]:
    """Rows of a raw-bar query for these tickers: collected by the cut-off, sessions up to the as-of date."""
    if not tickers or ctx.as_of is None:
        return []
    return ctx.con.execute(sql, [ctx.cutoff, ctx.as_of, tickers]).fetchall()


def open_trades(ctx: BuildContext) -> list[dict]:
    """The market's Open-trade records as of the cut-off, by trade id."""

    def compute() -> list[dict]:
        from marketbrief.warehouse.rm_common import status_block  # rm_common re-exports this module's readers

        session = date.fromisoformat(status_block(ctx)["session"]["session_date"])
        past_exit = int(load_intraday_config().get("trades", {}).get("max_sessions_past_exit", 0))
        by_ticker, _skipped = intraday_trades.open_trades(ctx.con, ctx.cfg, session, ctx.cutoff_time, past_exit)
        trades = [trade for ticker, rows in by_ticker.items() if ticker in ctx.collected for trade in rows]
        tickers = sorted({trade["ticker"] for trade in trades})
        opens = {(ticker, iso_day(day)): value for ticker, day, value in raw_bars(ctx, OPENS_SQL, tickers)}
        closes: dict[str, tuple] = {}
        for ticker, day, close in raw_bars(ctx, CLOSES_SQL, tickers):
            closes.setdefault(ticker, (iso_day(day), close))
        factors = intraday_trades.adjustment_factors(ctx.con, tickers, session, ctx.cutoff_time)
        out = []
        for trade in sorted(trades, key=lambda t: t["trade_id"]):
            entry = opens.get((trade["ticker"], trade["entry_date"].isoformat()))
            last_date, last = closes.get(trade["ticker"], (None, None))
            if entry is None or last is None or last_date < trade["entry_date"].isoformat():
                continue  # not entered yet: D's open is not stored by the cut-off
            known = [(ex, f) for ex, f in factors.get(trade["ticker"], []) if ex.isoformat() <= last_date]
            prices = {
                "entry": float(entry),
                "last": float(last),
                "last_date": last_date,
                "factor": intraday_trades.factor_after(known, trade["entry_date"]),
                "target_factor": intraday_trades.factor_after(known, trade["as_of_date"]),
            }
            record = open_trade_record(trade, ctx.market, ctx.cfg["currency"], prices)
            if record is not None:
                out.append(record)
        return out

    return ctx.shared("open_trades", compute)


# ---------- companies ----------
def latest_closes(ctx: BuildContext, tickers: list[str]) -> dict[str, dict]:
    """ticker -> {last_close, last_close_date, change_pct} from its newest two raw closes by the cut-off."""
    rows: dict[str, list] = {}
    for ticker, day, close in raw_bars(ctx, CLOSES_SQL, tickers):
        rows.setdefault(ticker, []).append((iso_day(day), close))
    out = {}
    for ticker, closes in rows.items():
        (day, close), previous = closes[0], closes[1][1] if len(closes) > 1 else None
        change = round((close / previous - 1) * 100, PCT) if previous else None
        out[ticker] = {"last_close": json_safe_float(close), "last_close_date": day, "change_pct": change}
    return out


def companies(ctx: BuildContext) -> list[dict]:
    """The market's Company records as of the cut-off (catalogue entity Company), active first, then by ticker."""

    def compute() -> list[dict]:
        records = ctx.companies
        closes = latest_closes(ctx, sorted(ctx.collected))
        n1 = {row["ticker"]: {"buy": row["buy"], "of": row["of"]} for row in agreement(ctx).get("1", [])}
        counts: dict[str, int] = {}
        for trade in open_trades(ctx):
            counts[trade["ticker"]] = counts.get(trade["ticker"], 0) + 1
        empty = {"last_close": None, "last_close_date": None, "change_pct": None}
        rows = []
        for record in records:
            ticker, active = record["ticker"], record["state"] == STATE_ACTIVE
            row = {key: record.get(key) for key in COMPANY_KEYS}
            row.update(
                added_at=iso_time(record.get("added_at")),
                state_since=iso_time(record.get("state_since")),
                amount=json_safe_float(record.get("amount")),
                **closes.get(ticker, empty),
                agreement_n1=n1.get(ticker) if active else None,
                open_trades=counts.get(ticker, 0),
            )
            rows.append(row)
        return sorted(rows, key=lambda row: (row["state"] != STATE_ACTIVE, row["ticker"]))

    return ctx.shared("companies", compute)
