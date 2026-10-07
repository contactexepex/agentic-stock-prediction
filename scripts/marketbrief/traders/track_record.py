"""A trader's own track record per confidence band (docs/SPEC.md F2.6: AI traders see it in their input and must lower
confidence or abstain where a band hits less often than stated).

Source: its settled accuracy-view paper trades (session B2's engine, `paper_trades_settled`), newest settlement per
trade (a re-settlement supersedes the old row), settled by the run's clock. A trade is a hit when its gross P&L is
above 0 (exit value, split-adjusted quantity, above the entry value: the event prob_up names). Only up predictions
trade (decision 3), so the record covers up calls only; a trader's down calls are not in it."""
from __future__ import annotations

from datetime import datetime

from marketbrief.traders.constants import CONFIDENCE_BANDS, MIN_BAND_TRADES

TRADES_SQL = """
SELECT t.strategy_id, t.prob_up, t.gross_pnl > 0 AS hit FROM paper_trades_settled t
WHERE t.view = 'accuracy' AND t.status = 'settled' AND t.family = 'ai' AND t.settled_at <= ?::TIMESTAMPTZ
  AND t.prob_up IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM paper_trades_settled s WHERE s.supersedes = t.id AND s.settled_at <= ?::TIMESTAMPTZ)
ORDER BY t.strategy_id, t.trade_id, t.id"""


def band_label(low: float, high: float) -> str:
    """'0.60-0.70'."""
    return f"{low:.2f}-{high:.2f}"


def band_of(confidence: float) -> tuple[float, float] | None:
    """The band a confidence falls in (the top band includes its upper edge)."""
    for low, high in CONFIDENCE_BANDS:
        if low <= confidence < high or (high == CONFIDENCE_BANDS[-1][1] and confidence == high):
            return low, high
    return None


def summarise(rows: list[tuple[str, float, bool]]) -> dict[str, dict[str, dict]]:
    """strategy -> band label -> {n, hits, hit_rate, low, high} from (strategy_id, confidence, hit) rows."""
    out: dict[str, dict[str, dict]] = {}
    for strategy_id, confidence, hit in rows:
        band = band_of(float(confidence))
        if band is None:
            continue
        cell = out.setdefault(strategy_id, {}).setdefault(
            band_label(*band), {"n": 0, "hits": 0, "low": band[0], "high": band[1]})
        cell["n"] += 1
        cell["hits"] += int(bool(hit))
    for bands in out.values():
        for cell in bands.values():
            cell["hit_rate"] = round(cell["hits"] / cell["n"], 4)
    return out


def load(con, now: datetime) -> dict[str, dict[str, dict]]:
    """The AI traders' band records as of `now`."""
    stamp = now.isoformat()
    return summarise(con.execute(TRADES_SQL, [stamp, stamp]).fetchall())


def refusal(confidence: float, bands: dict[str, dict]) -> dict | None:
    """The band cell that refuses this confidence (enough trades, hit rate below the band's lower edge), or None."""
    band = band_of(confidence)
    if band is None:
        return None
    cell = bands.get(band_label(*band))
    if cell and cell["n"] >= MIN_BAND_TRADES and cell["hit_rate"] < cell["low"]:
        return {**cell, "band": band_label(*band)}
    return None


def markdown(bands: dict[str, dict]) -> str:
    """The trader's own band table for its input file."""
    lines = ["| band | settled trades | hits | hit rate | rule |", "|---|---|---|---|---|"]
    for low, high in CONFIDENCE_BANDS:
        cell = bands.get(band_label(low, high))
        if not cell:
            lines.append(f"| {band_label(low, high)} | 0 | 0 | - | open |")
            continue
        closed = cell["n"] >= MIN_BAND_TRADES and cell["hit_rate"] < low
        lines.append(f"| {band_label(low, high)} | {cell['n']} | {cell['hits']} | {cell['hit_rate']:.0%} | "
                     f"{'CLOSED: no confidence in this band' if closed else 'open'} |")
    return "\n".join(lines)
