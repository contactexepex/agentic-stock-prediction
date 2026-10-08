"""The signal model (scripts/marketbrief/model; docs/DESIGN.md section 15) on synthetic bars: indicators equal
indicators.py at every date, the label convention, no look-ahead (perturbing bars or labels after an as-of
date changes nothing at it), calibration fitted only on the past, contributions that add up, the
logistic fit's optimality, costs, schemas and the daily score end to end.
Run: pytest -q tests/test_signal_model.py"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.analytics import indicators  # noqa: E402
from marketbrief.constants.model import (KIND_AGENT_REASONING, KIND_MODEL_SCORES, KIND_MODEL_VERSIONS,  # noqa: E402
                                         LABEL_CLOSE_TO_CLOSE, LABEL_OPEN_TO_CLOSE)
from marketbrief.core import calendar, paths  # noqa: E402
from marketbrief.core.horizons import horizons  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.model import daily_scores  # noqa: E402
from marketbrief.model.explain import explain_row  # noqa: E402
from marketbrief.model.labels import forward_labels  # noqa: E402
from marketbrief.model.logistic import fit_logistic, logit, sigmoid  # noqa: E402
from marketbrief.model.panel import build_panel  # noqa: E402
from marketbrief.model.settings import india_round_trip, load_costs, load_model_config, us_round_trip  # noqa: E402
from marketbrief.model.technical_panel import ticker_indicators  # noqa: E402
from marketbrief.model.walk_forward import fit_platt, refit_dates, resolved, walk_forward  # noqa: E402

CFG = load_market("us")
SETTINGS = {**load_model_config(), "min_train_sessions": 60, "platt_min_rows": 200, "warmup_bars": 40}
DAYS = pd.bdate_range("2025-01-02", periods=230)
INDICATOR_KEYS = ("ret_1d", "ret_3d", "ret_5d", "ret_20d", "roc_10", "ema_ratio", "rsi_14", "price_vs_20d_high",
                  "atr_pct", "realized_vol_10d", "ewma_vol", "bb_width", "obv_trend", "volume_ratio_20d", "beta_1y")


def frame(seed: int, days=DAYS, drift: float = 0.0) -> pd.DataFrame:
    """Random-walk daily bars."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, len(days))))
    opens = close * np.exp(rng.normal(0, 0.005, len(days)))
    high = np.maximum(opens, close) * (1 + rng.uniform(0, 0.01, len(days)))
    low = np.minimum(opens, close) * (1 - rng.uniform(0, 0.01, len(days)))
    volume = rng.integers(1_000_000, 5_000_000, len(days)).astype(float)
    return pd.DataFrame({"open": opens, "high": high, "low": low, "close": close, "volume": volume}, index=days)


def synthetic_inputs(days=DAYS) -> dict:
    """Bars for every US watchlist ticker and market symbol, no events or flows."""
    keys = [*CFG["tickers"], *CFG["symbols"]]
    bars = {key: frame(i, days) for i, key in enumerate(keys)}
    bars["VIX"] = bars["VIX"].assign(close=15 + 3 * np.sin(np.arange(len(days)) / 9))
    return {"bars": bars, "events": pd.DataFrame(), "shorts": pd.DataFrame(), "insiders": pd.DataFrame()}


def perturbed_after(inputs: dict, day: pd.Timestamp, factor: float = 1.37) -> dict:
    """A copy whose bars after `day` are changed (prices scaled, volumes doubled)."""
    bars = {}
    for key, bar in inputs["bars"].items():
        bar = bar.copy()
        later = bar.index > day
        bar.loc[later, ["open", "high", "low", "close"]] *= factor
        bar.loc[later, "volume"] *= 2
        bars[key] = bar
    return {**inputs, "bars": bars}


@pytest.fixture(scope="module")
def inputs() -> dict:
    return synthetic_inputs()


@pytest.fixture(scope="module")
def panel(inputs) -> pd.DataFrame:
    return build_panel(CFG, inputs, SETTINGS["warmup_bars"])


# ---------- features ----------

@pytest.mark.parametrize("cut", [25, 61, 140, 229])
def test_technical_panel_equals_indicators_at_every_date(cut):
    bars, bench = frame(1), frame(2)
    panel = ticker_indicators(bars, bench["close"])
    expected = indicators.compute(bars.iloc[:cut + 1], bench["close"].iloc[:cut + 1])
    row = panel.iloc[cut]
    for key in INDICATOR_KEYS:
        want, got = expected[key], row[key]
        if want is None:
            assert pd.isna(got), key
        else:
            assert got == pytest.approx(want, rel=1e-9, abs=1e-12), key
    assert row["atr_pct"] == pytest.approx(expected["atr_pct"], rel=1e-9)


