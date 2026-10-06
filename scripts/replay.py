#!/usr/bin/env python3
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

import bisect
import html
import json
import math
import sys
import time
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd

import backtest as bt
from marketbrief.analytics import adaptive_conformal as aci, event_history, range_switches
from marketbrief.analytics import indicators as ind, range_math as rl, regime as rg, scoring as sc
from marketbrief.constants.range_inputs import INPUTS
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.core.clock import utc_now
from marketbrief.core.market_config import benchmark_key, load_ranges_config, vol_index_key
from marketbrief.constants.messages import MSG_NO_BENCHMARK_BARS_PERIOD
from marketbrief.utils.event_dates import major_event_between
from marketbrief.utils.numbers import round_or_none, share_percent_text
from marketbrief.analytics.features import load_bars
from marketbrief.core import calendar as ev, cli, database, paths, storage

LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)   # calibration curve (stated coverage)
SIGNALS = ("always_up", "momentum_1d", "momentum_5d", "rsi_reversion")
SIGNAL_LABELS = {"always_up": "Always up", "momentum_1d": "1-day momentum", "momentum_5d": "5-day momentum",
                 "rsi_reversion": "RSI(14) mean reversion"}
RSI_LOW, RSI_HIGH = 30.0, 70.0
DEFAULT_LEVELS = {"q10": 0.10, "q25": 0.25, "q75": 0.75, "q90": 0.90}   # fixed band quantiles (ACI off)
MIN_MONTH_DAYS = 5   # the coverage-over-time chart leaves out months with fewer as-of days (kept in the JSON)


# ---------- inputs as known at d ----------

def known_versions(cfg: dict, versions: dict) -> dict:
    """Shift each earnings version's start (a 10-Q/10-K acceptance date c) to the last session before
    c: ranges.py made pre-open on session S uses the reports accepted by S, so as-of d (S = the next
    session after d) sees the version once d >= that session. backtest.input_columns then applies it."""
    return {t: [(None if s is None else ev.prev_session(cfg, s, include=False), e) for s, e in vs]
            for t, vs in versions.items()}


def next_earnings(versions: list, d: date) -> date | None:
    """The first earnings date after d in the version active pre-open the next session (the
    historical stand-in for ranges.py's upcoming `company_events` date when earnings_history is off)."""
    if not versions:
        return None
    starts = [date.min if s is None else s for s, _ in versions]
    k = bisect.bisect_right(starts, d) - 1
    if k < 0:
        return None
    dates = [x for x, _ in versions[k][1]]
    j = bisect.bisect_right(dates, d)
    return dates[j] if j < len(dates) else None


def regimes(cfg: dict, bars: dict, days: list[date]) -> pd.DataFrame:
    """Regime per as-of day as features.py computes it (closes stand in for pre-open vol quotes)."""
    bench = bars[benchmark_key(cfg)]["close"]
    vk = vol_index_key(cfg)
    vol = bars[vk]["close"] if vk in bars else pd.Series(dtype=float)
    vdates = [x.date() for x in vol.index]
    bdates = [x.date() for x in bench.index]
    mev = ev.market_events(cfg, days[0], days[-1] + timedelta(days=40)) if days else []
    rows = []
    for d in days:
        i = bisect.bisect_right(bdates, d)
        tail = bench.iloc[max(0, i - 31):i]
        j = bisect.bisect_right(vdates, d)
        lvl = float(vol.iloc[j - 1]) if j >= 1 else None
        prev = float(vol.iloc[j - 2]) if j >= 2 else None
        change = lvl / prev - 1 if lvl is not None and prev else None
        session = ev.next_session(cfg, d, include=False)
        near = ev.major_events_near(mev, session)
        r5, v10 = ind.period_return(tail, 5), ind.realized_vol(tail)
        label, stress, _ = rg.classify(cfg["regime"], lvl, r5, v10, bool(near), change)
        rows.append({"date": d, "regime": label, "stress": stress, "vol_level": lvl, "bench_ret_5d": r5,
                     "bench_vol_10d": v10, "major_event": bool(near)})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def major_dates(cfg: dict, start: date, end: date) -> list[date]:
    return sorted({e["date"] for e in ev.market_events(cfg, start, end) if e["major"]})


def rsi_series(close: pd.Series, n: int = 14) -> pd.Series:
    """indicators.rsi at every date (the same causal Wilder smoothing, so the value at d equals
    indicators.rsi(close[:d]); tests/test_replay.py checks it)."""
    diff = close.diff()
    gain = diff.clip(lower=0).iloc[1:].ewm(alpha=1 / n, adjust=False).mean()
    loss = (-diff.clip(upper=0)).iloc[1:].ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + gain / loss)
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0))
    out = out.reindex(close.index)
    out.iloc[:n] = np.nan
    return out


# ---------- the replay ----------

def ticker_frame(cfg: dict, rc: dict, df: pd.DataFrame, t: str, h: int, extra: dict) -> pd.DataFrame:
    """Per as-of date of one ticker: close, EWMA sigma, 20-day sigma (naive), outcome, range inputs."""
    c = df["close"]
    f = pd.DataFrame({"close": c, "sigma": rl.ewma_sigma(c, rc["ewma_lambda"]),
                      "s20": np.log(c / c.shift(1)).rolling(20).std(ddof=1),
                      "fwd": np.log(c.shift(-h) / c), "bars": np.arange(1, len(c) + 1),
                      "ret1": c / c.shift(1) - 1, "ret5": c / c.shift(5) - 1, "rsi": rsi_series(c)})
    f = f.join(bt.input_columns(cfg, rc, df, t, h, extra))
    f["own"] = np.nan                      # no stored pre-market/ADR history (next open = look-ahead)
    if (cfg.get("index_cue") or {}).get("beta", 1.0) != "fit":
        f["idx_cue"] = np.nan              # numeric beta: futures before the open, not stored
    f["target"] = pd.Series(df.index, index=df.index).shift(-h)
    return f


