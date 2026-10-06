"""Deterministic facts of settled calls for the reflection log: outcome, range position, evidence."""
from __future__ import annotations

import math
import pandas as pd
from marketbrief.pipeline.score_predictions import is_late
from marketbrief.constants.lessons import RANGE_SQL, SETTLED_SQL


def iso_utc_text(v) -> str | None:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    t = pd.Timestamp(v)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).isoformat()


def date_text(v) -> str | None:
    return None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)[:10]


def float_or_none(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def position(y: float, lo80: float, lo50: float, hi50: float, hi80: float) -> str:
    """Where the close landed against the published bands."""
    if y < lo80:
        return "below_80"
    if y < lo50:
        return "in_80_below_50"
    if y <= hi50:
        return "in_50"
    if y <= hi80:
        return "in_80_above_50"
    return "above_80"


def settled(cfg: dict, con) -> dict[str, dict]:
    """prediction_id -> deterministic lesson facts, for every call with a stored outcome. A call whose
    range is open (published, not late, not scored) maps to None: it waits for the range."""
    out = {}
    for r in con.execute(SETTLED_SQL).df().itertuples(index=False):
        rec = {"id": f"lesson-{r.id}", "prediction_id": r.id, "ticker": r.ticker, "horizon_days": int(r.horizon_days),
               "as_of_date": date_text(r.as_of_date), "made_at": iso_utc_text(r.made_at), "direction": r.direction,
               "confidence": float_or_none(r.confidence), "rationale": r.rationale,
               "evidence_ids": [str(x) for x in (r.evidence_ids if r.evidence_ids is not None else [])],
               "call_prompt_version": r.prompt_version, "base_date": date_text(r.base_date),
               "base_close": float_or_none(r.base_close), "target_date": date_text(r.target_date),
               "target_close": float_or_none(r.target_close), "actual_return": float_or_none(r.actual_return), "hit": bool(r.hit),
               "range_id": None, "range_target_date": None, "range_actual_close": None, "lo80": None, "lo50": None,
               "hi50": None, "hi80": None, "hit50": None, "hit80": None, "range_position": None,
               "settled_at": iso_utc_text(r.scored_at), "available_from": iso_utc_text(r.scored_at)}
        rg = con.execute(RANGE_SQL, [r.id]).df()
        if len(rg):
            g = rg.iloc[0]
            if g["scored_at"] is None or pd.isna(g["scored_at"]):
                if not is_late(cfg, g["as_of_date"], g["made_at"]):
                    out[r.id] = None        # its range is still open: wait so the lesson can cite it
                    continue
            else:
                y = float(g["actual_close"])
                rec.update({"range_id": g["id"], "range_target_date": date_text(g["target_date"]), "range_actual_close": y,
                            "lo80": float(g["lo80"]), "lo50": float(g["lo50"]), "hi50": float(g["hi50"]),
                            "hi80": float(g["hi80"]), "hit50": bool(g["hit50"]), "hit80": bool(g["hit80"]),
                            "range_position": position(y, g["lo80"], g["lo50"], g["hi50"], g["hi80"]),
                            "available_from": max(pd.Timestamp(rec["settled_at"]),
                                                  pd.Timestamp(iso_utc_text(g["scored_at"]))).isoformat()})
        out[r.id] = rec
    return out


def stored_ids(con) -> set[str]:
    return set(con.execute("SELECT DISTINCT id FROM lessons").df()["id"])


def evidence(con, ids: list[str]) -> list[dict]:
    """What each cited id said (title/description), for the reflector to read; not stored."""
    if not ids:
        return []
    rows = con.execute("""
        SELECT * FROM (SELECT id, 'news' AS kind, title AS text, published_at AS at FROM news WHERE list_contains(?, id)
        UNION ALL SELECT id, 'filing', form || ': ' || coalesce(description, ''), accepted_at FROM filings
            WHERE list_contains(?, id)
        UNION ALL SELECT id, 'announcement', coalesce(category, '') || ': ' || coalesce(subject, ''), published_at
            FROM announcements WHERE list_contains(?, id)
        ) ORDER BY id, kind = 'announcement', kind = 'filing', "at", text""", [ids, ids, ids]).df()
    first: dict[str, dict] = {}   # per id the news row, else the filing, else the announcement (ORDER BY)
    for r in rows.itertuples(index=False):
        first.setdefault(r.id, {"id": r.id, "kind": r.kind, "text": r.text, "at": iso_utc_text(r.at)})
    return [first.get(i, {"id": i, "kind": "unknown", "text": None, "at": None}) for i in dict.fromkeys(ids)]
