"""Intraday checks (WS5; scripts/intraday_check.py, marketbrief/intraday/): band flags at the edges, the
beta-adjusted residual, no news or bars after check_at, the closed-market and stale-quote skips, the
explainer's gate, idempotent reruns, the learning loop and the cockpit payload. Offline: a stand-in fetcher
serves 5-minute bars, and the stored inputs are fixture rows in a scratch data root."""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.core import paths  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.intraday import explain  # noqa: E402
from marketbrief.intraday.check import run_check  # noqa: E402
from marketbrief.intraday.explain_gate import validate_records  # noqa: E402
from marketbrief.intraday.measures import band_position, flags_for, residual  # noqa: E402
from marketbrief.intraday.outcomes import classify, explanation_outcomes  # noqa: E402
from marketbrief.intraday.payload import intraday_payload  # noqa: E402
from marketbrief.intraday.settings import load_intraday_config  # noqa: E402

MARKET = "wsfive"
SESSION = "2026-10-07"                       # a Wednesday, NYSE open 13:30-20:00 UTC
CHECK = datetime(2026, 10, 7, 16, 30, 7, tzinfo=timezone.utc)
CHECK_ID = "ic-wsfive-2026-10-07T16:30Z"
MARKET_YAML = """
market: wsfive
name: WS5 test market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  SPY: {role: benchmark, name: Benchmark}
  XLK: {role: sector_etf, name: Tech, sectors: [Tech]}
  ES: {role: cue, name: Futures}
sectors:
  Tech: [AAPL, MSFT]
  Banks: [JPM, BAC]
tickers:
  AAPL: {name: Apple}
  MSFT: {name: Microsoft}
  JPM: {name: JPMorgan}
  BAC: {name: Bank of America}
index_cue: {symbol: ES, beta: 1.0}
news:
  outlets: []
"""
# (open, last) of each symbol's session; AAPL jumps after the check (bars the check must not see)
PATHS = {"AAPL": (101.0, 106.0), "MSFT": (100.0, 100.5), "SPY": (100.0, 101.0), "XLK": (100.0, 102.0),
         "JPM": (100.0, 100.2), "BAC": (100.0, 99.0)}
AFTER_CHECK = {"AAPL": 90.0}


class FakeFetcher:
    """Serves 5-minute bars of the previous and the test session; JPM's newest bar is at 15:00 (stale)."""

    def __init__(self, stale=("JPM",), cue_ts="2026-10-07T16:20:00+00:00"):
        self.stale, self.cue_ts, self.calls = set(stale), cue_ts, []

    def bars(self, symbol: str) -> pd.DataFrame:
        self.calls.append(symbol)
        if symbol not in PATHS:
            raise ValueError("no data")
        start = pd.Timestamp("2026-10-07 13:30", tz="UTC")
        stamps = list(pd.date_range("2026-10-06 13:30", periods=78, freq="5min", tz="UTC"))
        stamps += list(pd.date_range(start, periods=78, freq="5min", tz="UTC"))
        if symbol in self.stale:
            stamps = [s for s in stamps if s <= pd.Timestamp("2026-10-07 15:00", tz="UTC")]
        open_price, last = PATHS[symbol]
        rows = []
        for stamp in stamps:
            if stamp < start:
                rows.append((99.0, 99.0))
            elif stamp == start:
                rows.append((open_price, open_price))
            elif stamp >= pd.Timestamp("2026-10-07 16:30", tz="UTC") and symbol in AFTER_CHECK:
                rows.append((AFTER_CHECK[symbol], AFTER_CHECK[symbol]))
            else:
                rows.append((last, last))
        return pd.DataFrame(rows, index=pd.DatetimeIndex(stamps), columns=["Open", "Close"])

    def cue(self, _symbol: str, _now: str) -> dict:
        return {"ts": self.cue_ts, "price": 5000.0, "prev_close": 4990.0, "change_pct": 0.002004}


def jl(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def bars_csv(root: Path, day: str, closes: dict[str, float], collected_at: str = "2026-10-07T00:00:00+00:00",
             name: str | None = None):
    path = root / "data" / MARKET / "prices" / day[:4] / day[5:7] / f"{name or day}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,ticker,open,high,low,close,adj_close,volume,collected_at"]
    lines += [f"{day},{t},{c},{c},{c},{c},{c},1000,{collected_at}" for t, c in closes.items()]
    path.write_text("\n".join(lines) + "\n")


