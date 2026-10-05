"""Yahoo collectors report empty and stale answers in `failed` (issue #5). yfinance hides most
request errors behind empty frames, empty tuples or empty dicts, so each collector checks what
came back. A fake yfinance module stands in for the network; collectors run in-process."""
from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
import collect_events  # noqa: E402
import collect_options  # noqa: E402
import collect_prices  # noqa: E402
import collect_quotes  # noqa: E402
from test_pipeline import MARKET, setup  # noqa: E402

TODAY = date(2026, 10, 5)                    # Monday; XNYS previous session Friday 2026-10-02
NOW = "2026-10-05T12:15:00+00:00"
NY = "America/New_York"


def daily(days: list[date], nan_last: bool = False) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(NY) for d in days])
    c = np.linspace(100, 110, len(days))
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Adj Close": c,
                       "Volume": 1000}, index=idx)
    if nan_last and len(df):
        df.iloc[-1, :4] = np.nan
    return df


def intraday(last: str, nan_tail: int = 0) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp(last, tz="UTC"), periods=6, freq="5min")
    close = [100.0, 100.5, 101.0, 101.5, 102.0, 102.5]
    for i in range(nan_tail):
        close[-1 - i] = np.nan
    return pd.DataFrame({"Close": close}, index=idx)


def bdays(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


class FakeTicker:
    specs: dict[str, dict] = {}

    def __init__(self, symbol: str):
        self.s = self.specs[symbol]

    def history(self, period=None, interval="1d", **_):
        return self.s.get("intraday" if interval == "5m" else "daily", pd.DataFrame()).copy()

    @property
    def options(self):
        return tuple(self.s.get("options", ()))

    def option_chain(self, e):
        return self.s["chain"]

    @property
    def fast_info(self):
        return {"lastPrice": 100.0}

    @property
    def calendar(self):
        if isinstance(self.s.get("calendar"), Exception):
            raise self.s["calendar"]
        return self.s.get("calendar", {})

    @property
    def dividends(self):
        if isinstance(self.s.get("dividends"), Exception):
            raise self.s["dividends"]
        return self.s.get("dividends", pd.Series(dtype=float))

    def _earn(self, key):
        v = self.s.get(key)
        if isinstance(v, Exception):
            raise v
        return v

    def get_earnings_dates(self, limit=12):
        return self._earn("page")

    def _get_earnings_dates_using_screener(self, limit=12):
        return self._earn("screener")


@pytest.fixture
def env(tmp_path, monkeypatch):
    root, cfg = setup(tmp_path)
    path = cfg / "markets" / f"{MARKET}.yaml"
    path.write_text(path.read_text().replace(
        "  VOLX: {role: vol_index, name: Vol index}\n",
        "  VOLX: {role: vol_index, name: Vol index}\n  CUE: {role: cue, name: Overseas cue}\n")
        + "options: yfinance\n")
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.setattr(common, "CONFIG", cfg)
    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(FakeTicker, "specs", {})
    for mod in (collect_prices, collect_quotes, collect_events, collect_options):
        monkeypatch.setattr(mod, "utc_today", lambda: TODAY)
        monkeypatch.setattr(mod, "utc_now", lambda: NOW)
    return root


def run_main(mod, monkeypatch, capsys, *args) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", [mod.__name__, "--market", MARKET, *args])
    code = mod.main()
    return code, json.loads(capsys.readouterr().out)


# ---------- prices ----------

def test_prices_report_empty_partial_and_stale_frames(env, monkeypatch, capsys):
    good = bdays(TODAY, 21)                                    # through today's (partial) bar
    FakeTicker.specs.update({
        "AAPL": {"daily": daily(good)},                        # fine: newest completed bar 2026-10-02
        "MSFT": {"daily": daily(bdays(date(2026, 9, 30), 20))},  # stock 2 sessions behind: stale
        "BENCH": {"daily": daily([TODAY])},                    # only today's partial bar
        "VOLX": {"daily": daily(bdays(date(2026, 10, 2), 20), nan_last=True)},  # newest bar all NaN
        "CUE": {"daily": daily(bdays(date(2026, 9, 30), 20))},  # other exchange: 5 days old is fine
    })
    code, out = run_main(collect_prices, monkeypatch, capsys)
    assert code == 0
    assert {f["ticker"]: f["error"] for f in out["failed"]} == {
        "MSFT": "stale: newest bar 2026-09-30, expected 2026-10-02 or later",
        "BENCH": "no completed bar",
        "VOLX": "stale: newest bar 2026-10-01, expected 2026-10-02 or later",
    }
    con = common.connect(MARKET)
    newest = dict(con.execute("SELECT ticker, max(date) FROM prices GROUP BY 1").fetchall())
    assert newest == {"AAPL": date(2026, 10, 2), "MSFT": date(2026, 9, 30),   # stale bars still stored
                      "VOLX": date(2026, 10, 1), "CUE": date(2026, 9, 30)}


def test_prices_stale_cue_after_a_week_and_empty_frame(env, monkeypatch, capsys):
    FakeTicker.specs.update({t: {"daily": daily(bdays(date(2026, 10, 2), 20))} for t in ("AAPL", "BENCH", "VOLX")})
    FakeTicker.specs["CUE"] = {"daily": daily(bdays(date(2026, 9, 25), 20))}
    FakeTicker.specs["MSFT"] = {"daily": pd.DataFrame()}
    code, out = run_main(collect_prices, monkeypatch, capsys)
    assert code == 0
    assert {f["ticker"]: f["error"] for f in out["failed"]} == {
        "CUE": "stale: newest bar 2026-09-25, expected 2026-09-28 or later", "MSFT": "no data"}


def test_prices_expected_bar_follows_the_exchange_calendar(env):
    cfg = common.load_market(MARKET)
    assert collect_prices.expected_bar(cfg, "AAPL", date(2026, 11, 27)) == date(2026, 11, 25)  # Thanksgiving
    assert collect_prices.expected_bar(cfg, "BENCH", date(2026, 10, 5)) == date(2026, 10, 2)
    assert collect_prices.expected_bar(cfg, "CUE", date(2026, 10, 5)) == date(2026, 9, 28)


# ---------- quotes ----------

def test_quotes_drop_nan_tail_and_report_stale(env, monkeypatch, capsys):
    prior = daily(bdays(date(2026, 10, 2), 20))
    FakeTicker.specs.update({
        "BENCH": {"intraday": intraday("2026-10-05 12:10", nan_tail=2), "daily": prior},
        "VOLX": {"intraday": intraday("2026-09-24 20:00"), "daily": daily(bdays(date(2026, 9, 23), 20))},
        "CUE": {"intraday": intraday("2026-10-05 12:10"), "daily": pd.DataFrame()},
    })
    code, out = run_main(collect_quotes, monkeypatch, capsys)
    assert code == 0 and out["written"] == 1
    assert {f["symbol"]: f["error"] for f in out["failed"]} == {
        "VOLX": "stale: last quote 2026-09-24T20:00:00+00:00", "CUE": "no data"}
    row = json.loads(next((env / "data" / MARKET / "quotes").glob("**/*.jsonl")).read_text())
    assert row["symbol"] == "BENCH" and row["price"] == 101.5          # last priced bar, not the NaN tail
    assert row["ts"] == "2026-10-05T12:00:00+00:00"
    assert row["change_pct"] == round(101.5 / 110.0 - 1, 6)


# ---------- options ----------

def chain(iv: float):
    k = [95.0, 100.0, 105.0]
    df = pd.DataFrame({"strike": k, "impliedVolatility": [iv] * 3, "bid": [5.0, 2.0, 0.5],
                       "ask": [5.2, 2.2, 0.7], "lastPrice": [5.1, 2.1, 0.6]})
    return types.SimpleNamespace(calls=df, puts=df.copy(), underlying={"regularMarketPrice": 100.0})


def test_options_ticker_without_snapshot_is_a_failure(env, monkeypatch, capsys):
    FakeTicker.specs.update({
        "AAPL": {"options": ["2026-10-09"], "chain": chain(0.3)},
        "MSFT": {"options": []},                                 # Yahoo's answer had no option result
    })
    code, out = run_main(collect_options, monkeypatch, capsys)
    assert code == 0 and out["written"] == 1 and out["tickers"] == 1
    assert out["failed"] == [{"ticker": "MSFT", "error": "no option expiries returned"}]
    FakeTicker.specs.update({"AAPL": {"options": ["2027-03-19"]},                  # beyond --max-days
                             "MSFT": {"options": ["2026-10-09"], "chain": chain(0.0)}})  # no plausible IV
    monkeypatch.setattr(collect_options, "recent_ids", lambda *a, **k: set())
    code, out = run_main(collect_options, monkeypatch, capsys)
    assert code == 1 and out["written"] == 0                    # every ticker failed
    assert out["failed"] == [{"ticker": "AAPL", "error": "no expiry within 1-45 days"},
                             {"ticker": "MSFT", "error": "no usable chain (no quote with a plausible implied vol)"}]


# ---------- events ----------

def earnings_frame(days: list[str]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz=NY) for d in days])
    return pd.DataFrame({"Event Type": ["Earnings"] * len(days)}, index=idx)


