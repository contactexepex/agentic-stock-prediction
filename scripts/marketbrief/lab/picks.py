"""F1.7 head-to-head picks (decisions 41-42), with the two corrections of docs/ws/b2.md:

Strongest strategy (decision 41, corrected): strategies of the family with >= MIN_TRADES_PER_COMPANY settled
accuracy-view trades on this company rank first, by profit after costs on it; the others follow by profit after
costs across all companies of the market; strategies with no settled trade at all rank last (a strategy with no
record cannot be "strongest" ahead of one with a record). Ties: more settled trades, then the lower id. The
strongest = the highest-ranked strategy with at least one candidate horizon today.

Expected gain (F1.7.3, corrected): from the latest stored close C and the strategy's own 80% range for the
horizon, the exit close X is read as normal with mean = target and sigma = (hi80 - lo80) / (2 x 1.2816). Then, in %
of the amount,
    move = E[X / C - 1 | X > C]      (the expected rise when the stock ends above C)
    loss = E[1 - X / C | X < C]      (the expected shortfall below C when it ends below)
    expected_gain = p x move - (1 - p) x loss - costs
with p the strategy's prob_up and costs the round trip of the amount at C. "Best expected gain" picks the horizon
with the highest expected gain per session held, expected_gain / k (gain_per_session_pct in the candidates JSON;
expected_gain_pct stays the per-trade value). Why per session: with the same p at every horizon the per-trade gain
grows with the spread (about sqrt(k)), so N+5 would always win, just as the draft (loss = 1 - lo80 / C, a tail
against a centre) made N+1 always win at a negative value; per session neither end is favoured by construction,
and costs (paid once per trade) weigh more on short horizons. Ties: the shorter horizon."""
from __future__ import annotations

from marketbrief.contracts.protocol import MIN_TRADES_PER_COMPANY
from marketbrief.lab import costs as lab_costs
from marketbrief.lab.constants import (BASIS_ALL, BASIS_PER_COMPANY, MONEY_DIGITS, PCT_DIGITS, PERCENT, PICK_GAIN,
                                       PICK_PROBABILITY, STATUS_SETTLED, VIEW_ACCURACY)
from marketbrief.lab.cost_views import viability
from marketbrief.lab.gain import conditional_move_loss, expected_gain_pct
from marketbrief.lab.scoreboard import latest_settlements
from marketbrief.lab.sizing import quantity


def costs_pct(market: str, rate: dict, amount: float, close: float, eurusd: float | None) -> float:
    """The round trip of the company's amount at C (bought and sold at C) in % of the amount."""
    shares = quantity(market, amount, close)
    if shares <= 0:
        return 0.0
    value = shares * close
    total = lab_costs.round_trip_costs(market, rate, value, value, shares, (eurusd, eurusd))["total"]
    return total / amount * PERCENT


def candidate(pred: dict, market: str, rate: dict, eurusd: float | None) -> dict | None:
    """One Candidate (contracts/protocol.py) of a qualifying prediction, with its cost-viable flag (decision 51);
    None when one share at C costs more than the amount (the trade would be skipped)."""
    close, prob = float(pred["base_close"]), float(pred["prob_up"])
    if quantity(market, float(pred["amount"]), close) <= 0:
        return None
    move, loss = conditional_move_loss(close, pred["target_price"], pred["lo80"], pred["hi80"])
    cost = costs_pct(market, rate, float(pred["amount"]), close, eurusd)
    gain = expected_gain_pct(prob, move, loss, cost)
    return {"horizon_days": int(pred["horizon_days"]), "prediction_id": pred["id"], "prob_up": prob,
            "move_pct": round(move, PCT_DIGITS), "loss_pct": round(loss, PCT_DIGITS),
            "costs_pct": round(cost, PCT_DIGITS), "expected_gain_pct": round(gain, PCT_DIGITS),
            "gain_per_session_pct": round(gain / int(pred["horizon_days"]), PCT_DIGITS), **cost_flags(pred, rate,
                                                                                                    eurusd)}


def cost_flags(pred: dict, rate: dict, eurusd: float | None) -> dict:
    """expected_move_pct, your_cost_pct, expected_gain_your_pct and cost_viable (lab/cost_views.py: viable = the
    expected gain after your cost > 0)."""
    found = viability(pred, rate, eurusd)
    out = {key: None if found[key] is None else round(found[key], PCT_DIGITS)
           for key in ("expected_move_pct", "your_cost_pct", "expected_gain_your_pct")}
    return {**out, "cost_viable": found["cost_viable"]}


def pick(candidates: list[dict], rule: str) -> dict | None:
    """best_expected_gain: the highest gain_per_session_pct; highest_probability: the highest prob_up; ties: the
    shorter horizon. Only eligible entries (qualifying predictions; `eligible` absent = eligible) are picked. None
    without one."""
    candidates = [c for c in candidates if c.get("eligible", True)]
    if not candidates:
        return None
    def value(c: dict) -> float:
        if rule != PICK_GAIN:
            return c["prob_up"]
        return c.get("gain_per_session_pct", c["expected_gain_pct"] / c["horizon_days"])

    return max(candidates, key=lambda c: (value(c), -c["horizon_days"]))


