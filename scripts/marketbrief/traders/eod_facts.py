"""The EOD analyst's facts (docs/SPEC.md F6.1, decision 43): what it must explain for one market and session.

Settled that day = paper_trades_settled rows with exit_date_actual = the session and status settled, newest
settlement per trade (a re-settlement supersedes the old row), settled by the run's clock. Items:
- every head-to-head trade (kind head_to_head, id tra:<trade_id>);
- the day's 5 biggest wins and 5 biggest misses across all trades: accuracy-view rows (every head-to-head trade
  repeats an accuracy trade's prediction) ranked by return_pct (percent of the amount, so companies with other
  amounts compare; decision 44), wins > 0 highest first, misses < 0 lowest first, ties by trade id (kind
  biggest_win / biggest_miss, rank 1-5, id tra:<trade_id>:<kind>).
Results (deterministic, stored with the analysis): per family of the accuracy view and per pick rule of the
head-to-head view: trades, wins (net_pnl > 0), net_pnl and return_pct = net_pnl / amount x 100, rounded to 2."""
from __future__ import annotations

from datetime import date, datetime

from marketbrief.traders.constants import BIGGEST_COUNT, KIND_HEAD_TO_HEAD, KIND_MISS, KIND_WIN
from marketbrief.traders.rows import records

SETTLED_SQL = """
SELECT * FROM paper_trades_settled t
WHERE t.exit_date_actual = ?::DATE AND t.status = 'settled' AND t.settled_at <= ?::TIMESTAMPTZ
  AND NOT EXISTS (SELECT 1 FROM paper_trades_settled s WHERE s.supersedes = t.id AND s.settled_at <= ?::TIMESTAMPTZ)
ORDER BY t.trade_id, t.settled_at DESC"""
FACT_KEYS = (
    "trade_id", "id", "ticker", "strategy_id", "family", "view", "pick_rule", "horizon_days", "entry_date",
    "exit_date_actual", "currency", "amount", "entry_price", "exit_price", "quantity", "gross_pnl", "costs", "net_pnl",
    "return_pct", "prob_up", "target_price", "target_error_pct", "lo80", "hi80", "range_hit", "target_reached",
    "target_reached_session", "max_favourable_pct", "max_adverse_pct", "move_pct", "market_pct", "sector_pct",
    "news_pct", "company_pct", "reason_code", "reason_codes", "news_ids", "flags", "regime",
)


def settled_rows(con, session: date, now: datetime) -> list[dict]:
    """The newest settlement of each trade whose exit was this session."""
    stamp = now.isoformat()
    seen, out = set(), []
    for row in records(con, SETTLED_SQL, [session.isoformat(), stamp, stamp]):
        if row["trade_id"] not in seen:
            seen.add(row["trade_id"])
            out.append(row)
    return out


def fact(row: dict, kind: str, rank: int | None) -> dict:
    """One item for the analyst: the trade's stored facts plus the reason id it must write."""
    out = {key: (str(row[key]) if isinstance(row.get(key), (date, datetime)) else row.get(key)) for key in FACT_KEYS}
    out["settlement_id"] = out.pop("id")
    suffix = "" if kind == KIND_HEAD_TO_HEAD else f":{kind}"
    return {"reason_id": f"tra:{row['trade_id']}{suffix}", "kind": kind, "rank": rank, **out}


def tally(rows: list[dict]) -> dict:
    """trades, wins, net_pnl and return_pct of some settled rows."""
    net = sum(float(row["net_pnl"]) for row in rows)
    amount = sum(float(row["amount"]) for row in rows)
    return {"trades": len(rows), "wins": sum(float(row["net_pnl"]) > 0 for row in rows), "net_pnl": round(net, 2),
            "return_pct": round(net / amount * 100, 2) if amount else 0.0}


def results(rows: list[dict]) -> dict:
    """Per family (accuracy view) and per pick rule (head-to-head view)."""
    out = {}
    accuracy = [row for row in rows if row["view"] == "accuracy"]
    for family in sorted({row["family"] for row in accuracy}):
        out[family] = tally([row for row in accuracy if row["family"] == family])
    head = [row for row in rows if row["view"] == "head_to_head"]
    for rule in sorted({row["pick_rule"] for row in head}):
        out[rule] = tally([row for row in head if row["pick_rule"] == rule])
    return out


def items(rows: list[dict]) -> list[dict]:
    """Every head-to-head trade, then the 5 biggest wins and 5 biggest misses."""
    out = [fact(row, KIND_HEAD_TO_HEAD, None) for row in rows if row["view"] == "head_to_head"]
    accuracy = [row for row in rows if row["view"] == "accuracy" and row["return_pct"] is not None]
    wins = sorted((row for row in accuracy if row["return_pct"] > 0), key=lambda r: (-r["return_pct"], r["trade_id"]))
    misses = sorted((row for row in accuracy if row["return_pct"] < 0), key=lambda r: (r["return_pct"], r["trade_id"]))
    out += [fact(row, KIND_WIN, rank) for rank, row in enumerate(wins[:BIGGEST_COUNT], 1)]
    out += [fact(row, KIND_MISS, rank) for rank, row in enumerate(misses[:BIGGEST_COUNT], 1)]
    return out


def eod_facts(con, market: str, session: date, now: datetime) -> dict:
    """The analyst's input: the day's results and the items to explain (already stored reasons left out)."""
    rows = settled_rows(con, session, now)
    stored = {row[0] for row in con.execute("SELECT id FROM trade_reasons_ai").fetchall()}
    eod_id = f"eod-{market}-{session}"
    done = bool(con.execute("SELECT count(*) FROM eod_analyses WHERE id = ?", [eod_id]).fetchone()[0])
    return {"id": eod_id, "market": market, "session_date": str(session), "settled_trades": len(rows),
            "results": results(rows), "summary_stored": done,
            "items": [item for item in items(rows) if item["reason_id"] not in stored]}
