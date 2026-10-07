"""The morning paper picks (SPEC F9 (1), decisions 30 and 39): the top 5 companies of a market by agreement at
N+1, each with its strongest other horizon, the family split, probability, target, amount and the Paper label,
plus the day's head-to-head trades (up to four) per pick. Agreement is computed from the stored
`strategy_predictions` of the session the way docs/DATA_CATALOGUE.md#agreement defines it."""
from __future__ import annotations

import statistics

from marketbrief.alerts import text as fmt
from marketbrief.alerts.constants import (
    FAMILY_LABELS,
    LABEL_PAPER_ONLY,
    MSG_FOOTER,
    MSG_NO_HEAD_TO_HEAD,
    MSG_NO_PICKS,
    MSG_NO_PREDICTIONS,
    MSG_NO_STRONG,
    PAPER,
    PICK_HORIZON,
    PICK_RULE_LABELS,
    TOP_PICKS,
)

FAMILIES = ("rule", "baseline", "ai")


def agreement(preds: list[dict], horizon_days: int) -> list[dict]:
    """Per company at one horizon: buy (qualifying calls), of (calls), by_family, avg_prob_up of the buyers
    that give one (4 decimals), mean target of the buyers; ranked most buyers first, then the higher average
    probability, then the ticker."""
    rows = []
    for ticker in sorted({p["ticker"] for p in preds}):
        mine = [p for p in preds if p["ticker"] == ticker and int(p["horizon_days"]) == horizon_days]
        if not mine:
            continue
        buys = [p for p in mine if p.get("qualifies")]
        probs = [p["prob_up"] for p in buys if not fmt.missing(p.get("prob_up"))]
        targets = [p["target_price"] for p in buys if not fmt.missing(p.get("target_price"))]
        rows.append({
            "ticker": ticker, "horizon_days": horizon_days, "buy": len(buys), "of": len(mine),
            "by_family": {f: {"buy": sum(p.get("family") == f for p in buys),
                              "of": sum(p.get("family") == f for p in mine)} for f in FAMILIES},
            "avg_prob_up": round(statistics.mean(probs), 4) if probs else None,
            "avg_target": round(statistics.mean(targets), 2) if targets else None,
            "base_close": mine[0].get("base_close"), "amount": mine[0].get("amount"),
            "currency": mine[0].get("currency"),
        })
    rows.sort(key=lambda r: (-r["buy"], -(r["avg_prob_up"] or 0), r["ticker"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def strongest_other(preds: list[dict], ticker: str, horizons: list[int]) -> dict | None:
    """The other horizon with the highest buy count (decision 39; ties: the shorter); None when no other
    horizon has a buyer."""
    best = None
    for k in sorted(h for h in horizons if h != PICK_HORIZON):
        row = next((r for r in agreement([p for p in preds if p["ticker"] == ticker], k)), None)
        if row and row["buy"] > 0 and (best is None or row["buy"] > best["buy"]):
            best = row
    return best


def picks(preds: list[dict], top: int = TOP_PICKS) -> list[dict]:
    """The top companies at N+1 with at least one buyer."""
    return [r for r in agreement(preds, PICK_HORIZON) if r["buy"] > 0][:top]


def family_split(row: dict) -> str:
    """'rule 6/8, baseline 2/3, AI 4/4' (families with no call at this horizon left out)."""
    parts = [f"{FAMILY_LABELS[f] if f == 'ai' else f} {c['buy']}/{c['of']}"
             for f, c in row["by_family"].items() if c["of"]]
    return ", ".join(parts)


def head_to_head_lines(pick_rows: list[dict], preds_by_id: dict, names: dict) -> list[str]:
    """One line per head-to-head pick of the company (rule then AI; gain pick then probability pick)."""
    order = {"rule": 0, "ai": 1, "best_expected_gain": 0, "highest_probability": 1}
    picked = sorted((p for p in pick_rows if p.get("status") == "picked"),
                    key=lambda p: (order.get(p["family"], 9), order.get(p["pick_rule"], 9)))
    if not picked:
        return [f"   {MSG_NO_HEAD_TO_HEAD}"]
    lines = []
    for p in picked:
        pred = preds_by_id.get(p.get("prediction_id"), {})
        cur = p.get("currency") or pred.get("currency")
        target = f", target {fmt.money(cur, pred['target_price'])}" if not fmt.missing(pred.get("target_price")) else ""
        side = f"{FAMILY_LABELS.get(p['family'], p['family'])}, {PICK_RULE_LABELS.get(p['pick_rule'], p['pick_rule'])}"
        lines.append(
            f"   • {side}:"
            f" {fmt.who(p['strategy_id'], names)} at {fmt.horizon(p['horizon_days'])},"
            f" P(up) {fmt.prob(p.get('prob_up'))}{target}, expected gain {fmt.pct(p.get('expected_gain_pct'))},"
            f" {fmt.money(cur, p.get('amount'))} {PAPER}")
    return lines


def pick_lines(row: dict, other: dict | None, company: str) -> list[str]:
    """The pick's own lines: agreement, family split, probability, target, amount, strongest other horizon."""
    cur = row["currency"]
    target = (f"average target {fmt.money(cur, row['avg_target'])}" if row["avg_target"] is not None
              else "no target")
    other_text = ("no other horizon has a buyer" if other is None else
                  f"{fmt.horizon(other['horizon_days'])} ({other['buy']} of {other['of']},"
                  f" average P(up) {fmt.prob(other['avg_prob_up'])})")
    return [
        f"{row['rank']}. *{company} ({row['ticker']})* {PAPER} — {row['buy']} of {row['of']} strategies buy at"
        f" N+1 ({family_split(row)}); average P(up) {fmt.prob(row['avg_prob_up'])}; {target}"
        f" (last close {fmt.money(cur, row['base_close'])}); {fmt.money(cur, row['amount'])} per trade.",
        f"   Strongest other horizon: {other_text}.",
    ]


def build_morning(market: str, session_date: str, preds: list[dict], h2h: list[dict], horizons: list[int],
                  names: dict | None = None) -> str:
    """The morning message. `preds` and `h2h` are the session's strategy_predictions and head_to_head_picks
    as of the run; `names` maps tickers and strategy ids to display names."""
    names = names or {}
    lines = [f"*{fmt.market_label(market)} — morning paper picks for {fmt.day_label(session_date)} (N+1)*",
             f"{LABEL_PAPER_ONLY} {MSG_NO_STRONG}"]
    top = picks(preds)
    if not preds:
        lines.append(MSG_NO_PREDICTIONS)
    elif not top:
        lines.append(MSG_NO_PICKS)
    preds_by_id = {p["id"]: p for p in preds}
    for row in top:
        other = strongest_other(preds, row["ticker"], horizons)
        lines += pick_lines(row, other, names.get(row["ticker"], row["ticker"]))
        lines.append("   Head-to-head today:")
        lines += head_to_head_lines([p for p in h2h if p["ticker"] == row["ticker"]], preds_by_id, names)
    lines.append(MSG_FOOTER)
    return "\n".join(lines) + "\n"
