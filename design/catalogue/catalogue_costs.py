"""The cost views of the example records (B2's kind `cost_views`, decisions 50-51; EXAMPLES only), computed with
B2's own row functions (marketbrief/lab/cost_views.py) so the example rows follow the engine exactly."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from make_examples import EURUSD

from marketbrief.lab import cost_views as lab_cost_views
from marketbrief.lab import costs as lab_costs


def market_data(market: str) -> SimpleNamespace:
    """The three things settlement_row reads from MarketData: the market, its rates and EUR/USD per date."""
    return SimpleNamespace(market=market, rates=lab_costs.rates(market), eurusd_on=lambda _day: EURUSD)


def cost_rows(preds: list[dict], picks: list[dict], settled: list[dict], past: list[dict]) -> list[dict]:
    """Prediction rows (each qualifying example prediction), pick rows (each picked head-to-head pick) and
    settlement rows (each settled example trade)."""
    by_id = {p["id"]: p for p in preds + past}
    rows = []
    for pred in preds:
        if pred["qualifies"]:
            made = datetime.fromisoformat(pred["made_at"].replace("Z", "+00:00"))
            rows.append(lab_cost_views.viability_row("prediction", pred["id"], pred, lab_costs.rates(pred["market"]),
                                                     EURUSD if pred["market"] == "us" else None, made))
    for pick in picks:
        if pick["status"] == "picked":
            pred = by_id[pick["prediction_id"]]
            made = datetime.fromisoformat(pick["made_at"].replace("Z", "+00:00"))
            rows.append(lab_cost_views.viability_row("pick", pick["id"], pred, lab_costs.rates(pred["market"]),
                                                     EURUSD if pred["market"] == "us" else None, made))
    for trade in settled:
        row = lab_cost_views.settlement_row(trade, by_id[trade["prediction_id"]], market_data(trade["market"]))
        if row is not None:
            rows.append(row)
    return rows
