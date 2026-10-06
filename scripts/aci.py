"""Adaptive Conformal Inference for the price ranges (library; docs/DESIGN.md section 4.5).

Gibbs & Candes (2021), "Adaptive conformal inference under distribution shift": per market x
horizon x band keep an effective miscoverage alpha_t and update it after each step's outcome

    alpha_{t+1} = alpha_t + gamma * (alpha_target - err_t)

with err_t = 1 when the realised close fell outside the band (here: the share of that step's
ranges that missed; one step = one target date). Misses push alpha down (wider band), hits push
it up (narrower). The band is then built from the calibration pool at quantile levels
alpha_t / 2 and 1 - alpha_t / 2 instead of the fixed (1 - band) / 2 levels.

No look-ahead: only ranges whose outcome was scored at or before the moment the quantiles are
computed (`scored_at <= now`) enter the update. Settings in config/ranges.yaml `aci:` (off by
default): gamma, `max_shift` (|alpha_t - alpha_target| clamp, applied to the state after every
step), `min_history` (steps before the adjusted alpha is used) and `by_regime` (a separate alpha
per regime label)."""
from __future__ import annotations

import pandas as pd

BANDS = {"50": 0.5, "80": 0.8}
TARGET = {"50": 0.5, "80": 0.2}   # target miss rates, written exactly (1 - 0.8 is not 0.2 in floats)
DEFAULTS = {"enabled": False, "gamma": 0.01, "max_shift": 0.15, "min_history": 20, "by_regime": True}


def settings(rc: dict) -> dict:
    return {**DEFAULTS, **(rc.get("aci") or {})}


def aci_step(alpha: float, target: float, err: float, gamma: float,
             lo: float | None = None, hi: float | None = None) -> float:
    """One ACI update. err in [0, 1] (1 = miss, or the share of misses in the step)."""
    a = alpha + gamma * (target - err)
    if lo is not None:
        a = max(lo, a)
    if hi is not None:
        a = min(hi, a)
    return a


def aci_path(errs, target: float, gamma: float, lo: float | None = None, hi: float | None = None,
             alpha0: float | None = None) -> list[float]:
    """alpha_0 .. alpha_T for an error sequence (alpha_0 = target unless given)."""
    a = target if alpha0 is None else alpha0
    out = [a]
    for e in errs:
        a = aci_step(a, target, float(e), gamma, lo, hi)
        out.append(a)
    return out


def clamps(target: float, max_shift: float) -> tuple[float, float]:
    """State bounds: within max_shift of the target and strictly inside (0, 1)."""
    return max(0.005, target - max_shift), min(0.995, target + max_shift)


class Tracker:
    """Running ACI state per (horizon, band, key); key = regime label when by_regime, else 'all'."""

    def __init__(self, rc: dict):
        self.s = settings(rc)
        self.alpha: dict[tuple, float] = {}
        self.steps: dict[tuple, int] = {}

    def key(self, regime: str | None) -> str:
        return (regime or "all") if self.s["by_regime"] else "all"

    def update(self, h: int, band: str, key: str, err: float) -> None:
        target = TARGET[band]
        k = (int(h), band, key)
        lo, hi = clamps(target, self.s["max_shift"])
        self.alpha[k] = aci_step(self.alpha.get(k, target), target, err, self.s["gamma"], lo, hi)
        self.steps[k] = self.steps.get(k, 0) + 1

    def effective(self, h: int, band: str, key: str) -> float:
        """alpha used for the band: the target until min_history steps were seen."""
        target = TARGET[band]
        k = (int(h), band, key)
        if self.steps.get(k, 0) < self.s["min_history"]:
            return target
        return self.alpha.get(k, target)

    def levels(self, h: int, key: str) -> dict[str, float]:
        """Quantile levels for q10/q25/q75/q90 (the 80% band stays at least as wide as the 50%)."""
        a50 = self.effective(h, "50", key)
        a80 = min(self.effective(h, "80", key), a50)
        return {"q10": a80 / 2, "q25": a50 / 2, "q75": 1 - a50 / 2, "q90": 1 - a80 / 2}

    def feed(self, df: pd.DataFrame) -> None:
        """Update from scored ranges (columns horizon_days, target_date, hit50, hit80 and, when
        by_regime, regime), one step per target date in date order; err = share of misses."""
        if df is None or df.empty:
            return
        d = df.copy()
        d["key"] = [self.key(r) for r in (d["regime"] if "regime" in d else [None] * len(d))]
        # each (horizon, key) series in target-date order
        for (h, key), g in d.groupby(["horizon_days", "key"], sort=True):
            for _, s in g.groupby("target_date", sort=True):
                for band in BANDS:
                    self.update(int(h), band, key, 1.0 - float(s[f"hit{band}"].astype(float).mean()))

    def snapshot(self) -> list[dict]:
        out = []
        for (h, band, key), a in sorted(self.alpha.items()):
            target = TARGET[band]
            out.append({"horizon_days": h, "band": band, "key": key, "alpha": round(a, 5),
                        "alpha_target": target, "steps": self.steps[(h, band, key)],
                        "effective_alpha": round(self.effective(h, band, key), 5),
                        "implied_coverage": round(1 - self.effective(h, band, key), 5)})
        return out


LIVE_SQL = """SELECT r.horizon_days, r.target_date, r.regime, r.hit50, r.hit80
FROM range_record r JOIN (SELECT range_id, min(scored_at) AS scored_at FROM range_outcomes GROUP BY range_id) o
  ON o.range_id = r.id
WHERE o.scored_at <= ?::TIMESTAMPTZ AND r.hit50 IS NOT NULL AND r.hit80 IS NOT NULL"""


def live_tracker(con, rc: dict, now: str, until=None) -> Tracker:
    """ACI state from live scored ranges known at `now` (scored_at <= now), optionally only
    target dates <= until."""
    df = con.execute(LIVE_SQL, [now]).df()
    if until is not None and not df.empty:
        df = df[pd.to_datetime(df["target_date"]).dt.date <= until]
    t = Tracker(rc)
    t.feed(df)
    return t
