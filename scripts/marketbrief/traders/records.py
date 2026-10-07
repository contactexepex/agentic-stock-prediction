"""The stored rows of the traders (core/schema_lab.py): a `strategy_predictions` row from a record that passed the gate,
and `strategy_abstentions` rows. Every column but the trader's own fields is derived from stored data, never copied
from the agent."""
from __future__ import annotations

import math
from datetime import date, datetime

from marketbrief.constants.range_publication import ROUND_PRICE
from marketbrief.traders.constants import METHOD_VERSION, PROB_DECIMALS
from marketbrief.traders.registry import Trader

EDGES = ("lo50", "hi50", "lo80", "hi80")


def prediction_id(strategy_id: str, as_of: date, ticker: str, horizon: int) -> str:
    """<strategy_id>:<as_of_date>-<ticker>-<k>d (F2.6)."""
    return f"{strategy_id}:{as_of}-{ticker}-{horizon}d"


def horizon_id(as_of: date, ticker: str, horizon: int) -> str:
    """<as_of_date>-<ticker>-<k>d: the id of the published range and the model score."""
    return f"{as_of}-{ticker}-{horizon}d"


def abstention_id(strategy_id: str, as_of: date | str, ticker: str) -> str:
    """<strategy_id>:<as_of_date>-<ticker>."""
    return f"{strategy_id}:{as_of}-{ticker}"


def widened(rng: dict, widen: float) -> dict[str, float]:
    """The range's band edges with its sigma times (1 + widen) around the same centre, as range_row.py widens an AI
    call's range: edge = base x exp(centre + (ln(edge / base) - centre) x (1 + widen)). widen 0 = the published
    edges. Only ever wider (widen >= 0)."""
    base, center = float(rng["base_close"]), float(rng["center"])
    out = {}
    for edge in EDGES:
        published = float(rng[edge])
        if widen == 0:
            out[edge] = published
            continue
        out[edge] = round(base * math.exp(center + (math.log(published / base) - center) * (1 + widen)), ROUND_PRICE)
    return out


def prediction_row(rec: dict, one: Trader, frame: dict, made_at: datetime) -> dict:  # noqa: PLR0913 - one row's parts
    """The stored row. frame: the gate's derived values (as_of, session, exit, range, edges, score, regime, quality,
    amount, currency, confidence, widen)."""
    prob = round(float(rec["prob_up"]), PROB_DECIMALS)
    score = frame["score"]
    anchored = one.sees_model_score and score is not None
    return {
        "id": prediction_id(one.strategy_id, frame["as_of"], rec["ticker"], rec["horizon_days"]),
        "strategy_id": one.strategy_id, "family": "ai", "market": frame["market"], "ticker": rec["ticker"],
        "made_at": made_at.isoformat().replace("+00:00", "Z"), "as_of_date": str(frame["as_of"]),
        "session_date": str(frame["session"]), "exit_date": str(frame["exit"]), "horizon_days": rec["horizon_days"],
        "direction": rec["direction"], "prob_up": prob, "confidence": frame["confidence"],
        "threshold": one.threshold, "qualifies": rec["direction"] == "up" and prob >= one.threshold,
        "base_close": float(frame["range"]["base_close"]), "target_price": float(rec["target_price"]),
        "range_id": frame["range"]["id"], **frame["edges"], "range_widen": frame["widen"],
        "model_score_id": score["id"] if anchored else None,
        "model_prob": float(rec["model_prob"]) if anchored else None,
        "agent_adjustment": float(rec["agent_adjustment"]) if anchored else None,
        "adjustment_reason": (rec.get("adjustment_reason") or None) if anchored else None,
        "evidence_ids": list(rec["evidence_ids"]), "reason": rec["reason"].strip(), "regime": frame["regime"],
        "quality": frame["quality"], "amount": frame["amount"], "currency": frame["currency"],
        "config_hash": one.config_hash, "prompt_version": one.prompt_version, "method_version": METHOD_VERSION,
    }


def abstention_row(one: Trader, frame: dict, ticker: str, horizons: list[int], how: dict) -> dict:
    """One strategy_abstentions row. frame: market, as_of, session, made_at (ISO); how: reason_code, reason,
    gate_codes, attempts."""
    return {
        "id": abstention_id(one.strategy_id, frame["as_of"], ticker), "strategy_id": one.strategy_id, "family": "ai",
        "market": frame["market"], "ticker": ticker, "made_at": frame["made_at"], "as_of_date": str(frame["as_of"]),
        "session_date": str(frame["session"]), "horizons": sorted(horizons), "reason_code": how["reason_code"],
        "reason": how.get("reason"), "gate_codes": sorted(set(how.get("gate_codes") or [])),
        "attempts": how.get("attempts", 1), "prompt_version": one.prompt_version,
    }
