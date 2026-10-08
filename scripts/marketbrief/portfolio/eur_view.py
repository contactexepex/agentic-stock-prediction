"""The EUR view of the owner's US paper positions (F1.11, decision 11): every open buy lot of a US position in
euros, with BUX's FX fee (config/costs.yaml broker.us.fx_fee_rate, confirmed final 2026-10-08) and the change of the EUR/USD rate.

Per lot (rates in USD per EUR; cost_usd = quantity x buy price + the buy's cost; value_usd = quantity x the mark):
  cost_eur      = cost_usd / eurusd_at_buy x (1 + fx_fee_rate)     euros needed to buy the dollars
  value_eur     = value_usd / eurusd_now x (1 - fx_fee_rate)       euros back if converted now (USD->EUR fee not
                                                                   found: the same rate is assumed)
  pnl_eur       = value_eur - cost_eur
  fx_effect_eur = value_usd / eurusd_now - value_usd / eurusd_at_buy   the part due to the rate change alone
A position sums its lots; eurusd_at_buy is then the lots' cost-weighted rate."""
from __future__ import annotations

from datetime import date

from marketbrief.portfolio.fx import EurUsd

MONEY, RATE = 2, 6


def lot_view(lot_row: dict, quantity: float, mark: float, rates: tuple[float, float], fee: float) -> dict:
    """The unrounded EUR numbers of one open lot."""
    at_buy, now = rates
    cost_usd = quantity * lot_row["price"] + lot_row["cost"] * quantity / lot_row["quantity"]
    value_usd = quantity * mark
    cost_eur = cost_usd / at_buy * (1 + fee)
    value_eur = value_usd / now * (1 - fee)
    return {"cost_usd": cost_usd, "value_usd": value_usd, "cost_eur": cost_eur, "value_eur": value_eur,
            "fx_effect_eur": value_usd / now - value_usd / at_buy, "rate_weight": cost_usd / at_buy}


def eur_view(book, marks: dict, fx: EurUsd, fee: float) -> list[dict]:
    """[{ticker, quantity, mark_date, eurusd_at_buy, eurusd_now, fx_fee_rate, cost_usd, value_usd, cost_eur,
    value_eur, pnl_eur, fx_effect_eur}] per open US position."""
    out = []
    for ticker in sorted(book.lots):
        lots = [lot for lot in book.lots[ticker] if lot.quantity > 1e-9]
        if not lots or ticker not in marks:
            continue
        mark_date, mark = marks[ticker]
        now = fx.required(date.fromisoformat(mark_date))
        parts = []
        for lot in lots:
            row = book.results[lot.trade_id]
            at_buy = fx.required(date.fromisoformat(row["trade_date"]))
            parts.append(lot_view(row, lot.quantity, mark, (at_buy, now), fee))
        total = {key: sum(part[key] for part in parts) for key in parts[0]}
        out.append({"ticker": ticker, "quantity": round(sum(lot.quantity for lot in lots), 6), "mark_date": mark_date,
                    "eurusd_at_buy": round(total["cost_usd"] / total["rate_weight"], RATE),
                    "eurusd_now": round(now, RATE), "fx_fee_rate": fee,
                    **{key: round(total[key], MONEY) for key in ("cost_usd", "value_usd", "cost_eur", "value_eur",
                                                                 "fx_effect_eur")},
                    "pnl_eur": round(total["value_eur"] - total["cost_eur"], MONEY),
                    "note": "BUX FX fee (config/costs.yaml broker.us, owner-confirmed 2026-10-08)"})
    return out