def replay_horizon(cfg: dict, rc: dict, bars: dict, h: int, days: list[date], reg: pd.DataFrame,
                   extra: dict, rank: dict, majors: list[date]) -> pd.DataFrame:
    mk = cfg["market"]
    use = {k: range_switches.enabled(rc, k, mk, h) for k in INPUTS}
    pool = bt.observations(bars, cfg["tickers"], h, rc, rank)
    z_all = pool["z"].to_numpy() if len(pool) else np.array([])
    r_all = pool["rank"].to_numpy() if len(pool) else np.array([])
    frames = {t: ticker_frame(cfg, rc, bars[t], t, h, extra) for t in cfg["tickers"] if t in bars}
    day_ts = [pd.Timestamp(d) for d in days]
    nd = NormalDist()
    normal = {"q10": rl.normal_quantiles(0.8)[0], "q25": rl.normal_quantiles(0.5)[0],
              "q75": rl.normal_quantiles(0.5)[1], "q90": rl.normal_quantiles(0.8)[1]}
    fixed = rc["earnings_vol_multiple"]
    bs = rc["beta_split"]
    # ACI (adaptive_conformal.py; off unless config/ranges.yaml or --aci switches it on): each day's quantile levels
    # come from the misses of ranges whose target close is on or before d (known pre-open next session)
    tracker = aci.Tracker(rc) if range_switches.enabled(rc, "aci", mk, h) else None
    pending: dict[int, dict[str, list]] = {}   # target rank -> key -> [n, misses50, misses80]
    rows = []
    for d, ts in zip(days, day_ts):
        rd = rank.get(ts)
        if rd is None:
            continue
        regime = reg.loc[d, "regime"] if d in reg.index else "EVENT_HEAVY"
        levels, akey = DEFAULT_LEVELS, None
        if tracker is not None:
            for tr in sorted(k for k in pending if k <= rd):
                for key, (n, m50, m80) in sorted(pending.pop(tr).items()):
                    tracker.update(h, "50", key, m50 / n)
                    tracker.update(h, "80", key, m80 / n)
            akey = tracker.key(regime)
            levels = tracker.levels(h, akey)
        known = (r_all + h <= rd) & (r_all > rd - rc["history_sessions"])
        if known.sum() >= rc["min_pool"]:       # calibrate.py: pool quantiles, else normal ones
            z, w = z_all[known], rl.recency_weights((rd - r_all[known]).astype(float), rc["half_life_sessions"])
            q = {k: rl.weighted_quantile(z, w, p) for k, p in levels.items()}
            order = np.argsort(z)
            zs, ws = z[order], w[order]
            cum = np.cumsum(ws) - 0.5 * ws
            pit = lambda x: float(np.interp(x, zs, cum) / ws.sum())   # noqa: E731  (inverse of weighted_quantile)
            source = "pool"
        else:
            q = normal if levels is DEFAULT_LEVELS else {k: nd.inv_cdf(p) for k, p in levels.items()}
            pit, source = nd.cdf, "normal"
        tgt_cal = ev.sessions_ahead(cfg, d + timedelta(days=1), h)[-1]   # ranges.target_date
        major = major_event_between(majors, d, tgt_cal)
        for t, f in frames.items():
            if ts not in f.index:
                continue
            o = f.loc[ts]
            sd = o["sigma"]
            if not (sd > 0 and math.isfinite(sd)) or o["bars"] < 31 or not math.isfinite(o["close"]):
                continue   # ranges.py needs ewma_vol (31 bars)
            base = float(o["close"])
            if use["earnings_history"]:
                in_h = bool(o["earn"])
                m_hist = o["m_hist"] if in_h and o["m_hist"] == o["m_hist"] else None
                mult = m_hist if m_hist is not None and m_hist != fixed else None
            else:
                e = next_earnings(extra["earnings"].get(t, []), d)
                in_h, mult = bool(e and e <= tgt_cal), None
            sigma_h, _ = rl.horizon_sigma(float(sd), h, in_h, rc, regime, major, mult)
            center = 0.0
            beta, idx_cue = o["beta"], o["idx_cue"]
            if use["beta_split"] and idx_cue == idx_cue and beta == beta:
                center += rl.beta_split_center(float(beta), float(idx_cue), None, bs["index_weight"],
                                               bs["own_weight"], rc["cue_weight"])
            cap = rc["max_center_shift_sigma"] * sigma_h
            center = max(-cap, min(cap, center))
            if use["ex_dividend"] and o["div_shift"]:
                center += float(o["div_shift"])
            band = lambda zq: base * math.exp(center + zq * sigma_h)  # noqa: E731
            row = {"date": d, "ticker": t, "rank": rd, "h": h, "regime": regime, "base": base,
                   "alpha50": 2 * levels["q25"], "alpha80": 2 * levels["q10"],
                   "center": center, "sigma_h": sigma_h, "q_source": source, "earn": in_h,
                   "div": bool(use["ex_dividend"] and o["div_shift"]), "major": major,
                   "lo50": band(q["q25"]), "hi50": band(q["q75"]), "lo80": band(q["q10"]), "hi80": band(q["q90"]),
                   "target_date": tgt_cal, "ret1": o["ret1"], "ret5": o["ret5"], "rsi": o["rsi"]}
            s20 = o["s20"]
            if s20 == s20 and s20 > 0:
                row["naive_lo50"], row["naive_hi50"] = rl.naive_range(base, float(s20), h, 0.5)
                row["naive_lo80"], row["naive_hi80"] = rl.naive_range(base, float(s20), h, 0.8)
            if o["fwd"] == o["fwd"]:
                y = base * math.exp(float(o["fwd"]))
                zeff = (float(o["fwd"]) - center) / sigma_h
                row.update({"actual": y, "bar_target": o["target"].date(), "fwd": float(o["fwd"]),
                            "hit50": row["lo50"] <= y <= row["hi50"], "hit80": row["lo80"] <= y <= row["hi80"],
                            "width50": 100 * (row["hi50"] - row["lo50"]) / base,
                            "width80": 100 * (row["hi80"] - row["lo80"]) / base,
                            "is50": 100 * rl.interval_score(row["lo50"], row["hi50"], y, 0.5) / base,
                            "is80": 100 * rl.interval_score(row["lo80"], row["hi80"], y, 0.8) / base,
                            "abs_err": 100 * abs(math.exp(float(o["fwd"])) - math.exp(center)), "pit": pit(zeff),
                            "qs": sc.range_scores_row(row["lo50"], row["hi50"], row["lo80"], row["hi80"], y, base)["qs_pct"]})
                if tracker is not None:   # the outcome becomes known at the target close (rank rd + h)
                    acc = pending.setdefault(rd + h, {}).setdefault(akey, [0, 0, 0])
                    acc[0] += 1
                    acc[1] += not row["hit50"]
                    acc[2] += not row["hit80"]
                if "naive_lo80" in row:
                    row.update({"naive_hit50": row["naive_lo50"] <= y <= row["naive_hi50"],
                                "naive_hit80": row["naive_lo80"] <= y <= row["naive_hi80"],
                                "naive_width80": 100 * (row["naive_hi80"] - row["naive_lo80"]) / base,
                                "naive_is50": 100 * rl.interval_score(row["naive_lo50"], row["naive_hi50"], y, 0.5) / base,
                                "naive_is80": 100 * rl.interval_score(row["naive_lo80"], row["naive_hi80"], y, 0.8) / base})
            rows.append(row)
    return pd.DataFrame(rows)


def window_days(bench: pd.DataFrame, rc: dict, start: date | None, end: date | None) -> list[date]:
    idx = [x.date() for x in bench.index]
    first = idx[min(rc["warmup_bars"], len(idx) - 1)] if idx else None
    lo = max(start, first) if start else first
    return [d for d in idx if lo and d >= lo and (end is None or d <= end)]


def load_inputs(cfg: dict, rc: dict, con) -> tuple[dict, dict]:
    bars = load_bars(con)
    bench = bars.get(benchmark_key(cfg))
    if bench is None or bench.empty:
        raise SystemExit(MSG_NO_BENCHMARK_BARS_PERIOD)
    evdf = event_history.load_events(con)
    extra = {"earnings": known_versions(cfg, event_history.earnings_versions(evdf)) if not evdf.empty else {},
             "dividends": event_history.dividend_events(evdf) if not evdf.empty else {}, "bench": bench,
             "index_cue": bt.index_cue_series(cfg, bars, rc) if range_switches.enabled(rc, "beta_split", cfg["market"]) else None}
    return bars, extra


def replay_rows(cfg: dict, rc: dict, bars: dict, extra: dict, start: date | None = None,
                end: date | None = None) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """Range rows per horizon (one per as-of day x ticker; scored where the outcome is stored) and
    the regime per day. Everything at d uses only what is known pre-open the next session."""
    bench = bars[benchmark_key(cfg)]
    days = window_days(bench, rc, start, end)
    rank = {x: i for i, x in enumerate(bench.index)}
    reg = regimes(cfg, bars, days)
    majors = major_dates(cfg, days[0], days[-1] + timedelta(days=30)) if days else []
    out = {h: replay_horizon(cfg, rc, bars, h, days, reg, extra, rank, majors) for h in rc["horizons"]}
    return out, reg


# ---------- statistics ----------

wilson = sc.wilson   # Wilson score interval (scoring.py)


def binom_p_two_sided(k: int, n: int, p: float = 0.5) -> float | None:
    """Exact two-sided binomial test (sum of outcomes no more likely than k)."""
    if not n:
        return None
    lp = lambda i: (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)  # noqa: E731
                    + i * math.log(p) + (n - i) * math.log(1 - p))
    ref = lp(k)
    total = sum(math.exp(lp(i)) for i in range(n + 1) if lp(i) <= ref + 1e-9)
    return min(1.0, total)