def test_panel_features_ignore_bars_after_the_as_of_date(inputs, panel):
    day = DAYS[150]
    other = build_panel(CFG, perturbed_after(inputs, day), SETTINGS["warmup_bars"])
    features = [c for c in panel.columns if not c.startswith(("ret_open", "ret_close", "end_", "entry_open",
                                                              "bench_ret_open", "session_d", "window_end"))]
    before = panel[panel["date"] <= day][features].reset_index(drop=True)
    after = other[other["date"] <= day][features].reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)


# ---------- labels ----------

def test_label_convention_open_d_to_close_d_plus_1():
    bars = frame(5).iloc[:12]
    pos = pd.Series(np.arange(len(bars)), index=bars.index)
    one, five = forward_labels(bars, pos, 1), forward_labels(bars, pos, 5)
    o, c = bars["open"].to_numpy(), bars["close"].to_numpy()
    assert one[f"ret_{LABEL_OPEN_TO_CLOSE}_1d"].iloc[3] == pytest.approx(c[5] / o[4] - 1)     # D = 4, D+1 = 5
    assert one[f"end_{LABEL_OPEN_TO_CLOSE}_1d"].iloc[3] == bars.index[5]
    assert five[f"ret_{LABEL_OPEN_TO_CLOSE}_5d"].iloc[3] == pytest.approx(c[9] / o[4] - 1)    # N+5: D+5 = 9
    assert five[f"end_{LABEL_OPEN_TO_CLOSE}_5d"].iloc[3] == bars.index[9]
    # close_to_close shares the exit of N+k (decision 37): the as-of close to the close of D+k
    assert one[f"ret_{LABEL_CLOSE_TO_CLOSE}_1d"].iloc[3] == pytest.approx(c[5] / c[3] - 1)
    assert five[f"ret_{LABEL_CLOSE_TO_CLOSE}_5d"].iloc[3] == pytest.approx(c[9] / c[3] - 1)
    assert one["entry_open_1d"].iloc[3] == pytest.approx(o[4])
    assert pd.isna(one[f"ret_{LABEL_OPEN_TO_CLOSE}_1d"].iloc[10])                              # D+1 past the data
    assert pd.isna(five[f"ret_{LABEL_OPEN_TO_CLOSE}_5d"].iloc[6])                              # D+5 = 12 past the data
    assert pd.notna(five[f"ret_{LABEL_OPEN_TO_CLOSE}_5d"].iloc[5])                             # D+5 = 11, the last bar


@pytest.mark.parametrize("horizon", [1, 2, 3, 4, 5])
def test_every_horizon_sells_at_the_close_of_the_kth_session_after_d(horizon):
    bars = frame(5).iloc[:12]
    pos = pd.Series(np.arange(len(bars)), index=bars.index)
    labels = forward_labels(bars, pos, horizon)
    o, c = bars["open"].to_numpy(), bars["close"].to_numpy()
    assert labels[f"ret_{LABEL_OPEN_TO_CLOSE}_{horizon}d"].iloc[2] == pytest.approx(c[3 + horizon] / o[3] - 1)
    assert labels[f"end_{LABEL_OPEN_TO_CLOSE}_{horizon}d"].iloc[2] == bars.index[3 + horizon]


def test_label_missing_when_a_session_is_skipped():
    bars = frame(6).iloc[:10]
    extra = pd.DatetimeIndex([bars.index[-1] + pd.Timedelta(days=1)])
    sessions = pd.Series(np.arange(11), index=bars.index.append(extra))
    gap = bars.drop(bars.index[5])                                                              # no bar on session 5
    labels = forward_labels(gap, sessions, 1)
    assert pd.isna(labels[f"ret_{LABEL_OPEN_TO_CLOSE}_1d"].loc[bars.index[3]])                 # spans session 5
    assert pd.isna(labels[f"ret_{LABEL_OPEN_TO_CLOSE}_1d"].loc[bars.index[4]])
    assert pd.notna(labels[f"ret_{LABEL_OPEN_TO_CLOSE}_1d"].loc[bars.index[1]])


# ---------- training never sees the future ----------

