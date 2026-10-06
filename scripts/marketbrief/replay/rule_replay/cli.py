"""Historical replay of everything rule-based (no AI) for one market, walk-forward over stored bars.

For each trading day d in the window (as-of dates, default: from `warmup_bars` sessions after the
first benchmark bar to the last one), using only what ranges.py would know pre-open the next
session, i.e. bars up to d's close and events as known then:
1. Ranges: the 1d and 5d 50%/80% ranges built as ranges.py builds them (calibration quantiles from
   the recency-weighted pool of outcomes known at d as calibrate.py, EWMA volatility, earnings,
   regime and major-event widening, beta-split centre and ex-dividend shift where config/ranges.yaml
   switches them on), scored on the close h sessions later against the naive baseline: coverage
   overall and by regime, sector, ticker, month and earnings-in-horizon, interval score and width,
   and calibration (stated vs actual coverage, the published 50%/80% bands plus a curve of other
   levels from the same quantile pool).
2. Regime: the label per day (regime.py classify on the vol index and benchmark closes, and the
   major events of config/events.yaml), as features.py computes it.
3. Direction BASELINES (not the product's forecasts; the AI forecaster must beat them later):
   always-up, 1d and 5d momentum sign, and RSI(14) mean reversion (below 30 up, above 70 down;
   indicators.py has no direction signal of its own, so the rule is defined here). Each with a hit
   rate, a 95% interval clustered by date blocks, a two-sided binomial test vs 50%, and the
   difference vs always-up on the same rows.
Event dates: earnings via event_history.earnings_versions (SEC 2.02 filings judged only by the
10-Q/10-K reports accepted by the session date, as ranges.py), dividends via dividend_events.

Not replayable, so left out (listed in the output): the AI's drift and widening, overnight own-stock
cues (US pre-market gaps, India ADRs: no stored history; the next open would be look-ahead), the US
index cue (futures before the open), implied volatility, live scored ranges in the calibration pool,
quote-based vol index levels (closes are used), and the relationship/smart-money widening (off).
Also, past event dates are taken as known in advance (scheduled), since backfilled rows do not say
when each date was first announced.

Writes reports/<market>/replay-<end>.html (self-contained) and .json, and appends one row to
data/<market>/replays/ (schema `replays` in marketbrief/core/schemas.py). Prints a JSON summary."""
from __future__ import annotations

import json
import time
from datetime import date
from marketbrief.analytics import adaptive_conformal, range_switches
from marketbrief.constants.range_inputs import INPUTS
from marketbrief.core.clock import utc_now
from marketbrief.core.market_config import benchmark_key, load_ranges_config
from marketbrief.core import cli, database, paths, storage
from marketbrief.replay.rule_replay.aci_compare import aci_comparison, aci_rc, aci_tag, held_out
from marketbrief.replay.rule_replay.inputs import load_inputs
from marketbrief.replay.rule_replay.narrative import headline, limitations, top_sentences
from marketbrief.replay.rule_replay.range_rows import replay_rows
from marketbrief.replay.rule_replay.replay_statistics import summarize
from marketbrief.replay.rule_replay.rule_html import html_report


def run(cfg: dict, rc: dict, con, start: date | None = None, end: date | None = None) -> tuple[dict, dict]:
    t0 = time.time()
    bars, extra = load_inputs(cfg, rc, con)
    res, reg = replay_rows(cfg, rc, bars, extra, start, end)
    s = summarize(cfg, rc, res, reg)
    bench = bars[benchmark_key(cfg)]
    days = reg.index.tolist()
    s.update({"market": cfg["market"], "name": cfg.get("name"), "start": str(days[0]) if days else None,
              "end": str(days[-1]) if days else None, "computed_at": utc_now(),
              "settings": {"inputs": {str(h): {k: range_switches.enabled(rc, k, cfg["market"], h) for k in INPUTS}
                                      for h in rc["horizons"]},
                           "regime_factor": rc["regime_factor"], "major_event_factor": rc["major_event_factor"],
                           "earnings_vol_multiple": rc["earnings_vol_multiple"], "history_sessions": rc["history_sessions"],
                           "half_life_sessions": rc["half_life_sessions"], "min_pool": rc["min_pool"],
                           "aci": {**adaptive_conformal.settings(rc), "on": {str(h): range_switches.enabled(rc, "aci", cfg["market"], h)
                                                              for h in rc["horizons"]}}},
              "data": {"first_bar": str(bench.index[0].date()), "last_bar": str(bench.index[-1].date()),
                       "tickers": sum(1 for t in cfg["tickers"] if t in bars),
                       "earnings_events": sum(len(v[-1][1]) for v in extra["earnings"].values() if v),
                       "dividends": sum(map(len, extra["dividends"].values()))},
              })
    s["limitations"] = limitations(cfg, rc, s)
    s["summary"] = headline(cfg, s)
    s["top"] = top_sentences(s)
    s["runtime_s"] = round(time.time() - t0, 1)
    return s, res


