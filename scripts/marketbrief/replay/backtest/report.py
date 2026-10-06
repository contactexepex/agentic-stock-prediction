"""Run of the backtest for one market and its markdown report."""

from __future__ import annotations

from marketbrief.analytics import event_history, range_switches
from marketbrief.constants.messages import MSG_NO_BENCHMARK_BARS_PERIOD
from marketbrief.analytics.features import load_bars
from marketbrief.core import database, market_config
from marketbrief.constants.backtest import INPUT_ARMS
from marketbrief.replay.backtest.evaluation import compare_inputs, evaluate, summarize
from marketbrief.replay.backtest.observations import index_cue_series, observations


def run(cfg: dict, ranges_config: dict, eval_sessions: int) -> dict:
    """Run the walk-forward backtest for one market and collect the summaries."""
    con = database.connect(cfg["market"])
    bars = load_bars(con)
    bench = bars.get(market_config.benchmark_key(cfg))
    if bench is None:
        raise SystemExit(MSG_NO_BENCHMARK_BARS_PERIOD)
    rank = {bar_date: position for position, bar_date in enumerate(bench.index)}
    evdf = event_history.load_events(con)
    extra = {
        "earnings": event_history.earnings_versions(evdf),
        "dividends": event_history.dividend_events(evdf),
        "bench": bench,
        "index_cue": index_cue_series(cfg, bars, ranges_config),
    }
    out = {
        "market": cfg["market"],
        "as_of_date": str(bench.index[-1].date()),
        "horizons": {},
        "by_ticker": {},
        "inputs": {},
        "event_history": {
            "earnings": sum(len(versions[-1][1]) for versions in extra["earnings"].values()),
            "dividends": sum(map(len, extra["dividends"].values())),
        },
    }
    for horizon in ranges_config["horizons"]:
        use = {key: range_switches.enabled(ranges_config, key, cfg["market"], horizon) for key in INPUT_ARMS}
        res = evaluate(
            observations(bars, cfg["tickers"], horizon, ranges_config, rank, cfg, extra),
            horizon,
            ranges_config,
            eval_sessions,
            use,
        )
        out["horizons"][horizon] = {
            "all": summarize(res),
            "last_60_days": summarize(res[res["rank"] > res["rank"].max() - 60]) if len(res) else {"n": 0},
        }
        if len(res):
            out["by_ticker"][horizon] = {ticker: summarize(group) for ticker, group in res.groupby("ticker")}
            out["inputs"][horizon] = compare_inputs(res, float(ranges_config.get("backtest_min_gain", 0.005)))
    return out


def markdown(cfg: dict, summary: dict) -> str:
    """The backtest report as markdown tables."""
    lines = [
        f"# Range backtest: {cfg['name']}, data to {summary['as_of_date']}",
        "",
        "_Formula only (no AI, no regime adjustments). Walk-forward: each day uses only "
        "outcomes known before it. Target coverage: 50% and 80%. Interval score: lower is better._",
        "",
        "| Horizon | Window | n | 50% cover | 80% cover | Naive 80% cover | 80% width % | Naive width % | Score | "
        "Naive score |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for horizon, horizon_summary in summary["horizons"].items():
        for name, window_summary in (
            ("all", horizon_summary["all"]),
            ("last 60 days", horizon_summary["last_60_days"]),
        ):
            if window_summary.get("n"):
                lines.append(
                    f"| {horizon}d | {name} | {window_summary['n']} | {window_summary['cover50']:.1%} | "
                    f"{window_summary['cover80']:.1%} | "
                    f"{window_summary['naive_cover80']:.1%} | {window_summary['width80_pct']} | "
                    f"{window_summary['naive_width80_pct']} | "
                    f"{window_summary['score80']} | {window_summary['naive_score80']} |"
                )
    if summary.get("inputs"):
        event_counts = summary.get("event_history", {})
        lines += [
            "",
            "## Range inputs (off vs on, scored where the input applies)",
            "",
            f"_Event history: {event_counts.get('earnings', 0)} earnings reports, {event_counts.get('dividends', 0)} "
            f"dividends. "
            "all_inputs = the formula before these inputs (fixed earnings multiple, direct cue) vs the inputs "
            "switched on in config/ranges.yaml for this market. "
            "Implied volatility has no stored history: live only._",
            "",
            "| Horizon | Input | Applies | Off 80% cover | On 80% cover | Off width % | On width % | Off score | On "
            "score | Verdict |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for horizon, per in summary["inputs"].items():
            for name, window_summary in per.items():
                if "off" not in window_summary:
                    continue
                off_summary, on_summary = window_summary["off"], window_summary["on"]
                if not off_summary.get("n"):
                    lines.append(f"| {horizon}d | {name} | 0 | | | | | | | {window_summary['verdict']} |")
                    continue
                lines.append(
                    f"| {horizon}d | {name} | {window_summary['applies']} | {off_summary['cover80']:.1%} | "
                    f"{on_summary['cover80']:.1%} | "
                    f"{off_summary['width80_pct']} | {on_summary['width80_pct']} | {off_summary['score80']} | "
                    f"{on_summary['score80']} | {window_summary['verdict']} |"
                )
    for horizon, per in summary["by_ticker"].items():
        lines += [
            "",
            f"## {horizon}-day, per ticker",
            "",
            "| Ticker | n | 80% cover | Score | Naive score |",
            "|---|---|---|---|---|",
        ]
        for ticker, window_summary in sorted(per.items()):
            lines.append(
                f"| {ticker} | {window_summary['n']} | {window_summary['cover80']:.1%} | {window_summary['score80']} "
                f"| {window_summary['naive_score80']} |"
            )
    return "\n".join(lines) + "\n"
