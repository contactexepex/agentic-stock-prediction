"""Cross-market features of the signal model (scripts/marketbrief/model/cross_market.py; docs/DESIGN.md section 15),
the long-history cache (history_cache.py) and the backtest variants (backtest_variants.py), on synthetic bars.

The look-ahead rule is by clock time: a feature of as-of date d may only use a bar whose close (+ the settle
time) is at or before the regular open of D, the first session after d. Each feature has a test that changes
every bar that is not final by that open (and every own-market bar after d) and finds the feature unchanged
on every row up to d, and a control that changing the bar the rule does use changes the value.
Run: pytest -q tests/test_cross_market.py"""
from __future__ import annotations

import gzip
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.constants.model import (CROSS_MARKET_FEATURES, CROSS_MAX_AGE_DAYS, FEATURE_GROUPS,  # noqa: E402
                                         FEATURE_TEXT, KIND_ADR_PREMIUM)
from marketbrief.core import calendar as cal  # noqa: E402
from marketbrief.core import paths  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.model import backtest_variants as variants  # noqa: E402
from marketbrief.model import history_cache  # noqa: E402
from marketbrief.model.cross_market import adr_symbols, available_at, close_time, newest_available  # noqa: E402
from marketbrief.model.panel import build_panel, feature_columns  # noqa: E402
from marketbrief.model.settings import cross_groups  # noqa: E402

DAYS = pd.bdate_range("2026-03-02", periods=110)
WARMUP = 40
CFGS = {market: load_market(market) for market in ("india", "us")}
ALL_GROUPS = {market: tuple(CROSS_MARKET_FEATURES[market]) for market in CFGS}
FEATURES = [(market, feature) for market in CFGS for groups in CROSS_MARKET_FEATURES[market].values()
            for feature in groups]


