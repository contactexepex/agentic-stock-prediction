"""Statistics of the replay: Wilson and binomial tests, clustered interval, coverage, baselines."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from marketbrief.analytics import scoring
from marketbrief.constants.regime import REGIME_ORDER
from marketbrief.utils.numbers import round_or_none
from marketbrief.constants.replay import LEVELS, RSI_HIGH, RSI_LOW, SIGNAL_LABELS


wilson = scoring.wilson   # Wilson score interval (scoring.py)


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
