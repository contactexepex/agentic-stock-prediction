"""B9: intraday checks of every open paper trade (docs/ws/b9.md): price vs entry, target and the trade's own range,
band edges, a target reached intraday, every horizon N+1..N+5, no look-ahead, a stale quote, the market closed, an
idempotent rerun, splits, the alerts feed and the explainer's extended input. Offline: W1's example predictions,
open trades and head-to-head picks (design/catalogue/) are the stored open trades, stored US bars of
2026-09-29..10-06 the history, and a stand-in fetcher serves 2026-10-07's 5-minute bars."""
from __future__ import annotations

import csv
import json
import math
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
from marketbrief.intraday.measures import flags_for, is_trigger  # noqa: E402
from marketbrief.intraday.payload import intraday_payload  # noqa: E402
from marketbrief.intraday.settings import load_intraday_config  # noqa: E402
from marketbrief.intraday.trade_rows import skipped_for_price, trade_flags  # noqa: E402

MARKET = "bnine"
SESSION = "2026-10-07"                                           # Wednesday; NYSE 13:30-20:00 UTC
CHECK = datetime(2026, 10, 7, 16, 27, 31, tzinfo=timezone.utc)  # 12:27 New York
CHECK_ID = "ic-bnine-2026-10-07T16:27Z"
ELAPSED = 175 / 390                                              # the 16:20 bar ends 16:25: 175 of 390 minutes
SIGMA = {"NVDA": 0.019129, "AAPL": 0.013523}                     # W1's stored 1d sigmas (make_examples.SIGMA_1D)
CATALOGUE = REPO / "design" / "catalogue"
MARKET_YAML = """
market: bnine
name: B9 test market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  SPY: {role: benchmark, name: Benchmark}
  XLK: {role: sector_etf, name: Tech, sectors: [Tech]}
  ES: {role: cue, name: Futures}
sectors:
  Tech: [NVDA, AAPL]
  Banks: [JPM]
tickers:
  NVDA: {name: Nvidia}
  AAPL: {name: Apple}
  JPM: {name: JPMorgan}
index_cue: {symbol: ES, beta: 1.0}
news:
  outlets: []
"""
# (open, last close, session high before the check) of 2026-10-07; JPM is stale (bars end at 15:00)
TODAY = {"NVDA": (239.0, 241.1, 251.0), "AAPL": (340.0, 334.95, 340.5), "SPY": (779.0, 781.0, 781.5),
         "XLK": (202.0, 203.0, 203.2), "JPM": (331.0, 330.0, 331.5)}


class FakeFetcher:
    """5-minute bars of 10-06 and 10-07 with Open/High/Low/Close. From 16:25 (bars ending after the 16:27 check)
    NVDA spikes to 300 when `spike` is set: a check at 16:27 must not see it."""

    def __init__(self, stale=("JPM",), spike=True, scale=None):
        self.stale, self.spike, self.scale = set(stale), spike, scale or {}

    def bars(self, symbol: str) -> pd.DataFrame:
        if symbol not in TODAY:
            raise ValueError("no data")
        start = pd.Timestamp("2026-10-07 13:30", tz="UTC")
        stamps = list(pd.date_range("2026-10-06 13:30", periods=78, freq="5min", tz="UTC"))
        stamps += list(pd.date_range(start, periods=78, freq="5min", tz="UTC"))
        if symbol in self.stale:
            stamps = [s for s in stamps if s <= pd.Timestamp("2026-10-07 15:00", tz="UTC")]
        open_price, last, high = TODAY[symbol]
        rows = []
        for stamp in stamps:
            if stamp < start:
                rows.append((200.0, 200.0, 200.0, 200.0))
            elif stamp == start:
                rows.append((open_price, open_price, open_price, open_price))
            elif stamp == pd.Timestamp("2026-10-07 14:00", tz="UTC"):
                rows.append((last, high, min(open_price, last), last))
            elif stamp >= pd.Timestamp("2026-10-07 16:25", tz="UTC") and symbol == "NVDA" and self.spike:
                rows.append((300.0, 300.0, 300.0, 300.0))
            else:
                rows.append((last, last, last, last))
        factor = self.scale.get(symbol, 1.0)
        return pd.DataFrame([[v * factor for v in row] for row in rows], index=pd.DatetimeIndex(stamps),
                            columns=["Open", "High", "Low", "Close"])

    def cue(self, _symbol: str, _now: str) -> dict:
        return {"ts": "2026-10-07T16:20:00+00:00", "price": 5000.0, "prev_close": 4990.0, "change_pct": 0.002004}


