"""Range engine inputs from stored data (library): past earnings-day moves, dividends going ex,
the overnight index cue for the beta split, and option-implied volatility.

Shared by ranges.py (live) and backtest.py (walk-forward), so both use the same rules. The math
is in rangelib.py; switches and settings are in config/ranges.yaml (`enabled` is true/false or a
list of markets)."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

import events as ev
import rangelib as rl
from common import benchmark_key

NEAR_DAYS = 3     # earnings dates this close together are the same report
MOVED_DAYS = 45   # an upcoming date superseded by a newer one this close was moved


def enabled(rc: dict, name: str, market: str) -> bool:
    on = (rc.get(name) or {}).get("enabled", False)
    return market in on if isinstance(on, list) else bool(on)


def _as_date(v) -> date:
    return pd.Timestamp(v).date()


# ---------- event history ----------

def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop upcoming rows whose date was later moved (a newer upcoming row within MOVED_DAYS)."""
    if df.empty:
        return df
    hist = df["source"].fillna("").str.endswith("_history")
    keep = []
    for i, r in df.iterrows():
        if hist[i]:
            keep.append(True)
            continue
        newer = df[(~hist) & (df["ticker"] == r["ticker"]) & (df["type"] == r["type"])
                   & (df["first_seen_at"] > r["first_seen_at"]) & (df["date"] != r["date"])]
        keep.append(not any(abs((d - r["date"]).days) <= MOVED_DAYS for d in newer["date"]))
    return df[keep]


def load_events(con) -> pd.DataFrame:
    df = con.execute("SELECT ticker, type, date, timing, amount, source, first_seen_at FROM event_history "
                     "WHERE type IN ('earnings', 'ex_dividend') ORDER BY ticker, type, date").df()
    if df.empty:
        return df
    df["date"] = df["date"].map(_as_date)
    return _clean(df)


def earnings_events(evdf: pd.DataFrame) -> dict[str, list[tuple[date, str | None]]]:
    """Per ticker: (date, timing) of every known earnings report, one row per report (a timed row
    beats an untimed one for the same report)."""
    out: dict[str, list] = {}
    if evdf.empty:
        return out
    e = evdf[evdf["type"] == "earnings"]
    for t, g in e.groupby("ticker"):
        rows = sorted(((r.date, None if pd.isna(r.timing) else r.timing) for r in g.itertuples()),
                      key=lambda x: (x[1] is None, x[0]))
        kept: list = []
        for d, tm in rows:
            if all(abs((d - k).days) > NEAR_DAYS for k, _ in kept):
                kept.append((d, tm))
        out[t] = sorted(kept)
    return out


def dividend_events(evdf: pd.DataFrame) -> dict[str, list[tuple[date, float | None]]]:
    """Per ticker: (ex-date, amount); a missing amount is the last known one before it."""
    out: dict[str, list] = {}
    if evdf.empty:
        return out
    d = evdf[evdf["type"] == "ex_dividend"]
    for t, g in d.groupby("ticker"):
        rows, last = [], None
        for dt, grp in g.groupby("date"):
            amts = [float(a) for a in grp["amount"] if a == a and a is not None]
            amt = amts[0] if amts else last
            rows.append((dt, amt))
            last = amt if amt is not None else last
        out[t] = rows
    return out


# ---------- earnings reaction windows ----------

def affected_sessions(cfg: dict, d: date, timing: str | None) -> list[date]:
    """Sessions whose close-to-close move contains the earnings reaction. Unknown timing: the day
    itself and the next session (could be before the open or after the close)."""
    if timing in ("before_open", "during"):
        return [ev.next_session(cfg, d)]
    if timing == "after_close":
        return [ev.next_session(cfg, d, include=False)]
    if ev.is_session(cfg, d):
        return [d, ev.next_session(cfg, d, include=False)]
    return [ev.next_session(cfg, d)]


def earnings_in_horizon(cfg: dict, events: list[tuple[date, str | None]], as_of: date, target: date) -> bool:
    for d, tm in events:
        if d > target or d < as_of - timedelta(days=7):
            continue
        if any(as_of < s <= target for s in affected_sessions(cfg, d, tm)):
            return True
    return False


def past_moves(cfg: dict, close: pd.Series, sigma: pd.Series, events, warmup: int) -> list[tuple]:
    """(last session of the window, log move, daily sigma before it, sessions) per past report."""
    idx = close.index
    pos = {d.date(): i for i, d in enumerate(idx)}
    out = []
    for d, tm in events:
        aff = affected_sessions(cfg, d, tm)
        if aff[0] not in pos or aff[-1] not in pos:
            continue
        i0, i1 = pos[aff[0]] - 1, pos[aff[-1]]
        if i0 < warmup:
            continue
        s = float(sigma.iloc[i0])
        if not s > 0:
            continue
        out.append((aff[-1], math.log(close.iloc[i1] / close.iloc[i0]), s, i1 - i0))
    return out