def ranking(family_ids: list[str], ticker: str, trades: list[dict]) -> list[dict]:
    """Decision 41 ranking (corrected) from settled accuracy-view trades of the market: [{strategy_id, rank,
    basis, settled_trades, net_pnl}] (net_pnl and trades on the company for per_company, else on all companies)."""
    stats = {sid: {"own": [0, 0.0], "all": [0, 0.0]} for sid in family_ids}
    for trade in latest_settlements(trades):           # a re-settled trade counts once, at its newest row
        sid = trade["strategy_id"]
        if sid not in stats or trade["view"] != VIEW_ACCURACY or trade["status"] != STATUS_SETTLED:
            continue
        for scope in ("all", "own") if trade["ticker"] == ticker else ("all",):
            stats[sid][scope][0] += 1
            stats[sid][scope][1] += float(trade["net_pnl"])

    def order(sid: str) -> tuple:
        own_n, own_net = stats[sid]["own"]
        all_n, all_net = stats[sid]["all"]
        if own_n >= MIN_TRADES_PER_COMPANY:
            return (0, -own_net, -own_n, sid)
        return (1 if all_n else 2, -all_net, -all_n, sid)

    out = []
    for rank, sid in enumerate(sorted(family_ids, key=order), 1):
        per_company = stats[sid]["own"][0] >= MIN_TRADES_PER_COMPANY
        trades_n, net = stats[sid]["own" if per_company else "all"]
        out.append({"strategy_id": sid, "rank": rank, "basis": BASIS_PER_COMPANY if per_company else BASIS_ALL,
                    "settled_trades": trades_n, "net_pnl": round(net, MONEY_DIGITS)})
    return out


def strongest(rank: list[dict], qualifying: list[dict]) -> dict | None:
    """The highest-ranked entry with at least one qualifying prediction today."""
    have = {pred["strategy_id"] for pred in qualifying}
    return next((entry for entry in rank if entry["strategy_id"] in have), None)


def horizon_table(preds: list[dict], ticker: str, best: dict | None, context: dict) -> list[dict]:
    """The strongest strategy's expected gain at EVERY horizon it predicted for the company (owner decision of
    2026-10-07: show the gain for every horizon held), sorted by horizon; `eligible` = the prediction qualifies
    (only eligible entries can be picked). A horizon without a probability, target or range, or whose amount buys
    no whole share at C, is left out."""
    if best is None:
        return []
    own = sorted((p for p in preds if p["ticker"] == ticker and p["strategy_id"] == best["strategy_id"]
                  and p.get("prob_up") is not None and None not in (p.get("target_price"), p.get("lo80"),
                                                                     p.get("hi80"))),
                 key=lambda p: p["horizon_days"])
    out = []
    for pred in own:
        found = candidate(pred, context["market"], context["rate"], context["eurusd"])
        if found:
            out.append({**found, "eligible": bool(pred.get("qualifies"))})
    return out


def pick_rows(ticker: str, family: str, context: dict, preds: list[dict], trades: list[dict]) -> list[dict]:
    """The head_to_head_picks rows (one per pick rule) of one company and family. context: market, rate, eurusd,
    family_ids, made_at, as_of_date, session_date, base_close, amount, currency, method_version."""
    mine = [p for p in preds if p["ticker"] == ticker and p["family"] == family and p.get("qualifies")]
    rank = ranking(context["family_ids"], ticker, trades)
    best = strongest(rank, mine)
    candidates = horizon_table(preds, ticker, best, context)
    rows = []
    for rule in (PICK_GAIN, PICK_PROBABILITY):
        chosen_one = pick(candidates, rule)
        row = {"id": f"h2h:{context['as_of_date']}-{ticker}-{family}-{rule}", "market": context["market"],
               "ticker": ticker, "made_at": context["made_at"], "as_of_date": context["as_of_date"],
               "session_date": context["session_date"], "family": family, "pick_rule": rule,
               "status": "picked" if chosen_one else "no_candidate",
               "strategy_id": best["strategy_id"] if chosen_one else None,
               "strongest_basis": best["basis"] if chosen_one else None, "ranking": rank,
               "base_close": context["base_close"], "candidates": candidates, "amount": context["amount"],
               "currency": context["currency"], "method_version": context["method_version"],
               **dict.fromkeys(("horizon_days", "prediction_id", "prob_up", "move_pct", "loss_pct", "costs_pct",
                                "expected_gain_pct"))}
        if chosen_one:
            row.update({key: chosen_one[key] for key in ("horizon_days", "prediction_id", "prob_up", "move_pct",
                                                         "loss_pct", "costs_pct", "expected_gain_pct")})
        rows.append(row)
    return rows
