"""L2-regularised logistic regression on standardised features, written out (library, pure numpy).

    z_j   = clip((x_j - mean_j) / sd_j, -z_clip, z_clip), and 0 (the training mean) when x_j is missing
    logit = b0 + sum_j b_j z_j,   p = 1 / (1 + exp(-logit))
    fit:  minimise  mean_i[-y_i ln p_i - (1 - y_i) ln(1 - p_i)] + alpha / 2 * sum_j b_j^2   (b0 not penalised)

solved by Newton's method (iteratively reweighted least squares); the objective is strictly convex, so
the solution is unique and the fit deterministic. Means and standard deviations come from the training
rows only. A feature enters only when it is non-missing in at least `min_coverage` of the training rows
and varies there; the others are listed as excluded with the reason."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from marketbrief.constants.model import MSG_EXCLUDED_CONSTANT, MSG_EXCLUDED_COVERAGE

MAX_ITERATIONS = 50
TOLERANCE = 1e-10
MIN_SD = 1e-12


def sigmoid(x):
    """The logistic function, stable for large |x|."""
    x = np.asarray(x, dtype=float)
    return np.where(x >= 0, 1 / (1 + np.exp(-np.abs(x))), np.exp(-np.abs(x)) / (1 + np.exp(-np.abs(x))))


def logit(p):
    """ln(p / (1 - p)), with p kept inside (1e-9, 1 - 1e-9)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


@dataclass
class LogisticModel:
    """A fitted model: the features in order, their training means and sds, the coefficients."""
    features: list[str]
    means: list[float]
    sds: list[float]
    coefficients: list[float]
    intercept: float
    z_clip: float
    excluded: dict[str, str] = field(default_factory=dict)

    def standardise(self, frame: pd.DataFrame) -> np.ndarray:
        """The z matrix of the model's features (missing -> 0, clipped to +-z_clip)."""
        raw = frame[self.features].to_numpy(dtype=float) if self.features else np.zeros((len(frame), 0))
        z = (raw - np.asarray(self.means)) / np.asarray(self.sds)
        return np.clip(np.nan_to_num(z, nan=0.0), -self.z_clip, self.z_clip)

    def contributions(self, frame: pd.DataFrame) -> np.ndarray:
        """b_j * z_j per row and feature (logit units); their row sum is logit - b0."""
        return self.standardise(frame) * np.asarray(self.coefficients)

    def raw_logit(self, frame: pd.DataFrame) -> np.ndarray:
        """b0 + sum_j b_j z_j per row."""
        return self.intercept + self.contributions(frame).sum(axis=1)

    def to_json(self) -> dict:
        """The model as plain JSON values (the stored formula)."""
        return {"features": self.features, "means": self.means, "sds": self.sds, "coefficients": self.coefficients,
                "intercept": self.intercept, "z_clip": self.z_clip, "excluded": self.excluded}

    @classmethod
    def from_json(cls, data: dict) -> LogisticModel:
        """The model back from to_json()."""
        return cls(list(data["features"]), list(data["means"]), list(data["sds"]), list(data["coefficients"]),
                   float(data["intercept"]), float(data["z_clip"]), dict(data.get("excluded") or {}))


def select_features(frame: pd.DataFrame, candidates: list[str], min_coverage: float) -> tuple[list[str], dict]:
    """(features usable in this training frame, {excluded feature: reason})."""
    kept, excluded = [], {}
    for name in candidates:
        column = frame[name] if name in frame else pd.Series(np.nan, index=frame.index)
        share = float(column.notna().mean()) if len(column) else 0.0
        if share < min_coverage:
            excluded[name] = MSG_EXCLUDED_COVERAGE.format(share=share, need=min_coverage)
        elif column.dropna().nunique() < 2:
            excluded[name] = MSG_EXCLUDED_CONSTANT
        else:
            kept.append(name)
    return kept, excluded


def newton_fit(z: np.ndarray, y: np.ndarray, alpha: float) -> tuple[float, np.ndarray]:
    """(intercept, coefficients) minimising the penalised mean log loss (IRLS)."""
    n, k = z.shape
    design = np.hstack([np.ones((n, 1)), z])
    beta = np.zeros(k + 1)
    beta[0] = float(logit(np.clip(y.mean(), 1e-6, 1 - 1e-6)))
    penalty = np.full(k + 1, alpha)
    penalty[0] = 0.0
    for _ in range(MAX_ITERATIONS):
        p = sigmoid(design @ beta)
        gradient = design.T @ (p - y) / n + penalty * beta
        hessian = (design * (p * (1 - p))[:, None]).T @ design / n + np.diag(penalty)
        step = np.linalg.solve(hessian + 1e-12 * np.eye(k + 1), gradient)
        beta = beta - step
        if np.max(np.abs(step)) < TOLERANCE:
            break
    return float(beta[0]), beta[1:]


def fit_logistic(frame: pd.DataFrame, y: np.ndarray, candidates: list[str], settings: dict) -> LogisticModel:
    """Fit on the training frame. settings: l2_alpha, z_clip, min_feature_coverage."""
    features, excluded = select_features(frame, candidates, settings["min_feature_coverage"])
    raw = frame[features].to_numpy(dtype=float)
    means = np.nanmean(raw, axis=0) if features else np.zeros(0)
    sds = np.nanstd(raw, axis=0) if features else np.zeros(0)
    sds = np.where(sds > MIN_SD, sds, 1.0)
    model = LogisticModel(features, [float(x) for x in means], [float(x) for x in sds], [0.0] * len(features), 0.0,
                          float(settings["z_clip"]), excluded)
    intercept, coefficients = newton_fit(model.standardise(frame), np.asarray(y, dtype=float), settings["l2_alpha"])
    model.intercept, model.coefficients = intercept, [float(x) for x in coefficients]
    return model
