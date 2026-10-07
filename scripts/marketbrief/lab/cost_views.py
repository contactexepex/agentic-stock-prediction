"""Owner decisions 50-51: the two cost views of every settled trade and the cost-viable flag of every prediction or
pick that would trade, as `cost_views` rows (core/schema_b2.py). Costs from lab/costs.py.

- prediction / pick (pre-open): the round trip of the company's amount bought and sold at the reference price
  C = base_close (India whole shares at C; none affordable: no cost, not viable), the US order fee at the EUR/USD
  close on or before D, the portfolio fee over the calendar days from D to the planned exit.
  expected_move_pct = (target / C - 1) x 100. Viable (owner decision of 2026-10-07, made in session B6 for every
  session; it replaces decision 51's "move > cost"): the expected gain after your cost is above 0,
      expected_gain_your_pct = p x move - (1 - p) x loss - your_cost_pct > 0,
  with the prediction's prob_up and the same move and loss as the head-to-head picks (lab/gain.py: the conditional
  rise and shortfall from its own 80% range). A prediction without a probability or a range (always-up, momentum)
  has no expected gain: cost_viable null.
- settlement (post-close): the settled trade's entry and exit values, both views; net and return per view."""
from __future__ import annotations

from datetime import date, datetime

from marketbrief.constants.kinds import KIND_COST_VIEWS
from marketbrief.core.schemas import SCHEMAS
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.constants import ENGINE_VERSION, MONEY_DIGITS, PCT_DIGITS, PERCENT, STATUS_SETTLED
from marketbrief.lab.gain import conditional_move_loss, expected_gain_pct
from marketbrief.lab.market_data import MarketData
from marketbrief.lab.settle import as_date
from marketbrief.lab.sizing import quantity
from marketbrief.utils.timefmt import as_utc_timestamp

KIND_PREDICTION, KIND_PICK, KIND_SETTLEMENT = "prediction", "pick", "settlement"


def holding_days(entry: date, exit_: date) -> int:
    """Calendar days from D to the exit session."""
    return (as_date(exit_) - as_date(entry)).days


def base_row(record_kind: str, record_id: str, pred: dict, computed_at: datetime) -> dict:
    """The columns every cost_views row shares, copied from the prediction."""
    row = dict.fromkeys(SCHEMAS[KIND_COST_VIEWS][1])
    row.update(id=f"cv:{record_kind}:{record_id}", record_kind=record_kind, record_id=record_id,
               prediction_id=pred["id"], strategy_id=pred["strategy_id"], market=pred["market"],
               ticker=pred["ticker"], horizon_days=pred["horizon_days"],
               session_date=str(as_date(pred["session_date"])),
               exit_date=str(as_date(pred["exit_date"])), amount=pred["amount"], currency=pred.get("currency"),
               target_price=pred.get("target_price"), computed_at=as_utc_timestamp(computed_at).isoformat(),
               method_version=ENGINE_VERSION)
    return row


def gain_after_your_cost(pred: dict, your_pct: float) -> float | None:
    """p x move - (1 - p) x loss - your cost in % (lab/gain.py), or None without a probability or a range."""
    if None in (pred.get("prob_up"), pred.get("target_price"), pred.get("lo80"), pred.get("hi80")):
        return None
    move, loss = conditional_move_loss(float(pred["base_close"]), pred["target_price"], pred["lo80"], pred["hi80"])
    return expected_gain_pct(float(pred["prob_up"]), move, loss, your_pct)


def viability(pred: dict, rate: dict, eurusd: float | None) -> dict:
    """{expected_move_pct, market_cost_pct, your_cost_pct, expected_gain_your_pct, cost_viable, views,
    holding_days} at C."""
    close, amount = float(pred["base_close"]), float(pred["amount"])
    target = pred.get("target_price")
    move = None if target is None else (float(target) / close - 1) * PERCENT
    days = holding_days(pred["session_date"], pred["exit_date"])
    shares = quantity(pred["market"], amount, close)
    if shares <= 0:   # one share costs more than the amount: no trade, no costs, no gain, so no verdict (null)
        return {"expected_move_pct": move, "market_cost_pct": None, "your_cost_pct": None,
                "expected_gain_your_pct": None, "cost_viable": None, "views": None, "holding_days": days}
    value = shares * close
    views = lab_costs.cost_views(pred["market"], rate, (value, value), shares,
                                 {"eurusd": (eurusd, eurusd), "holding_days": days})
    market_pct = views["market"]["total"] / amount * PERCENT
    your_pct = views["your"]["total"] / amount * PERCENT
    gain = gain_after_your_cost(pred, your_pct)
    return {"expected_move_pct": move, "market_cost_pct": market_pct, "your_cost_pct": your_pct,
            "expected_gain_your_pct": gain, "cost_viable": None if gain is None else bool(gain > 0), "views": views,
            "holding_days": days}


def viability_row(record_kind: str, record_id: str, pred: dict, rate: dict, eurusd: float | None,
                  computed_at: datetime) -> dict:
    """A prediction or pick row (decision 51)."""
    found = viability(pred, rate, eurusd)
    row = base_row(record_kind, record_id, pred, computed_at)
    market, your = (found["views"] or {}).get("market", {}), (found["views"] or {}).get("your", {})
    row.update(reference_price=float(pred["base_close"]), holding_days=found["holding_days"],
               cost_viable=found["cost_viable"], eurusd_entry=eurusd if pred["market"] == "us" else None,
               market_costs=market.get("total"), market_cost_lines=market.get("lines"),
               your_costs=your.get("total"), your_cost_lines=your.get("lines"),
               **{key: None if found[key] is None else round(found[key], PCT_DIGITS)
                  for key in ("expected_move_pct", "market_cost_pct", "your_cost_pct", "expected_gain_your_pct")})
    return row


def settlement_row(settled: dict, pred: dict, data: MarketData) -> dict | None:
    """The two views of a settled trade (None for no_entry and skipped rows)."""
    if settled["status"] != STATUS_SETTLED:
        return None
    entry, exit_ = as_date(settled["entry_date"]), as_date(settled["exit_date_actual"])
    eurusd = (data.eurusd_on(entry), data.eurusd_on(exit_)) if data.market == "us" else (None, None)
    days = holding_days(entry, exit_)
    views = lab_costs.cost_views(data.market, data.rates, (settled["entry_value"], settled["exit_value"]),
                                 settled["quantity"], {"eurusd": eurusd, "holding_days": days})
    gross, amount = float(settled["gross_pnl"]), float(settled["amount"])
    row = base_row(KIND_SETTLEMENT, settled["id"], pred, settled["settled_at"])
    row.update(trade_id=settled["trade_id"], exit_date=str(exit_), reference_price=settled["entry_price"],
               holding_days=days, eurusd_entry=eurusd[0], eurusd_exit=eurusd[1])
    for view in ("market", "your"):
        net = gross - views[view]["total"]
        row.update({f"{view}_costs": views[view]["total"], f"{view}_cost_lines": views[view]["lines"],
                    f"net_pnl_{view}": round(net, MONEY_DIGITS), f"return_pct_{view}": round(net / amount * PERCENT,
                                                                                              PCT_DIGITS),
                    f"{view}_cost_pct": round(views[view]["total"] / amount * PERCENT, PCT_DIGITS)})
    return row