def rng(ticker: str, horizon: int, bands: tuple, made_at: str = "2026-10-07T04:45:00+00:00") -> dict:
    lo80, lo50, hi50, hi80 = bands
    return {"id": f"2026-10-06-{ticker}-{horizon}d", "made_at": made_at, "as_of_date": "2026-10-06",
            "session_date": SESSION, "target_date": SESSION, "ticker": ticker, "horizon_days": horizon,
            "base_close": 100.0, "center": 0.0, "sigma_h": 0.01 if horizon == 1 else 0.03, "lo50": lo50,
            "hi50": hi50, "lo80": lo80, "hi80": hi80, "notes": ["cue +0.40% x0.5"], "inputs": []}


@pytest.fixture
def market(tmp_path, monkeypatch):
    root, config = tmp_path / "repo", tmp_path / "config"
    (config / "markets").mkdir(parents=True)
    (config / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
    shutil.copy(REPO / "config" / "intraday.yaml", config / "intraday.yaml")
    shutil.copy(REPO / "config" / "events.yaml", config / "events.yaml")
    shutil.copy(REPO / "config" / "settings.yaml", config / "settings.yaml")   # call_scoring switch: 2026-10-08
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "CONFIG", config)
    monkeypatch.delenv("MB_NOW", raising=False)
    bars_csv(root, "2026-10-05", dict.fromkeys(PATHS, 99.0))
    bars_csv(root, "2026-10-06", {key: 100.0 for key in PATHS if key != "MSFT"})
    # stored after the check time: MSFT's 10-06 bar and a corrected SPY bar must not be used at 16:30
    bars_csv(root, "2026-10-06", {"MSFT": 100.0, "SPY": 50.0}, collected_at="2026-10-07T17:00:00+00:00",
             name="2026-10-06-late")
    jl(root, "ranges", "2026-10-07", [
        rng("AAPL", 1, (96.0, 98.0, 102.0, 105.0)), rng("AAPL", 5, (90.0, 95.0, 105.0, 110.0)),
        rng("MSFT", 1, (97.0, 99.0, 100.2, 100.5)), rng("BAC", 1, (97.0, 99.0, 101.0, 103.0)),
        # published after the check: never used
        {**rng("JPM", 1, (1.0, 2.0, 3.0, 4.0), made_at="2026-10-07T17:00:00+00:00")},
    ])
    jl(root, "predictions", "2026-10-07", [
        {"id": "2026-10-06-AAPL-1d", "made_at": "2026-10-07T05:00:00+00:00", "as_of_date": "2026-10-06",
         "ticker": "AAPL", "horizon_days": 1, "direction": "down", "confidence": 0.6, "evidence_ids": ["n-in"]},
    ])
    jl(root, "model_scores", "2026-10-07", [
        {"id": "2026-10-06-BAC-1d", "as_of_date": "2026-10-06", "ticker": "BAC", "horizon_days": 1,
         "label_convention": "open_to_close", "prob_up": 0.60, "computed_at": "2026-10-07T04:40:00+00:00"},
        # entered at the open of 10-06 (D), sold at the close of 10-07 (D+1): still open on 10-07
        {"id": "2026-10-05-AAPL-1d", "as_of_date": "2026-10-05", "ticker": "AAPL", "horizon_days": 1,
         "label_convention": "open_to_close", "prob_up": 0.45, "computed_at": "2026-10-06T04:40:00+00:00"},
        # ended at the close of 10-06: not open on 10-07
        {"id": "2026-10-02-AAPL-1d", "as_of_date": "2026-10-02", "ticker": "AAPL", "horizon_days": 1,
         "label_convention": "open_to_close", "prob_up": 0.45, "computed_at": "2026-10-05T04:40:00+00:00"},
    ])
    jl(root, "features", "2026-10-06", [
        {"id": "2026-10-06-AAPL", "as_of_date": "2026-10-06", "ticker": "AAPL",
         "computed_at": "2026-10-07T04:30:00+00:00", "beta_1y": 1.2, "ewma_vol": 0.2},
    ])
    news = [("n-before", "2026-10-07T13:00:00+00:00"), ("n-in", "2026-10-07T15:00:00+00:00"),
            ("n-after", "2026-10-07T16:45:00+00:00")]
    jl(root, "news", "2026-10-07", [
        {"id": ident, "title": f"Apple headline {ident} up 4.5%", "url": "u", "source": "Wire",
         "published_at": seen, "first_seen_at": seen, "feed": "f", "category": "company", "tickers": ["AAPL"],
         "primary_tickers": ["AAPL"], "mentioned_tickers": [], "tag_confidence": "high", "tag_version": 99}
        for ident, seen in news
    ])
    verified = {"cluster_id": "AAPL-c1", "level": "cluster", "ticker": "AAPL", "claim_id": None,
                "status_ids": ["n-in"]}
    jl(root, "news_verified", "2026-10-07", [
        {**verified, "id": "v1", "as_of": "2026-10-07T15:30:00+00:00", "id_statuses": ["single_source"]},
        {**verified, "id": "v2", "as_of": "2026-10-07T17:00:00+00:00", "id_statuses": ["confirmed_primary"]},
    ])
    jl(root, "events", "2026-10-05", [
        {"id": "AAPL-earnings-2026-10-07", "date": SESSION, "type": "earnings", "ticker": "AAPL",
         "name": "Apple earnings", "source": "yahoo", "first_seen_at": "2026-10-05T00:00:00+00:00"},
    ])
    return root, load_market(MARKET), load_intraday_config()


