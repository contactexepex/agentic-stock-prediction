"""Plain signal tiers per ticker and horizon (Strong Buy, Buy, Hold/No call, Sell, Strong Sell) that never
overstate proof (config/portfolio.yaml `tiers` and `proof`).

final p = model_prob + the forecaster's agent_adjustment when a call exists for the score's id, else model_prob;
the direction is the side of 0.5 (the call's own direction when it exists) and confidence = max(p, 1 - p).
- Strong Buy / Strong Sell: only in a PROVEN (horizon, confidence band) cell (proof.py), with a forecaster call
  when tiers.strong_requires_call, and confidence >= tiers.strong_min_confidence.
- Buy / Sell: confidence >= tiers.buy_min_confidence.
- Hold/No call: otherwise, no model score (every active watchlist ticker x horizon of config/strategies.yaml gets
  a row), indicator quality BLOCKED,
  or earnings within earnings_block_days calendar days (features.days_to_earnings).
Every row carries paper_only (true unless it has a forecaster call in a proven cell) and then the label
"Paper only — no proven edge yet".
When no strong tier is emitted the payload says "No proven strong signals today" and lists up to
tiers.max_candidates Paper candidates, ranked by |model_prob - 0.5| (ties: ticker, horizon), each with the
score's own top drivers on its side as reasons. cockpit_payload() is the per-market payload for the cockpit's
read models (WS1) and API (wave 2)."""
from __future__ import annotations

from marketbrief.core.market_config import load_market
from marketbrief.portfolio import proof as proofs
from marketbrief.constants.horizons import LABEL_N_PLUS_K
from marketbrief.portfolio.horizons import active_tickers, horizons, resolved_label
from marketbrief.portfolio import signal_inputs as inputs
from marketbrief.portfolio.constants import (
    LABEL_PAPER_ONLY,
    LABEL_PROVEN,
    MSG_NO_SCORE,
    MSG_NO_STRONG,
    STRONG_TIERS,
    TIER_BUY,
    TIER_HOLD,
    TIER_SELL,
    TIER_STRONG_BUY,
    TIER_STRONG_SELL,
)

BLOCKED = "BLOCKED"
PROB_DIGITS = 4


def number(value) -> float | None:
    """A float, or None for a missing value (None or NaN)."""
    return None if value is None or value != value else float(value)


def final_probability(model_prob: float, call: dict | None) -> tuple[float, float | None]:
    """(final p, the call's adjustment) for a score and its call, if any."""
    adjustment = number(call.get("agent_adjustment")) if call else None
    return model_prob + (adjustment or 0.0), adjustment


def blocked_reason(block: dict | None, settings: dict) -> str | None:
    """Why the prediction rules allow no call for the ticker today, or None."""
    if not block:
        return None
    if block.get("quality") == BLOCKED:
        return "indicator quality BLOCKED"
    days = number(block.get("days_to_earnings"))
    if days is not None and days <= settings["tiers"]["earnings_block_days"]:
        return f"earnings in {int(days)} day(s)"
    return None


def tier_for(direction: str | None, confidence: float, proven: bool, has_call: bool, settings: dict) -> str:
    """The tier of a direction and confidence in a proven or unproven cell (pure; see the module docstring)."""
    rules = settings["tiers"]
    if direction not in ("up", "down") or confidence < rules["buy_min_confidence"]:
        return TIER_HOLD
    strong = proven and confidence >= rules["strong_min_confidence"] and (has_call or not rules["strong_requires_call"])
    if direction == "up":
        return TIER_STRONG_BUY if strong else TIER_BUY
    return TIER_STRONG_SELL if strong else TIER_SELL


def drivers(contributions: dict | None, direction: str | None, limit: int) -> list[str]:
    """The score's own top drivers on the side of `direction` (explain.py texts)."""
    side = "up" if direction == "up" else "down"
    items = (contributions or {}).get(side) or []
    return [item["text"] for item in items[:limit] if item.get("text")]


def proof_note(cell: dict | None, settings: dict) -> str:
    """One short sentence on the cell's proof."""
    if cell is None:
        return "confidence outside the proof bands"
    if cell["proven"]:
        return f"proven: {cell['hits']}/{cell['n']} hits in band {cell['band']}, Wilson low {cell['wilson_low']}"
    need = settings["proof"]["min_count"]
    return f"not proven: band {cell['band']} has {cell['n']} scored calls (needs {need} and a positive skill review)"


