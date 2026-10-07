"""record: validate forecaster calls against the replay root and store them."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from marketbrief.analytics.prediction_rules import RuleLabels, check_news_status, check_prediction
from marketbrief.constants.ai_replay import (
    MARKER,
    MSG_DAY_ALREADY_RECORDED,
    MSG_NOT_A_PREPARED_ROOT,
    MSG_NOT_JSON,
    MSG_ROOT_PREPARED_FOR_OTHER_DAY,
)
from marketbrief.core.clock import utc_now
from marketbrief.core.database import connect
from marketbrief.core.storage import append_jsonl
from marketbrief.pipeline.evidence_status import EvidenceStatuses
from marketbrief.replay.ai_replay.cutoff import leakage_label, training_cutoff
from marketbrief.replay.ai_replay.evidence import evidence
from marketbrief.replay.ai_replay.roots import data_root


def store_dir(results: Path, market: str) -> Path:
    """The results folder of a market (created when missing)."""
    directory = Path(results) / market
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def read_jsonl(path: Path) -> list[dict]:
    """The rows of a JSONL file, or an empty list when it is missing."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def replay_context(cfg: dict, root: Path, as_of_day: date) -> dict:
    """What the forecaster saw in the prepared root: snapshot quality, earnings, citable ids."""
    meta_path = root / "ai_replay.json"
    if not (root / MARKER).exists() or not meta_path.exists():
        raise SystemExit(MSG_NOT_A_PREPARED_ROOT.format(root=root))
    meta = json.loads(meta_path.read_text())
    if meta["market"] != cfg["market"] or meta["as_of_date"] != str(as_of_day):
        raise SystemExit(
            MSG_ROOT_PREPARED_FOR_OTHER_DAY.format(
                root=root,
                prepared_market=meta["market"],
                prepared_as_of_date=meta["as_of_date"],
                requested_market=cfg["market"],
                requested_as_of_day=as_of_day,
            )
        )
    with data_root(root):
        con = connect(cfg["market"])
        feats = con.execute(
            "SELECT ticker, quality, days_to_earnings FROM features_latest WHERE as_of_date = ?", [as_of_day]
        ).df()
        statuses = EvidenceStatuses(con)  # issue #39: the daily gate's news-status rules, as of the cutoff
        status_rules = statuses.active(meta["cutoff_utc"])
        if status_rules:
            statuses.preload(meta["cutoff_utc"])
    evidence_frame, _ = evidence(cfg["market"], root, datetime.fromisoformat(meta["cutoff_utc"]))
    return {
        "meta": meta,
        "features": {
            row.ticker: {
                "quality": row.quality,
                "days_to_earnings": None if pd.isna(row.days_to_earnings) else int(row.days_to_earnings),
            }
            for row in feats.itertuples()
        },
        "evidence": set(evidence_frame["id"]),
        "tickers": set(cfg["tickers"]),
        "statuses": statuses if status_rules else None,
    }


def validate(rec, ctx: dict, as_of_day: date, seen: set[str]) -> list[str]:
    """Reasons a forecaster record breaks the schema or the CLAUDE.md prediction rules (empty = valid):
    the shared check in prediction_rules.py, with the replay date as every ticker's as_of_date, then (when the
    root holds status rows by the cutoff) the daily gate's news-verification rules, each cited id's status as
    of the cutoff (the record's made_at once stored; issue #39)."""
    errs = check_prediction(
        rec,
        ctx,
        seen,
        as_of=as_of_day,
        labels=RuleLabels("the replay date", "the replay root's news/filings/announcements"),
    )
    statuses = ctx.get("statuses")
    if errs or statuses is None:
        return errs
    cutoff = ctx["meta"]["cutoff_utc"]
    found = [statuses.of(evidence_id, rec["ticker"], cutoff) for evidence_id in rec["evidence_ids"]]
    return [f"{code}: {reason}" for code, reason in check_news_status(rec, found)]


def record(cfg: dict, as_of_day: date, root: Path, calls_file: Path, results: Path) -> dict:
    """Validate the forecaster's calls and store the valid ones with the day's record."""
    market = cfg["market"]
    ctx = replay_context(cfg, root, as_of_day)
    store_directory = store_dir(results, market)
    days = read_jsonl(store_directory / "days.jsonl")
    if any(stored["date"] == str(as_of_day) for stored in days):
        raise SystemExit(
            MSG_DAY_ALREADY_RECORDED.format(market=market, as_of_day=as_of_day, store_directory=store_directory)
        )
    seen = {stored["id"] for stored in read_jsonl(store_directory / "calls.jsonl")}
    raw = (
        [stored for stored in calls_file.read_text(encoding="utf-8").splitlines() if stored.strip()]
        if calls_file.exists()
        else []
    )
    now, cutoff = utc_now(), ctx["meta"]["cutoff_utc"]
    model_cut = training_cutoff()
    label = leakage_label(as_of_day, model_cut)
    good, bad = [], []
    for index, line in enumerate(raw, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as error:
            bad.append({"line": index, "id": None, "reasons": [MSG_NOT_JSON.format(error=error)]})
            continue
        errs = validate(rec, ctx, as_of_day, seen)
        if errs:
            bad.append({"line": index, "id": rec.get("id") if isinstance(rec, dict) else None, "reasons": errs})
            continue
        seen.add(rec["id"])
        good.append(
            {
                **rec,
                "agent_made_at": rec.get("made_at"),
                "made_at": cutoff,
                "market": market,
                "replay": True,
                "recorded_at": now,
                "test": label,
                "model_training_cutoff": str(model_cut),
                "context_sha256": ctx["meta"]["context_pack"]["sha256"],
            }
        )
    append_jsonl(store_directory / "calls.jsonl", good)
    append_jsonl(
        store_directory / "rejected.jsonl",
        [{**rejected, "market": market, "date": str(as_of_day), "recorded_at": now} for rejected in bad],
    )
    eligible = sorted(
        ticker
        for ticker, feature in ctx["features"].items()
        if ticker in ctx["tickers"]
        and feature["quality"] != "BLOCKED"
        and not (feature["days_to_earnings"] is not None and feature["days_to_earnings"] <= 1)
    )
    day_record = {
        "market": market,
        "date": str(as_of_day),
        "test": label,
        "model_training_cutoff": str(model_cut),
        "session_date": ctx["meta"]["session_date"],
        "cutoff_utc": cutoff,
        "root": str(root),
        "n_tickers": len(ctx["tickers"]),
        "eligible": eligible,
        "n_calls": len(good),
        "n_rejected": len(bad),
        "prompt_versions": sorted({accepted["prompt_version"] for accepted in good}),
        "recorded_at": now,
        "citable_ids": ctx["meta"]["citable_evidence"]["total"],
        "news_status_rules": ctx.get("statuses") is not None,
    }
    append_jsonl(store_directory / "days.jsonl", [day_record])
    return {
        "step": "ai_replay.record",
        "market": market,
        "date": str(as_of_day),
        "test": label,
        "results": str(store_directory),
        "recorded": len(good),
        "rejected": bad,
        "eligible_tickers": len(eligible),
    }
