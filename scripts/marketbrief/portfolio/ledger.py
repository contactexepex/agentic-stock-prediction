"""Positions and P&L of the paper portfolio: FIFO lots, marked to the latest stored close (as of the clock).

Order of trades: trade_date, then within a day the open first, a manual price next, the close last, then
entered_at and id. Every price and quantity is put on today's split/bonus basis (price x factor, quantity /
factor; reads.factor_after), so a later split never shows as a loss; costs are charged on the traded value.

- Realised (on each sell): gross = sum over the FIFO lots it closes of (sell price - lot price) x quantity;
  net = gross - the closed lots' share of their buy costs - the sell's own cost.
- Unrealised (on each buy's open quantity): gross = (mark - lot price) x open quantity; net = gross - the open
  quantity's share of the buy cost - the estimated cost of selling it at the mark (est_exit_cost).
A sell larger than the quantity held is listed in `short_violations` (add-trade rejects it before storing)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from marketbrief.portfolio.constants import BASIS_ORDER, SIDE_BUY, SIDE_SELL
from marketbrief.portfolio.costs import trade_cost
from marketbrief.portfolio.reads import factor_after

QTY_EPS = 1e-9
MONEY_DIGITS, QTY_DIGITS, PRICE_DIGITS = 2, 6, 4


def money(value: float | None) -> float | None:
    """A currency amount rounded for output."""
    return None if value is None else round(float(value), MONEY_DIGITS) + 0.0


@dataclass
class Lot:
    """An open buy lot on today's basis."""
    trade_id: str
    quantity: float
    price: float
    cost_per_unit: float


@dataclass
class Book:
    """The FIFO state of one market: open lots per ticker and the per-trade results."""
    lots: dict[str, list[Lot]] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    violations: list[dict] = field(default_factory=list)


def ordered(trades: pd.DataFrame) -> pd.DataFrame:
    """Trades in ledger order (see the module docstring)."""
    if trades.empty:
        return trades
    frame = trades.assign(_basis=trades["price_basis"].map(BASIS_ORDER).fillna(1))
    return frame.sort_values(["trade_date", "_basis", "entered_at", "id"]).drop(columns="_basis")


def on_today_basis(trade, adjust: pd.DataFrame) -> tuple[float, float]:
    """(quantity, price) of a trade on today's split/bonus basis."""
    factor = factor_after(adjust, trade["ticker"], trade["trade_date"])
    return float(trade["quantity"]) / factor, float(trade["price"]) * factor


def apply_buy(book: Book, trade, quantity: float, price: float, cost: float) -> None:
    """Open a lot for a buy."""
    book.lots.setdefault(trade["ticker"], []).append(Lot(trade["id"], quantity, price, cost / quantity))


def apply_sell(book: Book, trade, quantity: float, price: float, cost: float) -> dict:
    """Close FIFO lots for a sell; returns its realised gross and net."""
    lots, left, gross, buy_costs = book.lots.get(trade["ticker"], []), quantity, 0.0, 0.0
    while left > QTY_EPS and lots:
        lot = lots[0]
        take = min(lot.quantity, left)
        gross += (price - lot.price) * take
        buy_costs += lot.cost_per_unit * take
        lot.quantity -= take
        left -= take
        if lot.quantity <= QTY_EPS:
            lots.pop(0)
    if left > QTY_EPS:
        held = quantity - left
        book.violations.append({"trade_id": trade["id"], "ticker": trade["ticker"],
                                "trade_date": str(trade["trade_date"]), "quantity": quantity,
                                "held": round(held, QTY_DIGITS), "left": round(-left, QTY_DIGITS)})
    return {"realised_gross": gross, "realised_net": gross - buy_costs - cost}


def run_book(trades: pd.DataFrame, adjust: pd.DataFrame, market: str, costs: dict) -> Book:
    """Replay the active trades in ledger order."""
    book = Book()
    for _, trade in ordered(trades).iterrows():
        quantity, price = on_today_basis(trade, adjust)
        cost = trade_cost(market, costs, trade["side"], float(trade["quantity"]), float(trade["price"]))
        row = {"id": trade["id"], "ticker": trade["ticker"], "side": trade["side"],
               "trade_date": str(trade["trade_date"]), "quantity": round(quantity, QTY_DIGITS),
               "price": round(price, PRICE_DIGITS), "price_basis": trade["price_basis"], "cost": cost}
        if trade["side"] == SIDE_BUY:
            apply_buy(book, trade, quantity, price, cost)
        elif trade["side"] == SIDE_SELL:
            row.update(apply_sell(book, trade, quantity, price, cost))
        book.results[trade["id"]] = row
    return book


def mark_lots(book: Book, marks: dict[str, tuple[str, float]], market: str, costs: dict) -> None:
    """Add each open lot's unrealised P&L at the ticker's mark (date, close on today's basis) to its buy row."""
    for ticker, lots in book.lots.items():
        mark = marks.get(ticker)
        for lot in lots:
            row = book.results[lot.trade_id]
            row["open_quantity"] = round(lot.quantity, QTY_DIGITS)
            if mark is None:
                row.update(unrealised_gross=None, unrealised_net=None, est_exit_cost=None, mark=None)
                continue
            gross = (mark[1] - lot.price) * lot.quantity
            exit_cost = trade_cost(market, costs, SIDE_SELL, lot.quantity, mark[1])
            row.update(mark=round(mark[1], PRICE_DIGITS), mark_date=mark[0], unrealised_gross=gross,
                       est_exit_cost=exit_cost, unrealised_net=gross - lot.cost_per_unit * lot.quantity - exit_cost)


def positions(book: Book, marks: dict[str, tuple[str, float]]) -> list[dict]:
    """Open position per ticker: quantity, average price (before costs), mark and market value."""
    out = []
    for ticker in sorted(book.lots):
        lots = [lot for lot in book.lots[ticker] if lot.quantity > QTY_EPS]
        quantity = sum(lot.quantity for lot in lots)
        if quantity <= QTY_EPS:
            continue
        average = sum(lot.quantity * lot.price for lot in lots) / quantity
        mark = marks.get(ticker)
        out.append({"ticker": ticker, "quantity": round(quantity, QTY_DIGITS),
                    "avg_price": round(average, PRICE_DIGITS),
                    "cost_value": money(quantity * average), "mark_date": mark[0] if mark else None,
                    "mark": round(mark[1], PRICE_DIGITS) if mark else None,
                    "market_value": money(quantity * mark[1]) if mark else None, "lots": len(lots)})
    return out


def totals(rows: list[dict]) -> dict:
    """Realised and unrealised P&L summed over the per-trade rows, before and after costs."""
    def total(key: str) -> float | None:
        values = [row[key] for row in rows if key in row]
        return None if any(value is None for value in values) else sum(values)
    out = {key: total(key) for key in ("realised_gross", "realised_net", "unrealised_gross", "unrealised_net",
                                       "est_exit_cost")}
    out["costs_paid"] = sum(row["cost"] for row in rows)
    for kind in ("gross", "net"):
        parts = [out[f"realised_{kind}"] or 0.0, out[f"unrealised_{kind}"]]
        out[f"total_{kind}"] = None if parts[1] is None else parts[0] + parts[1]
    return {key: money(value) for key, value in out.items()}


def rounded(row: dict) -> dict:
    """A per-trade row with its money fields rounded for output."""
    keys = ("cost", "realised_gross", "realised_net", "unrealised_gross", "unrealised_net", "est_exit_cost")
    return {key: money(value) if key in keys else value for key, value in row.items()}