def signal_row(score: dict, call: dict | None, band_range: dict | None, block: dict | None, proof: dict,
               settings: dict) -> dict:
    """The tier row of one score."""
    model_prob = float(score["prob_up"])
    final, adjustment = final_probability(model_prob, call)
    direction = (call or {}).get("direction") or ("up" if final > 0.5 else "down" if final < 0.5 else None)
    confidence = round(max(final, 1 - final), PROB_DIGITS)   # rounded first: 1 - 0.35 is 0.6499999999999999
    label = resolved_label(score["horizon_days"], score.get("horizon_label"), score.get("computed_at"))
    cell = proofs.cell(proof, int(score["horizon_days"]), proofs.band_of(confidence, settings["proof"]["bands"])) \
        if label == LABEL_N_PLUS_K else None
    cell_proven = bool(cell and cell["proven"])
    proven = cell_proven and call is not None   # a model-only row stays paper only, even in a proven cell
    why_blocked = blocked_reason(block, settings)
    tier = TIER_HOLD if why_blocked else tier_for(direction, confidence, cell_proven, call is not None, settings)
    reasons = [f"model P(up) {model_prob:.2f} (base rate {float(score['base_rate']):.2f})"]
    if call:
        reasons.append(f"forecaster: {call['direction']} at {float(call['confidence']):.2f}"
                       + (f", adjustment {adjustment:+.2f}" if adjustment else ""))
    if band_range:
        reasons.append(f"80% range {band_range['lo80']:.2f}-{band_range['hi80']:.2f} by {band_range['target_date']}")
    reasons.append(why_blocked or proof_note(cell, settings))
    return {"id": score["id"], "ticker": score["ticker"], "horizon_days": int(score["horizon_days"]),
            "horizon_label": label, "tier": tier,
            "direction": None if tier == TIER_HOLD and why_blocked else direction,
            "model_prob": round(model_prob, PROB_DIGITS), "agent_adjustment": adjustment,
            "final_prob": round(final, PROB_DIGITS), "confidence": confidence,
            "has_call": call is not None, "range": band_range, "band": cell["band"] if cell else None,
            "proven": proven, "paper_only": not proven, "label": LABEL_PROVEN if proven else LABEL_PAPER_ONLY,
            "blocked": why_blocked, "reasons": reasons,
            "drivers": drivers(score["contributions"], direction, settings["tiers"]["max_reasons"])}


def candidates(rows: list[dict], scores: dict[str, dict], settings: dict) -> list[dict]:
    """Up to tiers.max_candidates Paper candidates, the farthest model_prob from 0.5 first."""
    open_rows = [row for row in rows if not row["blocked"] and row["model_prob"] != 0.5]
    ranked = sorted(open_rows, key=lambda row: (-abs(row["model_prob"] - 0.5), row["ticker"], row["horizon_days"]))
    out = []
    for row in ranked[:settings["tiers"]["max_candidates"]]:
        side = "up" if row["model_prob"] > 0.5 else "down"
        out.append({"id": row["id"], "ticker": row["ticker"], "horizon_days": row["horizon_days"], "direction": side,
                    "model_prob": row["model_prob"], "distance": round(abs(row["model_prob"] - 0.5), PROB_DIGITS),
                    "tier": row["tier"], "paper_only": True, "label": LABEL_PAPER_ONLY,
                    "reasons": drivers(scores[row["id"]]["contributions"], side, settings["tiers"]["max_reasons"])
                    or ["no feature driver listed (the calibration shrank the score to the base rate)"]})
    return out


def unscored_rows(cfg: dict, as_of, scored: set[tuple[str, int]]) -> list[dict]:
    """Hold/No call rows for every watchlist ticker x horizon with no model score on the as-of date."""
    out = []
    for ticker in active_tickers(cfg):
        for horizon in horizons():
            if (ticker, horizon) in scored:
                continue
            out.append({"id": f"{as_of}-{ticker}-{horizon}d" if as_of else None, "ticker": ticker,
                        "horizon_days": horizon, "tier": TIER_HOLD, "direction": None, "model_prob": None,
                        "agent_adjustment": None, "final_prob": None, "confidence": None, "has_call": False,
                        "range": None, "band": None, "proven": False, "paper_only": True, "label": LABEL_PAPER_ONLY,
                        "blocked": MSG_NO_SCORE, "reasons": [MSG_NO_SCORE], "drivers": []})
    return out


def cockpit_payload(con, clock, market: str, settings: dict) -> dict:
    """Per market: proof status, the tier per ticker and horizon, Paper candidates and the as-of date."""
    proof = proofs.proof_status(con, clock, settings)
    scores = inputs.scores_on_latest_date(con, clock)
    as_of = scores["as_of_date"].iloc[0] if not scores.empty else None
    records = scores.to_dict("records")
    ids = [score["id"] for score in records]
    calls, ranges = inputs.calls_by_id(con, clock, ids), inputs.ranges_by_id(con, clock, ids)
    blocks = inputs.feature_blocks(con, clock, as_of) if as_of else {}
    rows = [signal_row(score, calls.get(score["id"]), ranges.get(score["id"]), blocks.get(score["ticker"]), proof,
                       settings) for score in records]
    rows += unscored_rows(load_market(market), as_of, {(s["ticker"], int(s["horizon_days"])) for s in records})
    rows.sort(key=lambda row: (row["ticker"], row["horizon_days"]))
    strong = [row for row in rows if row["tier"] in STRONG_TIERS]
    proven = proof["status"] == proofs.PROOF_PROVEN
    return {"market": market, "as_of_date": as_of.isoformat() if as_of else None, "computed_at": clock.isoformat(),
            "proof": proof, "paper_only": not proven, "label": LABEL_PROVEN if proven else LABEL_PAPER_ONLY,
            "strong_count": len(strong), "headline": None if strong else MSG_NO_STRONG, "tiers": rows,
            "candidates": [] if strong else candidates(rows, {s["id"]: s for s in records}, settings)}
