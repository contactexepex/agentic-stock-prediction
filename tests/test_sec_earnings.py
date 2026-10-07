"""SEC item 2.02 filings vs results releases (event_history.results_filter): one release per fiscal
quarter, picked by the 10-Q/10-K reports, without look-ahead. Dates are real EDGAR acceptance
dates (New York) and period ends, 2023-07 to 2026-10. Run: pytest -q"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketbrief.replay.backtest import observations  # noqa: E402
from marketbrief.constants import events as event_constants  # noqa: E402
from marketbrief.core import calendar as ev  # noqa: E402
from marketbrief.analytics import earnings_reaction, event_history  # noqa: E402
from test_range_inputs import ALL_ON, XNYS, run_events_main  # noqa: E402


def D(s: str) -> date:
    return date.fromisoformat(s)


def sec_rows(dates, timing="before_open"):
    return [(D(d), timing, "sec_history") for d in dates]


def reports(pairs):
    return [(D(a), D(b)) for a, b in pairs]


def kept(rows, reps, as_of=None) -> list[str]:
    return sorted({str(d) for d, _, _ in event_history.results_filter(rows, reps, as_of)})


# Tesla: an 8-K item 2.02 with the quarter's deliveries about the 2nd of each quarter's first month,
# then the results release about three weeks later; the 10-Q/10-K follows the release within a day.
TSLA_RESULTS = ["2023-07-19", "2023-10-18", "2024-01-24", "2024-04-23", "2024-07-23", "2024-10-23", "2025-01-29",
                "2025-04-22", "2025-07-23", "2025-10-22", "2026-01-28", "2026-04-22", "2026-07-22"]
TSLA_DELIVERIES = ["2023-07-03", "2023-10-02", "2024-01-02", "2024-04-02", "2024-07-02", "2024-10-02", "2025-01-02",
                   "2025-04-02", "2025-07-02", "2025-10-02", "2026-01-02", "2026-04-02", "2026-07-02", "2026-10-02"]
TSLA_REPORTS = [("2023-07-21", "2023-06-30"), ("2023-10-20", "2023-09-30"), ("2024-01-26", "2023-12-31"),
                ("2024-04-23", "2024-03-31"), ("2024-07-23", "2024-06-30"), ("2024-10-23", "2024-09-30"),
                ("2025-01-29", "2024-12-31"), ("2025-04-22", "2025-03-31"), ("2025-07-23", "2025-06-30"),
                ("2025-10-22", "2025-09-30"), ("2026-01-28", "2025-12-31"), ("2026-04-22", "2026-03-31"),
                ("2026-07-22", "2026-06-30")]
# Allstate: 2.02 catastrophe-loss pre-announcements (2023-07-20 .. 2024-04-18) before the release
ALL_PRE = ["2023-07-20", "2023-10-19", "2024-01-18", "2024-04-18"]
ALL_RESULTS = ["2023-08-01", "2023-11-01", "2024-02-07", "2024-05-01", "2024-07-31", "2024-10-30", "2025-02-05",
               "2025-04-30", "2025-07-30", "2025-11-05", "2026-02-04", "2026-04-29", "2026-08-05"]
ALL_REPORTS = [("2023-08-01", "2023-06-30"), ("2023-11-01", "2023-09-30"), ("2024-02-21", "2023-12-31"),
               ("2024-05-01", "2024-03-31"), ("2024-07-31", "2024-06-30"), ("2024-10-30", "2024-09-30"),
               ("2025-02-24", "2024-12-31"), ("2025-04-30", "2025-03-31"), ("2025-07-30", "2025-06-30"),
               ("2025-11-05", "2025-09-30"), ("2026-02-19", "2025-12-31"), ("2026-04-29", "2026-03-31"),
               ("2026-08-05", "2026-06-30")]
# Progressive: monthly results; the quarter-end month's release is the 2.02 (the other months are
# 7.01), and the 10-Q follows two to five weeks later
PGR_RESULTS = ["2023-07-13", "2023-10-13", "2024-01-24", "2024-04-12", "2024-07-16", "2024-10-15", "2025-01-29",
               "2025-04-16", "2025-07-16", "2025-10-15", "2026-01-28", "2026-04-15", "2026-07-15"]
PGR_REPORTS = [("2023-08-01", "2023-06-30"), ("2023-10-31", "2023-09-30"), ("2024-02-26", "2023-12-31"),
               ("2024-05-06", "2024-03-31"), ("2024-08-05", "2024-06-30"), ("2024-11-04", "2024-09-30"),
               ("2025-03-03", "2024-12-31"), ("2025-05-05", "2025-03-31"), ("2025-08-04", "2025-06-30"),
               ("2025-11-03", "2025-09-30"), ("2026-03-02", "2025-12-31"), ("2026-05-04", "2026-03-31"),
               ("2026-08-03", "2026-06-30")]
# Costco: 52/53-week year of 12/12/12/16-week quarters; the 10-Q a week after the release
COST_RESULTS = ["2023-09-26", "2023-12-14", "2024-03-07", "2024-05-30", "2024-09-26", "2024-12-12", "2025-03-06",
                "2025-05-29", "2025-09-25", "2025-12-11", "2026-03-05", "2026-05-28", "2026-09-24"]
COST_REPORTS = [("2023-10-10", "2023-09-03"), ("2023-12-20", "2023-11-26"), ("2024-03-13", "2024-02-18"),
                ("2024-06-05", "2024-05-12"), ("2024-10-08", "2024-09-01"), ("2024-12-18", "2024-11-24"),
                ("2025-03-12", "2025-02-16"), ("2025-06-04", "2025-05-11"), ("2025-10-07", "2025-08-31"),
                ("2025-12-17", "2025-11-23"), ("2026-03-11", "2026-02-15"), ("2026-06-03", "2026-05-10")]


def test_tesla_delivery_reports_are_not_earnings():
    rows = sec_rows(TSLA_RESULTS + TSLA_DELIVERIES)
    reps = reports(TSLA_REPORTS)
    assert kept(rows, reps) == TSLA_RESULTS          # every delivery 8-K dropped, 2026-10-02 too
    # walk-forward: once a year of releases is confirmed, a delivery 8-K is dropped on its own day
    # (two days after the quarter end, results come 18+ days after it) before the next 10-Q exists
    for d in TSLA_DELIVERIES[5:]:
        assert d not in kept(rows, reps, D(d)), d
    # the 1-day range made the day before a delivery report no longer contains earnings
    evs = [(d, tm) for d, tm, _ in event_history.results_filter(rows, reps, D("2026-10-01"))]
    assert not earnings_reaction.earnings_in_horizon(XNYS, evs, D("2026-10-01"), D("2026-10-02"))
    assert earnings_reaction.earnings_in_horizon(XNYS, [(d, tm) for d, tm, _ in rows], D("2026-10-01"), D("2026-10-02"))


def test_allstate_preannouncements_are_not_earnings():
    rows = sec_rows(ALL_PRE + ALL_RESULTS)
    reps = reports(ALL_REPORTS)
    assert kept(rows, reps) == ALL_RESULTS           # incl. 2023-07-20, inside the first report's window
    # a 2.02 before the first stored report's period end cannot be judged: kept
    early = sec_rows(["2023-06-15"]) + rows
    assert "2023-06-15" in kept(early, reps)
    # a release accepted the day after its 10-Q still belongs to that 10-Q (made-up dates)
    late = sec_rows(["2025-04-10", "2025-04-30"])
    assert kept(late, reports([("2025-04-29", "2025-03-31")])) == ["2025-04-30"]


def test_progressive_release_weeks_before_its_10q_and_sec_beats_yfinance():
    rows = sec_rows(PGR_RESULTS)
    reps = reports(PGR_REPORTS)
    assert kept(rows, reps) == PGR_RESULTS           # one per quarter although the 10-Q is weeks later
    # yfinance dated Q3 2023 on the 10-Q day (2023-10-31): +1.9% that day vs +8.1% on 2023-10-13
    yf = [(D("2023-10-31"), "before_open", "yfinance_history")]
    assert kept(rows + yf, reps) == PGR_RESULTS
    # Costco: yfinance 2024-06-06 (the day after the 10-Q) vs the SEC release of 2024-05-30
    cost = sec_rows(COST_RESULTS, "after_close") + [(D("2024-06-06"), "before_open", "yfinance_history")]
    assert kept(cost, reports(COST_REPORTS)) == COST_RESULTS
    # a yfinance date no confirmed SEC release is near stays (e.g. before SEC coverage), and an
    # upcoming calendar date is never touched
    other = [(D("2023-04-20"), None, "yfinance_history"), (D("2026-10-14"), None, "yfinance")]
    assert {"2023-04-20", "2026-10-14"} <= set(kept(rows + other, reps))


def test_most_recent_quarter_counts_before_its_10q():
    rows, reps = sec_rows(PGR_RESULTS), reports(PGR_REPORTS)
    assert "2026-07-15" in kept(rows, reps, D("2026-07-20"))   # 10-Q only on 2026-08-03
    # Costco's fiscal 2026 results (2026-09-24): the 10-K is not filed yet, the release counts
    assert kept(sec_rows(COST_RESULTS), reports(COST_REPORTS))[-1] == "2026-09-24"
    tsla = sec_rows(TSLA_RESULTS + TSLA_DELIVERIES)
    assert "2026-07-22" in kept(tsla, reports(TSLA_REPORTS), D("2026-07-22"))
    # a ticker without stored reports (non-SEC market, or history stored before reports were) is unchanged
    assert kept(tsla, []) == sorted(TSLA_RESULTS + TSLA_DELIVERIES)


def test_no_look_ahead():
    rows, reps = sec_rows(ALL_PRE + ALL_RESULTS), reports(ALL_REPORTS)
    # only reports accepted by as_of are used, whatever later reports say
    day = D("2023-07-01")
    while day <= D("2026-10-05"):
        assert kept(rows, reps, day) == kept(rows, [r for r in reps if r[0] <= day]), day
        day += timedelta(days=3)
    # with one release confirmed, the 2023-10-19 pre-announcement is pending and counts on that
    # day; the 10-Q of 2023-11-01 shows it was not the release, but only from 2023-11-01 on
    assert "2023-10-19" in kept(rows, reps, D("2023-10-20"))
    assert "2023-10-19" not in kept(rows, reps, D("2023-11-01"))
    v = {start: [str(d) for d, _ in evs] for start, evs in event_history.earnings_versions(evframe("ALL", rows, reps))["ALL"]}
    assert "2023-10-19" in v[D("2023-08-01")] and "2023-10-19" not in v[D("2023-11-01")]


def test_live_filter_counts_a_report_only_from_its_acceptance_time():
    """Issue #24: the live ranges count a 10-Q/10-K from its acceptance time, not from its date: a morning run on
    the day of an after-close 10-Q does not see it (the date-only filter did)."""
    rows, reps = sec_rows(ALL_PRE + ALL_RESULTS), reports(ALL_REPORTS)
    evdf = evframe("ALL", rows, reps)
    evdf["accepted_at"] = [pd.Timestamp(f"{d}T20:15:00Z") if t == "periodic_report" else pd.NaT
                           for d, t in zip(evdf["date"], evdf["type"])]
    day = D("2023-11-01")                                     # the 10-Q that rules out the 10-19 pre-announcement
    morning, evening = pd.Timestamp("2023-11-01T13:00:00Z"), pd.Timestamp("2023-11-01T21:00:00Z")
    dates = lambda **kw: [str(d) for d, _ in event_history.earnings_events(evdf, **kw)["ALL"]]  # noqa: E731
    assert "2023-10-19" in dates(as_of=day, made_at=morning.to_pydatetime())
    assert "2023-10-19" not in dates(as_of=day, made_at=evening.to_pydatetime())
    assert "2023-10-19" not in dates(as_of=day)               # the date filter alone counted it in the morning
    # a report stored without an acceptance time counts only from the next day
    evdf["accepted_at"] = pd.NaT
    assert "2023-10-19" in dates(as_of=day, made_at=evening.to_pydatetime())
    assert "2023-10-19" not in dates(as_of=D("2023-11-02"), made_at=pd.Timestamp("2023-11-02T12:00:00Z"))


def test_releases_up_to_near_days_before_are_the_same_report():
    """Issue #24: 2.02s up to NEAR_DAYS (3) days before a quarter's release belong to it; one day more does not."""
    reps = reports([("2024-02-21", "2023-12-31"), ("2024-05-01", "2024-03-31")])
    rows = sec_rows(["2024-02-07", "2024-04-27", "2024-04-28", "2024-05-01"])
    assert kept(rows, reps) == ["2024-02-07", "2024-04-28", "2024-05-01"]


