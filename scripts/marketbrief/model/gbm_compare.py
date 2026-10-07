"""A small gradient-boosted model for comparison only (backtest; never used for the daily score).

Same panel, same monthly refit dates and the same resolved-by-cutoff training rows and features as walk_forward.py,
scikit-learn's HistGradientBoostingClassifier (depth 3, 100 trees, learning rate 0.05, fixed seed;
settings chosen a priori, not tuned), raw probabilities without calibration. scikit-learn is not a
requirement of the project: without it the comparison is skipped and the backtest says so."""
from __future__ import annotations

import numpy as np
import pandas as pd

from marketbrief.constants.model import MSG_GBM_SKIPPED
from marketbrief.model.labels import label_columns
from marketbrief.model.logistic import select_features
from marketbrief.model.metrics import auc, brier, r
from marketbrief.model.panel import feature_columns
from marketbrief.model.settings import cross_groups
from marketbrief.model.walk_forward import refit_dates, resolved

GBM_PARAMS = {"max_depth": 3, "max_iter": 100, "learning_rate": 0.05, "random_state": 0}


def gbm_walk_forward(panel: pd.DataFrame, spec: tuple[str, str, int], settings: dict) -> dict:
    """{n, brier, brier_base_rate, auc} of the out-of-sample gradient-boosted probabilities, or {skipped}."""
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError:
        return {"skipped": MSG_GBM_SKIPPED}
    market, convention, horizon = spec
    ret_col, _ = label_columns(convention, horizon)
    candidates = feature_columns(market, horizon, cross_groups(settings, market))
    starts = refit_dates(panel["date"])
    probs, ups, bases = [], [], []
    for i, cutoff in enumerate(starts):
        train = resolved(panel, convention, horizon, cutoff)
        if train["date"].nunique() < settings["min_train_sessions"]:
            continue
        stop = starts[i + 1] if i + 1 < len(starts) else pd.Timestamp.max
        month = panel[(panel["date"] >= cutoff) & (panel["date"] < stop) & panel[ret_col].notna()]
        if month.empty:
            continue
        y = (train[ret_col] > 0).astype(int)
        features, _ = select_features(train, candidates, settings["min_feature_coverage"])
        model = HistGradientBoostingClassifier(**GBM_PARAMS).fit(train[features].to_numpy(dtype=float), y)
        probs.append(model.predict_proba(month[features].to_numpy(dtype=float))[:, 1])
        ups.append((month[ret_col] > 0).to_numpy(dtype=float))
        bases.append(np.full(len(month), y.mean()))
    if not probs:
        return {"n": 0}
    p, y, base = np.concatenate(probs), np.concatenate(ups), np.concatenate(bases)
    return {"n": int(len(y)), "brier": r(brier(p, y)), "brier_base_rate": r(brier(base, y)), "auc": r(auc(p, y)),
            "params": GBM_PARAMS}
