"""The owner's own costs in Slack (owner decisions 50-51, relayed by the orchestrator on 2026-10-07; the viability
rule decided by the owner in the B6 session on 2026-10-07 for everyone): each morning pick and head-to-head trade
says whether it is viable at the owner's costs, and close results show the net result after the owner's costs
beside the market-cost result.

Viable = expected gain after your cost > 0: p x move - (1 - p) x loss - your_cost (all % of the amount). B2 computes
it once (`marketbrief/lab/gain.py`, with the picks' own move and loss) and stores it in its kind `cost_views`
(docs/ws/b2.md) as `expected_gain_your_pct` and `cost_viable`, one row per prediction, pick or settlement
(`record_kind`, `record_id`). Slack recomputes nothing: reads.with_costs joins the newest row by the clock onto each
record under the names below (COST_SOURCES maps B2's columns to them); a record without one shows no cost text."""
from __future__ import annotations

import statistics

from marketbrief.alerts import text as fmt

YOUR_COST_PCT = "your_cost_pct"      # predictions and picks: the owner's round-trip cost, % of the amount
YOUR_GAIN_PCT = "your_gain_pct"      # predictions and picks: expected gain after your cost, % (B2's stored value)
YOUR_COSTS = "your_costs"            # settled trades: the owner's round-trip costs in the market currency
YOUR_NET_PNL = "your_net_pnl"        # settled trades: net profit after the owner's costs
YOUR_RETURN_PCT = "your_return_pct"  # settled trades: that net profit as % of the amount

# cost_views record_kind -> {B2 column: the name the messages read}
COST_SOURCES = {
    "prediction": {"your_cost_pct": YOUR_COST_PCT, "expected_gain_your_pct": YOUR_GAIN_PCT},
    "pick": {"your_cost_pct": YOUR_COST_PCT, "expected_gain_your_pct": YOUR_GAIN_PCT},
    "settlement": {"your_costs": YOUR_COSTS, "net_pnl_your": YOUR_NET_PNL, "return_pct_your": YOUR_RETURN_PCT},
}


def first_cost(rows: list[dict]) -> float | None:
    """The owner's cost of a company (the first stored value among its calls)."""
    return next((float(r[YOUR_COST_PCT]) for r in rows if not fmt.missing(r.get(YOUR_COST_PCT))), None)


def mean_gain(rows: list[dict]) -> float | None:
    """The mean of the rows' stored expected gain after your cost (2 decimals); None when none has one."""
    gains = [float(r[YOUR_GAIN_PCT]) for r in rows if not fmt.missing(r.get(YOUR_GAIN_PCT))]
    return round(statistics.mean(gains), 2) if gains else None


def pick_gain(row: dict) -> float | None:
    """A morning pick's gain: the mean stored gain of the strategies that buy it (agreement row `avg_your_gain`)."""
    return row.get("avg_your_gain")


def verdict(gain: float | None, cost) -> str:
    """'expected gain -0.71% after your cost 0.30% — not viable' (or '— viable'); '' without the numbers."""
    if gain is None or fmt.missing(cost):
        return ""
    return (f"expected gain {fmt.pct(gain)} after your cost {float(cost):.2f}% — "
            f"{'viable' if gain > 0 else 'not viable'}")


def pick_cost_text(row: dict) -> str:
    """' Expected gain -0.71% after your cost 0.30% — not viable.' for a pick line, '' without the numbers."""
    text = verdict(pick_gain(row), row.get(YOUR_COST_PCT))
    return f" {text[0].upper()}{text[1:]}." if text else ""


def head_to_head_cost_text(pick: dict) -> str:
    """'; expected gain -1.44% after your cost 0.30% — not viable' from the pick's stored gain, else ''."""
    gain = pick.get(YOUR_GAIN_PCT)
    text = verdict(None if fmt.missing(gain) else round(float(gain), 2), pick.get(YOUR_COST_PCT))
    return f"; {text}" if text else ""


def trade_cost_text(row: dict, currency: str) -> str:
    """'; after your costs ($2.80) net +$4.14 (+0.41%)' when the row has the owner's costs, else ''."""
    if fmt.missing(row.get(YOUR_NET_PNL)):
        return ""
    return (f"; after your costs ({fmt.money(currency, row.get(YOUR_COSTS))}) net"
            f" {fmt.signed_money(currency, row[YOUR_NET_PNL])} ({fmt.pct(row.get(YOUR_RETURN_PCT))})")


def your_net_total(rows: list[dict]) -> float | None:
    """Sum of the owner's net results of the settled rows; None unless every settled row has one (a partial sum
    would mislead)."""
    done = [r for r in rows if r.get("status") == "settled"]
    if not done or any(fmt.missing(r.get(YOUR_NET_PNL)) for r in done):
        return None
    return round(sum(r[YOUR_NET_PNL] for r in done), 2)
