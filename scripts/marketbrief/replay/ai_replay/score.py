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
    sd = Path(results) / cfg["market"]
    calls, days = read_jsonl(sd / "calls.jsonl"), read_jsonl(sd / "days.jsonl")
    if not days:
        raise SystemExit(f"nothing recorded in {sd}")
    bars = load_bars(connect(cfg["market"]))
    s = summarize(cfg, calls, days, bars)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_page(s), encoding="utf-8")
    js = out.with_suffix(".json")
    js.write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    return {"step": "ai_replay.score", "market": cfg["market"], "html": str(out), "json": str(js),
            "model_training_cutoff": s["model_training_cutoff"], "rule": s["rule"],
            **{label: {"n_days": g["n_days"], "n_calls": g["n_calls"], "n_scored": g["n_scored"],
                       "n_pending": g["n_pending"], "overall": {k: g["overall"].get(k) for k in ("n", "hit_rate", "ci95")},
                       "abstention": g["abstention"], "top": g["top"]}
               for label, g in ((FAIR, s[FAIR]), (CONTAMINATED, s[CONTAMINATED]))}}
