"""Weekly review for one market (docs/DESIGN.md sections 6, 7 and 10 phase 4): what improved
coverage, what to drop.

From stored range outcomes, scored calls and calibration, for the review week, a rolling
window and since start (all by target date, never past the week's end):
- 50%/80% coverage vs target, interval score and width vs the naive baseline, by horizon,
  regime, sector and widening note;
- direction hit rate vs the always-up baseline, overall and by confidence band;
- ablation of each range input: (a) replay of the stored live scored ranges with one input
  changed (cue, AI drift, AI widening, earnings/event/regime widening, centre cap), and
  (b) walk-forward on stored prices (backtest.py) for the width parameters and the regime and
  event widening rebuilt from stored bars.
Thresholds and variants live in config/review.yaml. Small samples are flagged and get no
proposal. Proposed config/ranges.yaml changes are written to the report, never applied.
Appends a record to data/<market>/reviews/ and writes reports/<market>/review-YYYY-Www.md."""
from __future__ import annotations

import json
from datetime import date, timedelta
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.database import connect
from marketbrief.core.market_config import load_ranges_config
from marketbrief.core import paths
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.analytics.features import load_bars
from marketbrief.constants.review import DEFAULTS
from marketbrief.pipeline.review.aci_review import aci_proposal, aci_state, latest_aci_replay
from marketbrief.pipeline.review.helpers import clean, load_review_config, previous_week, week_bounds
from marketbrief.pipeline.review.history_ablation import history_ablation
from marketbrief.pipeline.review.live_ablation import live_ablation
from marketbrief.pipeline.review.markdown import markdown
from marketbrief.pipeline.review.summaries import breakdown, by_horizon, call_summary, confidence_bands, load_calls, load_ranges, range_summary
from marketbrief.pipeline.review.verdicts import confidence_advice, judge, proper_scores, proposals


def build(cfg: dict, rc: dict, rv: dict, con, week: str, history: bool = True) -> tuple[dict, dict]:
    start, end = week_bounds(week)
    roll_start = end - timedelta(days=rv["rolling_days"] - 1)
    ranges, calls = load_ranges(con, cfg, end), load_calls(con, end)
    windows = {"week": start, "rolling": roll_start, "all": date.min}

    def win(df, s):
        return df[df["target_date"] >= s] if not df.empty else df
    d = {"partial_week": end >= utc_today(),
         "ranges": {w: by_horizon(win(ranges, s), range_summary) for w, s in windows.items()},
         "calls": {w: by_horizon(win(calls, s), call_summary) for w, s in windows.items()},
         "breakdowns": {w: {"regime": breakdown(win(ranges, s), "regime"), "sector": breakdown(win(ranges, s), "sector"),
                            "note": breakdown(win(ranges, s), "tags")} for w, s in windows.items()},
         "bands": {w: confidence_bands(win(calls, s), rv["confidence_bands"]) for w, s in windows.items()}}
    cal = con.execute("SELECT DISTINCT ON (horizon_days) * FROM calibration WHERE as_of_date <= ? "
                      "ORDER BY horizon_days, as_of_date DESC, computed_at DESC", [end]).df()
    d["calibration"] = [{k: (str(v)[:10] if k == "as_of_date" else v) for k, v in r.items() if k != "computed_at"}
                        for r in cal.to_dict("records")]
    d["live_ablation"] = live_ablation(ranges, rc, rv)
    d["history_ablation"] = history_ablation(cfg, rc, rv, load_bars(con), end) if history else \
        {"n": 0, "error": "skipped (--no-history)", "variants": []}
    for ab in (d["live_ablation"], d["history_ablation"]):
        judge(ab, rv)
    d["proposals"] = proposals(rc, d["live_ablation"], d["history_ablation"])
    d["scores"] = {w: proper_scores(win(ranges, s), win(calls, s)) for w, s in windows.items()}
    d["aci"] = aci_state(con, rc, end)
    d["aci"]["replay"] = latest_aci_replay(con, end, rc)
    p = aci_proposal(rc, d["aci"]["replay"])
    if p:
        d["proposals"].append(p)
    d["advice"] = confidence_advice(d["bands"]["all"], d["calls"]["all"], rv)

    ra, ca = d["ranges"]["all"]["all"], d["calls"]["all"]["all"]
    rec = {"id": week, "week": week, "week_start": str(start), "week_end": str(end), "computed_at": utc_now(),
           "report": f"reports/{cfg['market']}/review-{week}.md",
           "n_ranges_week": d["ranges"]["week"]["all"]["n"], "n_ranges_30d": d["ranges"]["rolling"]["all"]["n"],
           "n_ranges_all": ra["n"], "n_calls_week": d["calls"]["week"]["all"]["n"], "n_calls_all": ca["n"],
           "cover50_all": ra.get("cover50"), "cover80_all": ra.get("cover80"), "score80_all": ra.get("score80_pct"),
           "naive_score80_all": ra.get("naive_score80_pct"), "call_hit_all": ca.get("hit_rate"),
           "always_up_all": ca.get("always_up"), "low_sample": ra["n"] < rv["min_n_recommend"],
           "n_proposals": len(d["proposals"]), "proposals": d["proposals"],
           "detail": {k: d[k] for k in ("ranges", "calls", "breakdowns", "bands", "calibration", "advice",
                                        "scores", "aci")} | {
               "live_ablation": d["live_ablation"], "history_ablation": d["history_ablation"],
               "thresholds": {k: rv[k] for k in DEFAULTS if not k.endswith("_variants")}}}
    return clean(rec), d


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--week", help="ISO week to review, e.g. 2026-W40 (default: the previous ISO week)")
    ap.add_argument("--if-due", action="store_true", help="do nothing if this week's review is already stored")
    ap.add_argument("--no-history", action="store_true", help="skip the walk-forward on stored prices")
    args = ap.parse_args()
    cfg = require_market(args)
    week = args.week or previous_week(utc_today())
    week_bounds(week)
    con = connect(cfg["market"])
    if args.if_due and con.execute("SELECT count(*) FROM reviews WHERE id = ?", [week]).fetchone()[0]:
        print(json.dumps({"step": "review", "market": cfg["market"], "week": week, "due": False,
                          "report": f"reports/{cfg['market']}/review-{week}.md"}, indent=2))
        return 0
    rv = load_review_config()
    rec, d = build(cfg, load_ranges_config(cfg["market"]), rv, con, week, history=not args.no_history)
    path = paths.ROOT / rec["report"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(cfg, rv, rec, d))
    out = day_file(cfg["market"], "reviews", utc_today())
    append_jsonl(out, [rec])
    print(json.dumps({"step": "review", "market": cfg["market"], "week": week, "due": True, "report": rec["report"],
                      "record": str(out.relative_to(paths.ROOT)), "n_ranges_week": rec["n_ranges_week"],
                      "n_ranges_all": rec["n_ranges_all"], "n_calls_all": rec["n_calls_all"],
                      "low_sample": rec["low_sample"],
                      "proposals": [{**c, "source": p["source"], "n": p["n"], "rel_score": p["rel_score"]}
                                    for p in rec["proposals"] for c in p["changes"]]}, indent=2, default=str))
    return 0