def stored(root: Path, kind: str) -> list[dict]:
    files = sorted((root / "data" / MARKET / kind).glob("**/*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]


def check_rows(root: Path) -> dict[str, dict]:
    return {row["ticker"]: row for row in stored(root, "intraday_checks")}


def test_band_position_at_the_edges():
    band = {"lo80": 95.0, "lo50": 98.0, "hi50": 102.0, "hi80": 105.0}
    assert band_position(105.0, band) == "above50"        # on the 80% edge: still inside the 80% band
    assert band_position(105.0001, band) == "above80"
    assert band_position(95.0, band) == "below50"
    assert band_position(94.9999, band) == "below80"
    assert band_position(102.0, band) == "inside50"       # on the 50% edge: inside
    assert band_position(98.0, band) == "inside50"
    assert band_position(100.0, None) is None
    settings = load_intraday_config()
    assert flags_for({"band_1d": "above50"}, [], settings) == ["outside_1d_50"]
    assert flags_for({"band_1d": "below80", "band_5d": "above80"}, [], settings) == [
        "outside_1d_80", "outside_1d_50", "outside_5d_80"]


def test_beta_adjusted_residual(market):
    assert residual(0.03, 1.2, 0.01) == pytest.approx(0.018)
    assert residual(0.03, None, 0.01) is None
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    aapl = check_rows(root)["AAPL"]
    assert aapl["ret_since_open"] == pytest.approx(106 / 101 - 1, abs=1e-6)
    assert aapl["bench_ret"] == pytest.approx(0.01)
    assert aapl["beta"] == 1.2
    assert aapl["residual"] == pytest.approx(106 / 101 - 1 - 1.2 * 0.01, abs=1e-6)
    assert aapl["sector_ret"] == pytest.approx(0.02) and aapl["sector_source"] == "sector_etf"
    bac = check_rows(root)["BAC"]   # no features row: default beta, noted; JPM is stale, so no peer move
    assert bac["beta"] == 1.0 and "beta_default" in bac["notes"]
    assert bac["sector_ret"] is None


def test_flags_calls_and_no_bar_after_check(market):
    root, cfg, settings = market
    summary = run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    assert summary["status"] == "ok" and summary["check_id"] == CHECK_ID
    rows = check_rows(root)
    aapl = rows["AAPL"]
    assert aapl["last_price"] == 106.0                       # the 90.0 bars from 16:30 on are not seen
    assert aapl["last_time"] == "2026-10-07T16:25:00+00:00"
    assert aapl["band_1d"] == "above80" and aapl["flagged"]
    assert {"outside_1d_80", "large_move", "against_call"} <= set(aapl["flags"])
    call = next(c for c in aapl["calls"] if c["source"] == "prediction")   # made before 10-08: close_to_close
    assert call["basis"] == "close_to_close" and call["entry_kind"] == "close" and call["entry_price"] == 100.0
    assert call["direction"] == "down" and call["against"] and call["last_session"] == SESSION
    model = {c["id"]: c for c in aapl["calls"] if c["source"] == "model"}
    assert set(model) == {"2026-10-05-AAPL-1d"}                # D+1 of a 1-day call is still open
    held = model["2026-10-05-AAPL-1d"]
    assert held["entry_date"] == "2026-10-06" and held["last_session"] == SESSION and held["sessions_held"] == 2
    assert held["entry_price"] == 100.0 and held["direction"] == "down" and held["against"]
    msft = rows["MSFT"]                                      # last 100.5 == hi80 100.5: on the edge, inside
    assert msft["band_1d"] == "above50" and "outside_1d_80" not in msft["flags"]
    assert not msft["flagged"]
    bac = rows["BAC"]                                        # model side up, price -1% (z < -1): info flag only
    assert bac["band_1d"] == "inside50" and "against_model" in bac["flags"] and not bac["flagged"]
    assert rows["JPM"]["range_id_1d"] is None                # its range was published after the check


def test_call_windows_follow_the_scoring_basis():
    from marketbrief.intraday.inputs import call_window

    cfg = {"calendar": "XNYS", "timezone": "America/New_York"}
    as_of = datetime(2026, 10, 6).date()
    days = [d.isoformat() for d in call_window(cfg, as_of, 1, "open_to_close")]
    assert days == ["2026-10-07", "2026-10-08"]              # buy the open of D, sell the close of D+1
    # N+5 (decision 37, B10): sell at the close of the 5th session after D = D+5 (D+4 before B10)
    assert [d.isoformat() for d in call_window(cfg, as_of, 5, "open_to_close")] == ["2026-10-07", "2026-10-14"]
    # an old 5-day open-to-close call (label legacy_5d_d4, issue #94) keeps its D+4 window
    assert [d.isoformat() for d in call_window(cfg, as_of, 5, "open_to_close", "legacy_5d_d4")] == [
        "2026-10-07", "2026-10-13"]
    assert [d.isoformat() for d in call_window(cfg, as_of, 1, "close_to_close")] == ["2026-10-07", "2026-10-07"]


def test_stored_bars_as_of_the_check(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    rows = check_rows(root)
    assert rows["AAPL"]["prev_close"] == 100.0 and rows["AAPL"]["gap"] == pytest.approx(0.01)
    assert rows["MSFT"]["prev_close"] == 99.0                 # its 10-06 bar was stored after the check
    assert "prev_close_from_2026-10-05" in rows["MSFT"]["notes"]
    assert rows["AAPL"]["bench_ret"] == pytest.approx(0.01)   # intraday bars; the late SPY 50.0 bar is unused


def test_no_news_after_check_at(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    aapl = check_rows(root)["AAPL"]
    news = [c for c in aapl["candidates"] if c["kind"] == "news"]
    assert [c["id"] for c in news] == ["n-in"]               # n-before: before the open; n-after: after check
    assert news[0]["status"] == "single_source"              # the confirmed_primary row came at 17:00
    assert {"bench:SPY", "sector:XLK", "cue:ES", "AAPL-earnings-2026-10-07"} <= set(aapl["candidate_ids"])
    cue = next(c for c in aapl["candidates"] if c["kind"] == "cue")
    assert cue["range_notes"] == ["cue +0.40% x0.5"]


def test_cue_after_check_is_dropped(market):
    root, cfg, settings = market
    summary = run_check(cfg, settings, connect(MARKET), FakeFetcher(cue_ts="2026-10-07T16:40:00+00:00"), CHECK)
    assert summary["cue"] is None
    assert "cue:ES" not in check_rows(root)["AAPL"]["candidate_ids"]


@pytest.mark.parametrize("now", [datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),     # before the open
                                 datetime(2026, 10, 7, 21, 0, tzinfo=timezone.utc),     # after the close
                                 datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)])   # a Saturday
def test_closed_market_skips_cleanly(market, now):
    root, cfg, settings = market
    fetcher = FakeFetcher()
    summary = run_check(cfg, settings, connect(MARKET), fetcher, now)
    assert summary["status"] == "market_closed" and summary["written"] == 0
    assert fetcher.calls == []                                # nothing fetched
    assert stored(root, "intraday_checks") == []
    runs = stored(root, "intraday_runs")
    assert len(runs) == 1 and runs[0]["status"] == "market_closed"


def test_stale_quote(market):
    root, cfg, settings = market
    summary = run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    jpm = check_rows(root)["JPM"]
    assert jpm["quality"] == "stale_quote"
    assert jpm["flags"] == [] and not jpm["flagged"] and jpm.get("move_z") is None
    assert summary["stale"] == ["JPM"] and summary["status"] == "ok"
    everything_stale = FakeFetcher(stale=tuple(PATHS))
    later = run_check(cfg, settings, connect(MARKET), everything_stale, CHECK + timedelta(minutes=30))
    assert later["status"] == "stale" and later["flagged"] == 0


def test_rerun_of_the_same_check_time_is_idempotent(market):
    root, cfg, settings = market
    first = run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    again = run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK + timedelta(seconds=40))
    assert first["written"] == 4 and again["status"] == "duplicate" and again["written"] == 0
    assert len(stored(root, "intraday_checks")) == 4 and len(stored(root, "intraday_runs")) == 1
    out = root / "elsewhere"                                  # --out: same check id again under another root
    assert run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK, out)["status"] == "duplicate"