def earnings_stats(moves: list[tuple], rc: dict, as_of: date) -> tuple[float, int, float | None]:
    """(multiple, events used, median absolute move) from reactions completed by as_of."""
    eh = rc["earnings_history"]
    done = [m for m in moves if m[0] <= as_of][-int(eh["lookback_events"]):]
    m, n = rl.earnings_multiple([(r, s, k) for _, r, s, k in done], rc["earnings_vol_multiple"],
                                int(eh["min_events"]), float(eh["prior_events"]), float(eh["max_multiple"]))
    med = float(np.median([abs(r) for _, r, _, _ in done])) if done else None
    return m, n, med


# ---------- dividends ----------

def dividends_in_horizon(cfg: dict, divs: list[tuple[date, float | None]], as_of: date, target: date) -> list[float]:
    """Amounts of dividends whose ex-date session falls in (as_of, target]."""
    return [a for d, a in divs if a and d <= target and as_of < ev.next_session(cfg, d) <= target]


# ---------- index cue (beta split) ----------

def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def fit_cue_beta(bench: pd.Series, cue: pd.Series, upto: pd.Timestamp | None, n: int,
                 min_obs: int = 60) -> float | None:
    """Slope of the benchmark's daily log return on the cue's previous-session log return (the
    last cue session strictly before the benchmark date), over the last n benchmark sessions."""
    rb = log_returns(bench).dropna()
    rc_ = log_returns(cue).dropna()
    if upto is not None:
        rb = rb[rb.index <= upto]
    rb = rb.iloc[-n:]
    if len(rb) < min_obs or rc_.empty:
        return None
    a = pd.DataFrame({"date": rb.index, "rb": rb.to_numpy()})
    b = pd.DataFrame({"date": rc_.index, "rc": rc_.to_numpy()})
    j = pd.merge_asof(a, b, on="date", allow_exact_matches=False).dropna()
    if len(j) < min_obs or j["rc"].var() == 0:
        return None
    return float(j["rb"].cov(j["rc"]) / j["rc"].var())


def index_cue_beta(cfg: dict, bars: dict, rc: dict, upto: pd.Timestamp | None = None) -> float | None:
    ic = cfg.get("index_cue") or {}
    if not ic.get("symbol"):
        return None
    b = ic.get("beta", 1.0)
    if b != "fit":
        return float(b)
    bench, cue = bars.get(benchmark_key(cfg)), bars.get(ic["symbol"])
    if bench is None or cue is None:
        return None
    return fit_cue_beta(bench["close"], cue["close"], upto, int(rc["beta_split"]["fit_sessions"]))


def clip_beta(beta, rc: dict) -> float | None:
    if beta is None or pd.isna(beta):
        return None
    lo, hi = rc["beta_split"]["beta_clip"]
    return min(max(float(beta), lo), hi)


# ---------- implied volatility ----------

def implied_sigma(cfg: dict, opts: pd.DataFrame, as_of: date, target: date, sigma_daily: float,
                  earnings: list[tuple[date, str | None]], rc: dict) -> tuple[float, float | None, list[str]]:
    """Use the first expiry on or after the target date. Without earnings before that expiry the
    implied daily variance is blended into sigma; with earnings inside the expiry the IV mostly
    prices the report, so it sets the earnings multiple instead (if `use_for_earnings`).
    Returns (sigma_daily, implied earnings multiple or None, notes)."""
    iv_cfg = rc["implied_vol"]
    if opts is None or opts.empty:
        return sigma_daily, None, []
    o = opts[(opts["expiry"] >= target) & (opts["expiry"] <= target + timedelta(days=int(iv_cfg["max_expiry_days"])))]
    o = o[o["atm_iv"].notna() & (o["atm_iv"] > 0)].sort_values("expiry")
    if o.empty:
        return sigma_daily, None, []
    row = o.iloc[0]
    expiry = _as_date(row["expiry"])
    sessions = len(_sessions_between(cfg, as_of, expiry))
    if sessions < 1:
        return sigma_daily, None, []
    total = rl.implied_variance(float(row["atm_iv"]), (expiry - as_of).days)
    iv_txt = f"IV {float(row['atm_iv']):.0%} to {expiry}"
    if earnings_in_horizon(cfg, earnings, as_of, expiry):
        if not iv_cfg.get("use_for_earnings", True):
            return sigma_daily, None, []
        m = rl.implied_earnings_multiple(total, sessions, sigma_daily, float(rc["earnings_history"]["max_multiple"]))
        return sigma_daily, m, [f"{iv_txt} prices earnings"]
    w = float(iv_cfg["weight"])
    return rl.blend_sigma(sigma_daily, total / sessions, w), None, [f"{iv_txt} blended x{w}"]


def _sessions_between(cfg: dict, start: date, end: date) -> list[date]:
    """Trading sessions in (start, end]."""
    out, d = [], start
    while True:
        d = ev.next_session(cfg, d, include=False)
        if d > end:
            return out
        out.append(d)