def test_backtest_version_applies_only_from_its_start():
    """Issue #24: an events version (known from its 10-Q's acceptance) never marks days before its start."""
    sessions = ev.exchange_calendar("XNYS").sessions_in_range("2026-03-02", "2026-04-30")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(5).normal(0, 0.01, len(sessions))))
    df = pd.DataFrame({"open": close, "close": close}, index=sessions)
    rc = {**ALL_ON, "ewma_lambda": 0.94, "warmup_bars": 10, "earnings_vol_multiple": 3.0}
    start = D("2026-04-01")
    versions = {"X": [(None, []), (start, [(D("2026-03-16"), "after_close")])]}   # learnt on 04-01 about 03-16
    extra = {"earnings": versions, "dividends": {}, "bench": df, "index_cue": None}
    cols = observations.input_columns({**XNYS, "premarket_quotes": False}, rc, df, "X", 1, extra)
    assert not cols["earn"].any()                              # 03-13/03-16 are before the version's start


def test_events_just_after_the_last_bar_still_flag_the_last_days():
    """Issue #27: an earnings day or ex-date after the last stored bar flags the last days before it (their
    positions come from the exchange calendar), as a live run on those days would."""
    sessions = ev.exchange_calendar("XNYS").sessions_in_range("2026-08-03", "2026-09-30")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(7).normal(0, 0.01, len(sessions))))
    df = pd.DataFrame({"open": close, "close": close}, index=sessions)
    rc = {**ALL_ON, "ewma_lambda": 0.94, "warmup_bars": 10, "earnings_vol_multiple": 3.0}
    extra = {"earnings": {"X": [(None, [(D("2026-10-02"), "before_open")])]}, "dividends": {"X": [(D("2026-10-01"), 1.0)]},
             "bench": df, "index_cue": None}
    cols = observations.input_columns({**XNYS, "premarket_quotes": False}, rc, df, "X", 5, extra)
    assert cols["earn"].tail(4).all() and not cols["earn"].iloc[-5]     # 10-02 is the 2nd session after 09-30
    assert cols["has_div"].tail(5).all() and not cols["has_div"].iloc[-6]


