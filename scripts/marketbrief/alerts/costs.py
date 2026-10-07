"""The owner's own costs in Slack (owner decisions 50-51, relayed by the orchestrator on 2026-10-07; the viability
test chosen by the owner in this session on 2026-10-07): each morning pick says whether it is viable at the owner's
costs, and close results show the net result after the owner's costs beside the market-cost result.

Viable = expected gain after your cost > 0, with the head-to-head formula of F1.7.3 and the owner's round-trip
cost in place of the market costs: p x move - (1 - p) x loss - your_cost (all % of the amount; move = target vs
the last close, loss = the drop to the 80% range's low). Slack computes this itself from stored numbers; B2's
`cost_viable` (move > cost) is not used.

B2 stores the owner's costs in its kind `cost_views` (docs/ws/b2.md), one row per prediction, pick or
settlement (`record_kind`, `record_id`). reads.with_costs joins the newest row by the clock onto each record under
the names below (COST_SOURCES maps B2's columns to them); a record without one shows no cost text."""
from __future__ import annotations

from marketbrief.alerts import text as fmt

YOUR_COST_PCT = "your_cost_pct"      # predictions and picks: the owner's round-trip cost, % of the amount
YOUR_COSTS = "your_costs"            # settled trades: the owner's round-trip costs in the market currency
YOUR_NET_PNL = "your_net_pnl"        # settled trades: net profit after the owner's costs
YOUR_RETURN_PCT = "your_return_pct"  # settled trades: that net profit as % of the amount

# cost_views record_kind -> {B2 column: the name the messages read}
COST_SOURCES = {
    "prediction": {"your_cost_pct": YOUR_COST_PCT},
    "pick": {"your_cost_pct": YOUR_COST_PCT},
    "settlement": {"your_costs": YOUR_COSTS, "net_pnl_your": YOUR_NET_PNL, "return_pct_your": YOUR_RETURN_PCT},
}


def first_cost(rows: list[dict]) -> float | None:
    """The owner's cost of a company (the first stored value among its calls)."""
    return next((float(r[YOUR_COST_PCT]) for r in rows if not fmt.missing(r.get(YOUR_COST_PCT))), None)


def gain_after_your_cost(prob_up, move_pct, loss_pct, cost_pct) -> float | None:
    """p x move - (1 - p) x loss - your cost, in % (2 decimals); None when a number is missing."""
    if any(fmt.missing(v) for v in (prob_up, move_pct, loss_pct, cost_pct)):
        return None
    return round(prob_up * move_pct - (1 - prob_up) * loss_pct - cost_pct, 2)


def pick_parts(row: dict) -> tuple[float | None, float | None]:
    """A pick's move and loss in %: the buyers' average target and average 80% low against the last close."""
    base = row.get("base_close")
    if fmt.missing(base) or not base:
        return None, None
    move = None if fmt.missing(row.get("avg_target")) else (row["avg_target"] / base - 1) * 100
    loss = None if fmt.missing(row.get("avg_lo80")) else (1 - row["avg_lo80"] / base) * 100
    return move, loss


def pick_gain(row: dict) -> float | None:
    """The pick's expected gain after your cost, from the buyers' average probability, target and 80% low."""
    move, loss = pick_parts(row)
    return gain_after_your_cost(row.get("avg_prob_up"), move, loss, row.get(YOUR_COST_PCT))


def verdict(gain: float | None, cost) -> str:
    """'expected gain -0.71% after your cost 0.30% — not viable' (or '— viable'); '' without the numbers."""
    if gain is None:
        return ""
    return (f"expected gain {fmt.pct(gain)} after your cost {float(cost):.2f}% — "
            f"{'viable' if gain > 0 else 'not viable'}")


def pick_cost_text(row: dict) -> str:
    """' Expected gain -0.71% after your cost 0.30% — not viable.' for a pick line, '' without the numbers."""
    text = verdict(pick_gain(row), row.get(YOUR_COST_PCT))
    return f" {text[0].upper()}{text[1:]}." if text else ""


def head_to_head_cost_text(pick: dict) -> str:
    """'; expected gain -1.44% after your cost 0.30% — not viable' from the pick's stored parts, else ''."""
    gain = gain_after_your_cost(pick.get("prob_up"), pick.get("move_pct"), pick.get("loss_pct"),
                                pick.get(YOUR_COST_PCT))
    text = verdict(gain, pick.get(YOUR_COST_PCT))
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
