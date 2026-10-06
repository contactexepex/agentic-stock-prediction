"""As-of replay harness for the AI agents (deterministic; it never runs an LLM itself).

The model's training data runs to about mid-2026. ForecastBench's leakage rule (Karger et al.,
arXiv 2409.19839): only as-of dates AFTER the model's training cutoff (`model_training_cutoff` in
config/settings.yaml, 2026-06-30) are a fair test of the forecaster; earlier dates are labelled
"contaminated" (the model may have seen what happened), `prepare` refuses them unless
--allow-training-period, and `record`/`score` label every row and score the two groups separately,
never pooled. For a past as-of date D (a trading day: its close
is known) this script rebuilds what the routine would have known pre-open on the next session S,
lets the orchestrator run the agents on it, then records and scores their calls:

  dates   --market M                 the sample: every 5th trading day 2026-07-01..2026-09-25
  backfill --market M --source S --since 2026-06-01
          S = a scratch source root (refused: the repo, its data/ or anything inside/above them): a copy
          of data/<M>/ plus config/ whose lookbacks are lengthened in S only; the existing collectors
          then run into S one after another (US: SEC filings, Form 4, 13D/13G, events; India: NSE
          announcements and results filings, SEBI PIT insider trades, bulk/block deals with their
          `--since` option, events). Rows keep their real publication/acceptance times.
  prepare --market M --date D --root R [--source S] [--assume-earnings-known DAYS]
          R = a scratch root: copies of config/, sql/, templates/ and data/<M>/ truncated to what
          was public at the cutoff (the routine's start time on S, before the open; CUTOFF_LOCAL).
          Then features.py, calibrate.py, context.py (R/work/context.md) and ranges.py run with
          MB_ROOT=R and MB_NOW=cutoff (marketbrief/core/clock.py clock(): every "now"/"today" and DuckDB's
          current_date is the cutoff). Prints and saves (R/ai_replay.json) what was kept or dropped.
  record  --market M --date D --root R --calls F --results DIR
          validates forecaster-format records (schema `predictions` in marketbrief/core/schemas.py and the CLAUDE.md
          prediction rules, checked against R) and appends the valid ones to
          DIR/<M>/calls.jsonl tagged replay=true (never to data/<M>/predictions/).
  score   --market M --results DIR --out PAGE.html
          scores the recorded calls on the REAL stored closes (direction hit at 1 or 5 trading
          days, as score_predictions.py), against always-up and replay.py's rule baselines on the
          same ticker-days; writes a novice-first HTML page and PAGE.json.

Inclusion rules of `prepare` (per data kind; a row is kept only if public by the cutoff):
- prices: bars dated <= D (every symbol, also foreign cues);
- adjustments (splits and bonus issues, issue #31): ex_date <= D, whatever detected_at. The root's
  bars all date <= D, so an adjustment with a later ex-date would only re-scale them to a basis
  the live run never saw (its stored ranges and calls are on the old basis); one with ex_date <= D
  puts the bars before it on the basis of bar D, as the live run saw once the collector had
  recorded it (the run that collects the ex-date's bar). If it was recorded later than that, the
  live run saw a jump the root does not show; the jump carries no information about direction
  (an ex-date is announced in advance). An ex-date on the session S itself, recorded pre-open,
  is left out (ex_date > D), so the root stays on the old basis there;
- filings, fundamentals: SEC acceptance time, else the end of the filing date (UTC), as the
  fundamentals_*_asof macros in sql/views.sql; stakes, insiders, holdings: acceptance/disclosure/
  filing time, else first_seen_at; announcements: published_at; financials: filed_at;
- events: first_seen_at <= cutoff, plus backfilled past events (source *_history) dated <= D;
- predictions, ranges: made_at; outcomes, range_outcomes: scored_at and target_date <= D;
  lessons: available_from and target_date <= D;
  features, regime, calibration, reviews, replays: computed_at; judgments: recorded_at;
  quotes, options: collected_at; graph: added_at; graph_runs: run_at; news_articles, primary_texts:
  fetched_at; news_clusters, news_verified: as_of; news_claims: extracted_at (all cite news ids, which
  stay dropped, see below; a claim's source was available before its extracted_at);
- deals: trade date <= D (assumed: NSE publishes the day's bulk and block deals after the close);
- kinds with only an observation date and no publication time (macro, shorts, short_interest,
  fpi, indices, flows, delivery): kept only if first_seen_at <= cutoff, i.e. backfilled rows are
  dropped;
- --assume-earnings-known DAYS (off by default) adds the actual earnings dates within DAYS after D
  as events first seen at the cutoff, labelled ASSUMED (stored rows do not say when a date was
  announced);
- news and news_enriched: dropped (stored news only starts when live collection began); any other
  kind: dropped and listed. summaries/ and reports/ are never copied."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from marketbrief.core import paths
from marketbrief.core.market_config import load_market, market_names
from marketbrief.constants.messages import MSG_MARKET_REQUIRED
from marketbrief.constants.ai_replay import SAMPLE_END, SAMPLE_START, SAMPLE_STEP
from marketbrief.replay.ai_replay.backfill import backfill
from marketbrief.replay.ai_replay.cutoff import cutoff_for, next_session, sample_dates
from marketbrief.replay.ai_replay.prepare import prepare
from marketbrief.replay.ai_replay.record import record
from marketbrief.replay.ai_replay.score import score


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--market", default=os.environ.get("MB_MARKET"), help=f"one of {market_names()}")
        return p

    add("dates", "print the sample of as-of dates")
    p = add("prepare", "build an as-of scratch root and its context pack and ranges")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--source", type=Path, help="root whose data/ is read, e.g. a `backfill` source "
                                               "(default: $MB_ROOT or the repo)")
    p.add_argument("--force", action="store_true", help="rebuild a root this script prepared before")
    p.add_argument("--allow-training-period", action="store_true",
                   help="allow an as-of date on or before model_training_cutoff in config/settings.yaml "
                        "(labelled contaminated: not a fair test, scored separately)")
    p.add_argument("--assume-earnings-known", type=int, default=0, metavar="DAYS",
                   help="ASSUMPTION, off by default: treat actual earnings dates within DAYS after D as announced "
                        "before the cutoff (labelled in the context pack and the summary)")
    p = add("backfill", "copy data/<market> to a scratch source and run the collectors into it from --since")
    p.add_argument("--source", required=True, type=Path, help="scratch source root (never the repo or its data/)")
    p.add_argument("--since", required=True, type=date.fromisoformat)
    p = add("record", "validate forecaster calls and store them in the replay results")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--calls", required=True, type=Path, help="forecaster-format JSONL (may be empty: all abstain)")
    p.add_argument("--results", type=Path, default=paths.CODE / "work" / "ai_replay", help="results dir (default work/ai_replay)")
    p = add("score", "score the recorded calls on real closes; write HTML and JSON")
    p.add_argument("--results", type=Path, default=paths.CODE / "work" / "ai_replay")
    p.add_argument("--out", required=True, type=Path, help="HTML path; the JSON goes next to it")
    args = ap.parse_args()
    if not args.market:
        raise SystemExit(MSG_MARKET_REQUIRED.format(available=market_names()))
    cfg = load_market(args.market)
    if args.cmd == "dates":
        ds = sample_dates(cfg)
        res = {"market": cfg["market"], "rule": f"every {SAMPLE_STEP}th {cfg['calendar']} trading day from "
               f"{SAMPLE_START} to {SAMPLE_END}, starting with the first", "n": len(ds),
               "dates": [{"as_of_date": str(d), "session_date": str(next_session(cfg, d)),
                          "cutoff_utc": cutoff_for(cfg, d).isoformat()} for d in ds]}
    elif args.cmd == "prepare":
        res = prepare(cfg, args.date, args.root.resolve(), args.source, args.force, args.allow_training_period,
                      args.assume_earnings_known)
        res = {k: v for k, v in res.items() if k != "steps"} | {"steps": {k: (v if k != "features" else {
            x: v.get(x) for x in ("as_of_date", "session_date", "regime", "tickers", "blocked")} if isinstance(v, dict) else v)
            for k, v in res["steps"].items()}}
    elif args.cmd == "backfill":
        res = backfill(cfg, args.source, args.since)
    elif args.cmd == "record":
        res = record(cfg, args.date, args.root.resolve(), args.calls, args.results)
    else:
        res = score(cfg, args.results, args.out)
    print(json.dumps(res, indent=2, default=str))
    return 0