def test_fitted_index_cue_on_the_last_as_of_day():
    """Issue #27: with a fitted beta, the last as-of day of the data keeps its index cue: the session after it comes
    from the exchange calendar, and the cue's return before that session is stored."""
    days = ev.exchange_calendar("XBOM").sessions_in_range("2026-01-01", "2026-10-01")
    rng = np.random.default_rng(3)
    cue_days = ev.exchange_calendar("XNYS").sessions_in_range("2026-01-01", "2026-10-01")
    bench = pd.DataFrame({"open": 100.0, "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))}, index=days)
    cue = pd.DataFrame({"close": 50 * np.exp(np.cumsum(rng.normal(0, 0.01, len(cue_days))))}, index=cue_days)
    cfg = {"market": "india", "calendar": "XBOM", "timezone": "Asia/Kolkata", "index_cue": {"symbol": "SPX", "beta": "fit"},
           "symbols": {"NIFTY50": {"role": "benchmark"}}}
    series = observations.index_cue_series(cfg, {"NIFTY50": bench, "SPX": cue}, {"beta_split": {"fit_sessions": 60}})
    assert series.index[-1] == days[-1] and not np.isnan(series.iloc[-1])   # SPX's 10-01 move, before India's 10-05


def evframe(ticker: str, rows, reps) -> pd.DataFrame:
    t0 = pd.Timestamp("2026-10-05", tz="UTC")
    recs = [{"ticker": ticker, "type": "earnings", "date": d, "timing": tm, "amount": None, "source": src,
             "first_seen_at": t0, "period_end": None} for d, tm, src in rows]
    recs += [{"ticker": ticker, "type": "periodic_report", "date": f, "timing": "after_close", "amount": None,
              "source": "sec_history", "first_seen_at": t0, "period_end": pe} for f, pe in reps]
    return pd.DataFrame(recs)


def test_backtest_uses_the_events_known_at_each_day():
    """backtest.input_columns: each as-of day d sees the 2.02 filings classified with the reports
    accepted by d only."""
    # pre-announcements and deliveries come before the open, both companies' results after the close
    all_rows = sec_rows(ALL_PRE, "before_open") + sec_rows(ALL_RESULTS, "after_close")
    tsla_rows = sec_rows(TSLA_DELIVERIES, "before_open") + sec_rows(TSLA_RESULTS, "after_close")
    evdf = pd.concat([evframe("ALL", all_rows, reports(ALL_REPORTS)),
                      evframe("TSLA", tsla_rows, reports(TSLA_REPORTS))])
    versions = event_history.earnings_versions(evdf)
    assert [s for s, _ in versions["TSLA"]] == [None] + [D(f) for f, _ in TSLA_REPORTS]
    sessions = ev.exchange_calendar("XNYS").sessions_in_range("2023-01-03", "2026-10-02")
    n = len(sessions)
    close = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, n)))
    df = pd.DataFrame({"open": close, "close": close}, index=sessions)
    rc = {**ALL_ON, "ewma_lambda": 0.94, "warmup_bars": 60, "earnings_vol_multiple": 3.0}
    extra = {"earnings": versions, "dividends": {}, "bench": df, "index_cue": None}
    config = {**XNYS, "premarket_quotes": False}
    cols = {t: observations.input_columns(config, rc, df, t, 1, extra) for t in ("ALL", "TSLA")}
    at = lambda t, d: bool(cols[t].loc[pd.Timestamp(d), "earn"])  # noqa: E731
    # Allstate 2023-10-18: the 10-19 pre-announcement is pending as of then (the 10-Q that rules it
    # out comes on 11-01): it counts, as it would have live; a look-ahead replay would say no
    assert at("ALL", "2023-10-18")
    assert at("ALL", "2023-10-31") is False and at("ALL", "2023-11-01")   # release after the close
    # Tesla 2025-10-01: the next day's 2.02 is a delivery report, known as such from history
    assert at("TSLA", "2025-10-01") is False and at("TSLA", "2026-10-01") is False
    assert at("TSLA", "2025-10-22") and at("TSLA", "2025-10-21") is False  # results 10-22 after the close


