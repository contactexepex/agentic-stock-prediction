#!/usr/bin/env python3
"""Walk-forward backtest of the range formula (no AI) on stored bars for one market.

For each evaluation day d (the last --eval-sessions trading days) and horizon h, the range is
built exactly as live (EWMA volatility at d, empirical quantiles from a recency-weighted pool of
outcomes already known at d) and scored on the close h sessions later. The naive baseline is
last close +/- 20-day realized volatility with normal quantiles. Event, regime and cue
adjustments are not replayed (no historical event or pre-market data), so this tests the core.
Writes reports/<market>/backtest-<as_of>.md and prints a JSON summary."""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

import rangelib as rl
from common import ROOT, benchmark_key, connect, load_ranges_config, market_arg, require_market
from features import load_bars


def observations(bars, tickers, h: int, rc: dict, rank: dict) -> pd.DataFrame:
    out = []
    for t in tickers:
        df = bars.get(t)
        if df is None or len(df) < rc["warmup_bars"] + h + 21:
            continue
        c = df["close"]
        s = rl.standardized(c, h, rc["ewma_lambda"], rc["warmup_bars"])
        logr = np.log(c / c.shift(1))
        s20 = logr.rolling(20).std(ddof=1)
        s = s.assign(close=c.reindex(s.index), s20=s20.reindex(s.index), ticker=t)
        s["rank"] = [rank.get(d) for d in s.index]
        out.append(s.dropna(subset=["rank", "z", "s20"]))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out)
    df["rank"] = df["rank"].astype(int)
    return df[np.isfinite(df["z"])]


def evaluate(obs: pd.DataFrame, h: int, rc: dict, eval_sessions: int,
             scale: dict[int, float] | None = None) -> pd.DataFrame:
    """`scale` optionally widens sigma per start rank (regime/event factors replayed by review.py)."""
    last = int(obs["rank"].max())
    start = last - eval_sessions + 1
    z_all, r_all = obs["z"].to_numpy(), obs["rank"].to_numpy()
    rows = []
    for d in range(start, last + 1):
        known = (r_all + h <= d) & (r_all > d - rc["history_sessions"])
        if known.sum() < rc["min_pool"]:
            continue
        w = rl.recency_weights((d - r_all[known]).astype(float), rc["half_life_sessions"])
        z = z_all[known]
        q10, q25, q75, q90 = (rl.weighted_quantile(z, w, p) for p in (0.10, 0.25, 0.75, 0.90))
        today = obs[obs["rank"] == d]
        for o in today.itertuples():
            base, sh = o.close, o.sigma * math.sqrt(h) * (scale.get(d, 1.0) if scale else 1.0)
            y = base * math.exp(o.fwd)
            lo50, hi50 = base * math.exp(q25 * sh), base * math.exp(q75 * sh)
            lo80, hi80 = base * math.exp(q10 * sh), base * math.exp(q90 * sh)
            n50, n80 = rl.naive_range(base, o.s20, h, 0.5), rl.naive_range(base, o.s20, h, 0.8)
            rows.append({
                "rank": d, "ticker": o.ticker,
                "hit50": lo50 <= y <= hi50, "hit80": lo80 <= y <= hi80,
                "naive_hit50": n50[0] <= y <= n50[1], "naive_hit80": n80[0] <= y <= n80[1],
                "width80": 100 * (hi80 - lo80) / base, "naive_width80": 100 * (n80[1] - n80[0]) / base,
                "is80": 100 * rl.interval_score(lo80, hi80, y, 0.8) / base,
                "naive_is80": 100 * rl.interval_score(n80[0], n80[1], y, 0.8) / base,
                "is50": 100 * rl.interval_score(lo50, hi50, y, 0.5) / base,
                "naive_is50": 100 * rl.interval_score(n50[0], n50[1], y, 0.5) / base,
            })
    return pd.DataFrame(rows)


def summarize(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    m = res.mean(numeric_only=True)
    return {"n": int(len(res)), "days": int(res["rank"].nunique()),
            "cover50": round(float(m["hit50"]), 3), "cover80": round(float(m["hit80"]), 3),
            "naive_cover50": round(float(m["naive_hit50"]), 3), "naive_cover80": round(float(m["naive_hit80"]), 3),
            "width80_pct": round(float(m["width80"]), 2), "naive_width80_pct": round(float(m["naive_width80"]), 2),
            "score80": round(float(m["is80"]), 3), "naive_score80": round(float(m["naive_is80"]), 3)}


def run(cfg: dict, rc: dict, eval_sessions: int) -> dict:
    con = connect(cfg["market"])
    bars = load_bars(con)
    bench = bars.get(benchmark_key(cfg))
    if bench is None:
        raise SystemExit("no benchmark bars; run collect_prices.py --period 2y first")
    rank = {d: i for i, d in enumerate(bench.index)}
    out = {"market": cfg["market"], "as_of_date": str(bench.index[-1].date()), "horizons": {}, "by_ticker": {}}
    for h in rc["horizons"]:
        res = evaluate(observations(bars, cfg["tickers"], h, rc, rank), h, rc, eval_sessions)
        out["horizons"][h] = {"all": summarize(res),
                              "last_60_days": summarize(res[res["rank"] > res["rank"].max() - 60]) if len(res) else {"n": 0}}
        if len(res):
            out["by_ticker"][h] = {t: summarize(g) for t, g in res.groupby("ticker")}
    return out


def markdown(cfg: dict, s: dict) -> str:
    lines = [f"# Range backtest: {cfg['name']}, data to {s['as_of_date']}", "",
             "_Formula only (no AI, no event/regime/cue adjustments). Walk-forward: each day uses only "
             "outcomes known before it. Target coverage: 50% and 80%. Interval score: lower is better._", "",
             "| Horizon | Window | n | 50% cover | 80% cover | Naive 80% cover | 80% width % | Naive width % | Score | Naive score |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for h, v in s["horizons"].items():
        for name, r in (("all", v["all"]), ("last 60 days", v["last_60_days"])):
            if r.get("n"):
                lines.append(f"| {h}d | {name} | {r['n']} | {r['cover50']:.1%} | {r['cover80']:.1%} | "
                             f"{r['naive_cover80']:.1%} | {r['width80_pct']} | {r['naive_width80_pct']} | "
                             f"{r['score80']} | {r['naive_score80']} |")
    for h, per in s["by_ticker"].items():
        lines += ["", f"## {h}-day, per ticker", "", "| Ticker | n | 80% cover | Score | Naive score |", "|---|---|---|---|---|"]
        for t, r in sorted(per.items()):
            lines.append(f"| {t} | {r['n']} | {r['cover80']:.1%} | {r['score80']} | {r['naive_score80']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--eval-sessions", type=int, default=250, help="trading days to evaluate (default 250)")
    args = ap.parse_args()
    cfg = require_market(args)
    rc = load_ranges_config()
    s = run(cfg, rc, args.eval_sessions)
    path = ROOT / "reports" / cfg["market"] / f"backtest-{s['as_of_date']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(cfg, s))
    print(json.dumps({"step": "backtest", "report": str(path.relative_to(ROOT)),
                      "horizons": s["horizons"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
