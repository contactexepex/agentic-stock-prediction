"""F7.1 paired comparisons on identical company-days (settled trades only, newest settlement of each):
- rule_vs_ai: head-to-head trades of the rule and the AI family on the same company, entry day and pick rule;
- gain_vs_probability: the same family's two pick rules on the same company and entry day;
- versus_compared_to: each strategy against its registry `compared_to` (F2.5) on the same company, as-of day and
  horizon, accuracy view, both trading.
Each comparison: pairs, net profit of each side, wins of each side, mean difference of return_pct (a - b) and its
bootstrap interval (lab/luck.py, m = 1)."""
from __future__ import annotations

from marketbrief.lab.constants import (FAMILY_AI, FAMILY_RULE, MONEY_DIGITS, PCT_DIGITS, PICK_GAIN, PICK_PROBABILITY,
                                       STATUS_SETTLED, VIEW_ACCURACY, VIEW_HEAD_TO_HEAD)
from marketbrief.lab.luck import luck_test
from marketbrief.lab.scoreboard import latest_settlements


def as_of_of(trade: dict) -> str:
    """The as-of date inside a prediction id (<strategy>:<as_of>-<ticker>-<k>d)."""
    return trade["prediction_id"].split(":", 1)[1][:10]


def paired(label: str, pairs: list[tuple[dict, dict]], names: tuple[str, str]) -> dict:
    """The summary of matched (a, b) trades."""
    diffs = [a["return_pct"] - b["return_pct"] for a, b in pairs]
    return {"comparison": label, "a": names[0], "b": names[1], "pairs": len(pairs),
            "net_pnl_a": round(sum(a["net_pnl"] for a, _ in pairs), MONEY_DIGITS),
            "net_pnl_b": round(sum(b["net_pnl"] for _, b in pairs), MONEY_DIGITS),
            "wins_a": sum(a["net_pnl"] > b["net_pnl"] for a, b in pairs),
            "wins_b": sum(b["net_pnl"] > a["net_pnl"] for a, b in pairs),
            "mean_diff_pct": round(sum(diffs) / len(diffs), PCT_DIGITS) if diffs else None,
            "luck_test": luck_test(diffs, f"{label}|{names[0]}|{names[1]}", 1)}


def head_to_head_pairs(trades: list[dict]) -> list[dict]:
    """rule_vs_ai per market and pick rule, and gain_vs_probability per market and family."""
    by_key: dict[tuple, dict] = {}
    for trade in trades:
        if trade["view"] == VIEW_HEAD_TO_HEAD:
            by_key[(trade["market"], trade["ticker"], trade["entry_date"], trade["family"], trade["pick_rule"])] = trade
    out = []
    for market in sorted({k[0] for k in by_key}):
        for rule in (PICK_GAIN, PICK_PROBABILITY):
            pairs = [(t, by_key[(*k[:3], FAMILY_AI, rule)]) for k, t in sorted(by_key.items())
                     if k[0] == market and k[3] == FAMILY_RULE and k[4] == rule and (*k[:3], FAMILY_AI, rule) in by_key]
            out.append({"market": market, **paired(f"rule_vs_ai:{rule}", pairs, (FAMILY_RULE, FAMILY_AI))})
        for family in (FAMILY_RULE, FAMILY_AI):
            pairs = [(t, by_key[(*k[:4], PICK_PROBABILITY)]) for k, t in sorted(by_key.items())
                     if k[0] == market and k[3] == family and k[4] == PICK_GAIN
                     and (*k[:4], PICK_PROBABILITY) in by_key]
            out.append({"market": market, **paired(f"gain_vs_probability:{family}", pairs,
                                                   (PICK_GAIN, PICK_PROBABILITY))})
    return out


def versus_compared_to(trades: list[dict], specs: list[dict]) -> list[dict]:
    """Each strategy against its compared_to on identical predictions (accuracy view)."""
    index: dict[tuple, dict] = {}
    for trade in trades:
        if trade["view"] == VIEW_ACCURACY:
            key = (trade["market"], trade["strategy_id"], trade["ticker"], as_of_of(trade), trade["horizon_days"])
            index[key] = trade
    markets = sorted({k[0] for k in index})
    out = []
    for spec in specs:
        other = spec.get("compared_to")
        if not other:
            continue
        for market in markets:
            pairs = [(t, index[(market, other, *k[2:])]) for k, t in sorted(index.items())
                     if k[0] == market and k[1] == spec["id"] and (market, other, *k[2:]) in index]
            out.append({"market": market, "differs_in": spec.get("differs_in"),
                        **paired("versus_compared_to", pairs, (spec["id"], other))})
    return out


def comparisons(settled: list[dict], specs: list[dict]) -> dict:
    """{head_to_head: [...], versus_compared_to: [...]} from settled trades."""
    trades = [t for t in latest_settlements(settled) if t["status"] == STATUS_SETTLED]
    return {"head_to_head": head_to_head_pairs(trades), "versus_compared_to": versus_compared_to(trades, specs)}