def clustered_ci(values: np.ndarray, blocks: np.ndarray, zc: float = 1.96) -> tuple[float | None, float | None]:
    """95% interval of a mean when rows in the same date block move together (all stocks share a
    day; 5-day outcomes overlap): ratio estimator with block-level residuals."""
    n = len(values)
    if n == 0:
        return None, None
    m = float(values.mean())
    df = pd.DataFrame({"v": values - m, "b": blocks})
    s = df.groupby("b")["v"].sum().to_numpy()
    nb = len(s)
    if nb < 2:
        return None, None
    se = math.sqrt((s ** 2).sum() * nb / (nb - 1)) / n
    return m - zc * se, m + zc * se


def range_summary(g: pd.DataFrame, h: int) -> dict:
    g = g[g["actual"].notna()] if "actual" in g.columns else g.iloc[0:0]
    if g.empty:
        return {"n": 0}
    blocks = (g["rank"] // max(h, 1)).to_numpy()
    hit80 = g["hit80"].astype(float).to_numpy()
    lo, hi = clustered_ci(hit80, blocks)
    nv = g[g["naive_hit80"].notna()] if "naive_hit80" in g.columns else g.iloc[0:0]
    out = {"n": int(len(g)), "days": int(g["date"].nunique()),
           "cover50": round_or_none(g["hit50"].mean()), "cover80": round_or_none(g["hit80"].mean()),
           "cover80_ci": [round_or_none(lo), round_or_none(hi)],
           "width50_pct": round_or_none(g["width50"].mean(), 3), "width80_pct": round_or_none(g["width80"].mean(), 3),
           "score50": round_or_none(g["is50"].mean(), 3), "score80": round_or_none(g["is80"].mean(), 3),
           "qs_pct": round_or_none(g["qs"].mean(), 4) if "qs" in g else None,
           "abs_err_pct": round_or_none(g["abs_err"].mean(), 3)}
    if len(nv):
        out.update({"naive_n": int(len(nv)), "naive_cover50": round_or_none(nv["naive_hit50"].astype(float).mean()),
                    "naive_cover80": round_or_none(nv["naive_hit80"].astype(float).mean()),
                    "naive_width80_pct": round_or_none(nv["naive_width80"].mean(), 3),
                    "naive_score50": round_or_none(nv["naive_is50"].mean(), 3),
                    "naive_score80": round_or_none(nv["naive_is80"].mean(), 3),
                    "score80_same_rows": round_or_none(nv["is80"].mean(), 3)})
    return out


def calibration(g: pd.DataFrame) -> list[dict]:
    g = g[g["actual"].notna()] if "actual" in g.columns else g.iloc[0:0]
    if g.empty:
        return []
    u = g["pit"].to_numpy()
    out = []
    for lv in LEVELS:
        lo, hi = 0.5 - lv / 2, 0.5 + lv / 2
        out.append({"stated": lv, "actual": round_or_none(((u >= lo) & (u <= hi)).mean()),
                    "published": lv in (0.5, 0.8)})
    for p in out:   # the published bands are scored on the bands themselves
        if p["stated"] == 0.5:
            p["actual"] = round_or_none(g["hit50"].mean())
        elif p["stated"] == 0.8:
            p["actual"] = round_or_none(g["hit80"].mean())
    return out


def signals(g: pd.DataFrame) -> dict[str, pd.Series]:
    """Direction per row: +1 up, -1 down, 0 abstain."""
    sgn = lambda s: np.sign(s.fillna(0.0))  # noqa: E731
    rsi = g["rsi"]
    return {"always_up": pd.Series(1.0, index=g.index),
            "momentum_1d": sgn(g["ret1"]), "momentum_5d": sgn(g["ret5"]),
            "rsi_reversion": pd.Series(np.where(rsi < RSI_LOW, 1.0, np.where(rsi > RSI_HIGH, -1.0, 0.0)), index=g.index)}


def baseline_stats(g: pd.DataFrame, h: int) -> dict:
    """Hit rate per baseline signal (a flat close is a miss for both directions, as score_predictions.py)."""
    g = g[g["actual"].notna()] if "actual" in g.columns else g.iloc[0:0]
    if g.empty:
        return {}
    up, down = g["fwd"] > 0, g["fwd"] < 0
    au_hit = up.astype(float)
    blocks = (g["rank"] // max(h, 1)).to_numpy()
    out = {}
    for name, s in signals(g).items():
        call = s != 0
        hit = ((s > 0) & up) | ((s < 0) & down)
        n, k = int(call.sum()), int(hit[call].sum())
        rate = k / n if n else None
        lo, hi = clustered_ci(hit[call].astype(float).to_numpy(), blocks[call.to_numpy()])
        wl, wh = wilson(k, n)
        diff = (hit[call].astype(float) - au_hit[call]).to_numpy()
        dlo, dhi = clustered_ci(diff, blocks[call.to_numpy()])
        out[name] = {"label": SIGNAL_LABELS[name], "calls": n, "coverage": round_or_none(n / len(g)), "hits": k,
                     "hit_rate": round_or_none(rate), "ci95": [round_or_none(lo), round_or_none(hi)],
                     "ci95_iid": [round_or_none(wl), round_or_none(wh)],
                     "p_vs_50": None if not n else float(f"{binom_p_two_sided(k, n):.3g}"),
                     "always_up_same_rows": round_or_none(au_hit[call].mean()) if n else None,
                     "diff_vs_always_up": round_or_none(diff.mean()) if n else None,
                     "diff_ci95": [round_or_none(dlo), round_or_none(dhi)]}
    return out


def summarize(cfg: dict, rc: dict, res: dict[int, pd.DataFrame], reg: pd.DataFrame) -> dict:
    sector = {t: m.get("sector") or "Other" for t, m in cfg["tickers"].items()}
    out = {"horizons": {}, "baselines": {}}
    for h, g in res.items():
        if g.empty:
            out["horizons"][str(h)] = {"overall": {"n": 0}}
            continue
        g = g.assign(sector=g["ticker"].map(sector), month=g["date"].map(lambda d: d.strftime("%Y-%m")),
                     year=g["date"].map(lambda d: str(d.year)))
        hs = {"overall": range_summary(g, h), "unscored_rows": int(g["actual"].isna().sum()) if "actual" in g else len(g),
              "calibration": calibration(g)}
        for key, col in (("by_regime", "regime"), ("by_sector", "sector"), ("by_ticker", "ticker"),
                         ("by_month", "month"), ("by_year", "year")):
            hs[key] = {str(k): range_summary(x, h) for k, x in g.groupby(col)}
        hs["by_regime"] = {k: hs["by_regime"][k] for k in REGIME_ORDER if k in hs["by_regime"]}
        hs["by_earnings"] = {"earnings in horizon": range_summary(g[g["earn"]], h),
                             "no earnings": range_summary(g[~g["earn"]], h)}
        hs["by_major_event"] = {"major event in horizon": range_summary(g[g["major"]], h),
                                "no major event": range_summary(g[~g["major"]], h)}
        sc = g[g["actual"].notna()] if "actual" in g else g.iloc[0:0]
        hs["calendar_mismatch"] = int((sc["bar_target"] != sc["target_date"]).sum()) if len(sc) else 0
        hs["pool_fallback_days"] = int(g.loc[g["q_source"] == "normal", "date"].nunique())
        last = g[g["date"] == g["date"].max()]
        hs["alpha"] = {"mean50": round_or_none(g["alpha50"].mean()), "mean80": round_or_none(g["alpha80"].mean()),
                       "last50": round_or_none(last["alpha50"].iloc[0]),
                       "last80": round_or_none(last["alpha80"].iloc[0])}
        out["horizons"][str(h)] = hs
        out["baselines"][str(h)] = baseline_stats(g, h)
    counts = reg["regime"].value_counts() if not reg.empty else pd.Series(dtype=int)
    out["regime_days"] = {k: int(counts.get(k, 0)) for k in REGIME_ORDER}
    out["regime_timeline"] = [{"date": str(d), "regime": r} for d, r in reg["regime"].items()] if not reg.empty else []
    return out


# ---------- plain-language summary ----------

def pct(x, k: int = 0) -> str:
    """A share as a whole percent by default (`k` decimals when given); 'n/a' when missing."""
    return share_percent_text(x, k)


def headline(cfg: dict, s: dict) -> list[str]:
    lines = []
    for h, hs in s["horizons"].items():
        o = hs["overall"]
        if not o.get("n"):
            continue
        c80, c50 = o["cover80"], o["cover50"]
        verdict = ("about right" if abs(c80 - 0.8) <= 0.03 else
                   ("too narrow: the price fell outside more often than promised" if c80 < 0.8 else
                    "too wide: the price stayed inside more often than needed"))
        ci = o["cover80_ci"]
        lines.append(f"{h}-day ranges: the 80% band contained the actual close {pct(c80, 1)} of the time "
                     f"(95% interval {pct(ci[0], 1)} to {pct(ci[1], 1)}; target 80%) and the 50% band "
                     f"{pct(c50, 1)} (target 50%) over {o['n']:,} ranges on {o['days']} days: {verdict}.")
        if o.get("naive_score80") is not None:
            better = o["score80_same_rows"] < o["naive_score80"]
            lines.append(f"{h}-day accuracy vs the naive range (last close +/- 20-day volatility): interval score "
                         f"{o['score80_same_rows']:.2f} vs {o['naive_score80']:.2f} (lower is better), width "
                         f"{o['width80_pct']:.2f}% vs {o['naive_width80_pct']:.2f}% of the price; the formula is "
                         f"{'better' if better else 'not better'} than the naive range.")
        regs = {k: v for k, v in hs["by_regime"].items() if v.get("n", 0) >= 100}
        if regs:
            worst = min(regs.items(), key=lambda kv: kv[1]["cover80"])
            best = max(regs.items(), key=lambda kv: kv[1]["cover80"])
            lines.append(f"{h}-day by regime: 80% coverage ranges from {pct(worst[1]['cover80'], 1)} in {worst[0]} "
                         f"to {pct(best[1]['cover80'], 1)} in {best[0]}.")
        e = hs["by_earnings"]["earnings in horizon"]
        if e.get("n"):
            lines.append(f"{h}-day with earnings inside the horizon: 80% coverage {pct(e['cover80'], 1)} "
                         f"over {e['n']} ranges (no earnings: {pct(hs['by_earnings']['no earnings'].get('cover80'), 1)}).")
        tick = {k: v for k, v in hs["by_ticker"].items() if v.get("n", 0) >= 50}
        low = sorted(tick.items(), key=lambda kv: kv[1]["cover80"])[:3]
        if low:
            lines.append(f"{h}-day lowest 80% coverage by ticker: "
                         + ", ".join(f"{t} {pct(v['cover80'], 1)}" for t, v in low) + ".")
    for h, b in s["baselines"].items():
        au = b.get("always_up")
        if not au:
            continue
        parts = []
        for name in SIGNALS[1:]:
            x = b.get(name)
            if not x or not x["calls"]:
                continue
            d, ci = x["diff_vs_always_up"], x["diff_ci95"]
            sig = ci[0] is not None and (ci[0] > 0 or ci[1] < 0)
            parts.append(f"{x['label']} {pct(x['hit_rate'], 1)} ({x['calls']:,} calls, "
                         f"{'+' if d >= 0 else ''}{100 * d:.1f} pts vs always-up on the same rows"
                         f"{', clear' if sig else ', within noise'})")
        lines.append(f"{h}-day direction baselines: always-up was right {pct(au['hit_rate'], 1)} of the time "
                     f"(95% interval {pct(au['ci95'][0], 1)} to {pct(au['ci95'][1], 1)}); " + "; ".join(parts) + ".")
    return lines


def _groups(hs: dict, min_n: int = 100) -> dict[str, dict]:
    """Named slices of one horizon (regimes, earnings or a major event in the horizon) with enough rows."""
    out = {f"{k} markets": v for k, v in hs.get("by_regime", {}).items()}
    out["earnings inside the horizon"] = hs.get("by_earnings", {}).get("earnings in horizon", {})
    out["a major market event inside the horizon"] = hs.get("by_major_event", {}).get("major event in horizon", {})
    return {k: v for k, v in out.items() if v.get("n", 0) >= min_n and v.get("cover80") is not None}


def top_sentences(s: dict) -> list[str]:
    """At most three short sentences for the top of the page, one per question (exact figures, one decimal)."""
    hz, out = s["horizons"], []
    o = {h: hz.get(h, {}).get("overall", {}) for h in ("1", "5")}
    if o["1"].get("n") and o["5"].get("n"):
        c = [o["1"]["cover80"], o["5"]["cover80"]]
        verdict = ("about right" if all(abs(x - 0.8) <= 0.03 for x in c) else
                   "too wide (they held more often than promised)" if all(x > 0.8 for x in c) else
                   "too narrow (they held less often than promised)" if all(x < 0.8 for x in c) else "mixed")
        out.append(f"Do the ranges keep their promise? The 80% ranges contained the later close {pct(c[0], 1)} of the "
                   f"time 1 day ahead and {pct(c[1], 1)} 5 days ahead, and the 50% ranges {pct(o['1']['cover50'], 1)} "
                   f"and {pct(o['5']['cover50'], 1)}, so overall they are {verdict}.")
    parts = []
    for h in ("1", "5"):
        g = _groups(hz.get(h, {}))
        if not g:
            continue
        hi = max(g.items(), key=lambda kv: kv[1]["cover80"])
        lo = min(g.items(), key=lambda kv: kv[1]["cover80"])
        prep = lambda name: "in" if name.endswith("markets") else "with"  # noqa: E731
        hi_txt = (f"{'widest' if hi[1]['cover80'] > 0.8 else 'closest to 80%'} {prep(hi[0])} {hi[0]} "
                  f"({pct(hi[1]['cover80'], 1)} held)")
        lo_txt = (f"{'too narrow' if lo[1]['cover80'] < 0.8 else 'closest to 80%'} {prep(lo[0])} {lo[0]} "
                  f"({pct(lo[1]['cover80'], 1)})")
        parts.append(f"{h}-day ranges were {hi_txt} and {lo_txt}")
    if parts:
        out.append("Where are they too wide or too narrow? " + "; ".join(parts) + ".")
    b = s.get("baselines", {})
    au = {h: (b.get(h) or {}).get("always_up") for h in ("1", "5")}
    if au["1"] and au["5"]:
        better, worse, noise = [], 0, 0
        for h in ("1", "5"):
            for name in SIGNALS[1:]:
                x = (b.get(h) or {}).get(name)
                if not x or not x["calls"] or x["diff_ci95"][0] is None:
                    continue
                if x["diff_ci95"][0] > 0:
                    better.append(f"{x['label']} {h}-day (+{100 * x['diff_vs_always_up']:.1f} percentage points)")
                elif x["diff_ci95"][1] < 0:
                    worse += 1
                else:
                    noise += 1
        n = worse + noise + len(better)
        were = "was" if worse == 1 else "were"
        tail = (f"of the momentum and RSI rules only {', '.join(better)} beat it clearly ({worse} of {n} tests {were} "
                "clearly worse)" if better else
                f"none of the momentum and RSI rules beat it clearly ({worse} of {n} tests {were} clearly worse, the rest "
                "within noise)")
        out.append(f"Do simple up/down rules work? Always calling \"up\" was right {pct(au['1']['hit_rate'], 1)} of the "
                   f"time 1 day ahead and {pct(au['5']['hit_rate'], 1)} 5 days ahead (a coin flip is 50%), and {tail}.")
    return out


LIMITATIONS = [
    "No AI: the forecaster's drift and widening are judged only live (the model may have seen past prices).",
    "No overnight own-stock cue: pre-market gaps (US) and ADR moves (India) have no stored history, and the "
    "next open would be look-ahead.",
    "Implied volatility has no stored history and is off in config/ranges.yaml.",
    "The vol index level is the as-of close; live runs use the pre-open quote.",
    "The calibration pool holds stored history only (no live scored ranges, which include AI changes).",
    "Relationship and smart-money widening are off in config/ranges.yaml and not replayed.",
    "Past earnings and ex-dividend dates are treated as known in advance (they are scheduled); a backfilled "
    "row does not say when its date was first announced.",
    "Confidence intervals are clustered by date blocks (all stocks share a day; 5-day outcomes overlap), "
    "so they are wider than a naive binomial interval.",
]


def limitations(cfg: dict, rc: dict, s: dict) -> list[str]:
    market, out = cfg["market"], list(LIMITATIONS)
    ic = cfg.get("index_cue") or {}
    if ic.get("symbol") and range_switches.enabled(rc, "beta_split", market):
        on = [h for h in rc["horizons"] if range_switches.enabled(rc, "beta_split", market, h)]
        if ic.get("beta", 1.0) == "fit":
            out.append(f"Index cue (beta split, on for {', '.join(f'{h}d' for h in on)}): {ic['symbol']}'s last session "
                       "return before the next session x the beta fitted on bars up to d, as the live pre-open quote gives it.")
        else:
            out.append(f"Index cue {ic['symbol']} (quoted before the open) has no stored history: the beta split has no "
                       "index cue in the replay.")
    mism = {h: v.get("calendar_mismatch", 0) for h, v in s["horizons"].items() if v.get("calendar_mismatch")}
    if mism:
        out.append("Ranges are scored on the close h stored bars later. On " + ", ".join(f"{n} {h}d" for h, n in mism.items())
                   + " rows that bar is not the exchange-calendar target date a live range names (bars on special "
                   "sessions such as India's Muhurat trading, or a session without a bar).")
    if (rc.get("relation_widen") or {}).get("enabled") or float(rc.get("activist_13d_factor", 1.0)) != 1.0:
        out.append("WARNING: relationship or smart-money widening is switched on but cannot be replayed.")
    if range_switches.enabled(rc, "implied_vol", market):
        out.append("WARNING: implied_vol is switched on but cannot be replayed; replayed ranges omit it.")
    return out


# ---------- HTML ----------

CSS = """
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--axis:#c3c2b7;--s1:#2a78d6;--s2:#eb6834;--ring:rgba(11,11,11,.10);--good:#006300;--bad:#d03b3b;--chip:#f0efec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;
--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--s1:#3987e5;--s2:#d95926;--ring:rgba(255,255,255,.10);
--good:#0ca30c;--bad:#e66767;--chip:#383835}}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;
--axis:#383835;--s1:#3987e5;--s2:#d95926;--ring:rgba(255,255,255,.10);--good:#0ca30c;--bad:#e66767;--chip:#383835}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 8px}p,li{color:var(--ink2)}.sub{color:var(--muted);margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin:12px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile .v{font-size:30px;font-weight:600;color:var(--ink)}.tile .l{font-size:13px;color:var(--muted)}
.tile .n{font-size:13px;color:var(--ink2)}.summary li{margin:6px 0;color:var(--ink)}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid)}th{color:var(--muted);font-weight:600}
td:first-child,th:first-child{text-align:left}.scroll{overflow-x:auto}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin:4px 0 8px}
.sw{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:6px;vertical-align:middle}
.sw.line{height:2px;width:16px;border-radius:1px}.dash{border-top:2px dashed var(--muted);width:16px;display:inline-block;
margin-right:6px;vertical-align:middle}
svg{display:block;width:100%;height:auto}svg text{fill:var(--muted);font-size:11px}
.mark:hover{opacity:.75}.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);
border:1px solid var(--ring);border-radius:8px;padding:6px 9px;font-size:12.5px;box-shadow:0 2px 8px rgba(0,0,0,.15);
display:none;z-index:10;max-width:260px}select{font:inherit;padding:4px 8px;border-radius:8px;border:1px solid var(--axis);
background:var(--surface);color:var(--ink)}.bad{color:var(--bad)}.good{color:var(--good)}
.note{font-size:13px;color:var(--muted)}.caption{font-size:13.5px;color:var(--ink2);margin:8px 0 0}.top .answer{color:var(--ink);font-size:16px;margin:8px 0}details{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:10px 16px;margin:10px 0}summary{cursor:pointer;font-weight:600;color:var(--ink)}details[open] summary{margin-bottom:8px}code{background:var(--chip);padding:1px 4px;border-radius:4px}
"""

JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.addEventListener('mousemove',e=>{tip.style.display='block';tip.textContent=el.dataset.tip;
  const x=Math.min(e.clientX+14,window.innerWidth-270);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'});
 el.addEventListener('mouseleave',()=>{tip.style.display='none'});});
const sel=document.getElementById('sector');
if(sel){sel.addEventListener('change',()=>{document.querySelectorAll('#tickers tbody tr').forEach(r=>{
 r.style.display=(sel.value==='all'||r.dataset.sector===sel.value)?'':'none'})})}
"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def _f(x, k=1, suffix="%", scale=100.0) -> str:
    return "n/a" if x is None else f"{scale * x:.{k}f}{suffix}"


def svg_calibration(s: dict) -> str:
    W, H, L, R, T, B = 640, 360, 48, 16, 16, 40
    pw, ph = W - L - R, H - T - B
    X = lambda v: L + v * pw  # noqa: E731
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Stated vs actual coverage">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
        out.append(f'<text x="{X(v):.1f}" y="{H - B + 16}" text-anchor="middle">{int(v * 100)}%</text>')
    out.append(f'<text x="{L + pw / 2}" y="{H - 4}" text-anchor="middle">stated coverage (what the range promises)</text>')
    out.append(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" stroke="var(--muted)" stroke-dasharray="4 4"/>')
    for h, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        pts = s["horizons"].get(h, {}).get("calibration") or []
        if not pts:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{X(p['stated']):.1f},{Y(p['actual']):.1f}" for i, p in enumerate(pts))
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for p in pts:
            r = 6 if p["published"] else 4
            tipx = (f"{h}-day {'published ' if p['published'] else ''}{int(p['stated'] * 100)}% range: "
                    f"actual {_f(p['actual'])}")
            out.append(f'<circle class="mark" cx="{X(p["stated"]):.1f}" cy="{Y(p["actual"]):.1f}" r="{r}" fill="{color}" '
                       f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>')
    out.append("</svg>")
    return "".join(out)


def svg_regime(s: dict) -> str:
    regs = REGIME_ORDER
    W, H, L, R, T, B = 640, 300, 48, 16, 16, 44
    pw, ph = W - L - R, H - T - B
    Y = lambda v: T + (1 - v) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="80% coverage by regime">']
    for v in (0, .2, .4, .6, .8, 1):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>')
    slot = pw / len(regs)
    bw = min(24, slot / 3)
    for i, name in enumerate(regs):
        cx = L + slot * (i + .5)
        days = s.get("regime_days", {}).get(name, 0)
        out.append(f'<text x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{cx:.1f}" y="{H - B + 30}" text-anchor="middle">{days} days</text>')
        for j, (h, color) in enumerate((("1", "var(--s1)"), ("5", "var(--s2)"))):
            r = s["horizons"].get(h, {}).get("by_regime", {}).get(name)
            if not r or not r.get("n"):
                continue
            v = r["cover80"]
            x = cx + (j - 1) * (bw + 2) + 1
            y0, y1 = Y(0), Y(v)
            hgt = max(y0 - y1, 0.5)
            rr = min(4, hgt)
            d = (f"M{x:.1f},{y0:.1f} L{x:.1f},{y1 + rr:.1f} Q{x:.1f},{y1:.1f} {x + rr:.1f},{y1:.1f} "
                 f"L{x + bw - rr:.1f},{y1:.1f} Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 + rr:.1f} L{x + bw:.1f},{y0:.1f} Z")
            tipx = f"{name}, {h}-day: 80% coverage {_f(v)} over {r['n']:,} ranges ({r['days']} days)"
            out.append(f'<path class="mark" d="{d}" fill="{color}" data-tip="{esc(tipx)}"/>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(.8):.1f}" y2="{Y(.8):.1f}" stroke="var(--ink2)" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{L + 4}" y="{Y(.8) - 5:.1f}" text-anchor="start">promise 80%</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--axis)"/>')
    out.append("</svg>")
    return "".join(out)


def svg_time(s: dict) -> str:
    months = sorted({m for h in ("1", "5") for m, v in s["horizons"].get(h, {}).get("by_month", {}).items()
                     if v.get("days", 0) >= MIN_MONTH_DAYS})
    if not months:
        return ""
    W, H, L, R, T, B = 640, 300, 48, 30, 16, 36
    pw, ph = W - L - R, H - T - B
    vals = [v["cover80"] for h in ("1", "5") for v in s["horizons"].get(h, {}).get("by_month", {}).values()
            if v.get("days", 0) >= MIN_MONTH_DAYS]
    lo = max(0.0, math.floor(min(vals + [0.6]) * 10) / 10)
    X = lambda i: L + (i + .5) * pw / len(months)  # noqa: E731
    Y = lambda v: T + (1 - (v - lo) / (1 - lo)) * ph  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="80% coverage by month">']
    v = lo
    while v <= 1.0001:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{round(v * 100)}%</text>')
        v += 0.1
    step = max(1, len(months) // 8)
    for i, m in enumerate(months):
        if i % step == 0:
            out.append(f'<text x="{X(i):.1f}" y="{H - B + 16}" text-anchor="middle">{m}</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(.8):.1f}" y2="{Y(.8):.1f}" stroke="var(--ink2)" stroke-dasharray="4 4"/>')
    for h, color in (("1", "var(--s1)"), ("5", "var(--s2)")):
        bm = s["horizons"].get(h, {}).get("by_month", {})
        pts = [(i, bm[m]) for i, m in enumerate(months) if bm.get(m, {}).get("days", 0) >= MIN_MONTH_DAYS]
        if not pts:
            continue
        path = " ".join(f"{'M' if k == 0 else 'L'}{X(i):.1f},{Y(r['cover80']):.1f}" for k, (i, r) in enumerate(pts))
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for i, r in pts:
            tipx = f"{months[i]}, {h}-day: 80% coverage {_f(r['cover80'])} ({r['n']:,} ranges)"
            out.append(f'<circle class="mark" cx="{X(i):.1f}" cy="{Y(r["cover80"]):.1f}" r="4" fill="{color}" '
                       f'stroke="var(--surface)" stroke-width="2" data-tip="{esc(tipx)}"/>')
    out.append("</svg>")
    return "".join(out)


def legend(extra: str = "") -> str:
    return ('<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>1-day ranges</span>'
            '<span><span class="sw" style="background:var(--s2)"></span>5-day ranges</span>' + extra + "</div>")


def range_table(groups: dict, label: str) -> str:
    rows = []
    for k, (a, b) in groups.items():
        cells = [esc(k)]
        for r in (a, b):
            if r and r.get("n"):
                cells += [f"{r['n']:,}", _f(r["cover50"]), _f(r["cover80"]),
                          f"{r['width80_pct']:.2f}%", f"{r['score80']:.2f}", f"{r.get('naive_score80', 0) or 0:.2f}"]
            else:
                cells += ["0", "", "", "", "", ""]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    head = (f"<tr><th>{esc(label)}</th>" + "".join(f"<th>{h} n</th><th>{h} 50%</th><th>{h} 80%</th><th>{h} 80% width</th>"
                                                   f"<th>{h} score</th><th>{h} naive score</th>" for h in ("1d", "5d")) + "</tr>")
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def fmt_p(p) -> str:
    return "" if p is None else ("<0.001" if p < 0.001 else f"{p:.3g}")


SCORE_NOTE = ("Score = interval score: the 80% range's width plus a penalty when the price lands outside it, in % of "
              "the price; lower is better. Naive = a simple range of last close +/- the last 20 days' typical move.")
CI_NOTE = ("95% interval = the span the true rate most likely lies in, allowing for stocks moving together on the "
           "same day.")


def html_report(cfg: dict, s: dict) -> str:
    hz = s["horizons"]
    h1, h5 = hz.get("1", {}).get("overall", {}), hz.get("5", {}).get("overall", {})
    au = {h: (s["baselines"].get(h) or {}).get("always_up", {}) for h in ("1", "5")}

    def tile(label, v, ci, note):
        span = "" if not ci or ci[0] is None else f"95% interval {_f(ci[0])} to {_f(ci[1])}"
        return (f'<div class="card tile"><div class="l">{esc(label)}</div><div class="v">{_f(v)}</div>'
                f'<div class="n">{esc(note)}</div><div class="n">{span}</div></div>')

    tiles = "".join([
        tile("1-day 80% ranges that held", h1.get("cover80"), h1.get("cover80_ci"), f"promise 80% · {h1.get('n', 0):,} ranges"),
        tile("5-day 80% ranges that held", h5.get("cover80"), h5.get("cover80_ci"), f"promise 80% · {h5.get('n', 0):,} ranges"),
        tile("“Always up” right, 1 day ahead", au["1"].get("hit_rate"), au["1"].get("ci95"), "a coin flip is 50%"),
        tile("“Always up” right, 5 days ahead", au["5"].get("hit_rate"), au["5"].get("ci95"), "a coin flip is 50%")])
    top = "".join(f"<p class=\"answer\"><b>{esc(x.split('? ', 1)[0])}?</b> {esc(x.split('? ', 1)[1])}</p>"
                  if "? " in x else f"<p class=\"answer\">{esc(x)}</p>" for x in s.get("top", []))
    summary = "".join(f"<li>{esc(x)}</li>" for x in s["summary"])
    pair = lambda key: {k: (hz.get("1", {}).get(key, {}).get(k), hz.get("5", {}).get(key, {}).get(k))  # noqa: E731
                        for k in dict.fromkeys(list(hz.get("1", {}).get(key, {})) + list(hz.get("5", {}).get(key, {})))}
    brows = []
    for h in ("1", "5"):
        for name, b in (s["baselines"].get(h) or {}).items():
            d, (dlo, dhi) = b["diff_vs_always_up"], b["diff_ci95"]
            vs = "" if name == "always_up" or d is None else f"{100 * d:+.1f} pts"
            vs_ci = "" if name == "always_up" or dlo is None else f"{100 * dlo:+.1f} to {100 * dhi:+.1f}"
            brows.append(f"<tr><td>{esc(b['label'])}</td><td>{h}d</td><td>{b['calls']:,}</td><td>{_f(b['hit_rate'])}</td>"
                         f"<td>{_f(b['ci95'][0])} to {_f(b['ci95'][1])}</td><td>{esc(fmt_p(b['p_vs_50']))}</td>"
                         f"<td>{vs}</td><td>{vs_ci}</td></tr>")
    sector = {t: m.get("sector") or "Other" for t, m in cfg["tickers"].items()}
    trows = []
    for t in sorted(cfg["tickers"]):
        a = hz.get("1", {}).get("by_ticker", {}).get(t, {})
        b = hz.get("5", {}).get("by_ticker", {}).get(t, {})
        if not a.get("n") and not b.get("n"):
            continue
        cell = lambda r, k: _f(r.get(k)) if r.get("n") else ""  # noqa: E731
        num = lambda r, k: f"{r[k]:.2f}" if r.get("n") and r.get(k) is not None else ""  # noqa: E731
        trows.append(f'<tr data-sector="{esc(sector[t])}"><td>{esc(t)}</td><td>{esc(sector[t])}</td>'
                     f"<td>{a.get('n', 0):,}</td><td>{cell(a, 'cover50')}</td><td>{cell(a, 'cover80')}</td>"
                     f"<td>{num(a, 'score80')}</td><td>{num(a, 'naive_score80')}</td>"
                     f"<td>{cell(b, 'cover50')}</td><td>{cell(b, 'cover80')}</td><td>{num(b, 'score80')}</td>"
                     f"<td>{num(b, 'naive_score80')}</td></tr>")
    opts = "".join(f'<option value="{esc(x)}">{esc(x)}</option>' for x in sorted(set(sector.values())))
    lim = "".join(f"<li>{esc(x)}</li>" for x in s["limitations"])
    inputs = "; ".join(f"{h}d: " + (", ".join(k for k, v in u.items() if v) or "none") for h, u in s["settings"]["inputs"].items())
    dash = '<span><span class="dash"></span>perfect calibration</span>'
    tgt = '<span><span class="dash"></span>promise 80%</span>'
    score_note = f'<p class="note">{esc(SCORE_NOTE)}</p>'
    ic = cfg.get("index_cue") or {}
    replayed_cue = ic.get("symbol") and ic.get("beta", 1.0) == "fit" and any(
        u.get("beta_split") for u in s["settings"]["inputs"].values())
    cue_name = (cfg["symbols"].get(ic.get("symbol")) or {}).get("name") or ic.get("symbol")
    cue_txt = f", and the {esc(cue_name)} as an overnight cue" if replayed_cue else ""
    a = s["settings"].get("aci") or {}
    aci_block = "" if not s.get("aci_comparison") else (
        "<h2>Adaptive bands (ACI): before and after</h2><div class=\"card\">"
        f"<p>This page shows the ranges with Adaptive Conformal Inference on (gamma {a.get('gamma')}, at most "
        f"{a.get('max_shift')} from the target miss rate, after {a.get('min_history')} scored days, "
        f"{'one rate per regime' if a.get('by_regime') else 'one rate per horizon and band'}): each day the share "
        "of past ranges that missed moves the band's quantile level. The table compares the same rows with fixed bands "
        "(before) and ACI (after). Width and scores in % of the price, lower is better. These settings may have "
        "been chosen on this same window: in-sample unless the held-out check below agrees.</p>"
        f"{aci_table(s['aci_comparison'])}{held_out_html(s.get('aci_held_out'))}</div>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Historical Replay {esc(cfg['market'].upper())}</title>
<style>{CSS}</style></head><body><main>
<h1>Historical replay: {esc(cfg.get('name', cfg['market']))}</h1>
<p class="sub">Every past trading day from {esc(s['start'])} to {esc(s['end'])}, the price ranges were rebuilt using only what
was known before the next session opened (prices up to that day's close, scheduled events{cue_txt}), then checked
against the actual close. Rule-based parts only, no AI. Research only,
not investment advice.</p>
<div class="card top">{top}</div>
<div class="tiles">{tiles}</div>
<p class="note">An 80% range promises to contain the later closing price 8 times in 10. {esc(CI_NOTE)}</p>
<h2>Do the ranges hold as often as they promise?</h2>
<div class="card">{legend(dash)}{svg_calibration(s)}
<p class="caption">Look for: points above the dashed line mean the ranges held more often than promised (too wide); below it,
too narrow. The large points are the published 50% and 80% ranges.</p></div>
<h2>Coverage by market mood (regime)</h2>
<div class="card">{legend(tgt)}{svg_regime(s)}
<p class="caption">Look for: bars well above the dashed 80% line are market moods (CALM, TRENDING, EVENT_HEAVY around
scheduled events, UNSTABLE in stress) where the ranges are wider than needed.</p></div>
<h2>Coverage over time</h2>
<div class="card">{legend(tgt)}{svg_time(s)}
<p class="caption">Look for: long runs below the 80% line, which would mean the ranges fell behind in some periods
(months with fewer than {MIN_MONTH_DAYS} days are left out).</p></div>
{aci_block}<h2>More detail</h2>
<details><summary>All findings, with every number</summary>
<p class="note">{esc(CI_NOTE)} pts = percentage points. {esc(SCORE_NOTE)}</p><ul class="summary">{summary}</ul></details>
<details><summary>Coverage by regime (table)</summary>{range_table(pair('by_regime'), 'Regime')}{score_note}</details>
<details><summary>Earnings, market events and years</summary>
<p>Coverage split by whether a company earnings report or a major market event fell inside the horizon, and by year.</p>
{range_table(pair('by_earnings'), 'Earnings')}
{range_table(pair('by_major_event'), 'Market event')}
{range_table(pair('by_year'), 'Year')}{score_note}</details>
<details><summary>Direction baselines (simple up/down rules, not the product's forecasts)</summary>
<p>Simple rules the AI forecaster must beat later. A call is right if the close h days later moved in the called direction
(no change counts as wrong). {esc(CI_NOTE)} "vs always-up" compares each rule with always-up on the same stocks and days,
in pts (percentage points).</p>
<div class="scroll"><table><thead><tr><th>Rule</th><th>Horizon</th><th>Calls</th><th>Hit rate</th><th>95% interval</th>
<th>p vs 50% (if independent)</th><th>vs always-up</th><th>95% interval</th></tr></thead><tbody>{"".join(brows)}</tbody></table></div>
<p class="note">The p-value is an exact binomial test that treats every call as independent; stocks move together, so it
overstates the evidence. Trust the 95% intervals: a rule only beats 50% (or always-up) if its interval stays above it.
Momentum: call the sign of the last 1 or 5 days' return. RSI mean reversion: RSI(14) below {RSI_LOW:g} calls up, above
{RSI_HIGH:g} calls down, otherwise no call (defined in replay.py; indicators.py computes RSI but has no signal).</p></details>
<details><summary>Per ticker</summary>
<p>Filter by sector: <select id="sector"><option value="all">All sectors</option>{opts}</select></p>
<div class="scroll"><table id="tickers"><thead><tr><th>Ticker</th><th>Sector</th><th>n (1d)</th><th>1d 50%</th><th>1d 80%</th>
<th>1d score</th><th>1d naive</th><th>5d 50%</th><th>5d 80%</th><th>5d score</th><th>5d naive</th></tr></thead>
<tbody>{"".join(trows)}</tbody></table></div>{score_note}</details>
<details><summary>Method and limits</summary>
<p>Each as-of day uses only bars up to its close and events as known pre-open the next session, built with the same code as
the live ranges (marketbrief/analytics/range_math.py, the range-input modules, backtest.py helpers, regime.py). Range inputs switched on
(config/ranges.yaml): {esc(inputs)}. Data: {esc(s['data']['first_bar'])} to {esc(s['data']['last_bar'])},
{s['data']['tickers']} tickers, {s['data']['earnings_events']} earnings and {s['data']['dividends']} dividend events.
Computed {esc(s['computed_at'])}, runtime {s['runtime_s']:.0f} s.</p><ul>{lim}</ul></details>
</main><div id="tip" class="tip"></div><script>{JS}</script></body></html>"""


# ---------- run ----------

CMP_KEYS = ("n", "cover50", "cover80", "width50_pct", "width80_pct", "score50", "score80", "qs_pct")


def aci_comparison(before: dict, after: dict) -> dict:
    """Same rows, fixed bands (before) vs ACI (after): overall, by regime and by major event."""
    out = {}
    for h, hb in before["horizons"].items():
        ha = after["horizons"].get(h, {})
        groups = {"overall": (hb.get("overall", {}), ha.get("overall", {}))}
        for sect in ("by_regime", "by_major_event"):
            for k, v in (hb.get(sect) or {}).items():
                groups[k] = (v, (ha.get(sect) or {}).get(k, {}))
        out[h] = {k: {"before": {c: b.get(c) for c in CMP_KEYS}, "after": {c: a.get(c) for c in CMP_KEYS}}
                  for k, (b, a) in groups.items()}
    return out


def _num(x, k: int = 2) -> str:
    return "" if x is None else f"{x:.{k}f}"


ACI_GRID = tuple((g, br) for g in (0.002, 0.005, 0.01, 0.02) for br in (False, True))   # held-out tuning grid
ACI_SETTING_KEYS = ("gamma", "max_shift", "min_history", "by_regime")


def aci_tag(a: dict, tune_end: date | None = None) -> str:
    """Replay id / file suffix naming the ACI settings (and the held-out split), e.g.
    -aci-g0.01-regime-s0.15-m20-t2024-12-31."""
    t = (f"-aci-g{a['gamma']:g}-{'regime' if a['by_regime'] else 'all'}-s{a['max_shift']:g}"
         f"-m{int(a['min_history'])}")
    return t + (f"-t{tune_end}" if tune_end else "")


def _cmp_groups(g: pd.DataFrame, h: int) -> dict:
    out = {"overall": range_summary(g, h)}
    for k, x in g.groupby("regime"):
        out[str(k)] = range_summary(x, h)
    out["major event in horizon"] = range_summary(g[g["major"]], h)
    out["no major event"] = range_summary(g[~g["major"]], h)
    return out


def rows_comparison(fixed: dict, after: dict, keep) -> dict:
    """fixed vs ACI on the rows `keep(frame)` selects, per horizon: overall, by regime, by major event."""
    out = {}
    for h, gf in fixed.items():
        b, a = _cmp_groups(gf[keep(gf)], h), _cmp_groups(after[h][keep(after[h])], h)
        out[str(h)] = {k: {"before": {c: v.get(c) for c in CMP_KEYS}, "after": {c: a.get(k, {}).get(c) for c in CMP_KEYS}}
                       for k, v in b.items()}
    return out


def mean_rel_score80(cmp: dict) -> float | None:
    rel = [g["overall"]["after"]["score80"] / g["overall"]["before"]["score80"] - 1 for g in cmp.values()
           if g["overall"]["before"].get("score80") and g["overall"]["after"].get("score80") is not None]
    return float(np.mean(rel)) if rel else None


def held_out(cfg: dict, rc: dict, con, tune_end: date, start: date | None = None, end: date | None = None) -> dict:
    """Out-of-sample check of the ACI settings: every ACI_GRID variant is replayed (ACI runs online over
    the whole window), the variant with the lowest mean relative 80% interval score on the TUNING rows
    (as-of date and target close on or before tune_end) is selected, and fixed bands vs that variant (and
    vs the config's settings) are compared on the TEST rows only (as-of date after tune_end)."""
    bars, extra = load_inputs(cfg, rc, con)
    fixed, _ = replay_rows(cfg, {**rc, "aci": {**aci.settings(rc), "enabled": False}}, bars, extra, start, end)

    def tune(g: pd.DataFrame) -> pd.Series:   # outcome known by tune_end too (5-day targets cross it)
        return (g["date"] <= tune_end) & g["bar_target"].map(lambda x: isinstance(x, date) and x <= tune_end)

    def test(g: pd.DataFrame) -> pd.Series:
        return g["date"] > tune_end

    variants, frames = [], {}
    for gamma, br in ACI_GRID:
        r = aci_rc(rc, gamma, br)
        res, _ = replay_rows(cfg, r, bars, extra, start, end)
        key = aci_tag(r["aci"])
        frames[key] = (r["aci"], res)
        variants.append({"tag": key, "gamma": gamma, "by_regime": br,
                         "tune_rel_score80": round_or_none(mean_rel_score80(rows_comparison(fixed, res, tune)))})
    best = min((v for v in variants if v["tune_rel_score80"] is not None), key=lambda v: v["tune_rel_score80"])
    sel_settings, sel_res = frames[best["tag"]]
    cur = aci_rc(rc)["aci"]
    cur_key = aci_tag(cur)
    if cur_key not in frames:
        frames[cur_key] = (cur, replay_rows(cfg, aci_rc(rc), bars, extra, start, end)[0])
    return {"tune_end": str(tune_end), "grid": variants,
            "selected": {k: sel_settings[k] for k in ACI_SETTING_KEYS},
            "config": {k: cur[k] for k in ACI_SETTING_KEYS},
            "selected_is_config": all(sel_settings[k] == cur[k] for k in ACI_SETTING_KEYS),
            "test_selected": rows_comparison(fixed, sel_res, test),
            "test_config": rows_comparison(fixed, frames[cur_key][1], test),
            "tune_config": rows_comparison(fixed, frames[cur_key][1], tune)}


def held_out_html(ho: dict | None) -> str:
    if not ho:
        return "<p class=\"note\">No held-out check in this run (replay.py --aci --aci-tune-end DATE).</p>"
    sel = ho["selected"]
    return (f"<h3>Held-out check</h3><p>gamma and one-or-per-regime alpha picked from {len(ho['grid'])} variants on "
            f"as-of dates up to {esc(ho['tune_end'])} only (lowest 80% interval score): gamma {sel['gamma']}, "
            f"{'per regime' if sel['by_regime'] else 'one alpha'}"
            f"{' = the config settings' if ho['selected_is_config'] else ' (not the config settings)'}. "
            f"Fixed bands vs that choice on the later, unseen as-of dates:</p>{aci_table(ho['test_selected'])}"
            + ("" if ho["selected_is_config"] else
               f"<p>Fixed bands vs the config settings on the same later dates:</p>{aci_table(ho['test_config'])}"))


def aci_table(cmp: dict) -> str:
    rows = []
    for h, groups in cmp.items():
        for k, v in groups.items():
            b, a = v["before"], v["after"]
            if not b.get("n"):
                continue
            rows.append(f"<tr><td>{h}d</td><td>{esc(k)}</td><td>{b['n']:,}</td>"
                        + "".join(f"<td>{_f(b.get(c))} → {_f(a.get(c))}</td>" for c in ("cover50", "cover80"))
                        + "".join(f"<td>{_num(b.get(c))} → {_num(a.get(c))}</td>"
                                  for c in ("width80_pct", "score50", "score80"))
                        + f"<td>{_num(b.get('qs_pct'), 3)} → {_num(a.get('qs_pct'), 3)}</td></tr>")
    head = ("<tr><th>H</th><th>Group</th><th>n</th><th>50% held</th><th>80% held</th><th>80% width</th>"
            "<th>50% score</th><th>80% score</th><th>Quantile score</th></tr>")
    return f'<div class="scroll"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def aci_rc(rc: dict, gamma: float | None = None, by_regime: bool | None = None) -> dict:
    """A copy of the range settings with ACI switched on (optionally another gamma / by_regime)."""
    a = {**aci.settings(rc), "enabled": True}
    if gamma is not None:
        a["gamma"] = gamma
    if by_regime is not None:
        a["by_regime"] = by_regime
    return {**rc, "aci": a}


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
                           "aci": {**aci.settings(rc), "on": {str(h): range_switches.enabled(rc, "aci", cfg["market"], h)
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


if __name__ == "__main__":
    sys.exit(main())
