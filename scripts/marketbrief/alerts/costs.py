"""The owner's own costs in Slack (owner decisions 50-51, relayed by the orchestrator on 2026-10-07): each morning
pick says whether its expected move clears the owner's round-trip cost, and close results show the net result
after the owner's costs beside the market-cost result. B2 stores these fields. Until B2 documents them in
docs/ws/b2.md, the names below are this session's assumption (docs/ws/b6.md): a row without them shows no
cost text."""
from __future__ import annotations

from marketbrief.alerts import text as fmt

YOUR_COST_PCT = "your_cost_pct"      # predictions and picks: the owner's round-trip cost, % of the amount
COST_VIABLE = "cost_viable"          # predictions and picks: the predicted move exceeds that cost
YOUR_COSTS = "your_costs"            # settled trades: the owner's round-trip costs in the market currency
YOUR_NET_PNL = "your_net_pnl"        # settled trades: net profit after the owner's costs
YOUR_RETURN_PCT = "your_return_pct"  # settled trades: that net profit as % of the amount


def first_cost(rows: list[dict]) -> float | None:
    """The owner's cost of a company (the first stored value among its calls)."""
    return next((float(r[YOUR_COST_PCT]) for r in rows if not fmt.missing(r.get(YOUR_COST_PCT))), None)


def expected_move_pct(row: dict) -> float | None:
    """The pick's expected move: the buyers' average target against the last close, in % (2 decimals)."""
    if fmt.missing(row.get("avg_target")) or fmt.missing(row.get("base_close")) or not row["base_close"]:
        return None
    return round((row["avg_target"] / row["base_close"] - 1) * 100, 2)


def pick_viable(row: dict) -> bool | None:
    """Whether the pick's expected move exceeds the owner's cost; None without both numbers."""
    move = expected_move_pct(row)
    return None if move is None or row.get(YOUR_COST_PCT) is None else move > row[YOUR_COST_PCT]


def pick_cost_text(row: dict) -> str:
    """' Expected +3.10% vs your cost 2.70% — viable.' / '… — not viable at your costs.' / ''."""
    viable = pick_viable(row)
    if viable is None:
        return ""
    verdict = "viable" if viable else "not viable at your costs"
    return f" Expected {fmt.pct(expected_move_pct(row))} vs your cost {row[YOUR_COST_PCT]:.2f}% — {verdict}."


def head_to_head_cost_text(pick: dict) -> str:
    """'; viable at your costs' / '; not viable at your costs' from the pick's stored flag, else ''."""
    flag = pick.get(COST_VIABLE)
    if flag is None:
        return ""
    return "; viable at your costs" if flag else "; not viable at your costs"


def trade_cost_text(row: dict, currency: str) -> str:
    """'; after your costs (2.80) net +$1.80 (+0.18%)' when the row has the owner's costs, else ''."""
    if fmt.missing(row.get(YOUR_NET_PNL)):
        return ""
    return (f"; after your costs ({fmt.money(currency, row.get(YOUR_COSTS))}) net"
            f" {fmt.signed_money(currency, row[YOUR_NET_PNL])} ({fmt.pct(row.get(YOUR_RETURN_PCT))})")


def your_net_total(rows: list[dict]) -> float | None:
    """Sum of the owner's net results of settled rows; None when no row has one."""
    values = [r[YOUR_NET_PNL] for r in rows if r.get("status") == "settled" and not fmt.missing(r.get(YOUR_NET_PNL))]
    return round(sum(values), 2) if values else None