def jl(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def copy_bars(root: Path, symbols=("NVDA", "AAPL", "JPM", "SPY", "XLK")) -> None:
    """The stored US bars of 2026-09-29..10-06 (repo data), collected at a fixed time before the check."""
    for path in sorted((REPO / "data" / "us" / "prices" / "2026").glob("*/2026-*.csv")):
        if not "2026-09-29" <= path.stem[:10] <= "2026-10-06":
            continue
        rows = [row for row in csv.DictReader(path.open()) if row["ticker"] in symbols]
        out = root / "data" / MARKET / "prices" / path.parent.parent.name / path.parent.name / path.name
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = ["date,ticker,open,high,low,close,adj_close,volume,collected_at"]
        lines += [f"{r['date']},{r['ticker']},{r['open']},{r['high']},{r['low']},{r['close']},{r['adj_close']},"
                  f"{r['volume']},2026-10-07T04:31:00+00:00" for r in rows]
        out.write_text("\n".join(lines) + "\n")


def late_bar(root: Path) -> None:
    """A corrected NVDA 10-06 bar collected after the check (high 270): never used at 16:27."""
    out = root / "data" / MARKET / "prices" / "2026" / "10" / "2026-10-06-late.csv"
    out.write_text("date,ticker,open,high,low,close,adj_close,volume,collected_at\n"
                   "2026-10-06,NVDA,242.1,270.0,238.93,239.24,239.24,1,2026-10-07T17:00:00+00:00\n")


def catalogue(name: str) -> list[dict]:
    return json.loads((CATALOGUE / f"{name}.json").read_text())["records"]


def past_prediction(trade: dict, **extra) -> dict:
    """A strategy_predictions row behind one of W1's example open trades (D = 2026-09-30, as of 09-29)."""
    pid = trade["prediction_id"]
    return {"id": pid, "strategy_id": trade["strategy_id"], "family": trade["family"], "market": MARKET,
            "ticker": trade["ticker"], "made_at": "2026-09-30T11:45:00Z", "as_of_date": "2026-09-29",
            "session_date": trade["entry_date"], "exit_date": trade["exit_date"], "horizon_days": trade["horizon_days"],
            "direction": "up", "prob_up": 0.58, "qualifies": True, "target_price": trade["target_price"],
            "lo50": trade["lo50"], "hi50": trade["hi50"], "lo80": trade["lo80"], "hi80": trade["hi80"],
            "amount": trade["amount"], "currency": "USD", **extra}


def custom(pid: str, dates: tuple, target: float, band: tuple, made_at: str = "2026-10-07T11:45:00Z") -> dict:
    """A strategy prediction <strategy>:<as_of>-<ticker>-<k>d; dates = (as_of, D, exit)."""
    lo80, lo50, hi50, hi80 = band
    (as_of, entry, exit_), ticker, horizon = dates, pid.split("-")[-2], int(pid.split("-")[-1][:-1])
    return {"id": pid, "strategy_id": pid.split(":")[0], "family": "rule", "market": MARKET, "ticker": ticker,
            "made_at": made_at, "as_of_date": as_of, "session_date": entry, "exit_date": exit_,
            "horizon_days": horizon, "direction": "up", "prob_up": 0.6, "qualifies": True, "target_price": target,
            "lo50": lo50, "hi50": hi50, "lo80": lo80, "hi80": hi80, "amount": 1000.0, "currency": "USD"}


CUSTOM = [
    # entered 10-05 (D), exit 10-08 (N+3): today is session 3; target 250 reached only by today's 251 high
    custom("rule.b9_reached.v1:2026-10-02-NVDA-3d", ("2026-10-02", "2026-10-05", "2026-10-08"), 250.0,
           (225.0, 232.0, 248.0, 255.0), made_at="2026-10-05T11:45:00Z"),
    # target 260: not reached by the check (the 300 spike and the late 270 bar come after it): far from target
    custom("rule.b9_far.v1:2026-10-02-NVDA-3d", ("2026-10-02", "2026-10-05", "2026-10-08"), 260.0,
           (230.0, 235.0, 255.0, 265.0), made_at="2026-10-05T11:45:00Z"),
    # band edges: the last price 241.1 exactly on hi80 is inside the 80% range; 241.09 is outside
    custom("rule.b9_edge_in.v1:2026-10-06-NVDA-2d", ("2026-10-06", SESSION, "2026-10-09"), 239.5,
           (230.0, 235.0, 240.0, 241.1)),
    custom("rule.b9_edge_out.v1:2026-10-06-NVDA-2d", ("2026-10-06", SESSION, "2026-10-09"), 239.5,
           (230.0, 235.0, 240.0, 241.09)),
    # AAPL fell from its 340 open to 334.95: against the up prediction
    custom("base.b9_against.v1:2026-10-06-AAPL-1d", ("2026-10-06", SESSION, "2026-10-08"), 333.63,
           (326.0, 330.0, 337.0, 341.0)),
    # made after D's open (13:30): refused, not locked (F1.8)
    custom("rule.b9_unlocked.v1:2026-10-06-NVDA-1d", ("2026-10-06", SESSION, "2026-10-08"), 239.5,
           (230.0, 235.0, 244.0, 248.0), made_at="2026-10-07T13:45:00Z"),
    # stored after the check: never seen
    custom("rule.b9_late.v1:2026-10-06-NVDA-1d", ("2026-10-06", SESSION, "2026-10-08"), 239.5,
           (230.0, 235.0, 244.0, 248.0), made_at="2026-10-07T16:40:00Z"),
]


def ranges_for(ticker: str, horizon: int, band: tuple) -> dict:
    lo80, lo50, hi50, hi80 = band
    return {"id": f"2026-10-06-{ticker}-{horizon}d", "made_at": "2026-10-07T11:40:00+00:00",
            "as_of_date": "2026-10-06", "session_date": SESSION, "target_date": SESSION, "ticker": ticker,
            "horizon_days": horizon, "base_close": 239.24, "center": 0.0, "sigma_h": SIGMA[ticker] * math.sqrt(horizon),
            "lo50": lo50, "hi50": hi50, "lo80": lo80, "hi80": hi80, "notes": [], "inputs": []}


@pytest.fixture
def market(tmp_path, monkeypatch):
    root, config = tmp_path / "repo", tmp_path / "config"
    (config / "markets").mkdir(parents=True)
    (config / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
    for name in ("intraday.yaml", "events.yaml", "settings.yaml", "strategies.yaml"):
        shutil.copy(REPO / "config" / name, config / name)
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "CONFIG", config)
    monkeypatch.delenv("MB_NOW", raising=False)
    copy_bars(root)
    late_bar(root)
    today = [{**row, "market": MARKET} for row in catalogue("prediction") if row["market"] == "us"]
    past = [past_prediction(t) for t in catalogue("open_trade") if t["view"] == "accuracy"
            and t["ticker"] in ("NVDA", "AAPL", "JPM")]
    jl(root, "strategy_predictions", "2026-09-30", past + CUSTOM[:2])
    jl(root, "strategy_predictions", SESSION, today + CUSTOM[2:])
    picks = [{**row, "market": MARKET} for row in catalogue("head_to_head_pick") if row["ticker"] == "NVDA"]
    jl(root, "head_to_head_picks", SESSION, picks)
    model_only = {row["horizon_days"]: row for row in today if row["strategy_id"] == "base.model_only.v1"}
    jl(root, "ranges", SESSION, [ranges_for("NVDA", k, (r["lo80"], r["lo50"], r["hi50"], r["hi80"]))
                                 for k, r in sorted(model_only.items())]
       + [ranges_for("AAPL", k, (326.0, 330.0, 337.0, 341.0)) for k in (1, 5)])
    news = [("nv-high", "2026-10-07T15:00:00Z", "high", "2026-10-07T15:05:00Z"),
            ("nv-overnight", "2026-10-07T02:00:00Z", "high", "2026-10-07T03:00:00Z"),
            ("nv-medium", "2026-10-07T15:10:00Z", "medium", "2026-10-07T15:12:00Z"),
            ("nv-late", "2026-10-07T15:20:00Z", "high", "2026-10-07T17:00:00Z"),    # enriched after the check
            ("nv-yesterday", "2026-10-06T15:00:00Z", "high", "2026-10-06T15:05:00Z")]  # before the prev close
    jl(root, "news", SESSION, [
        {"id": ident, "title": f"Nvidia item {ident}", "url": "u", "source": "Wire", "published_at": seen,
         "first_seen_at": seen, "feed": "f", "category": "company", "tickers": ["NVDA"], "primary_tickers": ["NVDA"],
         "mentioned_tickers": [], "tag_confidence": "high", "tag_version": 99} for ident, seen, _, _ in news])
    jl(root, "news_enriched", SESSION, [
        {"id": ident, "analyzed_at": at, "relevance": 0.9, "sentiment": 0.3, "materiality": level}
        for ident, _, level, at in news])
    return root, load_market(MARKET), load_intraday_config()


def stored(root: Path, kind: str) -> list[dict]:
    files = sorted((root / "data" / MARKET / kind).glob("**/*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]


def trade_view(root: Path) -> dict[str, dict]:
    """{trade_id: trade_checks row merged with its details row}."""
    details = {row["id"]: row for row in stored(root, "trade_check_details")}
    return {row["trade_id"]: {**details[row["id"]], **row} for row in stored(root, "trade_checks")}


def test_w1_example_trade_matches_its_record_and_every_open_trade_is_checked(market):
    root, cfg, settings = market
    summary = run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    assert summary["status"] == "ok" and summary["check_id"] == CHECK_ID
    trades = trade_view(root)
    # W1's trade_check.json: NVDA N+5 from 09-30, session 6 (the exit session), price 241.1 above its 80% range
    nvda = trades["acc:rule.model_news.v1:2026-09-29-NVDA-5d"]
    example = next(r for r in catalogue("trade_check") if r["trade_id"] == nvda["trade_id"])
    for key in ("entry_price", "last_price", "target_price", "lo80", "lo50", "hi50", "hi80", "band", "flags",
                "session_number", "horizon_days", "entry_date", "exit_date", "view", "flagged"):
        assert nvda[key] == example[key], key
    assert nvda["ret_since_entry_pct"] == pytest.approx(example["ret_since_entry_pct"], abs=0.005)
    assert nvda["to_target_pct"] == pytest.approx(example["to_target_pct"], abs=0.005)
    assert nvda["check_row_id"] == f"{CHECK_ID}-NVDA" and nvda["id"] == f"{CHECK_ID}-{nvda['trade_id']}"
    assert nvda["target_reached"] is True and nvda["target_reached_session"] == 1   # 09-30 high 232.37 >= 228.03
    # every qualifying prediction is an accuracy trade, every picked head-to-head an h2h trade; nothing else
    today = [r for r in catalogue("prediction") if r["market"] == "us" and r["qualifies"]]
    expected = {f"acc:{r['id']}" for r in today}
    expected |= {f"acc:{t['prediction_id']}" for t in catalogue("open_trade")
                 if t["view"] == "accuracy" and t["ticker"] in ("NVDA", "AAPL", "JPM")}
    expected |= {f"acc:{c['id']}" for c in CUSTOM[:5]}
    picks = [p for p in catalogue("head_to_head_pick") if p["ticker"] == "NVDA" and p["status"] == "picked"]
    expected |= {f"h2h:{p['pick_rule']}:{p['prediction_id']}" for p in picks
                 if p["prediction_id"] in {r["id"] for r in today}
                 or f"acc:{p['prediction_id']}" in expected}
    assert "h2h:highest_probability:ai.combined.opus.v1:2026-09-29-NVDA-5d" in expected
    assert "h2h:best_expected_gain:rule.model_news.v1:2026-09-29-NVDA-1d" not in expected   # exited 09-30
    assert set(trades) == expected
    assert summary["open_trades"] == len(expected) and summary["skipped_trades"]["not_locked"] == 1
    runs = stored(root, "intraday_runs")
    assert runs[0]["open_trades"] == len(expected) and runs[0]["trades_flagged"] == summary["trades_flagged"]
    checks = {row["ticker"]: row for row in stored(root, "intraday_checks")}
    assert checks["NVDA"]["open_trades"] == sum(t["ticker"] == "NVDA" for t in trades.values())
    assert "open_trade_flagged" in checks["NVDA"]["flags"] and checks["NVDA"]["flagged"]


def test_every_horizon_and_its_sessions(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    trades = trade_view(root)
    today = {k: trades[f"acc:rule.model_news.v1:2026-10-06-NVDA-{k}d"] for k in (1, 2, 3, 4, 5)}
    for k, row in today.items():
        assert row["horizon_days"] == k and row["session_number"] == 1 and row["entry_source"] == "intraday_open"
        assert row["entry_price"] == 239.0                                      # today's first 5-minute open
        assert row["sessions_left"] == pytest.approx(k + 1 - ELAPSED, abs=1e-4)  # exit = close of the k-th after D
        assert row["sessions_held"] == pytest.approx(ELAPSED, abs=1e-4)
    assert today[3]["exit_date"] == "2026-10-12"                                # Fri 10-09 + Monday
    assert trades["acc:rule.b9_reached.v1:2026-10-02-NVDA-3d"]["session_number"] == 3
    checks = {row["ticker"]: row for row in stored(root, "intraday_checks")}
    assert sorted(checks["NVDA"]["bands"], key=int) == ["1", "2", "3", "4", "5"]  # every published horizon
    assert checks["NVDA"]["band_1d"] == checks["NVDA"]["bands"]["1"]["band"]      # legacy columns kept
    assert checks["AAPL"]["notes"].count("no_range_2d") == 1                       # published for NVDA only
    assert checks["NVDA"]["sigma_1d"] == pytest.approx(SIGMA["NVDA"])


def test_band_edges_and_flags(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    trades = trade_view(root)
    on_edge = trades["acc:rule.b9_edge_in.v1:2026-10-06-NVDA-2d"]
    beyond = trades["acc:rule.b9_edge_out.v1:2026-10-06-NVDA-2d"]
    assert on_edge["band"] == "above50" and "outside_range" not in on_edge["flags"]
    assert beyond["band"] == "above80" and "outside_range" in beyond["flags"] and beyond["flagged"]
    aapl = trades["acc:base.b9_against.v1:2026-10-06-AAPL-1d"]
    z = (334.95 / 340.0 - 1) / (SIGMA["AAPL"] * math.sqrt(ELAPSED))
    assert aapl["z_since_entry"] == pytest.approx(z, abs=1e-3) and "against_prediction" in aapl["flags"]
    far = trades["acc:rule.b9_far.v1:2026-10-02-NVDA-3d"]
    target_z = (260 / 241.1 - 1) / (SIGMA["NVDA"] * math.sqrt(2 - ELAPSED))
    assert far["target_z"] == pytest.approx(target_z, abs=1e-3) and far["flags"] == ["far_from_target"]
    rules = {"thresholds": {"target_z": 2.0, "against_call_z": 1.0}}
    assert trade_flags({"direction": "up"}, "below80", -1.0, 2.0, False, rules) == [
        "outside_range", "far_from_target", "against_prediction"]
    assert trade_flags({"direction": "up"}, "below50", -0.999, 1.999, False, rules) == []
    assert trade_flags({"direction": "up"}, "inside50", 0.0, 5.0, True, rules) == []    # reached: never far
    # ticker flags for every published horizon, the 80% template in flag_on, the 50% flag on the shortest only
    assert flags_for({"bands": {"2": {"band": "above50"}, "3": {"band": "above80"}}}, [], settings) == [
        "outside_2d_50", "outside_3d_80"]
    assert is_trigger("outside_3d_80", settings["flag_on"]) and not is_trigger("outside_2d_50", settings["flag_on"])


def test_target_reached_intraday_and_no_look_ahead(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    trades = trade_view(root)
    strict = trades["acc:rule.b9_reached.v1:2026-10-02-NVDA-3d"]
    assert strict["target_reached"] is True and strict["target_reached_session"] == 3   # today's 251 high
    high = trades["acc:rule.b9_far.v1:2026-10-02-NVDA-3d"]
    assert high["target_reached"] is False and high["target_reached_session"] is None  # not the 270 or 300 later
    assert high["high_since_entry_pct"] == pytest.approx((251.0 / 236.09 - 1) * 100, abs=1e-3)
    one_day = trades["acc:rule.model_news.v1:2026-10-06-NVDA-1d"]
    assert one_day["target_reached"] is True and one_day["target_reached_session"] == 1   # 239.54 <= 251 today
    assert all(row["last_price"] == 241.1 for row in trades.values() if row["ticker"] == "NVDA")   # not 300
    ids = set(trades)
    assert "acc:rule.b9_late.v1:2026-10-06-NVDA-1d" not in ids      # stored after the check
    assert "acc:rule.b9_unlocked.v1:2026-10-06-NVDA-1d" not in ids    # made after D's open


def test_stale_quote_rows_carry_no_measures(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    jpm = [row for row in trade_view(root).values() if row["ticker"] == "JPM"]
    assert len(jpm) == 3
    for row in jpm:
        assert row["quality"] == "stale_quote" and row["last_price"] is None and row["band"] is None
        assert row["flags"] == [] and not row["flagged"] and row["entry_price"] == 334.89   # stored 09-30 open
    # before today JPM's highs (336.34 on 09-30) reach every JPM target, so it is known without today's quote
    assert all(row["target_reached"] is True and row["target_reached_session"] == 1 for row in jpm)


def test_market_closed_writes_only_the_run_row(market):
    root, cfg, settings = market
    saturday = datetime(2026, 10, 10, 16, 27, tzinfo=timezone.utc)
    summary = run_check(cfg, settings, connect(MARKET), FakeFetcher(), saturday)
    assert summary["status"] == "market_closed"
    assert stored(root, "trade_checks") == [] and stored(root, "intraday_alerts") == []
    assert [row["status"] for row in stored(root, "intraday_runs")] == ["market_closed"]


def test_idempotent_rerun_and_alerts_once_per_session(market):
    root, cfg, settings = market
    first = run_check(cfg, settings, connect(MARKET), FakeFetcher(spike=False), CHECK)
    counts = {kind: len(stored(root, kind)) for kind in
              ("trade_checks", "trade_check_details", "intraday_alerts", "intraday_checks", "intraday_runs")}
    again = run_check(cfg, settings, connect(MARKET), FakeFetcher(spike=False), CHECK + timedelta(seconds=20))
    assert again["status"] == "duplicate" and again["written"] == 0
    assert counts == {kind: len(stored(root, kind)) for kind in counts}
    alerts = {row["id"]: row for row in stored(root, "intraday_alerts")}
    news = sorted(row["news_id"] for row in alerts.values() if row["alert_type"] == "material_news_open_trade")
    assert news == ["nv-high", "nv-overnight"]          # medium, enriched-after-check and yesterday's: none
    trade_alert = alerts[f"{CHECK_ID}-NVDA-trades"]
    assert trade_alert["repeat"] is False and set(trade_alert["trade_ids"]) == {
        trade["trade_id"] for trade in trade_alert["trades"]}
    assert set(first["alert_ids"]) == set(alerts)
    later = run_check(cfg, settings, connect(MARKET), FakeFetcher(spike=False), CHECK + timedelta(minutes=30))
    assert later["status"] == "ok"
    new = [row for row in stored(root, "intraday_alerts") if row["check_id"] == later["check_id"]]
    assert [row["alert_type"] for row in new if row["ticker"] == "NVDA"] == ["open_trade_flagged"]  # no news again
    assert next(row for row in new if row["ticker"] == "NVDA")["repeat"] is True


def test_split_inside_the_holding_window(market):
    root, cfg, settings = market
    jl(root, "adjustments", "2026-10-07", [
        {"id": "AAPL-2026-10-07", "ticker": "AAPL", "ex_date": SESSION, "factor": 0.5, "source": "yahoo",
         "detected_at": "2026-10-07T05:00:00Z"},
        {"id": "NVDA-2026-10-07", "ticker": "NVDA", "ex_date": SESSION, "factor": 0.1, "source": "yahoo",
         "detected_at": "2026-10-07T17:00:00Z"}])                   # detected after the check: not applied
    run_check(cfg, settings, connect(MARKET), FakeFetcher(scale={"AAPL": 0.5}), CHECK)
    trades = trade_view(root)
    aapl = trades["acc:rule.model_news.v1:2026-09-29-AAPL-5d"]
    assert aapl["entry_price"] == 330.8 and aapl["basis_factor"] == 0.5 and aapl["entry_adj"] == 165.4
    assert aapl["ret_since_entry_pct"] == pytest.approx((334.95 / 330.8 - 1) * 100, abs=1e-3)   # split-neutral
    assert aapl["target_price"] == 329.9 and aapl["target_adj"] == pytest.approx(164.95)
    assert trades["acc:rule.model_news.v1:2026-09-29-NVDA-5d"]["basis_factor"] == 1.0


def test_explainer_input_and_gate_cover_the_trades(market, tmp_path):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    con = connect(MARKET)
    summary = explain.prepare(con, tmp_path / "flags.jsonl", None)
    lines = (tmp_path / "flags.jsonl").read_text().splitlines()
    rows = {json.loads(line)["ticker"]: json.loads(line) for line in lines}
    assert summary["n"] == len(rows) and "NVDA" in rows
    nvda = rows["NVDA"]
    flagged = {row["trade_id"] for row in trade_view(root).values() if row["ticker"] == "NVDA" and row["flagged"]}
    assert {trade["trade_id"] for trade in nvda["trades"]} == flagged and nvda["candidate_ids"]
    rules = {"explainer": {"max_words": 60, "prompt_version": "deviation-v1"}}
    note = {"check_row_id": nvda["id"], "attribution": "idiosyncratic", "cited_ids": [],
            "text": "NVDA trade acc:rule.model_news.v1:2026-09-29-NVDA-5d is up 5.16% since entry, above its 80% "
                    "range at N+5 (session 6); the price is 0.09% over its upper edge.",
            "prompt_version": "deviation-v1"}
    good, bad = validate_records([note], explain.flagged_rows(con), set(), rules)
    assert bad == [] and len(good) == 1
    wrong = {**note, "text": "NVDA trade is up 7.7% since entry."}
    _, bad = validate_records([wrong], explain.flagged_rows(con), set(), rules)
    assert any("7.7" in error for error in bad[0]["errors"])


def test_payload_rows_pass_the_schema_gate_and_india_price_skip(market, monkeypatch):
    from marketbrief.pipeline.validate.row_checks import check_rows as schema_problems

    root, cfg, settings = market
    monkeypatch.setenv("MB_NOW", CHECK.isoformat())
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    monkeypatch.delenv("MB_NOW")
    now = pd.Timestamp(CHECK) + pd.Timedelta(minutes=5)
    for kind in ("trade_checks", "trade_check_details", "intraday_alerts", "intraday_checks", "intraday_runs"):
        rows = stored(root, kind)
        assert rows and schema_problems(kind, rows, False, now, timedelta(minutes=5)) == [], kind
    from marketbrief.core.schemas import SCHEMAS

    assert all(list(row) == list(SCHEMAS["trade_checks"][1]) for row in stored(root, "trade_checks"))   # W1 format
    payload = intraday_payload(connect(MARKET), MARKET, settings, as_of=now.to_pydatetime())
    assert {row["trade_id"] for row in payload["trades"]} == set(trade_view(root))
    assert {row["id"] for row in payload["alerts"]} == {row["id"] for row in stored(root, "intraday_alerts")}
    json.dumps(payload)
    early = intraday_payload(connect(MARKET), MARKET, settings, as_of=datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc))
    assert early["trades"] == [] and early["alerts"] == []
    assert skipped_for_price("india", 100000.0, 150000.0) and not skipped_for_price("india", 100000.0, 99999.0)
    assert not skipped_for_price("us", 1000.0, 5000.0)


def test_busy_ticker_alerts_every_material_item(market):
    """More news than any count limit on one ticker: every high-materiality item is alerted, late ones too."""
    root, cfg, settings = market
    items = [(f"nv-bulk-{n:02d}", f"2026-10-07T14:{n:02d}:00Z", "high" if n >= 25 else "low") for n in range(30)]
    jl(root, "news", SESSION, [
        {"id": ident, "title": f"Nvidia bulk {ident}", "url": "u", "source": "Wire", "published_at": seen,
         "first_seen_at": seen, "feed": "f", "category": "company", "tickers": ["NVDA"], "primary_tickers": ["NVDA"],
         "mentioned_tickers": [], "tag_confidence": "high", "tag_version": 99} for ident, seen, _ in items])
    jl(root, "news_enriched", SESSION, [
        {"id": ident, "analyzed_at": "2026-10-07T15:00:00Z", "relevance": 0.9, "sentiment": 0.1, "materiality": level}
        for ident, _, level in items])
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    alerts = stored(root, "intraday_alerts")
    news = {row["news_id"] for row in alerts if row["alert_type"] == "material_news_open_trade"}
    assert news == {"nv-high", "nv-overnight"} | {ident for ident, _, level in items if level == "high"}


def test_gate_allows_only_the_horizons_a_row_knows(market):
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), CHECK)
    con = connect(MARKET)
    rows = explain.flagged_rows(con)
    row = rows[f"{CHECK_ID}-NVDA"]
    rules = {"explainer": {"max_words": 60, "prompt_version": "deviation-v1"}}
    base = {"check_row_id": row["id"], "attribution": "idiosyncratic", "cited_ids": [],
            "prompt_version": "deviation-v1"}
    good, _ = validate_records([{**base, "text": "NVDA sits above its N+5 range."}], rows, set(), rules)
    assert len(good) == 1
    _, bad = validate_records([{**base, "text": "NVDA sits above its N+7 range."}], rows, set(), rules)
    assert any("7" in error for error in bad[0]["errors"])



def test_backfilled_earlier_check_ignores_later_alerts(market):
    """Issue #70: a later check stored first never suppresses an earlier check's alerts or sets its repeat."""
    root, cfg, settings = market
    run_check(cfg, settings, connect(MARKET), FakeFetcher(spike=False), CHECK + timedelta(minutes=30))
    run_check(cfg, settings, connect(MARKET), FakeFetcher(spike=False), CHECK)
    early = [row for row in stored(root, "intraday_alerts") if row["check_id"] == CHECK_ID]
    assert sorted(row["news_id"] for row in early if row["news_id"]) == ["nv-high", "nv-overnight"]
    assert next(row for row in early if row["alert_type"] == "open_trade_flagged")["repeat"] is False


def test_adjustment_correction_counts_only_once_detected(market):
    """Issue #71: a correction (supersedes) detected after the check is not applied at the check."""
    root, cfg, settings = market
    jl(root, "adjustments", "2026-10-07", [
        {"id": "AAPL-2026-10-07", "ticker": "AAPL", "ex_date": SESSION, "factor": 0.5, "source": "yahoo",
         "detected_at": "2026-10-07T05:00:00Z"},
        {"id": "AAPL-2026-10-07-fix", "ticker": "AAPL", "ex_date": SESSION, "factor": 1.0, "source": "manual",
         "detected_at": "2026-10-07T17:00:00Z", "supersedes": "AAPL-2026-10-07"}])
    run_check(cfg, settings, connect(MARKET), FakeFetcher(scale={"AAPL": 0.5}), CHECK)
    assert trade_view(root)["acc:rule.model_news.v1:2026-09-29-AAPL-5d"]["basis_factor"] == 0.5
    later = CHECK + timedelta(hours=1)                      # the correction is known by then: no split
    run_check(cfg, settings, connect(MARKET), FakeFetcher(), later)
    rows = [row for row in trade_view(root).values() if row["check_at"].startswith("2026-10-07T17:27")]
    assert {row["basis_factor"] for row in rows if row["ticker"] == "AAPL"} == {1.0}


def test_unwatched_ticker_rows_and_alerts_cli_dates(market, monkeypatch, capsys):
    """Issue #74: a trade on a ticker without a check row has no check_row_id; issue #72: the alerts CLI prints
    session_date as a date. Issue #75: the horizon list is read once per file version."""
    from marketbrief.intraday import cli
    from marketbrief.intraday.settings import _horizons_in, configured_horizons

    root, cfg, settings = market
    jl(root, "strategy_predictions", SESSION, [
        custom("rule.b9_unwatched.v1:2026-10-06-MSFT-1d", ("2026-10-06", SESSION, "2026-10-08"), 400.0,
               (380.0, 390.0, 410.0, 420.0))])
    monkeypatch.setattr(cli, "YahooIntraday", lambda: FakeFetcher(spike=False))
    monkeypatch.setenv("MB_NOW", CHECK.isoformat())
    monkeypatch.setattr(sys, "argv", ["intraday_check.py", "--market", MARKET])
    assert cli.main() == 0
    capsys.readouterr()
    msft = trade_view(root)["acc:rule.b9_unwatched.v1:2026-10-06-MSFT-1d"]
    assert msft["check_row_id"] is None and "not_on_watchlist" in msft["notes"] and msft["quality"] == "no_quote"
    monkeypatch.setattr(sys, "argv", ["intraday_check.py", "--market", MARKET, "alerts"])
    assert cli.main() == 0
    alerts = json.loads(capsys.readouterr().out)["alerts"]
    assert alerts and {row["session_date"] for row in alerts} == {SESSION}
    assert configured_horizons() == (1, 2, 3, 4, 5)                  # B10's contract (built)
    from marketbrief.contracts import horizons as horizon_contract

    def not_built():
        raise NotImplementedError("session B10")
    monkeypatch.setattr(horizon_contract, "horizons", not_built)    # the fallback: strategies.yaml, cached
    before = _horizons_in.cache_info().hits
    assert configured_horizons() == configured_horizons() == (1, 2, 3, 4, 5)
    assert _horizons_in.cache_info().hits >= before + 1