def frame(seed: int, days=DAYS) -> pd.DataFrame:
    """Random-walk daily bars."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, len(days))))
    opens = close * np.exp(rng.normal(0, 0.004, len(days)))
    return pd.DataFrame({"open": opens, "high": np.maximum(opens, close) * 1.004,
                         "low": np.minimum(opens, close) * 0.996, "close": close,
                         "volume": rng.integers(1_000_000, 3_000_000, len(days)).astype(float)}, index=days)


def synthetic_inputs(market: str) -> dict:
    """Bars for every ticker and symbol of the market (cross symbols on every weekday, like the benchmark)."""
    cfg = CFGS[market]
    keys = [*cfg["tickers"], *cfg["symbols"]]
    bars = {key: frame(i) for i, key in enumerate(keys)}
    vol = cfg["regime"]["calm_vol"] + 2
    for key, meta in cfg["symbols"].items():
        if meta.get("role") == "vol_index":
            bars[key] = bars[key].assign(close=vol + np.sin(np.arange(len(DAYS)) / 7))
    out = {"bars": bars, "events": pd.DataFrame()}
    return {**out, "flows": pd.DataFrame(), "fpi": pd.DataFrame()} if market == "india" else \
        {**out, "shorts": pd.DataFrame(), "insiders": pd.DataFrame()}


def open_of_next_session(cfg: dict, day: pd.Timestamp) -> pd.Timestamp:
    """The regular open (UTC) of the first synthetic session after `day`."""
    nxt = DAYS[DAYS.get_loc(day) + 1]
    return pd.Timestamp(cal.session_open_utc(cfg, nxt.date()))


def perturbed_after_open(cfg: dict, inputs: dict, day: pd.Timestamp, factor: float = 1.29) -> dict:
    """A copy in which every cross-market bar not final by the open of D (the session after `day`) and every
    own-market bar after `day` is changed."""
    cutoff = open_of_next_session(cfg, day)
    bars = {}
    for key, bar in inputs["bars"].items():
        bar = bar.copy()
        timed = (cfg["symbols"].get(key) or {}).get("close_time")
        later = (available_at(bar.index, timed) > cutoff) if timed else (bar.index > day)
        bar.loc[np.asarray(later), ["open", "high", "low", "close"]] *= factor
        bars[key] = bar
    return {**inputs, "bars": bars}


@pytest.fixture(scope="module")
def panels() -> dict:
    out = {}
    for market in CFGS:
        inputs = synthetic_inputs(market)
        out[market] = (inputs, build_panel(CFGS[market], inputs, WARMUP, ALL_GROUPS[market]))
    return out


# ---------- the clock rule ----------

def test_available_at_is_local_close_plus_settle():
    stamps = available_at(pd.DatetimeIndex(["2026-10-06", "2026-01-06"]), "15:30 Asia/Seoul")
    assert list(stamps) == [pd.Timestamp("2026-10-06 08:30", tz="UTC"), pd.Timestamp("2026-01-06 08:30", tz="UTC")]
    london = available_at(pd.DatetimeIndex(["2026-07-01", "2026-01-05"]), "23:59 Europe/London")
    assert list(london) == [pd.Timestamp("2026-07-02 00:59", tz="UTC"), pd.Timestamp("2026-01-06 01:59", tz="UTC")]


@pytest.mark.parametrize("market, want", [
    # India opens 09:15 IST (03:45 UTC): every other market's bar of D closes after that, so all use d
    ("india", {"KOSPI": "d", "TAIWAN": "d", "SHANGHAI": "d", "NIKKEI": "d", "HANGSENG": "d", "STOXX50": "d",
               "NASDAQ": "d", "SPX": "d", "USVIX": "d", "USDJPY": "d", "USDINR": "d", "DXY": "d", "US10Y": "d",
               "BRENT": "d", "GOLD": "d", "ADR_HDB": "d", "ADR_INFY": "d"}),
    # the US opens 09:30 ET: Asia of D has closed (and settled) by then, Europe of D has not
    ("us", {"NIKKEI": "D", "HANGSENG": "D", "KOSPI": "D", "STOXX50": "d", "DAX": "d", "FTSE": "d",
            "USDJPY": "d", "USDCNY": "d", "DXY": "d", "US10Y": "d", "WTI": "d", "GOLD": "d"}),
])
@pytest.mark.parametrize("d", ["2026-07-06", "2026-12-07"])        # summer and winter time
def test_which_session_each_symbol_contributes(market, want, d):
    cfg = CFGS[market]
    day = pd.Timestamp(d)
    nxt = day + pd.Timedelta(days=1)
    opens = pd.DatetimeIndex([pd.Timestamp(cal.session_open_utc(cfg, nxt.date()))])
    for key, which in want.items():
        series = pd.Series([1.0, 2.0, 3.0], index=pd.DatetimeIndex([day - pd.Timedelta(days=1), day, nxt]))
        values, dates = newest_available(series, close_time(cfg, key), opens, pd.Series([nxt]))
        assert pd.Timestamp(dates[0]) == (day if which == "d" else nxt), key


def test_stale_bar_is_missing_not_zero():
    cfg = CFGS["us"]
    nxt = pd.Timestamp("2026-10-15")
    opens = pd.DatetimeIndex([pd.Timestamp(cal.session_open_utc(cfg, nxt.date()))])
    old = nxt - pd.Timedelta(days=CROSS_MAX_AGE_DAYS + 1)
    values, dates = newest_available(pd.Series([0.01], index=[old]), close_time(cfg, "STOXX50"), opens,
                                     pd.Series([nxt]))
    assert np.isnan(values[0]) and pd.isna(dates[0])


# ---------- one no-look-ahead test per feature ----------

@pytest.mark.parametrize("market, feature", FEATURES)
def test_feature_ignores_bars_not_final_before_the_open(panels, market, feature):
    inputs, panel = panels[market]
    cfg = CFGS[market]
    day = DAYS[80]
    other = build_panel(cfg, perturbed_after_open(cfg, inputs, day), WARMUP, ALL_GROUPS[market])
    before = panel[panel["date"] <= day][["date", "ticker", feature]].reset_index(drop=True)
    after = other[other["date"] <= day][["date", "ticker", feature]].reset_index(drop=True)
    assert before[feature].notna().any(), feature
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize("market, feature", FEATURES)
def test_feature_uses_the_bar_the_rule_names(panels, market, feature):
    """Control: changing the newest bar that IS final before the open changes the feature at d."""
    inputs, panel = panels[market]
    cfg = CFGS[market]
    day = DAYS[80]
    key, kind = next(spec for groups in CROSS_MARKET_FEATURES[market].values() for f, spec in groups.items()
                     if f == feature)
    keys = list(adr_symbols(cfg).values()) if kind == KIND_ADR_PREMIUM else [key]
    cutoff = open_of_next_session(cfg, day)
    bars = dict(inputs["bars"])
    for name in keys:
        bar = bars[name].copy()
        used = bar.index[np.asarray(available_at(bar.index, close_time(cfg, name)) <= cutoff)][-1]
        bar.loc[used, "close"] *= 1.05
        bars[name] = bar
    other = build_panel(cfg, {**inputs, "bars": bars}, WARMUP, ALL_GROUPS[market])
    at, changed = panel[panel["date"] == day][feature], other[other["date"] == day][feature]
    assert not np.allclose(at.fillna(0).to_numpy(), changed.fillna(0).to_numpy()), feature


def test_missing_before_the_symbol_has_data(panels):
    inputs, _ = panels["india"]
    cfg = CFGS["india"]
    late = {**inputs["bars"], **{key: inputs["bars"][key].iloc[70:] for key in ("KOSPI", "ADR_HDB")}}
    panel = build_panel(cfg, {**inputs, "bars": late}, WARMUP, ALL_GROUPS["india"])
    early = panel[panel["date"] < DAYS[70]]
    assert early["x_kospi_ret"].isna().all()
    assert early[early["ticker"] == "HDFCBANK"]["adr_premium_dev"].isna().all()
    assert (early[early["ticker"] == "TCS"]["adr_premium_dev"] == 0).all()           # no ADR: not applicable
    later = panel[panel["date"] > DAYS[72]]
    assert later["x_kospi_ret"].notna().all()


def test_adr_premium_deviation_by_hand(panels):
    inputs, panel = panels["india"]
    bars = inputs["bars"]
    rows = panel[panel["ticker"] == "INFY"].set_index("date")
    premium = np.log(bars["ADR_INFY"]["close"] * bars["USDINR"]["close"] / bars["INFY"]["close"]).reindex(rows.index)
    day = rows.index[50]
    i = rows.index.get_loc(day)
    want = premium.iloc[i] - premium.iloc[i - 20:i].mean()
    assert rows.loc[day, "adr_premium_dev"] == pytest.approx(want, rel=1e-9)


# ---------- config, switches and names ----------

def test_every_cross_symbol_is_configured_with_a_close_time():
    for market, groups in CROSS_MARKET_FEATURES.items():
        cfg = CFGS[market]
        for features in groups.values():
            for feature, (key, _) in features.items():
                assert close_time(cfg, key).split()[1], (market, key)
                assert feature in FEATURE_TEXT and FEATURE_GROUPS[feature].startswith("cross: ")


def test_adr_symbols_match_the_watchlist_adr_field():
    cfg = CFGS["india"]
    mapped = adr_symbols(cfg)
    assert mapped == {t: f"ADR_{m['adr']}" for t, m in cfg["tickers"].items() if m.get("adr")}
    for ticker, key in mapped.items():
        assert cfg["symbols"][key]["yahoo"] == cfg["tickers"][ticker]["adr"]
        assert close_time(cfg, key) == "16:00 America/New_York"


def test_feature_columns_follow_the_switches():
    base = feature_columns("us", 1)
    assert not any(f.startswith("x_") for f in base)
    settings = variants.with_groups({}, "us", ("asia",))
    assert cross_groups(settings, "us") == ("asia",)
    assert feature_columns("us", 1, ("asia",)) == [*base, "x_nikkei_ret", "x_hangseng_ret", "x_kospi_ret"]


def test_default_panel_has_no_cross_columns(panels):
    inputs, _ = panels["us"]
    plain = build_panel(CFGS["us"], inputs, WARMUP)
    assert not [c for c in plain.columns if c.startswith("x_")]


# ---------- backtest variants ----------

def test_parse_groups_and_ablation_variants():
    assert variants.parse_groups("none", "us", ("asia",)) == ()
    assert variants.parse_groups("config", "us", ("asia",)) == ("asia",)
    assert variants.parse_groups("all", "us", ()) == ALL_GROUPS["us"]
    assert variants.parse_groups("fx, europe", "us", ()) == ("fx", "europe")
    with pytest.raises(SystemExit):
        variants.parse_groups("adr", "us", ())
    names = [name for name, _ in variants.ablation_variants("india")]
    assert names[:2] == ["all", "none"] and len(names) == 2 + 2 * len(ALL_GROUPS["india"])
    assert dict(variants.ablation_variants("us"))["all minus asia"] == ("europe", "fx", "rates_commodities")


def paper_block(low: float, positions: int = 30) -> dict:
    vs = {name: {"mean_pct": 0.1, "ci95_pct": [low, 0.3], "dates": 40} for name in ("always_up", "momentum_5d")}
    return {"long": {"positions": positions, "dates": 40, "mean_pct": 0.2, "ci95_pct": [0.05, 0.4]}, "vs": vs}


@pytest.mark.parametrize("skill, auc_low, paper_low, want", [
    (0.01, 0.51, 0.01, True), (-0.01, 0.51, 0.01, False), (0.01, 0.49, 0.01, False), (0.01, 0.51, -0.01, False)])
def test_headline_skill_needs_all_three(skill, auc_low, paper_low, want):
    res = {"n": 100, "first_date": "a", "last_date": "b", "up_share": 0.5, "brier": 0.24, "brier_base_rate": 0.25,
           "brier_skill": skill, "auc": 0.53, "auc95": [auc_low, 0.56],
           "paper": {"thresholds": {"0.55": paper_block(paper_low)}}}
    assert variants.headline(res)["skill"] is want
    assert variants.headline(res)["scores_skill"] is (skill > 0 and auc_low > 0.5)
    sparse = paper_block(paper_low)
    sparse["vs"]["momentum_5d"]["dates"] = 5                                   # too few common dates to compare
    assert variants.headline({**res, "paper": {"thresholds": {"0.55": sparse}}})["skill"] is False
    no_paper = variants.headline({**res, "paper": None})
    assert no_paper["skill"] is False and no_paper["scores_skill"] is (skill > 0 and auc_low > 0.5)


# ---------- long-history cache ----------

class FakeTicker:
    """A yfinance.Ticker stand-in returning one fixed frame per symbol."""

    def __init__(self, frames: dict, symbol: str):
        self.frame = frames.get(symbol)

    def history(self, **_window):
        if self.frame is None:
            raise ValueError("no such symbol")
        return self.frame


class FakeYfinance:
    def __init__(self, frames: dict):
        self.frames = frames

    def Ticker(self, symbol):  # noqa: N802 - the yfinance name
        return FakeTicker(self.frames, symbol)


def yahoo_frame(days, close) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                         "Volume": np.full(len(close), 1000.0)}, index=pd.DatetimeIndex(days))


def test_fetch_market_writes_only_under_work(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    cfg = {**CFGS["india"], "tickers": {"INFY": CFGS["india"]["tickers"]["INFY"]},
           "symbols": {k: CFGS["india"]["symbols"][k] for k in ("NIFTY50", "KOSPI")}}
    days = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]   # 10-02: holiday
    flat = yahoo_frame(days, [10, 11, 12, 13, 14, 15])
    flat.iloc[3, :4] = 12.0
    flat.iloc[3, 4] = 0.0                                                             # flat zero-volume stock bar
    frames = {"INFY.NS": flat, "^NSEI": yahoo_frame(days, [1, 2, 3, 4, 5, 6]),
              "^KS11": yahoo_frame(days, [5, 6, 7, 8, 9, 10])}
    now = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)          # before the 10-07 close has settled
    manifest = history_cache.fetch_market(cfg, date(2026, 8, 1), FakeYfinance(frames), now)
    assert not (tmp_path / "data").exists()
    folder = tmp_path / "work" / "model_history" / "india"
    bars = pd.read_csv(io.BytesIO(gzip.decompress((folder / "bars.csv.gz").read_bytes())))
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    infy = bars[bars["ticker"] == "INFY"]["date"].tolist()
    assert infy == ["2026-09-30", "2026-10-01", "2026-10-06"]    # holiday, flat bar and today's bar dropped
    assert bars[bars["ticker"] == "NIFTY50"]["date"].tolist() == ["2026-09-30", "2026-10-01", "2026-10-05",
                                                                  "2026-10-06"]
    assert bars[bars["ticker"] == "KOSPI"]["date"].tolist() == days[:5]               # other calendar: kept
    assert manifest["symbols"]["INFY"]["dropped_non_session"] == 1
    assert manifest["symbols"]["INFY"]["dropped_flat_zero_volume"] == 1
    assert manifest["rows"] == len(bars) and manifest["fetched_at"] == "2026-10-07T11:00:00Z"
    cached, again = history_cache.load_cache("india")
    assert again == manifest and list(cached["KOSPI"].columns) == ["open", "high", "low", "close", "volume"]


def test_a_failed_fetch_keeps_the_previous_cache(tmp_path, monkeypatch):
    """A Yahoo outage never empties the cache: a symbol whose fetch errs, returns nothing or keeps no bar after
    cleaning keeps its previous rows and manifest entry (kept_from), reported in `failed` (B2's finding)."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    cfg = {**CFGS["india"], "tickers": {"INFY": CFGS["india"]["tickers"]["INFY"]},
           "symbols": {k: CFGS["india"]["symbols"][k] for k in ("NIFTY50", "KOSPI")}}
    days = ["2026-09-30", "2026-10-01", "2026-10-05", "2026-10-06"]
    good = {"INFY.NS": yahoo_frame(days, [10, 11, 12, 13]), "^NSEI": yahoo_frame(days, [1, 2, 3, 4]),
            "^KS11": yahoo_frame(days, [5, 6, 7, 8])}
    first = history_cache.fetch_market(cfg, date(2026, 8, 1), FakeYfinance(good),
                                       datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc))
    before, _ = history_cache.load_cache("india")
    outage = {"^NSEI": yahoo_frame(days, [1, 2, 3, 4]).iloc[:0],                      # no data
              "^KS11": yahoo_frame(["2026-10-08"], [9])}                              # only today's bar: none left
    later = datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)
    second = history_cache.fetch_market(cfg, date(2026, 8, 1), FakeYfinance(outage), later)   # INFY raises
    after, manifest = history_cache.load_cache("india")
    assert manifest == second and second["rows"] == first["rows"] == 4 + 4 + 4
    for key in ("INFY", "NIFTY50", "KOSPI"):
        pd.testing.assert_frame_equal(after[key], before[key])
        assert second["symbols"][key] == {**first["symbols"][key], "kept_from": "2026-10-07T11:00:00Z"}
    assert {f["ticker"]: (f["error"], f["kept_previous_rows"]) for f in second["failed"]} == {
        "INFY": ("no such symbol", 4), "NIFTY50": ("no data", 4), "KOSPI": ("no bar after cleaning", 4)}
    fresh = tmp_path / "other"                                       # no previous cache: nothing to keep
    monkeypatch.setattr(paths, "ROOT", fresh)
    empty = history_cache.fetch_market(cfg, date(2026, 8, 1), FakeYfinance({}), later)
    assert empty["rows"] == 0 and all("kept_previous_rows" not in f for f in empty["failed"])


def test_merged_bars_keep_stored_bars_and_rebase_the_cache():
    days = pd.bdate_range("2020-01-01", periods=60)
    cached = frame(3, days)
    stored = cached.iloc[30:].copy()
    stored[["open", "high", "low", "close"]] *= 2.0                # stored on another basis (e.g. a later split)
    stored.iloc[-1, stored.columns.get_loc("close")] = 999.0       # stored bars win on their dates
    merged, diag = history_cache.merged_bars({"A": stored, "B": stored}, {"A": cached, "C": cached})
    assert merged["A"].index.equals(days) and merged["A"]["close"].iloc[-1] == 999.0
    assert merged["A"]["close"].iloc[0] == pytest.approx(cached["close"].iloc[0] * 2)
    returns = merged["A"]["close"].pct_change()
    assert returns.iloc[30] == pytest.approx(cached["close"].pct_change().iloc[30])  # no jump at the splice
    assert diag["A"]["ratio"] == pytest.approx(2.0) and diag["A"]["cache_rows"] == 30
    assert merged["B"] is stored and "B" not in diag and len(merged["C"]) == 60