def test_training_uses_only_labels_resolved_by_the_cutoff(panel):
    cutoff = refit_dates(panel["date"])[5]
    train = resolved(panel, LABEL_OPEN_TO_CLOSE, 5, cutoff)
    assert (train[f"end_{LABEL_OPEN_TO_CLOSE}_5d"] <= cutoff).all()
    ret = f"ret_{LABEL_OPEN_TO_CLOSE}_5d"
    changed = panel.copy()
    later = changed[f"end_{LABEL_OPEN_TO_CLOSE}_5d"] > cutoff
    changed.loc[later, ret] = -changed.loc[later, ret]                                          # flip unresolved labels
    _, fits = walk_forward(panel, ("us", LABEL_OPEN_TO_CLOSE, 5), SETTINGS, until=cutoff)
    _, fits_changed = walk_forward(changed, ("us", LABEL_OPEN_TO_CLOSE, 5), SETTINGS, until=cutoff)
    assert fits[-1].cutoff == cutoff
    assert fits[-1].model.coefficients == fits_changed[-1].model.coefficients
    assert fits[-1].platt == fits_changed[-1].platt


def test_score_at_a_past_date_ignores_everything_after_it(inputs, panel):
    day = DAYS[200]
    other = build_panel(CFG, perturbed_after(inputs, day), SETTINGS["warmup_bars"])
    spec = ("us", LABEL_OPEN_TO_CLOSE, 1)
    oos, fits = walk_forward(panel, spec, SETTINGS, until=day)
    oos_other, fits_other = walk_forward(other, spec, SETTINGS, until=day)
    at = oos[oos["date"] == day][["ticker", "prob", "raw_logit"]].reset_index(drop=True)
    at_other = oos_other[oos_other["date"] == day][["ticker", "prob", "raw_logit"]].reset_index(drop=True)
    assert len(at) == len(CFG["tickers"])
    pd.testing.assert_frame_equal(at, at_other)
    assert fits[-1].model.to_json() == fits_other[-1].model.to_json()


def test_platt_is_fitted_only_on_past_out_of_sample_rows(panel):
    spec = ("us", LABEL_OPEN_TO_CLOSE, 1)
    oos, fits = walk_forward(panel, spec, SETTINGS)
    calibrated = [f for f in fits if f.platt is not None]
    assert calibrated, "the synthetic history should reach platt_min_rows"
    fit = calibrated[0]
    past = oos[(oos["up"].notna()) & (oos["end"] <= fit.cutoff)]
    assert (past["date"] < fit.cutoff).all()
    assert fit_platt(past, SETTINGS["platt_min_rows"]) == (fit.platt, fit.platt_rows)
    before = [f for f in fits if f.cutoff < fit.cutoff]
    assert all(f.platt is None for f in before)


def test_platt_slope_never_inverts_the_ranking():
    rng = np.random.default_rng(9)
    raw = rng.normal(size=600)
    inverted = pd.DataFrame({"raw_logit": raw, "up": (rng.random(600) < sigmoid(-raw)).astype(float)})
    (slope, offset), rows = fit_platt(inverted, 100)
    assert rows == 600 and slope == 0.0
    assert offset == pytest.approx(float(logit(inverted["up"].mean())))
    aligned = inverted.assign(up=(rng.random(600) < sigmoid(raw)).astype(float))
    assert fit_platt(aligned, 100)[0][0] > 0
    assert fit_platt(aligned, 601) == (None, 600)


def test_metrics_auc_reliability_and_bootstrap():
    from marketbrief.model.metrics import auc, block_bootstrap, reliability
    assert auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == pytest.approx(0.75)
    assert auc([0.5, 0.5], [0, 1]) == pytest.approx(0.5)
    assert auc([0.2, 0.3], [1, 1]) is None
    bins = reliability([0.42, 0.44, 0.61, 1.0], [0, 1, 1, 1], [0.0, 0.45, 0.6, 1.0])
    assert [b["n"] for b in bins] == [2, 0, 2] and bins[0]["up_share"] == 0.5 and bins[2]["bin"] == "[0.60, 1.00]"
    low, high = block_bootstrap(pd.Series([0.01] * 50), 5, 200, 1)
    assert low == high == 0.01


def test_paper_strategy_nets_costs_per_date():
    from marketbrief.model.paper import paper_results
    days = pd.to_datetime(["2026-01-05", "2026-01-05", "2026-01-06", "2026-01-06"])
    frame_ = pd.DataFrame({"date": days, "ticker": ["A", "B", "A", "B"], "prob": [0.7, 0.3, 0.7, 0.7],
                           "ret": [0.02, -0.01, -0.01, 0.03], "entry_open": 100.0, "ret_5d": [0.01, -0.02, 0.0, 0.01],
                           "rsi_14": [50, 25, 50, 50], "bench_ret": [0.001, 0.001, 0.002, 0.002]})
    settings = {"backtest": {**SETTINGS["backtest"], "thresholds": [0.65], "bootstrap_samples": 50}}
    costs = load_costs("india")
    out = paper_results(frame_, "india", costs, settings, 1)
    cost = india_round_trip(costs)
    long = out["thresholds"]["0.65"]["long"]
    assert long["positions"] == 3 and long["dates"] == 2
    assert long["mean_pct"] == pytest.approx(round(100 * ((0.02 - cost) + (0.01 - cost)) / 2, 4))   # day 2: 1%
    sell = out["thresholds"]["0.65"]["sell_if_held"]["gross"]
    assert sell["positions"] == 1 and sell["mean_pct"] == pytest.approx(1.0)
    assert out["baselines"]["rsi_mean_reversion"]["positions"] == 1