def test_collector_stores_periodic_reports_and_reader_uses_them(tmp_path, monkeypatch, capsys):
    """collect_events stores 10-Q/10-K acceptances (not amendments) as `periodic_report` rows with
    the period end; read back through DuckDB, the delivery-type 2.02 is no earnings date."""
    fx = tmp_path / "sec"
    fx.mkdir()
    filings = [("8-K", "2.02,9.01", "2026-04-02T13:07:00.000Z", "2026-04-02"),      # deliveries
               ("8-K", "2.02,9.01", "2026-04-22T20:10:00.000Z", "2026-04-22"),      # results, after the close
               ("10-Q", "", "2026-04-23T01:43:00.000Z", "2026-03-31"),
               ("10-K/A", "", "2026-04-30T21:13:00.000Z", "2025-12-31"),            # amendment: not stored
               ("8-K", "5.02", "2026-05-01T20:00:00.000Z", "2026-05-01")]           # not 2.02
    sub = {"name": "Apple", "filings": {"recent": {
        "form": [f[0] for f in filings], "items": [f[1] for f in filings],
        "acceptanceDateTime": [f[2] for f in filings], "reportDate": [f[3] for f in filings]}}}
    (fx / "sub.json").write_text(json.dumps(sub))
    (fx / "urls.json").write_text(json.dumps({
        "https://www.sec.gov/files/company_tickers.json": str(Path(__file__).resolve().parent / "fixtures" / "sec"
                                                              / "company_tickers.json"),
        "https://data.sec.gov/submissions/CIK0000320193.json": "sub.json"}))
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fx))
    monkeypatch.setenv("SEC_USER_AGENT", "market-brief tests test@example.com")
    cfg = {"market": "testsecrep", "name": "Test", "calendar": "XNYS", "timezone": "America/New_York",
           "filings": "sec", "tickers": {"AAPL": {"yahoo": "AAPL", "name": "Apple"}}}
    yf_data = {"AAPL": {"calendar": {"Earnings Date": [date(2026, 10, 29)]}}}
    s = run_events_main(monkeypatch, capsys, tmp_path, cfg, yf_data, date(2026, 10, 5))
    assert s["sec_reports"] == 1 and s["new_history"]["earnings"] == 2 and s["new_events"] == 1
    out = tmp_path / "data" / "testsecrep" / "events" / "2026" / "10" / "2026-10-05.jsonl"
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    rep = [r for r in rows if r["type"] == "periodic_report"]
    assert [(r["id"], r["date"], r["period_end"], r["source"]) for r in rep] == [
        ("AAPL-periodic_report-2026-04-22", "2026-04-22", "2026-03-31", "sec_history")]
    assert rep[0]["accepted_at"] == "2026-04-23T01:43:00+00:00"           # issue #24: the time, for made_at
    assert all("period_end" not in r for r in rows if r["type"] != "periodic_report")
    # second run: nothing new (append-only, ids de-duplicated)
    s = run_events_main(monkeypatch, capsys, tmp_path, cfg, yf_data, date(2026, 10, 5))
    assert s["sec_reports"] == 0 and s["new_history"]["earnings"] == 0
    from marketbrief.core.database import connect
    evdf = event_history.load_events(connect("testsecrep"))
    assert event_history.earnings_events(evdf)["AAPL"] == [(D("2026-04-22"), "after_close"), (D("2026-10-29"), None)]
    assert event_constants.REPORT_FORMS == ("10-Q", "10-K")