def test_events_report_silent_yahoo_gaps(env, monkeypatch, capsys):
    blocked = ConnectionError("curl: (56) CONNECT tunnel failed, response 403")
    divs = pd.Series([0.25, 0.26], index=pd.DatetimeIndex([pd.Timestamp("2026-05-11", tz=NY),
                                                          pd.Timestamp("2026-08-10", tz=NY)]))
    FakeTicker.specs.update({
        # Yahoo lists an ex-dividend date in the window but the dividend history came back empty;
        # both earnings-date methods raised
        "AAPL": {"calendar": {"Earnings Date": [date(2026, 10, 29)], "Ex-Dividend Date": date(2026, 8, 10)},
                 "page": blocked, "screener": blocked},
        # empty calendar; the earnings page is refused but the screener answers
        "MSFT": {"calendar": {}, "dividends": divs, "page": blocked,
                 "screener": earnings_frame(["2026-07-29 16:05", "2026-04-29 16:05"])},
    })
    code, out = run_main(collect_events, monkeypatch, capsys)
    assert code == 0
    assert [(f["ticker"], f["what"]) for f in out["failed"]] == [
        ("AAPL", "dividends"), ("AAPL", "earnings_history"), ("MSFT", "calendar")]
    err = {(f["ticker"], f["what"]): f["error"] for f in out["failed"]}
    assert err[("AAPL", "dividends")] == "no dividends returned (calendar lists ex-dividend 2026-08-10)"
    assert err[("AAPL", "earnings_history")].startswith("get_earnings_dates: curl: (56)")
    assert "; get_earnings_dates_using_screener: curl: (56)" in err[("AAPL", "earnings_history")]
    assert err[("MSFT", "calendar")] == "empty calendar"
    assert out["earnings_history_sources"] == {"get_earnings_dates_using_screener": 1}
    assert out["new_history"] == {"earnings": 2, "ex_dividend": 2}