def test_backtest_verdict_words():
    from marketbrief.model.backtest import threshold_verdicts
    paper = {"long": {"positions": 300}, "vs": {
        "a": {"dates": 40, "mean_pct": 0.3, "ci95_pct": [0.1, 0.5]},
        "b": {"dates": 40, "mean_pct": -0.3, "ci95_pct": [-0.5, -0.1]},
        "c": {"dates": 40, "mean_pct": 0.0, "ci95_pct": [-0.2, 0.2]},
        "d": {"dates": 3, "mean_pct": -0.7, "ci95_pct": [-0.7, -0.7]}}}
    lines = threshold_verdicts("0.60", paper)
    assert "beats a" in lines[0] and "is worse than b" in lines[1] and "is not distinguishable from c" in lines[2]
    assert "3 common date(s), fewer than 20: no verdict" in lines[3]
    assert "no long positions" in threshold_verdicts("0.65", {"long": {"positions": 0}, "vs": {}})[0]


# ---------- the formula ----------

def test_logistic_fit_is_the_penalised_optimum():
    rng = np.random.default_rng(3)
    frame_ = pd.DataFrame({"a": rng.normal(size=800), "b": rng.normal(size=800), "c": np.nan})
    y = (rng.random(800) < sigmoid(0.8 * frame_["a"] - 0.3)).astype(float)
    settings = {"l2_alpha": 0.05, "z_clip": 5.0, "min_feature_coverage": 0.8}
    model = fit_logistic(frame_, y, ["a", "b", "c"], settings)
    assert model.features == ["a", "b"] and "c" in model.excluded
    z = model.standardise(frame_)
    p = sigmoid(model.raw_logit(frame_))
    gradient = z.T @ (p - y) / len(y) + settings["l2_alpha"] * np.asarray(model.coefficients)
    assert np.abs(gradient).max() < 1e-8 and abs(float(np.mean(p - y))) < 1e-8
    assert np.allclose(model.contributions(frame_).sum(axis=1), model.raw_logit(frame_) - model.intercept)


def test_contributions_add_up_to_the_probability(panel):
    _, fits = walk_forward(panel, ("us", LABEL_OPEN_TO_CLOSE, 5), SETTINGS)
    fit = fits[-1]
    row = panel[panel["date"] == panel["date"].max()].head(1).reset_index(drop=True)
    out = explain_row(fit, row, news_logit=0.07, news_text="news")
    items = out["logit_items"]
    assert sum(items.values()) == pytest.approx(float(logit(out["prob_up"]) - logit(fit.base_rate)), abs=1e-9)
    assert sum(out["points"].values()) == pytest.approx(100 * (out["prob_up"] - fit.base_rate), abs=0.05)
    issued = float(fit.probability(fit.model.raw_logit(row))[0])
    assert out["prob_model"] == pytest.approx(issued)
    assert out["prob_up"] == pytest.approx(float(sigmoid(logit(issued) + 0.07)))
    assert len(out["up"]) <= 3 and len(out["down"]) <= 3


# ---------- costs ----------

def test_india_round_trip_cost():
    costs = load_costs("india")
    taxable = 0.0 + 0.0000307 + 0.000001
    expected = 2 * (taxable + 0.001 + 0.18 * taxable) + 0.00015
    assert india_round_trip(costs) == pytest.approx(expected)
    assert expected == pytest.approx(0.002224812, abs=1e-12)   # about 0.222% per round trip


def test_us_round_trip_cost_and_taf_cap():
    costs = load_costs("us")                                              # TAF paused at $0 (2026-10-01..12-31)
    assert us_round_trip(costs, 100.0) == pytest.approx(0.0000206)
    regular = {**costs, "finra_taf_per_share_sell": 0.000195, "finra_taf_max_per_trade": 9.79}   # from 2027-01-01
    assert us_round_trip(regular, 100.0) == pytest.approx(0.0000206 + 0.000195 * 100 / 10000)
    tiny = us_round_trip(regular, 0.01)                                   # 1,000,000 shares: TAF capped
    assert tiny == pytest.approx(0.0000206 + 9.79 / 10000)


