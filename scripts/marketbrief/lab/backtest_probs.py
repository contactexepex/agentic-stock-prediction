"""The signal model's out-of-sample probabilities for the F2.3 back-test's model strategies without news
(base.model_only.v1 and any model strategy with news weight 0): B10's walk-forward (model/walk_forward.py, the same
monthly expanding-window fits as model_backtest.py and the live daily score) on the open_to_close label of every
horizon N+k of the registry, as of the run's clock.

No look-ahead: the panel's inputs are cut to what was known at the end of the clock's last complete session
(model/panel_inputs.inputs_until: bars dated on or before it, events and flows by their first-seen or publication day),
so a label needing a later bar is missing; walk_forward then fits each month only on labels resolved by that month's
first as-of date (end date <= the refit date) and predicts only that month's as-of dates; `until` is the same
session, and any prediction dated after it is dropped. Research only: nothing here trades."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from marketbrief.constants.model import LABEL_OPEN_TO_CLOSE
from marketbrief.core.calendar import last_complete_session
from marketbrief.core.market_config import benchmark_key
from marketbrief.lab import registry
from marketbrief.model.history_cache import merged_bars
from marketbrief.model.panel import build_panel
from marketbrief.model.panel_inputs import inputs_until, read_inputs
from marketbrief.model.settings import cross_groups, load_model_config
from marketbrief.model.walk_forward import walk_forward

PROBS_SOURCE = "walk_forward:{version}"
MSG_NO_MODEL_BENCHMARK = "model-only not run: no stored benchmark bars for the signal model's panel"
MSG_NO_MODEL_FIT = ("model-only not run: the walk-forward has no fit yet (fewer than {need} resolved sessions by the "
                    "clock; --history adds the long-history cache)")


def model_probs(con, cfg: dict, now: datetime, cached: dict | None = None) -> tuple[dict, str | None, str | None]:
    """({(ticker, k): Series of p_up by as-of date}, probs_source, note). `cached`: the long-history cache's bars
    (--history; data/'s bars win on their dates). probs_source is None and note says why when no probability came
    out; otherwise note is None."""
    market, settings = cfg["market"], load_model_config()
    inputs = read_inputs(con, market)
    if cached:
        inputs["bars"], _ = merged_bars(inputs["bars"], cached)
    last = pd.Timestamp(last_complete_session(cfg, now))
    inputs = inputs_until(inputs, last)
    if benchmark_key(cfg) not in inputs["bars"] or inputs["bars"][benchmark_key(cfg)].empty:
        return {}, None, MSG_NO_MODEL_BENCHMARK
    panel = build_panel(cfg, inputs, settings["warmup_bars"], cross_groups(settings, market))
    probs: dict[tuple[str, int], pd.Series] = {}
    for k in registry.horizons():
        if panel.empty:
            break
        oos, _ = walk_forward(panel, (market, LABEL_OPEN_TO_CLOSE, k), settings, until=last)
        if oos.empty:
            continue
        oos = oos[pd.to_datetime(oos["date"]) <= last]
        for ticker, group in oos.groupby("ticker"):
            probs[(ticker, k)] = pd.Series(group["prob"].to_numpy(dtype=float),
                                           index=pd.DatetimeIndex(pd.to_datetime(group["date"]))).sort_index()
    if not probs:
        return {}, None, MSG_NO_MODEL_FIT.format(need=settings["min_train_sessions"])
    return probs, PROBS_SOURCE.format(version=settings["model_version"]), None
