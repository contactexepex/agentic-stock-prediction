"""prepare: build the as-of scratch root, its context pack and ranges."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
from marketbrief.core import calendar, paths
from marketbrief.core.database import connect
from marketbrief.core.market_config import benchmark_key
from marketbrief.core.storage import append_jsonl
from marketbrief.constants.ai_replay import CONTAMINATED, CUTOFF_LOCAL, FAIR, MARKER
from marketbrief.replay.ai_replay.copy_asof import copy_asof
from marketbrief.replay.ai_replay.cutoff import cutoff_for, leakage_label, next_session, training_cutoff
from marketbrief.replay.ai_replay.evidence import evidence, evidence_section
from marketbrief.replay.ai_replay.roots import check_root, data_root, json_or_text, run_step


def assumed_earnings(cfg: dict, src: Path, d: date, cutoff: datetime, days: int) -> list[dict]:
    """ASSUMPTION (opt-in, --assume-earnings-known DAYS): the actual earnings dates in (D, D + DAYS]
    from the source's backfilled past events (event_history.earnings_events over every *_history row,
    i.e. with today's knowledge) are treated as announced before the cutoff, as replay.py treats past
    event dates. Stored rows do not say when a date was first announced (companies usually announce
    2-4 weeks ahead), so this is labelled in the event name, the source and the prepare summary."""
    from marketbrief.analytics import event_history
    with data_root(src):
        evdf = event_history.load_events(connect(cfg["market"]))
    if evdf.empty:
        return []
    out = []
    for t, evs in event_history.earnings_events(evdf).items():
        if t not in cfg["tickers"]:
            continue
        for day, timing in evs:
            if d < day <= d + timedelta(days=days):
                name = cfg["tickers"][t].get("name", t)
                out.append({"id": f"{t}-earnings-{day}-assumed", "date": str(day), "type": "earnings", "ticker": t,
                            "name": f"{name} earnings (ASSUMED known in advance: actual date from later data)",
                            "source": "assumed_known", "first_seen_at": cutoff.isoformat(), "timing": timing})
                break
    return out


def prepare(cfg: dict, d: date, root: Path, src: Path | None = None, force: bool = False,
            allow_training_period: bool = False, assume_earnings_days: int = 0) -> dict:
    market = cfg["market"]
    src = Path(src or paths.ROOT)
    model_cut = training_cutoff()
    if leakage_label(d, model_cut) == CONTAMINATED and not allow_training_period:
        raise SystemExit(f"{d} is on or before the model's training cutoff {model_cut} (config/settings.yaml "
                         "model_training_cutoff): contaminated, not a fair test. "
                         "Pass --allow-training-period to prepare it anyway.")
    if not calendar.is_session(cfg, d):
        raise SystemExit(f"{d} is not a {market} trading day")
    check_root(root, src, force)
    session, cutoff = next_session(cfg, d), cutoff_for(cfg, d)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text(f"{market} {d}\n")
    shutil.copytree(paths.CONFIG, root / "config")
    for name in ("sql", "templates"):
        if (paths.CODE / name).exists():
            shutil.copytree(paths.CODE / name, root / name)
    copied = copy_asof(market, src, root, d, cutoff)
    assumed = assumed_earnings(cfg, src, d, cutoff, assume_earnings_days) if assume_earnings_days else []
    if assumed:
        path = root / "data" / market / "events" / f"{cutoff:%Y}" / f"{cutoff:%m}" / f"{cutoff:%Y-%m-%d}.assumed.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(path, assumed)
    bench = benchmark_key(cfg)
    with data_root(root):
        last = connect(market).execute("SELECT max(date) FROM ohlc WHERE ticker = ?", [bench]).fetchone()[0]
    if last is None or pd.Timestamp(last).date() != d:
        raise SystemExit(f"no {bench} bar dated {d} in {src} (latest kept: {last})")
    now = cutoff.isoformat()
    steps = {"features": json_or_text(run_step("features.py", root, market, now)),
             "calibrate": json_or_text(run_step("calibrate.py", root, market, now))}
    ctx = root / "work" / "context.md"
    run_step("context.py", root, market, now, stdout=ctx)
    steps["ranges"] = json_or_text(run_step("ranges.py", root, market, now, "--now", now))
    ev_df, counts = evidence(market, root, cutoff)
    with ctx.open("a", encoding="utf-8") as f:
        f.write("\n" + evidence_section(ev_df, cutoff))
    text = ctx.read_text(encoding="utf-8")
    if isinstance(steps["calibrate"], dict):   # keep the summary short
        steps["calibrate"] = {"calibration": [{k: c.get(k) for k in ("horizon_days", "source", "n_history", "n_live")}
                                              for c in steps["calibrate"].get("calibration", [])]}
    out = {
        "step": "ai_replay.prepare", "market": market, "as_of_date": str(d), "session_date": str(session),
        "cutoff_utc": now, "cutoff_rule": ("routine start on the next session, exchange time "
                                           f"{CUTOFF_LOCAL.get(market, 'open - 75 min')}"),
        "fair_test": leakage_label(d, model_cut) == FAIR, "test": leakage_label(d, model_cut),
        "model_training_cutoff": str(model_cut), "source_root": str(src), "root": str(root),
        "context_pack": {"path": str(ctx), "bytes": len(text.encode("utf-8")), "lines": text.count("\n"),
                         "approx_tokens": round(len(text) / 4), "sha256": hashlib.sha256(text.encode()).hexdigest()},
        "citable_evidence": counts,
        "assumptions": ([f"ASSUMED: {len(assumed)} actual earnings dates within {assume_earnings_days} days after D "
                         "treated as announced before the cutoff (--assume-earnings-known): "
                         + ", ".join(f"{a['ticker']} {a['date']}" for a in assumed)] if assume_earnings_days else [])
                       + (["ASSUMED: bulk/block deals dated <= D were public before the cutoff (NSE publishes "
                           "them after the close)"] if copied["kinds"].get("deals", {}).get("rows_kept") else []),
        "upcoming_earnings": upcoming(root, market, d),
        "included": copied["kinds"], "excluded": copied["excluded"],
        "not_copied": ["summaries/ (written live with later knowledge)", "reports/"],
        "steps": steps,
        "limitations": limitations(copied, counts),
        "prepared_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    (root / "ai_replay.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out


def upcoming(root: Path, market: str, d: date) -> dict:
    """The as-of indicator snapshot's earnings view: tickers with days_to_earnings, those <= 1 (no call
    allowed) and BLOCKED tickers."""
    with data_root(root):
        f = connect(market).execute("SELECT ticker, quality, days_to_earnings FROM features_latest "
                                    "WHERE as_of_date = ? ORDER BY ticker", [d]).df()
    known = f[f["days_to_earnings"].notna()]
    return {"with_days_to_earnings": {r.ticker: int(r.days_to_earnings) for r in known.itertuples()},
            "earnings_within_1_day": sorted(known.loc[known["days_to_earnings"] <= 1, "ticker"]),
            "blocked": sorted(f.loc[f["quality"] == "BLOCKED", "ticker"])}


def limitations(copied: dict, counts: dict) -> list[str]:
    k = copied["kinds"]
    out = [f"No news: stored news starts {copied['first_news_file']} (live collection only), so the news-analyst "
           "has nothing to read and calls can cite only SEC filings (US) or NSE announcements (India).",
           "No overnight quotes before live collection: cue_change_pct is empty and the vol-index level is the "
           "last close, not the pre-open quote.",
           "Upcoming earnings and ex-dividend dates first seen after the cutoff are dropped, so days_to_earnings "
           "is empty unless such a row was stored before the cutoff; the earnings-day block can then not apply.",
           "Price bars are as stored: history downloaded after a split is already on the post-split basis; "
           "splits recorded in data/<market>/adjustments/ apply in the root only when their ex-date is on or before D.",
           "The model's own memory is the remaining risk: only as-of dates after "
           f"{training_cutoff()} (model_training_cutoff) are treated as a fair test; earlier ones are "
           "labelled contaminated and scored separately."]
    if counts["total"] == 0:
        out.insert(0, "No citable evidence ids at all as of the cutoff: under the CLAUDE.md rule (evidence_ids "
                      "required) the forecaster can only abstain.")
    if not k.get("prices", {}).get("rows_kept"):
        out.insert(0, "No price bars kept.")
    return out