# ---------- schemas and the daily score ----------

def test_new_kinds_have_schemas():
    for kind in (KIND_MODEL_SCORES, KIND_MODEL_VERSIONS, KIND_AGENT_REASONING):
        assert kind in SCHEMAS
    for column in ("model_prob", "agent_adjustment", "adjustment_reason"):
        assert column in SCHEMAS["predictions"][1]


def write_prices(root: Path, inputs: dict) -> None:
    """The synthetic bars as stored price files."""
    rows = [{"date": d.date().isoformat(), "ticker": key, "open": b.open, "high": b.high, "low": b.low,
             "close": b.close, "adj_close": b.close, "volume": int(b.volume), "collected_at": f"{d.date()}T22:00:00Z"}
            for key, bars in inputs["bars"].items() for d, b in bars.iterrows()]
    out = pd.DataFrame(rows)
    for day, group in out.groupby("date"):
        path = root / "data" / "us" / "prices" / day[:4] / day[5:7] / f"{day}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        group[list(SCHEMAS["prices"][1])].to_csv(path, index=False)


def test_daily_scores_end_to_end(tmp_path, monkeypatch, inputs):
    write_prices(tmp_path, inputs)
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setenv("MB_NOW", f"{DAYS[-1].date() + pd.Timedelta(days=1)}T12:00:00+00:00")
    monkeypatch.setattr(daily_scores, "load_model_config", lambda: SETTINGS)
    first = daily_scores.run(CFG)
    count = 2 * len(horizons())               # N+1..N+5 (config/strategies.yaml) x the base and cross_market models
    assert first["scores"] == count * len(CFG["tickers"]) and len(first["new_model_versions"]) == count
    files = list((tmp_path / "data" / "us" / KIND_MODEL_SCORES).rglob("*.jsonl"))
    rows = [json.loads(x) for f in files for x in f.read_text().splitlines()]
    assert set(rows[0]) == set(SCHEMAS[KIND_MODEL_SCORES][1])
    rows = sorted(rows, key=lambda r: r["id"])
    assert rows[0]["id"] == f"{DAYS[-1].date()}-{rows[0]['ticker']}-{rows[0]['horizon_days']}d"
    assert all(0 < r["prob_up"] < 1 and r["label_convention"] == LABEL_OPEN_TO_CLOSE for r in rows)
    assert {r["horizon_days"] for r in rows} == set(horizons()) and {r["horizon_label"] for r in rows} == {"n_plus_k"}
    assert not any("cross_market" in r["id"] or "model_variant" in r for r in rows)   # base model only
    variant = [json.loads(x) for f in (tmp_path / "data" / "us" / "model_variant_scores").rglob("*.jsonl")
               for x in f.read_text().splitlines()]
    assert len(variant) == len(rows) and {r["model_variant"] for r in variant} == {"cross_market"}
    assert all(r["id"].endswith("d-cross_market") and set(r) == set(SCHEMAS["model_variant_scores"][1])
               for r in variant)
    for r in rows:                                                        # D and the k-th session after D
        days = calendar.sessions_ahead(CFG, DAYS[-1].date() + pd.Timedelta(days=1), r["horizon_days"] + 1)
        assert (r["entry_date"], r["exit_date"]) == (str(days[0]), str(days[-1]))
    versions = [json.loads(x) for f in (tmp_path / "data" / "us" / KIND_MODEL_VERSIONS).rglob("*.jsonl")
                for x in f.read_text().splitlines()]
    assert set(versions[0]) == set(SCHEMAS[KIND_MODEL_VERSIONS][1])
    assert not math.isnan(versions[0]["model"]["intercept"])
    fits = [json.loads(x) for f in (tmp_path / "data" / "us" / "model_variant_versions").rglob("*.jsonl")
            for x in f.read_text().splitlines()]
    base = {v["horizon_days"]: set(v["model"]["features"]) for v in versions}
    cross = {v["horizon_days"]: set(v["model"]["features"]) for v in fits}
    assert sorted(cross) == sorted(base) == list(horizons())                 # the variant's own fits (issue #124)
    assert all(base[h] < cross[h] and all(x.startswith("x_") for x in cross[h] - base[h]) for h in base)
    second = daily_scores.run(CFG)                                        # same day again: stored model reused
    assert second["scores"] == 0 and second["unchanged"] == count * len(CFG["tickers"])
    assert second["new_model_versions"] == []