def record(s: dict, report: str) -> dict:
    o = {h: s["horizons"].get(h, {}).get("overall", {}) for h in ("1", "5")}
    b = {h: (s["baselines"].get(h) or {}).get("always_up", {}) for h in ("1", "5")}
    return {"id": f"{s['start']}_{s['end']}", "market": s["market"], "start_date": s["start"], "end_date": s["end"],
            "computed_at": s["computed_at"], "report": report, "n_days": len(s["regime_timeline"]),
            "n_ranges": sum(x.get("n", 0) for x in o.values()),
            "cover50_1d": o["1"].get("cover50"), "cover80_1d": o["1"].get("cover80"),
            "cover50_5d": o["5"].get("cover50"), "cover80_5d": o["5"].get("cover80"),
            "score80_1d": o["1"].get("score80_same_rows"), "naive_score80_1d": o["1"].get("naive_score80"),
            "score80_5d": o["5"].get("score80_same_rows"), "naive_score80_5d": o["5"].get("naive_score80"),
            "always_up_1d": b["1"].get("hit_rate"), "always_up_5d": b["5"].get("hit_rate"),
            "runtime_s": s["runtime_s"], "settings": s["settings"],
            "detail": {k: v for k, v in s.items() if k not in ("settings", "regime_timeline")}}


def main() -> int:
    ap = cli.market_arg(__doc__)
    ap.add_argument("--start", type=date.fromisoformat, help="first as-of date (default: after the warm-up bars)")
    ap.add_argument("--end", type=date.fromisoformat, help="last as-of date (default: the last benchmark bar)")
    ap.add_argument("--aci", action="store_true",
                    help="also replay with Adaptive Conformal Inference on (adaptive_conformal.py) and compare on the same rows; "
                         "writes replay-<end>-aci.html|json")
    ap.add_argument("--aci-gamma", type=float, help="with --aci: gamma instead of config/ranges.yaml aci.gamma")
    ap.add_argument("--aci-by-regime", choices=("on", "off"), help="with --aci: one alpha per regime (on) or one overall")
    ap.add_argument("--aci-tune-end", type=date.fromisoformat,
                    help="with --aci: held-out check; pick gamma/by_regime from a grid on as-of dates up to this date, "
                         "report fixed vs ACI on the dates after it (out of sample)")
    args = ap.parse_args()
    if (args.aci_gamma is not None or args.aci_by_regime or args.aci_tune_end) and not args.aci:
        raise SystemExit("--aci-gamma, --aci-by-regime and --aci-tune-end need --aci")
    cfg = cli.require_market(args)
    rc = load_ranges_config(cfg["market"])
    con = database.connect(cfg["market"])
    s, _ = run(cfg, rc, con, args.start, args.end)
    if not s["end"]:
        raise SystemExit("no trading days in the window")
    suffix = ""
    if args.aci:
        before = s
        by = None if args.aci_by_regime is None else args.aci_by_regime == "on"
        rc_aci = aci_rc(rc, args.aci_gamma, by)
        s, _ = run(cfg, rc_aci, con, args.start, args.end)
        s["aci_comparison"] = aci_comparison(before, s)
        if args.aci_tune_end:
            s["aci_held_out"] = held_out(cfg, rc_aci, con, args.aci_tune_end, args.start, args.end)
        suffix = aci_tag(rc_aci["aci"], args.aci_tune_end)
    out = paths.ROOT / "reports" / cfg["market"]
    out.mkdir(parents=True, exist_ok=True)
    page, js = out / f"replay-{s['end']}{suffix}.html", out / f"replay-{s['end']}{suffix}.json"
    page.write_text(html_report(cfg, s), encoding="utf-8")
    js.write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    rel = str(page.relative_to(paths.ROOT))
    rec = record(s, rel)
    rec["id"] += suffix
    storage.append_jsonl(storage.day_file(cfg["market"], "replays", date.fromisoformat(s["end"])), [rec])
    print(json.dumps({"step": "replay", "market": cfg["market"], "report": rel, "json": str(js.relative_to(paths.ROOT)),
                      "start": s["start"], "end": s["end"], "runtime_s": s["runtime_s"],
                      "aci": s["settings"]["aci"],
                      "overall": {h: v["overall"] for h, v in s["horizons"].items()},
                      "aci_comparison": {h: v["overall"] for h, v in s.get("aci_comparison", {}).items()} or None,
                      "aci_held_out": None if "aci_held_out" not in s else {
                          **{k: s["aci_held_out"][k] for k in ("tune_end", "selected", "config", "selected_is_config")},
                          "test_selected": {h: v["overall"] for h, v in s["aci_held_out"]["test_selected"].items()},
                          "test_config": {h: v["overall"] for h, v in s["aci_held_out"]["test_config"].items()}},
                      "always_up": {h: (b or {}).get("always_up", {}).get("hit_rate") for h, b in s["baselines"].items()},
                      "summary": s["summary"]}, indent=2, default=str))
    return 0
