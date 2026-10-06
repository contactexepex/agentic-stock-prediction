"""Walk-forward fitting of the signal model: expanding window, monthly refit, out-of-sample only.

For each calendar month of the panel, the refit date c is the month's first as-of date. The model used
for every as-of date of that month is fitted on the rows whose label had resolved by c (end date <= c),
never later ones. Platt calibration (p = sigmoid(a * raw_logit + b)) is fitted at c on the earlier
months' out-of-sample predictions whose labels had resolved by c, once there are `platt_min_rows` of
them, with a slope kept >= 0 (fit_platt); before that the probability is the raw model's (calibrated =
false). The live daily score (daily_scores.py) runs this same loop up to the as-of date, so the stored
model of a month is the one the backtest used for that month."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from marketbrief.model.labels import label_columns
from marketbrief.model.logistic import LogisticModel, fit_logistic, logit, newton_fit, sigmoid
from marketbrief.model.panel import feature_columns


@dataclass
class MonthlyFit:
    """The model fitted at one refit date, its calibration and its training summary."""
    cutoff: pd.Timestamp
    model: LogisticModel
    platt: tuple[float, float] | None
    platt_rows: int
    base_rate: float
    train_rows: int
    train_sessions: int

    def probability(self, raw_logit) -> np.ndarray:
        """The issued probability: Platt-calibrated when available, else the raw model's."""
        raw_logit = np.asarray(raw_logit, dtype=float)
        if self.platt is None:
            return sigmoid(raw_logit)
        slope, offset = self.platt
        return sigmoid(slope * raw_logit + offset)


def refit_dates(dates: pd.Series) -> list[pd.Timestamp]:
    """The first as-of date of each calendar month, ascending."""
    unique = pd.Series(sorted(pd.to_datetime(dates.unique())))
    return list(unique.groupby(unique.dt.to_period("M")).min())


def resolved(panel: pd.DataFrame, convention: str, horizon: int, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Rows with a label resolved by the cutoff's close (end date <= cutoff)."""
    ret_col, end_col = label_columns(convention, horizon)
    return panel[panel[ret_col].notna() & (panel[end_col] <= cutoff)]


def fit_platt(history: pd.DataFrame, min_rows: int) -> tuple[tuple[float, float] | None, int]:
    """((slope, offset), rows) fitted on past out-of-sample raw logits and outcomes, or (None, rows).
    The slope is kept >= 0 (calibration is monotone: it may shrink the model toward the base rate but
    never turn its ranking upside down, which would also reverse every explained driver); when the
    unconstrained fit gives a negative slope, the slope is 0 and the offset the past rows' logit up share."""
    if len(history) < min_rows:
        return None, len(history)
    up = history["up"].to_numpy(dtype=float)
    offset, slope = newton_fit(history[["raw_logit"]].to_numpy(), up, 0.0)
    if slope[0] < 0:
        return (0.0, float(logit(up.mean()))), len(history)
    return (float(slope[0]), float(offset)), len(history)


def fit_month(panel: pd.DataFrame, oos: pd.DataFrame, cutoff: pd.Timestamp, spec: tuple[str, str, int],
              settings: dict) -> MonthlyFit | None:
    """The fit at one refit date, or None while fewer than min_train_sessions sessions have resolved.
    spec = (market, convention, horizon)."""
    market, convention, horizon = spec
    ret_col, end_col = label_columns(convention, horizon)
    train = resolved(panel, convention, horizon, cutoff)
    sessions = int(train["date"].nunique())
    if sessions < settings["min_train_sessions"]:
        return None
    up = (train[ret_col] > 0).to_numpy(dtype=float)
    model = fit_logistic(train, up, feature_columns(market, horizon), settings)
    past = oos[oos["end"] <= cutoff] if len(oos) else oos
    platt, platt_rows = fit_platt(past, settings["platt_min_rows"])
    return MonthlyFit(cutoff, model, platt, platt_rows, float(up.mean()), len(train), sessions)


def predict_rows(fit: MonthlyFit, rows: pd.DataFrame, convention: str, horizon: int) -> pd.DataFrame:
    """Out-of-sample predictions of one month's rows (with their realised labels when resolved)."""
    ret_col, end_col = label_columns(convention, horizon)
    raw = fit.model.raw_logit(rows)
    out = rows[["date", "ticker"]].copy()
    out["raw_logit"] = raw
    out["prob_raw"] = sigmoid(raw)
    out["prob"] = fit.probability(raw)
    out["calibrated"] = fit.platt is not None
    out["base_rate"] = fit.base_rate
    out["cutoff"] = fit.cutoff
    out["ret"] = rows[ret_col].to_numpy()
    out["end"] = rows[end_col].to_numpy()
    out["up"] = (out["ret"] > 0).astype(float).where(out["ret"].notna())
    return out


def walk_forward(panel: pd.DataFrame, spec: tuple[str, str, int], settings: dict,
                 until: pd.Timestamp | None = None) -> tuple[pd.DataFrame, list[MonthlyFit]]:
    """(out-of-sample predictions for every as-of date with a model, the monthly fits), as-of dates up
    to `until` (default: all). spec = (market, convention, horizon)."""
    _, convention, horizon = spec
    rows = panel if until is None else panel[panel["date"] <= until]
    starts = refit_dates(rows["date"])
    predictions, fits = [], []
    oos = pd.DataFrame()
    for i, cutoff in enumerate(starts):
        fit = fit_month(rows, oos, cutoff, spec, settings)
        if fit is None:
            continue
        stop = starts[i + 1] if i + 1 < len(starts) else None
        month = rows[(rows["date"] >= cutoff) & ((rows["date"] < stop) if stop is not None else True)]
        predicted = predict_rows(fit, month, convention, horizon)
        predictions.append(predicted)
        oos = pd.concat([oos, predicted[predicted["up"].notna()]], ignore_index=True)
        fits.append(fit)
    out = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    return out, fits
