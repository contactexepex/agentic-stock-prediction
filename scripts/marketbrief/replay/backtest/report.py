"""Run of the backtest for one market and its markdown report."""
from __future__ import annotations

from marketbrief.analytics import event_history, range_switches
from marketbrief.constants.messages import MSG_NO_BENCHMARK_BARS_PERIOD
from marketbrief.analytics.features import load_bars
from marketbrief.core import database, market_config
from marketbrief.constants.backtest import INPUT_ARMS
from marketbrief.replay.backtest.evaluation import compare_inputs, evaluate, summarize
from marketbrief.replay.backtest.observations import index_cue_series, observations


def run(cfg: dict, rc: dict, eval_sessions: int) -> dict:
    con = database.connect(cfg["market"])
    bars = load_bars(con)
    bench = bars.get(market_config.benchmark_key(cfg))
    if bench is None:
        raise SystemExit(MSG_NO_BENCHMARK_BARS_PERIOD)
    rank = {d: i for i, d in enumerate(bench.index)}
    evdf = event_history.load_events(con)
    extra = {"earnings": event_history.earnings_versions(evdf), "dividends": event_history.dividend_events(evdf), "bench": bench,
             "index_cue": index_cue_series(cfg, bars, rc)}
    out = {"market": cfg["market"], "as_of_date": str(bench.index[-1].date()), "horizons": {}, "by_ticker": {},
           "inputs": {}, "event_history": {"earnings": sum(len(v[-1][1]) for v in extra["earnings"].values()),
                                           "dividends": sum(map(len, extra["dividends"].values()))}}
    for h in rc["horizons"]:
        use = {k: range_switches.enabled(rc, k, cfg["market"], h) for k in INPUT_ARMS}
        res = evaluate(observations(bars, cfg["tickers"], h, rc, rank, cfg, extra), h, rc, eval_sessions, use)
        out["horizons"][h] = {"all": summarize(res),
                              "last_60_days": summarize(res[res["rank"] > res["rank"].max() - 60]) if len(res) else {"n": 0}}
        if len(res):
            out["by_ticker"][h] = {t: summarize(g) for t, g in res.groupby("ticker")}
            out["inputs"][h] = compare_inputs(res, float(rc.get("backtest_min_gain", 0.005)))
    return out


def markdown(cfg: dict, s: dict) -> str:
    lines = [f"# Range backtest: {cfg['name']}, data to {s['as_of_date']}", "",
             "_Formula only (no AI, no regime adjustments). Walk-forward: each day uses only "
             "outcomes known before it. Target coverage: 50% and 80%. Interval score: lower is better._", "",
             "| Horizon | Window | n | 50% cover | 80% cover | Naive 80% cover | 80% width % | Naive width % | Score | Naive score |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for h, v in s["horizons"].items():
        for name, r in (("all", v["all"]), ("last 60 days", v["last_60_days"])):
            if r.get("n"):
                lines.append(f"| {h}d | {name} | {r['n']} | {r['cover50']:.1%} | {r['cover80']:.1%} | "
                             f"{r['naive_cover80']:.1%} | {r['width80_pct']} | {r['naive_width80_pct']} | "
                             f"{r['score80']} | {r['naive_score80']} |")
    if s.get("inputs"):
        eh = s.get("event_history", {})
        lines += ["", "## Range inputs (off vs on, scored where the input applies)", "",
                  f"_Event history: {eh.get('earnings', 0)} earnings reports, {eh.get('dividends', 0)} dividends. "
                  "all_inputs = the formula before these inputs (fixed earnings multiple, direct cue) vs the inputs "
                  "switched on in config/ranges.yaml for this market. "
                  "Implied volatility has no stored history: live only._", "",
                  "| Horizon | Input | Applies | Off 80% cover | On 80% cover | Off width % | On width % | Off score | On score | Verdict |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for h, per in s["inputs"].items():
            for name, r in per.items():
                if "off" not in r:
                    continue
                a, b = r["off"], r["on"]
                if not a.get("n"):
                    lines.append(f"| {h}d | {name} | 0 | | | | | | | {r['verdict']} |")
                    continue
                lines.append(f"| {h}d | {name} | {r['applies']} | {a['cover80']:.1%} | {b['cover80']:.1%} | "
                             f"{a['width80_pct']} | {b['width80_pct']} | {a['score80']} | {b['score80']} | {r['verdict']} |")
    for h, per in s["by_ticker"].items():
        lines += ["", f"## {h}-day, per ticker", "", "| Ticker | n | 80% cover | Score | Naive score |", "|---|---|---|---|---|"]
        for t, r in sorted(per.items()):
            lines.append(f"| {t} | {r['n']} | {r['cover80']:.1%} | {r['score80']} | {r['naive_score80']} |")
    return "\n".join(lines) + "\n"