def test_out_folder_leaves_data_untouched(market, tmp_path):
    root, cfg, settings = market
    out = tmp_path / "live"
    summary = run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK, out)
    assert summary["written"] == 4
    assert stored(root, "intraday_checks") == [] and stored(root, "intraday_runs") == []
    assert len(list((out / "intraday_checks").glob("**/*.jsonl"))) == 1


SETTINGS = {"explainer": {"max_words": 60, "prompt_version": "deviation-v2"}}


def good_note(row_id: str) -> dict:
    return {"check_row_id": row_id, "attribution": "news", "cited_ids": ["n-in", "bench:SPY"],
            "text": "AAPL is 4.95% above its open and above the 80% band (105); the benchmark rose 1%. "
                    "Headline n-in (single source) cites up 4.5%.",
            "prompt_version": "deviation-v2"}


def test_gate_rejects_invented_ids_wrong_numbers_and_predictions(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    con = connect(MARKET)
    rows, row_id = explain.flagged_rows(con), f"{CHECK_ID}-AAPL"
    good, bad = validate_records([good_note(row_id)], rows, set(), SETTINGS)
    assert bad == [] and len(good) == 1
    cue_note = {**good_note(row_id), "attribution": "cue", "cited_ids": ["cue:ES", "AAPL-earnings-2026-10-07"],
                "text": "Futures (cue:ES) are +0.2% and the range notes cite cue +0.40% x0.5; the earnings event "
                        "AAPL-earnings-2026-10-07 falls today. Move z 7.3 vs the 2% sector gain."}
    assert validate_records([cue_note], rows, set(), SETTINGS)[1] == []
    cases = {
        "invented id": {**good_note(row_id), "cited_ids": ["n-in", "n-made-up"]},
        "id after the check": {**good_note(row_id), "cited_ids": ["n-after"]},
        "wrong number": {**good_note(row_id), "text": "AAPL is 7.3% above its open."},
        "wrong sign": {**good_note(row_id), "text": "AAPL moved -4.95% since its open."},
        "prediction": {**good_note(row_id), "text": "AAPL will keep rising after n-in; buy the dip."},
        "bad enum": {**good_note(row_id), "attribution": "vibes"},
        "attribution not cited": {**good_note(row_id), "attribution": "event", "cited_ids": ["n-in"]},
        "unflagged row": {**good_note(f"{CHECK_ID}-BAC")},
        "too long": {**good_note(row_id), "text": "word " * 61},
        "other prompt version": {**good_note(row_id), "prompt_version": "deviation-v0"},
    }
    for name, rec in cases.items():
        good, bad = validate_records([rec], rows, set(), SETTINGS)
        assert good == [] and bad, name
    _, bad = validate_records([good_note(row_id), good_note(row_id)], rows, set(), SETTINGS)
    assert any("twice" in error for error in bad[0]["errors"])


def test_add_stores_once_and_learning_loop_pairs_the_close(market, tmp_path, monkeypatch):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    con = connect(MARKET)
    summary = explain.prepare(con, tmp_path / "flags.jsonl", None)
    assert summary["check_id"] == CHECK_ID and summary["n"] == 1
    prepared = json.loads((tmp_path / "flags.jsonl").read_text().splitlines()[0])
    assert prepared["id"] == f"{CHECK_ID}-AAPL" and "n-in" in prepared["candidate_ids"]
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:40:00+00:00")
    good, bad = validate_records([good_note(prepared["id"])], explain.flagged_rows(con), set(), SETTINGS)
    explain.add(MARKET, good, explain.flagged_rows(con))
    monkeypatch.delenv("MB_NOW")
    notes = stored(root, "intraday_explanations")
    assert len(notes) == 1 and notes[0]["id"] == f"ix-{CHECK_ID}-AAPL" and notes[0]["created_at"].startswith(
        "2026-10-07T16:40")
    con = connect(MARKET)
    rows, done = explain.flagged_rows(con), explain.explained_ids(con)
    _, bad = validate_records([good_note(prepared["id"])], rows, done, SETTINGS)
    assert any("already has" in error for error in bad[0]["errors"])
    assert explanation_outcomes(con, settings)[0]["outcome"] == "pending"   # no close yet
    bars_csv(root, SESSION, {"AAPL": 99.0}, collected_at="2026-10-07T21:00:00+00:00")
    con = connect(MARKET)
    outcome = explanation_outcomes(con, settings)[0]
    assert outcome["outcome"] == "reversed" and outcome["closed_outside_1d_80"] is False
    as_of = datetime(2026, 10, 7, 20, 30, tzinfo=timezone.utc)   # before the close was collected
    assert explanation_outcomes(con, settings, as_of=as_of)[0]["outcome"] == "pending"
    payload = intraday_payload(con, MARKET, settings, as_of=datetime(2026, 10, 7, 16, 35, tzinfo=timezone.utc))
    assert payload["session_date"] == SESSION and len(payload["tickers"]) == 4
    assert payload["deviations"][0]["explanation"] is None     # written at 16:40, after this as_of
    later = intraday_payload(con, MARKET, settings, as_of=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert later["deviations"][0]["attribution"] == "news" and later["history"]["outcomes"] == {"reversed": 1}
    json.dumps(later)                                           # JSON-ready


def test_classify():
    assert classify(0.02, 0.015, 0.5) == "held"
    assert classify(0.02, 0.005, 0.5) == "faded"
    assert classify(0.02, -0.001, 0.5) == "reversed"
    assert classify(-0.02, -0.03, 0.5) == "held"
    assert classify(0.02, None, 0.5) == "pending"


def test_cli_run_is_mb_now_aware_and_rows_pass_the_schema_gate(market, monkeypatch, tmp_path, capsys):
    from marketbrief.intraday import cli
    from marketbrief.pipeline.validate.row_checks import check_rows as schema_problems

    root, _cfg, _settings = market
    monkeypatch.setattr(cli, "YahooIntraday", FakeFetcher)
    monkeypatch.setenv("MB_NOW", CHECK.isoformat())
    monkeypatch.setattr(sys, "argv", ["intraday_check.py", "--market", MARKET])
    assert cli.main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["check_id"] == CHECK_ID and summary["flagged_tickers"] == {
        "AAPL": next(row["flags"] for row in stored(root, "intraday_checks") if row["ticker"] == "AAPL")}
    now = pd.Timestamp(CHECK) + pd.Timedelta(minutes=5)
    for kind in ("intraday_checks", "intraday_runs"):
        assert schema_problems(kind, stored(root, kind), False, now, timedelta(minutes=5)) == []
    flags = tmp_path / "flags.jsonl"
    monkeypatch.setattr(sys, "argv", ["intraday_check.py", "--market", MARKET, "prepare", "--out", str(flags)])
    assert cli.main() == 0
    notes = tmp_path / "notes.jsonl"
    bad = {**good_note(f"{CHECK_ID}-AAPL"), "cited_ids": ["n-invented"]}
    notes.write_text(json.dumps(bad) + "\n")
    for command in ("validate", "add"):
        monkeypatch.setattr(sys, "argv", ["intraday_check.py", "--market", MARKET, command, str(notes)])
        assert cli.main() == 1
    assert stored(root, "intraday_explanations") == []
    notes.write_text(json.dumps(good_note(f"{CHECK_ID}-AAPL")) + "\n")
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:41:00+00:00")
    assert cli.main() == 0
    stored_notes = stored(root, "intraday_explanations")
    assert len(stored_notes) == 1
    assert schema_problems("intraday_explanations", stored_notes, False, now + pd.Timedelta(hours=1),
                           timedelta(minutes=5)) == []


def test_daily_sigma_fallbacks():
    from marketbrief.intraday.inputs import daily_sigma

    assert daily_sigma({1: {"sigma_h": 0.01}, 5: {"sigma_h": 0.05}}, None) == (0.01, None)
    sigma, note = daily_sigma({5: {"sigma_h": 0.05}}, {"ewma_vol": 0.2})
    assert sigma == pytest.approx(0.05 / 5 ** 0.5) and note == "sigma_from_5d_range"
    assert daily_sigma({}, {"ewma_vol": 0.2})[1] == "sigma_from_ewma_vol"
    assert daily_sigma({}, None) == (None, "no_sigma")


def test_weekly_review_section_and_reflector_input(market, monkeypatch):
    from datetime import date

    from marketbrief.intraday.outcomes import notes_in_window
    from marketbrief.pipeline.lessons.facts import intraday_notes
    from marketbrief.pipeline.review.intraday_review import intraday_outcomes, markdown_lines

    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    con = connect(MARKET)
    monkeypatch.setenv("MB_NOW", "2026-10-07T16:40:00+00:00")
    good, _ = validate_records([good_note(f"{CHECK_ID}-AAPL")], explain.flagged_rows(con), set(), SETTINGS)
    explain.add(MARKET, good, explain.flagged_rows(con))
    bars_csv(root, SESSION, {"AAPL": 106.5}, collected_at="2026-10-07T21:00:00+00:00")   # held by the close
    con = connect(MARKET)
    week = (date(2026, 10, 5), date(2026, 10, 11))
    assert intraday_outcomes(con, *week)["week"]["outcomes"] == {"pending": 1}   # the close is not stored at 16:40
    monkeypatch.setenv("MB_NOW", "2026-10-12T06:00:00+00:00")
    data = intraday_outcomes(con, *week)
    assert data["week"]["outcomes"] == {"held": 1} and data["all"]["by_attribution"] == {"news": {"held": 1}}
    assert intraday_outcomes(con, date(2026, 9, 28), date(2026, 10, 4))["week"]["n"] == 0   # an earlier week
    lines = markdown_lines(data, {"week": "week 2026-W41", "all": "since start"})
    assert "| week 2026-W41 | 1 | 1 | 0 | 0 | 0 |" in lines and "| since start · news | 1 | 1 | 0 | 0 | 0 |" in lines
    empty = intraday_outcomes(con, date(2026, 9, 28), date(2026, 10, 4))
    assert "No explained intraday deviation" in "\n".join(markdown_lines(empty, {"week": "w", "all": "a"}))
    notes = notes_in_window(con, settings, "AAPL", (date(2026, 10, 6), date(2026, 10, 7)))
    assert [(n["explanation_id"], n["outcome"], n["attribution"]) for n in notes] == [
        (f"ix-{CHECK_ID}-AAPL", "held", "news")]
    assert notes_in_window(con, settings, "AAPL", (date(2026, 10, 7), date(2026, 10, 9))) == []  # after the session
    assert notes_in_window(con, settings, "MSFT", (date(2026, 10, 6), date(2026, 10, 7))) == []
    fact = {"ticker": "AAPL", "base_date": "2026-10-06", "target_date": "2026-10-07",
            "settled_at": "2026-10-08T12:00:00+00:00"}
    assert [n["outcome"] for n in intraday_notes(con, fact)] == ["held"]
    early = {**fact, "settled_at": "2026-10-07T16:35:00+00:00"}   # before the note was written (16:40)
    assert intraday_notes(con, early) == [] and intraday_notes(con, {"ticker": "AAPL"}) == []
