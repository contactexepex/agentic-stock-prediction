#!/usr/bin/env python3
"""Walk-forward backtest of the range formula (no AI) on stored bars for one market.

For each evaluation day d (the last --eval-sessions trading days) and horizon h, the range is built exactly as live
(EWMA volatility at d, empirical quantiles from a recency-weighted pool of outcomes already known at d) and scored on
the close h sessions later. The naive baseline is last close +/- 20-day realized volatility with normal quantiles.
Regime and AI adjustments are not replayed, so the headline numbers test the core formula.

Range inputs (config/ranges.yaml, docs/DESIGN.md section 11) are then switched off and on, each
scored where it applies (docs/DESIGN.md section 7: keep an input only if it improves accuracy):
- earnings_history: earnings widening sized from the stock's past earnings-day moves (only
  reactions completed before d) vs the fixed multiplier; earnings dates from event_history, with
  the SEC 2.02 filings that are not results releases dropped as known at d (only 10-Q/10-K
  reports accepted by d are used: range_inputs.earnings_versions).
- ex_dividend: centre shifted down by dividends going ex inside the horizon vs no shift.
- beta_split: beta x index cue + own cue net of it vs the direct own cue. Historical cues are
  proxies: a numeric index_cue beta (US futures) uses the benchmark's next open gap; "fit" uses
  the cue's previous session return (exactly what is known live); the own cue is the stock's
  next open gap if the market has pre-market quotes, else none (ADR history is not stored).
- implied_vol has no stored history: live only, not backtested.
Writes reports/<market>/backtest-<as_of>.md (or --out) and prints a JSON summary."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import events as ev
import range_inputs as ri
import rangelib as rl
from common import ROOT, benchmark_key, connect, load_ranges_config, market_arg, require_market
from marketbrief.constants.messages import MSG_NO_BENCHMARK_BARS_PERIOD
from features import load_bars

# input -> (arm when off, arm when on, column marking the rows where it applies)
INPUTS = {"earnings_history": ("earn_fixed", "earn_hist", "earn"),
          "ex_dividend": ("core", "exdiv", "has_div"),
          "beta_split": ("cue_direct", "cue_beta", "has_cue")}


def rolling_beta(close: pd.Series, bench: pd.Series, n: int = rl.TRADING_DAYS, min_obs: int = 60) -> pd.Series:
    j = pd.concat([ri.log_returns(close), ri.log_returns(bench)], axis=1, join="inner").dropna()
    a, b = j.iloc[:, 0], j.iloc[:, 1]
    return (a.rolling(n, min_periods=min_obs).cov(b) / b.rolling(n, min_periods=min_obs).var()).reindex(close.index)


def index_cue_series(cfg: dict, bars: dict, rc: dict) -> pd.Series | None:
    """Historical proxy of the index cue (log move expected for the benchmark), by as-of date."""
    ic = cfg.get("index_cue") or {}
    bench = bars.get(benchmark_key(cfg))
    if not ic.get("symbol") or bench is None:
        return None
    if ic.get("beta", 1.0) != "fit":
        return float(ic.get("beta", 1.0)) * np.log(bench["open"].shift(-1) / bench["close"])
    cue = bars.get(ic["symbol"])
    if cue is None:
        return None
    nxt = pd.Series(bench.index[1:].tolist() + [pd.NaT], index=bench.index)
    a = pd.DataFrame({"asof": bench.index, "date": nxt.to_numpy()}).dropna()
    rc_ = ri.log_returns(cue["close"]).dropna()
    b = pd.DataFrame({"date": rc_.index, "r": rc_.to_numpy()})
    j = pd.merge_asof(a.sort_values("date"), b, on="date", allow_exact_matches=False).set_index("asof")["r"]
    betas = pd.Series({d: ri.fit_cue_beta(bench["close"], cue["close"], d, int(rc["beta_split"]["fit_sessions"]))
                       for d in j.index}, dtype=float)
    return (betas * j).reindex(bench.index)


def mark_window(n: int, positions: list[int], h: int) -> np.ndarray:
    """Rows i whose horizon (i, i+h] contains one of the positions."""
    out = np.zeros(n, dtype=bool)
    for p in positions:
        out[max(0, p - h):max(0, p)] = True
    return out


def observations(bars, tickers, h: int, rc: dict, rank: dict, cfg: dict | None = None,
                 extra: dict | None = None) -> pd.DataFrame:
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
        if cfg is not None and extra is not None:
            s = s.join(input_columns(cfg, rc, df, t, h, extra))
        s["rank"] = [rank.get(d) for d in s.index]
        out.append(s.dropna(subset=["rank", "z", "s20"]))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out)
    df["rank"] = df["rank"].astype(int)
    return df[np.isfinite(df["z"])]


def input_columns(cfg: dict, rc: dict, df: pd.DataFrame, t: str, h: int, extra: dict) -> pd.DataFrame:
    """Per as-of date: earnings in horizon and the walk-forward multiple, ex-dividend log shift,
    beta at d and the cue proxies."""
    c, idx = df["close"], df.index
    n = len(idx)
    pos = {d.date(): i for i, d in enumerate(idx)}
    cols = pd.DataFrame(index=idx)
    # earnings: each as-of date d uses the events as known at d (SEC 2.02 filings classified by
    # the 10-Q/10-K reports accepted by d; ri.earnings_versions)
    earn, mh = np.zeros(n, dtype=bool), np.full(n, np.nan)
    sigma = rl.ewma_sigma(c, rc["ewma_lambda"])
    days = np.array([d.date() for d in idx])
    versions = extra["earnings"].get(t, [])
    for k, (start, events) in enumerate(versions):
        end = versions[k + 1][0] if k + 1 < len(versions) else None
        live = np.ones(n, dtype=bool)
        if start is not None:
            live &= days >= start
        if end is not None:
            live &= days < end
        if not live.any():
            continue
        eps = [pos[s] for d, tm in events for s in ri.affected_sessions(cfg, d, tm) if s in pos]
        win = mark_window(n, eps, h) & live
        earn |= win
        moves = ri.past_moves(cfg, c, sigma, events, rc["warmup_bars"])
        for i in np.flatnonzero(win):
            mh[i] = ri.earnings_stats(moves, rc, idx[i].date())[0]
    cols["earn"] = earn
    cols["m_hist"] = mh
    # dividends: log shift for ex-dates inside (d, d+h]
    shift = np.zeros(n)
    for d, a in extra["dividends"].get(t, []):
        p = pos.get(ev.next_session(cfg, d))
        if p is None or not a:
            continue
        for i in range(max(0, p - h), p):
            shift[i] += rl.ex_dividend_shift(float(c.iloc[i]), [a])
    cols["div_shift"] = shift
    cols["has_div"] = shift != 0
    # cues
    bench = extra["bench"]
    cols["beta"] = rolling_beta(c, bench["close"]).clip(*rc["beta_split"]["beta_clip"])
    cols["own"] = np.log(df["open"].shift(-1) / c) if cfg.get("premarket_quotes") else np.nan
    cols["idx_cue"] = extra["index_cue"].reindex(idx) if extra["index_cue"] is not None else np.nan
    cols["has_cue"] = cols["idx_cue"].notna() & cols["beta"].notna()
    return cols


def score(base: float, y: float, center: float, sh: float, q: tuple) -> dict:
    q10, q25, q75, q90 = q
    lo50, hi50 = base * math.exp(center + q25 * sh), base * math.exp(center + q75 * sh)
    lo80, hi80 = base * math.exp(center + q10 * sh), base * math.exp(center + q90 * sh)
    return {"hit50": lo50 <= y <= hi50, "hit80": lo80 <= y <= hi80,
            "width80": 100 * (hi80 - lo80) / base, "is80": 100 * rl.interval_score(lo80, hi80, y, 0.8) / base}


def arm_params(o, h: int, rc: dict, use: dict) -> dict[str, tuple[float, float]]:
    """(centre, horizon sigma) per arm for one observation. `configured` = the inputs switched on
    in config/ranges.yaml for this market; `current` = the formula before these inputs."""
    sd = o.sigma
    var = sd * sd * h
    fixed = rc["earnings_vol_multiple"]
    earn = bool(getattr(o, "earn", False))
    m_hist = o.m_hist if earn and o.m_hist == o.m_hist else fixed
    sh = {"core": math.sqrt(var),
          "fixed": math.sqrt(var + (fixed ** 2 - 1) * sd * sd) if earn else math.sqrt(var),
          "hist": math.sqrt(var + (m_hist ** 2 - 1) * sd * sd) if earn else math.sqrt(var)}
    own = o.own if o.own == o.own else None
    idx_cue = o.idx_cue if o.idx_cue == o.idx_cue else None
    beta = o.beta if o.beta == o.beta else None
    direct = rc["cue_weight"] * own if own is not None else 0.0
    bs = rc["beta_split"]
    split = rl.beta_split_center(beta, idx_cue, own, bs["index_weight"], bs["own_weight"], rc["cue_weight"])
    cap = lambda x, s: max(-rc["max_center_shift_sigma"] * s, min(rc["max_center_shift_sigma"] * s, x))  # noqa: E731
    div = o.div_shift
    s_cfg = sh["hist"] if use.get("earnings_history") else sh["fixed"]
    return {"core": (0.0, sh["core"]), "earn_fixed": (0.0, sh["fixed"]), "earn_hist": (0.0, sh["hist"]),
            "exdiv": (div, sh["core"]),
            "cue_direct": (cap(direct, sh["core"]), sh["core"]), "cue_beta": (cap(split, sh["core"]), sh["core"]),
            "current": (cap(direct, sh["fixed"]), sh["fixed"]),
            "configured": (cap(split if use.get("beta_split") else direct, s_cfg)
                           + (div if use.get("ex_dividend") else 0.0), s_cfg)}


def evaluate(obs: pd.DataFrame, h: int, rc: dict, eval_sessions: int, use: dict | None = None, *,
             scale: dict[int, float] | None = None) -> pd.DataFrame:
    """`use`: the range inputs switched on (config/ranges.yaml) for the per-input arms.
    `scale` (keyword only) widens sigma per start rank (regime/event factors replayed by review.py)."""
    last = int(obs["rank"].max())
    start = last - eval_sessions + 1
    z_all, r_all = obs["z"].to_numpy(), obs["rank"].to_numpy()
    with_inputs = "earn" in obs.columns
    rows = []
    for d in range(start, last + 1):
        known = (r_all + h <= d) & (r_all > d - rc["history_sessions"])
        if known.sum() < rc["min_pool"]:
            continue
        w = rl.recency_weights((d - r_all[known]).astype(float), rc["half_life_sessions"])
        z = z_all[known]
        q = tuple(rl.weighted_quantile(z, w, p) for p in (0.10, 0.25, 0.75, 0.90))
        today = obs[obs["rank"] == d]
        for o in today.itertuples():
            base, sh = o.close, o.sigma * math.sqrt(h) * (scale.get(d, 1.0) if scale else 1.0)
            y = base * math.exp(o.fwd)
            core = score(base, y, 0.0, sh, q)
            lo50, hi50 = base * math.exp(q[1] * sh), base * math.exp(q[2] * sh)
            n50, n80 = rl.naive_range(base, o.s20, h, 0.5), rl.naive_range(base, o.s20, h, 0.8)
            row = {
                "rank": d, "ticker": o.ticker,
                "hit50": core["hit50"], "hit80": core["hit80"],
                "naive_hit50": n50[0] <= y <= n50[1], "naive_hit80": n80[0] <= y <= n80[1],
                "width80": core["width80"], "naive_width80": 100 * (n80[1] - n80[0]) / base,
                "is80": core["is80"],
                "naive_is80": 100 * rl.interval_score(n80[0], n80[1], y, 0.8) / base,
                "is50": 100 * rl.interval_score(lo50, hi50, y, 0.5) / base,
                "naive_is50": 100 * rl.interval_score(n50[0], n50[1], y, 0.5) / base,
            }
            if with_inputs:
                row.update({"earn": bool(o.earn), "has_div": bool(o.has_div), "has_cue": bool(o.has_cue)})
                for arm, (center, s) in arm_params(o, h, rc, use or {}).items():
                    for k, v in score(base, y, center, s, q).items():
                        row[f"{arm}_{k}"] = v
            rows.append(row)
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


def arm_summary(res: pd.DataFrame, arm: str) -> dict:
    if res.empty:
        return {"n": 0}
    return {"n": int(len(res)), "cover50": round(float(res[f"{arm}_hit50"].mean()), 3),
            "cover80": round(float(res[f"{arm}_hit80"].mean()), 3),
            "width80_pct": round(float(res[f"{arm}_width80"].mean()), 3),
            "score80": round(float(res[f"{arm}_is80"].mean()), 4)}


def verdict(off: dict, on: dict, min_gain: float) -> str:
    """DESIGN section 7 rule: improves only if the interval score drops by more than min_gain
    (relative); a change within it is noise."""
    if not off.get("n"):
        return "no data"
    a, b = off["score80"], on["score80"]
    if a == b:
        return "same"
    gain = (a - b) / a
    return "improves" if gain > min_gain else ("worse" if gain < -min_gain else "noise")


def compare_inputs(res: pd.DataFrame, min_gain: float = 0.005) -> dict:
    out = {}
    for name, (off, on, col) in INPUTS.items():
        sub = res[res[col]] if col in res.columns else res.iloc[0:0]
        a, b = arm_summary(sub, off), arm_summary(sub, on)
        out[name] = {"applies": a["n"], "off": a, "on": b, "verdict": verdict(a, b, min_gain)}
    if len(res):
        a, b = arm_summary(res, "current"), arm_summary(res, "configured")
        out["all_inputs"] = {"applies": int(len(res)), "off": a, "on": b, "verdict": verdict(a, b, min_gain)}
    out["implied_vol"] = {"verdict": "live only (no stored option history)"}
    return out


def run(cfg: dict, rc: dict, eval_sessions: int) -> dict:
    con = connect(cfg["market"])
    bars = load_bars(con)
    bench = bars.get(benchmark_key(cfg))
    if bench is None:
        raise SystemExit(MSG_NO_BENCHMARK_BARS_PERIOD)
    rank = {d: i for i, d in enumerate(bench.index)}
    evdf = ri.load_events(con)
    extra = {"earnings": ri.earnings_versions(evdf), "dividends": ri.dividend_events(evdf), "bench": bench,
             "index_cue": index_cue_series(cfg, bars, rc)}
    out = {"market": cfg["market"], "as_of_date": str(bench.index[-1].date()), "horizons": {}, "by_ticker": {},
           "inputs": {}, "event_history": {"earnings": sum(len(v[-1][1]) for v in extra["earnings"].values()),
                                           "dividends": sum(map(len, extra["dividends"].values()))}}
    for h in rc["horizons"]:
        use = {k: ri.enabled(rc, k, cfg["market"], h) for k in INPUTS}
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


def main() -> int:
    ap = market_arg(__doc__)
    ap.add_argument("--eval-sessions", type=int, default=250, help="trading days to evaluate (default 250)")
    ap.add_argument("--out", help="write the report here instead of reports/<market>/")
    args = ap.parse_args()
    cfg = require_market(args)
    rc = load_ranges_config(cfg["market"])
    s = run(cfg, rc, args.eval_sessions)
    path = Path(args.out) if args.out else ROOT / "reports" / cfg["market"] / f"backtest-{s['as_of_date']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(cfg, s))
    print(json.dumps({"step": "backtest", "report": str(path), "horizons": s["horizons"],
                      "inputs": s["inputs"], "event_history": s["event_history"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
