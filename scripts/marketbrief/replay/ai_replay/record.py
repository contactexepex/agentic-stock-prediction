"""record: validate forecaster calls against the replay root and store them."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
import pandas as pd
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl
from marketbrief.analytics.prediction_rules import RuleLabels, check_prediction
from marketbrief.constants.ai_replay import MARKER
from marketbrief.replay.ai_replay.cutoff import leakage_label, training_cutoff
from marketbrief.replay.ai_replay.evidence import evidence
from marketbrief.replay.ai_replay.roots import data_root


def store_dir(results: Path, market: str) -> Path:
    p = Path(results) / market
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def replay_context(cfg: dict, root: Path, d: date) -> dict:
    """What the forecaster saw in the prepared root: snapshot quality, earnings, citable ids."""
    meta_path = root / "ai_replay.json"
    if not (root / MARKER).exists() or not meta_path.exists():
        raise SystemExit(f"{root} is not a prepared ai_replay root (run prepare first)")
    meta = json.loads(meta_path.read_text())
    if meta["market"] != cfg["market"] or meta["as_of_date"] != str(d):
        raise SystemExit(f"{root} was prepared for {meta['market']} {meta['as_of_date']}, not {cfg['market']} {d}")
    with data_root(root):
        con = connect(cfg["market"])
        feats = con.execute("SELECT ticker, quality, days_to_earnings FROM features_latest WHERE as_of_date = ?",
                            [d]).df()
    ev_df, _ = evidence(cfg["market"], root, datetime.fromisoformat(meta["cutoff_utc"]))
    return {"meta": meta, "features": {r.ticker: {"quality": r.quality,
                                                  "days_to_earnings": None if pd.isna(r.days_to_earnings) else int(r.days_to_earnings)}
                                       for r in feats.itertuples()},
            "evidence": set(ev_df["id"]), "tickers": set(cfg["tickers"])}


def validate(rec, ctx: dict, d: date, seen: set[str]) -> list[str]:
    """Reasons a forecaster record breaks the schema or the CLAUDE.md prediction rules (empty = valid):
    the shared check in prediction_rules.py, with the replay date as every ticker's as_of_date."""
    return check_prediction(rec, ctx, seen, as_of=d,
                            labels=RuleLabels("the replay date", "the replay root's news/filings/announcements"))


def record(cfg: dict, d: date, root: Path, calls_file: Path, results: Path) -> dict:
    market = cfg["market"]
    ctx = replay_context(cfg, root, d)
    sd = store_dir(results, market)
    days = read_jsonl(sd / "days.jsonl")
    if any(x["date"] == str(d) for x in days):
        raise SystemExit(f"{market} {d} is already recorded in {sd}; use a new --results directory to re-run it")
    seen = {x["id"] for x in read_jsonl(sd / "calls.jsonl")}
    raw = [x for x in calls_file.read_text(encoding="utf-8").splitlines() if x.strip()] if calls_file.exists() else []
    now, cutoff = utc_now(), ctx["meta"]["cutoff_utc"]
    model_cut = training_cutoff()
    label = leakage_label(d, model_cut)
    good, bad = [], []
    for i, line in enumerate(raw, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            bad.append({"line": i, "id": None, "reasons": [f"not JSON: {e}"]})
            continue
        errs = validate(rec, ctx, d, seen)
        if errs:
            bad.append({"line": i, "id": rec.get("id") if isinstance(rec, dict) else None, "reasons": errs})
            continue
        seen.add(rec["id"])
        good.append({**rec, "agent_made_at": rec.get("made_at"), "made_at": cutoff, "market": market,
                     "replay": True, "recorded_at": now, "test": label, "model_training_cutoff": str(model_cut),
                     "context_sha256": ctx["meta"]["context_pack"]["sha256"]})
    append_jsonl(sd / "calls.jsonl", good)
    append_jsonl(sd / "rejected.jsonl", [{**b, "market": market, "date": str(d), "recorded_at": now}
                                                for b in bad])
    eligible = sorted(t for t, f in ctx["features"].items() if t in ctx["tickers"] and f["quality"] != "BLOCKED"
                      and not (f["days_to_earnings"] is not None and f["days_to_earnings"] <= 1))
    day = {"market": market, "date": str(d), "test": label, "model_training_cutoff": str(model_cut),
           "session_date": ctx["meta"]["session_date"], "cutoff_utc": cutoff,
           "root": str(root), "n_tickers": len(ctx["tickers"]), "eligible": eligible,
           "n_calls": len(good), "n_rejected": len(bad),
           "prompt_versions": sorted({g["prompt_version"] for g in good}), "recorded_at": now,
           "citable_ids": ctx["meta"]["citable_evidence"]["total"]}
    append_jsonl(sd / "days.jsonl", [day])
    return {"step": "ai_replay.record", "market": market, "date": str(d), "test": label, "results": str(sd),
            "recorded": len(good), "rejected": bad, "eligible_tickers": len(eligible)}
