"""score: score the recorded calls on real closes and write the page and JSON."""

from __future__ import annotations

import json
from pathlib import Path
from marketbrief.core.database import connect
from marketbrief.analytics.features import load_bars
from marketbrief.constants.ai_replay import CONTAMINATED, FAIR
from marketbrief.replay.ai_replay.ai_html import html_page
from marketbrief.replay.ai_replay.record import read_jsonl
from marketbrief.replay.ai_replay.summaries import summarize


def score(cfg: dict, results: Path, out: Path) -> dict:
    store_directory = Path(results) / cfg["market"]
    calls, days = read_jsonl(store_directory / "calls.jsonl"), read_jsonl(store_directory / "days.jsonl")
    if not days:
        raise SystemExit(f"nothing recorded in {store_directory}")
    bars = load_bars(connect(cfg["market"]))
    summary = summarize(cfg, calls, days, bars)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_page(summary), encoding="utf-8")
    json_path = out.with_suffix(".json")
    json_path.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return {
        "step": "ai_replay.score",
        "market": cfg["market"],
        "html": str(out),
        "json": str(json_path),
        "model_training_cutoff": summary["model_training_cutoff"],
        "rule": summary["rule"],
        **{
            label: {
                "n_days": group["n_days"],
                "n_calls": group["n_calls"],
                "n_scored": group["n_scored"],
                "n_pending": group["n_pending"],
                "overall": {key: group["overall"].get(key) for key in ("n", "hit_rate", "ci95")},
                "abstention": group["abstention"],
                "top": group["top"],
            }
            for label, group in ((FAIR, summary[FAIR]), (CONTAMINATED, summary[CONTAMINATED]))
        },
    }