def test_events_no_dividend_payer_is_fine_but_a_stored_payer_is_not(env, monkeypatch, capsys):
    shot = earnings_frame(["2026-07-22 16:05"])
    FakeTicker.specs.update({
        "AAPL": {"calendar": {"Earnings Date": [date(2026, 10, 21)]}, "page": shot},          # pays none
        "MSFT": {"calendar": {"Earnings Date": [date(2026, 10, 28)],
                              "Ex-Dividend Date": date(2008, 1, 7)}, "page": shot},       # long ago
    })
    code, out = run_main(collect_events, monkeypatch, capsys)
    assert (code, out["failed"]) == (0, [])
    common.append_jsonl(common.day_file(MARKET, "events", date(2026, 9, 1)), [
        {"id": "MSFT-ex_dividend-2026-08-20", "date": "2026-08-20", "type": "ex_dividend", "ticker": "MSFT",
         "name": "Microsoft ex-dividend", "source": "yfinance_history", "first_seen_at": NOW, "amount": 0.83}])
    code, out = run_main(collect_events, monkeypatch, capsys)
    assert out["failed"] == [{"ticker": "MSFT", "what": "dividends", "error": "no dividends returned (1 stored)"}]


def test_events_exit_code_when_every_calendar_fails(env, monkeypatch, capsys):
    FakeTicker.specs.update({t: {"calendar": RuntimeError("boom"), "page": earnings_frame([])}
                             for t in ("AAPL", "MSFT")})
    FakeTicker.specs["MSFT"]["dividends"] = RuntimeError("divs down")
    code, out = run_main(collect_events, monkeypatch, capsys, "--no-history")
    assert code == 1
    assert [(f["ticker"], f["what"], f["error"]) for f in out["failed"]] == [
        ("AAPL", "calendar", "boom"), ("MSFT", "calendar", "boom"), ("MSFT", "dividends", "divs down")]


def test_events_sec_errors_are_failures(env, monkeypatch, capsys):
    class Edgar:
        def __init__(self, ua):
            pass

        def cik_map(self):
            return {"AAPL": "320193", "MSFT": "789019"}

        def recent(self, cik):
            if cik == "789019":
                raise OSError("HTTP 503")
            return {"form": ["8-K"], "items": ["2.02"], "acceptanceDateTime": ["2026-07-30T16:30:00-04:00"]}

    import sec
    monkeypatch.setattr(sec, "Edgar", Edgar)
    errors: dict = {}
    us = {"market": "us", "calendar": "XNYS", "timezone": NY}
    out = collect_events.sec_earnings(us, {"AAPL": {}, "MSFT": {}}, "t t@example.com", errors)
    assert list(out) == ["AAPL"] and errors == {"MSFT": "HTTP 503"}
    path = common.CONFIG / "markets" / f"{MARKET}.yaml"
    path.write_text(path.read_text() + "filings: sec\n")
    monkeypatch.setenv("SEC_USER_AGENT", "t t@example.com")
    shot = earnings_frame(["2026-07-22 16:05"])
    FakeTicker.specs.update({t: {"calendar": {"Earnings Date": [date(2026, 10, 28)]}, "page": shot}
                             for t in ("AAPL", "MSFT")})
    code, out = run_main(collect_events, monkeypatch, capsys)
    assert out["failed"] == [{"ticker": "MSFT", "what": "sec_earnings", "error": "HTTP 503"}]
    monkeypatch.setattr(sec, "Edgar", None)                       # the whole SEC step fails
    code, out = run_main(collect_events, monkeypatch, capsys)
    assert [(f["ticker"], f["what"]) for f in out["failed"]] == [(None, "sec_earnings")]
    assert out["sec_error"] == out["failed"][0]["error"]
