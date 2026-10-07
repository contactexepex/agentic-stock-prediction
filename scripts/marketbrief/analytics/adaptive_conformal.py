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
TARGET = {"50": 0.5, "80": 0.2}  # target miss rates, written exactly (1 - 0.8 is not 0.2 in floats)
DEFAULTS = {"enabled": False, "gamma": 0.01, "max_shift": 0.15, "min_history": 20, "by_regime": True}


def settings(ranges_config: dict) -> dict:
    """The ACI settings: the defaults overridden by `aci:` in the ranges config."""
    return {**DEFAULTS, **(ranges_config.get("aci") or {})}


def aci_step(
    alpha: float,
    target: float,
    err: float,
    gamma: float,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> float:
    """One ACI update. err in [0, 1] (1 = miss, or the share of misses in the step)."""
    updated_alpha = alpha + gamma * (target - err)
    if lower_bound is not None:
        updated_alpha = max(lower_bound, updated_alpha)
    if upper_bound is not None:
        updated_alpha = min(upper_bound, updated_alpha)
    return updated_alpha


def aci_path(
    errs,
    target: float,
    gamma: float,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
    alpha0: float | None = None,
) -> list[float]:
    """alpha_0 .. alpha_T for an error sequence (alpha_0 = target unless given)."""
    alpha = target if alpha0 is None else alpha0
    out = [alpha]
    for error in errs:
        alpha = aci_step(alpha, target, float(error), gamma, lower_bound, upper_bound)
        out.append(alpha)
    return out


def clamps(target: float, max_shift: float) -> tuple[float, float]:
    """State bounds: within max_shift of the target and strictly inside (0, 1)."""
    return max(0.005, target - max_shift), min(0.995, target + max_shift)


class Tracker:
    """Running ACI state per (horizon, band, key); key = regime label when by_regime, else 'all'."""

    def __init__(self, ranges_config: dict):
        """Start with no alphas or step counts (an alpha starts at its target miss rate)."""
        self.s = settings(ranges_config)
        self.alpha: dict[tuple, float] = {}
        self.steps: dict[tuple, int] = {}

    def key(self, regime: str | None) -> str:
        """The alpha key of a regime (one per regime, or `all`)."""
        return (regime or "all") if self.s["by_regime"] else "all"

    def update(self, horizon: int, band: str, key: str, err: float) -> None:
        """Move one band's alpha by one ACI step from the observed miss rate."""
        target = TARGET[band]
        state_key = (int(horizon), band, key)
        lower_bound, upper_bound = clamps(target, self.s["max_shift"])
        self.alpha[state_key] = aci_step(
            self.alpha.get(state_key, target), target, err, self.s["gamma"], lower_bound, upper_bound
        )
        self.steps[state_key] = self.steps.get(state_key, 0) + 1

    def effective(self, horizon: int, band: str, key: str) -> float:
        """alpha used for the band: the target until min_history steps were seen."""
        target = TARGET[band]
        state_key = (int(horizon), band, key)
        if self.steps.get(state_key, 0) < self.s["min_history"]:
            return target
        return self.alpha.get(state_key, target)

    def levels(self, horizon: int, key: str) -> dict[str, float]:
        """Quantile levels for q10/q25/q75/q90 (the 80% band stays at least as wide as the 50%)."""
        a50 = self.effective(horizon, "50", key)
        a80 = min(self.effective(horizon, "80", key), a50)
        return {"q10": a80 / 2, "q25": a50 / 2, "q75": 1 - a50 / 2, "q90": 1 - a80 / 2}

    def feed(self, scored_ranges: pd.DataFrame) -> None:
        """Update from scored ranges (columns horizon_days, target_date, hit50, hit80 and, when
        by_regime, regime), one step per target date in date order; err = share of misses."""
        if scored_ranges is None or scored_ranges.empty:
            return
        scored_copy = scored_ranges.copy()
        scored_copy["key"] = [
            self.key(regime_label)
            for regime_label in (scored_copy["regime"] if "regime" in scored_copy else [None] * len(scored_copy))
        ]
        # each (horizon, key) series in target-date order
        for (horizon, key), series_rows in scored_copy.groupby(["horizon_days", "key"], sort=True):
            for _, target_day_rows in series_rows.groupby("target_date", sort=True):
                for band in BANDS:
                    self.update(
                        int(horizon), band, key, 1.0 - float(target_day_rows[f"hit{band}"].astype(float).mean())
                    )

    def snapshot(self) -> list[dict]:
        """The current alphas of every horizon, band and key."""
        out = []
        for (horizon, band, key), alpha in sorted(self.alpha.items()):
            target = TARGET[band]
            out.append(
                {
                    "horizon_days": horizon,
                    "band": band,
                    "key": key,
                    "alpha": round(alpha, 5),
                    "alpha_target": target,
                    "steps": self.steps[(horizon, band, key)],
                    "effective_alpha": round(self.effective(horizon, band, key), 5),
                    "implied_coverage": round(1 - self.effective(horizon, band, key), 5),
                }
            )
        return out


# N+k ranges only: legacy_cc ranges (stored before B10) covered another window than the same horizon now
LIVE_SQL = """SELECT r.horizon_days, r.target_date, r.regime, r.hit50, r.hit80
FROM range_record r JOIN (SELECT range_id, min(scored_at) AS scored_at FROM range_outcomes GROUP BY range_id) o
  ON o.range_id = r.id
WHERE o.scored_at <= ?::TIMESTAMPTZ AND r.hit50 IS NOT NULL AND r.hit80 IS NOT NULL
  AND r.horizon_label = 'n_plus_k' ORDER BY r.id"""


def live_tracker(con, ranges_config: dict, now: str, until=None) -> Tracker:
    """ACI state from live scored ranges known at `now` (scored_at <= now), optionally only
    target dates <= until."""
    scored_ranges = con.execute(LIVE_SQL, [now]).df()
    if until is not None and not scored_ranges.empty:
        scored_ranges = scored_ranges[pd.to_datetime(scored_ranges["target_date"]).dt.date <= until]
    tracker = Tracker(ranges_config)
    tracker.feed(scored_ranges)
    return tracker
