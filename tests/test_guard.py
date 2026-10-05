"""Late-run guard: market_status late_run detection and the ranges.py guard against publishing
ranges for a session that had already closed (the 2026-10-05 India run at 20:10 IST)."""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
import events as ev  # noqa: E402
import market_status as ms  # noqa: E402
import ranges  # noqa: E402
from test_pipeline import MARKET, run, setup, write_bars  # noqa: E402

INDIA = {"market": "india", "calendar": "XBOM", "timezone": "Asia/Kolkata"}
US = {"market": "us", "calendar": "XNYS", "timezone": "America/New_York"}


def at(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------- session close and late_run ----------

def test_session_close_utc():
    assert ev.session_close_utc(INDIA, date(2026, 10, 5)) == at("2026-10-05T10:00:00+00:00")   # 15:30 IST
    assert ev.session_close_utc(US, date(2026, 10, 5)) == at("2026-10-05T20:00:00+00:00")      # 16:00 EDT
    assert ev.session_close_utc(US, date(2026, 12, 7)) == at("2026-12-07T21:00:00+00:00")      # 16:00 EST
    assert ev.session_close_utc(US, date(2026, 11, 27)) == at("2026-11-27T18:00:00+00:00")     # early close
    # beyond the calendar's range: the regular local close time
    assert ev.session_close_utc(INDIA, date(2031, 1, 6)) == at("2031-01-06T10:00:00+00:00")
    # no calendar at all: assume 16:00 local
    assert ev.session_close_utc({**INDIA, "calendar": "NOPE"}, date(2026, 10, 5)) == at("2026-10-05T10:30:00+00:00")


@pytest.mark.parametrize("cfg, now, trading, session, late", [
    (INDIA, "2026-10-05T02:40:00+00:00", True, "2026-10-05", False),    # 08:10 IST, pre-open
    (INDIA, "2026-10-05T09:59:00+00:00", True, "2026-10-05", False),    # 15:29 IST, still open
    (INDIA, "2026-10-05T10:00:00+00:00", True, "2026-10-05", True),     # 15:30 IST, the close
    (INDIA, "2026-10-05T14:40:00+00:00", True, "2026-10-05", True),     # 20:10 IST, the incident
    (INDIA, "2026-10-02T14:40:00+00:00", False, "2026-10-05", False),   # Gandhi Jayanti holiday
    (INDIA, "2026-10-03T14:40:00+00:00", False, "2026-10-05", False),   # Saturday
    (US, "2026-10-05T12:00:00+00:00", True, "2026-10-05", False),       # 08:00 ET
    (US, "2026-10-05T20:30:00+00:00", True, "2026-10-05", True),        # 16:30 ET
    (US, "2026-11-26T22:00:00+00:00", False, "2026-11-27", False),      # Thanksgiving
    (US, "2026-11-27T17:30:00+00:00", True, "2026-11-27", False),       # before the 13:00 ET early close
    (US, "2026-11-27T18:30:00+00:00", True, "2026-11-27", True),        # after it
])
def test_late_run(cfg, now, trading, session, late):
    s = ms.status(cfg, at(now))
    assert (s["trading_day"], s["session_date"], s["late_run"]) == (trading, session, late)
    assert at(s["session_close_utc"]) == ev.session_close_utc(cfg, date.fromisoformat(session))


def test_market_status_cli_now(tmp_path):
    root, cfg = setup(tmp_path)
    late = json.loads(run("market_status.py", root, cfg, "--now", "2026-10-05T20:30:00+00:00").stdout)
    early = json.loads(run("market_status.py", root, cfg, "--now", "2026-10-05T08:00:00-04:00").stdout)
    assert late["late_run"] is True and early["late_run"] is False
    assert late["session_close_utc"] == early["session_close_utc"] == "2026-10-05T20:00:00+00:00"
    assert run("market_status.py", root, cfg, "--now", "2026-10-05T20:30:00").returncode != 0  # needs an offset




# ---------- ranges guard ----------

AS_OF = date(2026, 10, 2)        # Friday; first target session Monday 2026-10-05 closes 20:00 UTC
DAY = date(2026, 10, 5)
CUE = 0.02
ALL = [f"{AS_OF}-{t}-{h}d" for t in ("AAPL", "MSFT") for h in (1, 5)]


def jsonl(root: Path, kind: str, day: date, rows: list[dict]) -> None:
    p = common.day_file(MARKET, kind, day)
    with p.open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def quotes(root: Path, ts: str) -> None:
    """Quotes stamped and collected at ts (as collect_quotes.py does on each run)."""
    jsonl(root, "quotes", DAY, [{"symbol": t, "yahoo": t, "ts": ts, "price": 1.0, "prev_close": 1.0,
                                 "change_pct": CUE, "collected_at": ts} for t in ("AAPL", "MSFT")])


def snapshot(root: Path, computed_at: str) -> None:
    """The features.py snapshot (its cue came from the latest quote collected before computed_at)."""
    jsonl(root, "features", AS_OF, [
        {"id": f"{AS_OF}-{t}", "as_of_date": str(AS_OF), "ticker": t, "computed_at": computed_at,
         "close": 100.0, "ewma_vol": 0.25, "quality": "OK", "cue_change_pct": CUE, "warnings": []}
        for t in ("AAPL", "MSFT")])


@pytest.fixture
def market(tmp_path, monkeypatch):
    root, cfg_dir = setup(tmp_path)
    monkeypatch.setattr(common, "ROOT", root)
    days = [AS_OF - timedelta(days=i) for i in range(60) if (AS_OF - timedelta(days=i)).weekday() < 5][::-1]
    write_bars(root, {"AAPL": [150 + i * 0.1 for i in range(len(days))],
                      "MSFT": [300 - i * 0.1 for i in range(len(days))],
                      "BENCH": [100.0] * len(days)}, days)
    jsonl(root, "regime", AS_OF, [{"id": str(AS_OF), "as_of_date": str(AS_OF), "session_date": str(DAY),
                                   "computed_at": "2026-10-05T11:00:00+00:00", "regime": "CALM"}])
    cfg = {**US, "market": MARKET, "tickers": {"AAPL": {}, "MSFT": {}}}
    return root, cfg_dir, cfg, common.load_ranges_config()


def build(cfg, rc, now: str) -> dict[str, dict]:
    return {r["id"]: r for r in ranges.build(cfg, rc, common.connect(MARKET), now)}


def assert_cue_applied(rows: dict, rc: dict) -> None:
    for r in rows.values():
        assert f"cue {CUE:+.2%} x{rc['cue_weight']}" in r["notes"]
        assert not any("cue ignored" in n for n in r["notes"])
        cap = rc["max_center_shift_sigma"] * r["sigma_h"]
        assert r["center"] == round(min(rc["cue_weight"] * math.log1p(CUE), cap), 6) > 0


def test_ranges_pre_open_unchanged(market):
    root, _, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")                 # pre-market cue
    snapshot(root, "2026-10-05T11:00:00+00:00")
    rows = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    assert sorted(rows) == ALL
    assert all(r["notes"] == [f"cue {CUE:+.2%} x{rc['cue_weight']}"] for r in rows.values())
    assert_cue_applied(rows, rc)
    assert rows[f"{AS_OF}-AAPL-1d"]["target_date"] == str(DAY)


def test_ranges_late_run_skips_closed_targets_and_late_cues(market):
    root, _, cfg, rc = market
    quotes(root, "2026-10-05T20:25:00+00:00")                 # after the 20:00 close
    snapshot(root, "2026-10-05T20:30:00+00:00")
    rows = build(cfg, rc, "2026-10-05T20:40:00+00:00")
    assert sorted(rows) == [f"{AS_OF}-AAPL-5d", f"{AS_OF}-MSFT-5d"]   # the 1d target closed
    for r in rows.values():
        assert r["center"] == 0.0
        assert r["notes"] == ["late: 2026-10-05 closed before made_at", "cue ignored: quoted after 2026-10-05 close"]


def test_ranges_keep_the_cue_features_used_when_quotes_are_recollected(market):
    root, _, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")                 # the cue features.py used
    snapshot(root, "2026-10-05T11:00:00+00:00")
    quotes(root, "2026-10-05T20:25:00+00:00")                 # re-collected after the close
    assert_cue_applied(build(cfg, rc, "2026-10-05T11:30:00+00:00"), rc)
    late = build(cfg, rc, "2026-10-05T20:40:00+00:00")        # still the pre-close cue, but late
    assert sorted(late) == [f"{AS_OF}-AAPL-5d", f"{AS_OF}-MSFT-5d"]
    assert_cue_applied(late, rc)
    assert all("late: 2026-10-05 closed before made_at" in r["notes"] for r in late.values())


def test_ranges_after_every_target_closed(market):
    root, _, cfg, rc = market
    snapshot(root, "2026-10-05T11:00:00+00:00")
    assert build(cfg, rc, "2026-10-12T21:00:00+00:00") == {}


def test_ranges_cli_late_flag(market):
    root, cfg_dir, _, _ = market
    snapshot(root, "2026-10-05T11:00:00+00:00")
    out = json.loads(run("ranges.py", root, cfg_dir, "--now", "2026-10-12T21:00:00+00:00").stdout)
    assert (out["written"], out["late"]) == (0, True)          # late even though nothing was written
    out = json.loads(run("ranges.py", root, cfg_dir, "--now", "2026-10-05T20:40:00+00:00").stdout)
    assert (out["written"], out["late"]) == (2, True)
    out = json.loads(run("ranges.py", root, cfg_dir, "--now", "2026-10-05T11:30:00+00:00").stdout)
    assert (out["written"], out["late"]) == (2, False)         # the 5d ids were already written
    rows = [json.loads(x) for f in (root / "data" / MARKET / "ranges").glob("**/*.jsonl")
            for x in f.read_text().splitlines()]
    assert {r["made_at"] for r in rows} == {"2026-10-05T20:40:00+00:00", "2026-10-05T11:30:00+00:00"}
    assert run("ranges.py", root, cfg_dir, "--now", "2026-10-05T11:30:00").returncode != 0   # needs an offset


# ---------- scoring never counts late records ----------

def test_scoring_skips_records_made_after_the_first_session_closed(market):
    """A range or call made at/after the close of the first session after as_of (DAY closes
    20:00 UTC) already knew part of its outcome: it is never scored. On-time ones are."""
    root, cfg_dir, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")
    snapshot(root, "2026-10-05T11:00:00+00:00")
    rows = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    for r in rows.values():                                     # MSFT published late, AAPL on time
        if r["ticker"] == "MSFT":
            r["made_at"] = "2026-10-05T20:40:00+00:00"
    jsonl(root, "ranges", AS_OF, list(rows.values()))
    jsonl(root, "predictions", AS_OF, [
        {"id": f"{AS_OF}-{t}-1d", "made_at": made, "as_of_date": str(AS_OF), "ticker": t, "horizon_days": 1,
         "direction": "up", "confidence": 0.6, "rationale": "test", "evidence_ids": ["x"],
         "prompt_version": "test"}
        for t, made in (("AAPL", "2026-10-05T11:30:00+00:00"), ("MSFT", "2026-10-05T20:00:00+00:00"))])
    days = [AS_OF - timedelta(days=i) for i in range(60) if (AS_OF - timedelta(days=i)).weekday() < 5][::-1]
    write_bars(root, {"AAPL": [150 + i * 0.1 for i in range(len(days) + 1)],
                      "MSFT": [300 - i * 0.1 for i in range(len(days) + 1)],
                      "BENCH": [100.0] * (len(days) + 1)}, days + [DAY])
    r = run("score_predictions.py", root, cfg_dir)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["late_skipped"] == {"calls": 1, "ranges": 1}       # MSFT 1d call (made at the close) and range
    assert (out["scored"], out["ranges_scored"]) == (1, 1)         # AAPL only; 5d targets have no bar yet
    con = common.connect(MARKET)
    assert [x for (x,) in con.execute("SELECT prediction_id FROM outcomes").fetchall()] == [f"{AS_OF}-AAPL-1d"]
    assert [x for (x,) in con.execute("SELECT range_id FROM range_outcomes").fetchall()] == [f"{AS_OF}-AAPL-1d"]
    again = json.loads(run("score_predictions.py", root, cfg_dir).stdout)  # late ones are not "open" either
    assert (again["scored"], again["ranges_scored"], again["still_open"]) == (0, 0, 0)


def test_report_labels_late_ranges_and_links_the_review(market):
    root, cfg_dir, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")
    snapshot(root, "2026-10-05T11:00:00+00:00")
    rows = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    for r in rows.values():
        if r["ticker"] == "MSFT":
            r["made_at"] = "2026-10-05T20:40:00+00:00"            # after DAY's 20:00 UTC close
    jsonl(root, "ranges", AS_OF, list(rows.values()))
    jsonl(root, "regime", AS_OF, [{"id": str(AS_OF), "as_of_date": str(AS_OF), "session_date": str(DAY),
                                   "computed_at": "2026-10-05T11:05:00+00:00", "regime": "CALM",
                                   "vol_level": 15.0, "vol_change_1d": 0.0, "bench_ret_5d": 0.0,
                                   "bench_vol_10d": 0.1, "major_event": False, "major_event_names": [],
                                   "stress": False, "notes": []}])
    r = run("report.py", root, cfg_dir, "--force")
    assert r.returncode == 0, r.stderr
    text = (root / "reports" / MARKET / f"{DAY}.md").read_text()
    line = {t: next(x for x in text.splitlines() if x.startswith(f"| {t} |")) for t in ("AAPL", "MSFT")}
    assert "late: not a forecast, never scored" in line["MSFT"]
    assert line["MSFT"].split(" | ")[7] == "–"                   # cue blanked on the late row
    assert line["AAPL"].split(" | ")[7] != "–"
    assert "late:" not in line["AAPL"]
    assert "1 stock(s) have ranges made after the session they target had closed" in text
    import report
    assert report.md_link("review-2026-W40.md") == "[review-2026-W40.md](review-2026-W40.md)"


def test_context_pack_labels_late_ranges(market):
    root, cfg_dir, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")
    snapshot(root, "2026-10-05T11:00:00+00:00")
    rows = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    for r in rows.values():
        if r["ticker"] == "MSFT":
            r["made_at"] = "2026-10-05T20:40:00+00:00"
    jsonl(root, "ranges", AS_OF, list(rows.values()))
    r = run("context.py", root, cfg_dir)
    assert r.returncode == 0, r.stderr
    sec = r.stdout.split("## Price ranges published", 1)[1].split("\n## ", 1)[0]
    lines = [x for x in sec.splitlines() if x.startswith("| AAPL") or x.startswith("| MSFT")]
    assert len(lines) == 4
    assert all(x.rstrip(" |").endswith("late: not a forecast, never scored") == x.startswith("| MSFT") for x in lines)


# ---------- mid-session runs (issue #7): the 1-day target session has opened ----------

def test_session_open_utc():
    assert ev.session_open_utc(INDIA, date(2026, 10, 5)) == at("2026-10-05T03:45:00+00:00")     # 09:15 IST
    assert ev.session_open_utc(US, date(2026, 10, 5)) == at("2026-10-05T13:30:00+00:00")        # 09:30 EDT
    assert ev.session_open_utc(US, date(2026, 12, 7)) == at("2026-12-07T14:30:00+00:00")        # 09:30 EST
    assert ev.session_open_utc(US, date(2026, 11, 27)) == at("2026-11-27T14:30:00+00:00")       # early-close day
    # beyond the calendar's range: the regular local open time
    assert ev.session_open_utc(INDIA, date(2031, 1, 6)) == at("2031-01-06T03:45:00+00:00")
    # no calendar at all: assume 09:30 local
    assert ev.session_open_utc({**INDIA, "calendar": "NOPE"}, date(2026, 10, 5)) == at("2026-10-05T04:00:00+00:00")


@pytest.mark.parametrize("cfg, now, trading, session, in_session, late", [
    (INDIA, "2026-10-05T02:40:00+00:00", True, "2026-10-05", False, False),   # 08:10 IST routine
    (INDIA, "2026-10-05T03:44:59+00:00", True, "2026-10-05", False, False),   # just before the open
    (INDIA, "2026-10-05T03:45:00+00:00", True, "2026-10-05", True, False),    # the open
    (INDIA, "2026-10-05T09:59:59+00:00", True, "2026-10-05", True, False),
    (INDIA, "2026-10-05T10:00:00+00:00", True, "2026-10-05", False, True),    # the close
    (INDIA, "2026-10-02T05:00:00+00:00", False, "2026-10-05", False, False),  # Gandhi Jayanti, mid-day
    (US, "2026-10-05T12:15:00+00:00", True, "2026-10-05", False, False),      # 08:15 ET routine
    (US, "2026-10-05T13:30:00+00:00", True, "2026-10-05", True, False),
    (US, "2026-11-26T15:00:00+00:00", False, "2026-11-27", False, False),     # Thanksgiving, mid-day
    (US, "2026-11-27T17:59:00+00:00", True, "2026-11-27", True, False),       # before the 13:00 ET early close
    (US, "2026-11-27T18:00:00+00:00", True, "2026-11-27", False, True),       # the early close
])
def test_in_session(cfg, now, trading, session, in_session, late):
    s = ms.status(cfg, at(now))
    assert (s["trading_day"], s["session_date"], s["in_session"], s["late_run"]) == (trading, session, in_session, late)
    assert at(s["session_open_utc"]) == ev.session_open_utc(cfg, date.fromisoformat(session))


def test_is_late_by_horizon():
    from score_predictions import is_late
    assert not is_late(US, AS_OF, "2026-10-05T13:29:59+00:00", 1)
    assert is_late(US, AS_OF, "2026-10-05T13:30:00+00:00", 1)                 # 1 day: from the open
    assert not is_late(US, AS_OF, "2026-10-05T19:59:59+00:00", 5)             # 5 days: from the close
    assert is_late(US, AS_OF, "2026-10-05T20:00:00+00:00", 5)
    assert not is_late(US, AS_OF, "2026-10-05T13:30:00+00:00")                # no horizon: the close
    wed = date(2026, 11, 25)                                                    # next session Fri 27 (early close)
    assert not is_late(US, wed, "2026-11-26T15:00:00+00:00", 1)               # Thanksgiving mid-day
    assert is_late(US, wed, "2026-11-27T14:30:00+00:00", 1)
    assert not is_late(US, wed, "2026-11-27T17:59:00+00:00", 5)
    assert is_late(US, wed, "2026-11-27T18:00:00+00:00", 5)


def test_ranges_mid_session_publishes_5d_only_and_unchanged(market):
    root, _, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")                 # pre-market cue
    snapshot(root, "2026-10-05T11:00:00+00:00")
    pre = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    assert sorted(build(cfg, rc, "2026-10-05T13:29:59+00:00")) == ALL
    mid = build(cfg, rc, "2026-10-05T13:30:00+00:00")         # the open
    assert sorted(mid) == [f"{AS_OF}-AAPL-5d", f"{AS_OF}-MSFT-5d"]
    for rid, r in mid.items():                                 # 5d: same as before the open
        assert r == {**pre[rid], "made_at": "2026-10-05T13:30:00+00:00"}
    assert sorted(build(cfg, rc, "2026-10-05T19:59:00+00:00")) == sorted(mid)


def test_ranges_1d_ignores_a_cue_quoted_after_the_open(market):
    root, _, cfg, rc = market
    quotes(root, "2026-10-05T13:40:00+00:00")                 # an intraday quote, not an overnight cue
    snapshot(root, "2026-10-05T13:45:00+00:00")
    rows = build(cfg, rc, "2026-10-05T13:29:00+00:00")        # replay with made_at before the open
    for t in ("AAPL", "MSFT"):
        one, five = rows[f"{AS_OF}-{t}-1d"], rows[f"{AS_OF}-{t}-5d"]
        assert one["notes"] == ["cue ignored: quoted after 2026-10-05 open"] and one["center"] == 0.0
        assert five["notes"] == [f"cue {CUE:+.2%} x{rc['cue_weight']}"] and five["center"] > 0


def test_ranges_index_cue_cut_by_horizon(market):
    root, _, cfg, rc = market
    cfg = {**cfg, "index_cue": {"symbol": "BENCH", "beta": 1.0}}
    rc = {**rc, "beta_split": {**rc["beta_split"], "enabled": {MARKET: [1, 5]}}}
    jsonl(root, "quotes", DAY, [{"symbol": "BENCH", "yahoo": "BENCH", "ts": "2026-10-05T13:40:00+00:00",
                                 "price": 1.0, "prev_close": 1.0, "change_pct": 0.01,
                                 "collected_at": "2026-10-05T13:40:00+00:00"}])
    snapshot(root, "2026-10-05T13:45:00+00:00")
    jsonl(root, "regime", AS_OF, [{"id": str(AS_OF), "as_of_date": str(AS_OF), "session_date": str(DAY),
                                   "computed_at": "2026-10-05T13:45:00+00:00", "regime": "CALM"}])
    rows = build(cfg, rc, "2026-10-05T13:29:00+00:00")
    assert "index cue ignored: BENCH quoted after 2026-10-05 open" in rows[f"{AS_OF}-AAPL-1d"]["notes"]
    assert not any("index cue ignored" in n for n in rows[f"{AS_OF}-AAPL-5d"]["notes"])


def test_ranges_option_snapshot_after_the_open_never_reaches_a_1d_range(market):
    root, _, cfg, rc = market
    cfg = {**cfg, "options": "yfinance"}
    quotes(root, "2026-10-05T10:55:00+00:00")
    snapshot(root, "2026-10-05T11:00:00+00:00")
    jsonl(root, "options", DAY, [{"id": f"{DAY}-AAPL-2026-10-16", "ticker": "AAPL", "collected_at":
                                  "2026-10-05T13:40:00+00:00", "expiry": "2026-10-16", "days_to_expiry": 11,
                                  "spot": 150, "strike": 150, "call_iv": 0.6, "put_iv": 0.6, "atm_iv": 0.6,
                                  "straddle": 8, "straddle_pct": 0.053, "source": "yfinance"}])
    before = build(cfg, rc, "2026-10-05T13:29:00+00:00")      # pre-open: the snapshot is not known yet
    assert before[f"{AS_OF}-AAPL-1d"]["iv_sigma_h"] is None and before[f"{AS_OF}-AAPL-5d"]["iv_sigma_h"] is None
    after = build(cfg, rc, "2026-10-05T13:45:00+00:00")       # mid-session: no 1d range; 5d may use it
    assert sorted(after) == [f"{AS_OF}-AAPL-5d", f"{AS_OF}-MSFT-5d"]
    assert after[f"{AS_OF}-AAPL-5d"]["iv_sigma_h"] is not None


def test_ranges_holiday_and_early_close(market):
    """As of Wed 2026-11-25 the first target is Fri 11-27 (Thanksgiving in between; 13:00 ET early
    close = 18:00 UTC, open 14:30 UTC)."""
    root, _, cfg, rc = market
    wed, thu = date(2026, 11, 25), date(2026, 11, 26)
    jsonl(root, "regime", wed, [{"id": str(wed), "as_of_date": str(wed), "session_date": "2026-11-27",
                                 "computed_at": "2026-11-26T15:00:00+00:00", "regime": "CALM"}])
    jsonl(root, "quotes", thu, [{"symbol": t, "yahoo": t, "ts": "2026-11-26T14:55:00+00:00", "price": 1.0,
                                 "prev_close": 1.0, "change_pct": CUE, "collected_at": "2026-11-26T14:55:00+00:00"}
                                for t in ("AAPL", "MSFT")])
    jsonl(root, "features", wed, [
        {"id": f"{wed}-{t}", "as_of_date": str(wed), "ticker": t, "computed_at": "2026-11-26T15:00:00+00:00",
         "close": 100.0, "ewma_vol": 0.25, "quality": "OK", "cue_change_pct": CUE, "warnings": []}
        for t in ("AAPL", "MSFT")])
    holiday = build(cfg, rc, "2026-11-26T15:05:00+00:00")     # mid-day, but the exchange is closed
    assert sorted(holiday) == [f"{wed}-{t}-{h}d" for t in ("AAPL", "MSFT") for h in (1, 5)]
    assert holiday[f"{wed}-AAPL-1d"]["target_date"] == "2026-11-27"
    assert holiday[f"{wed}-AAPL-1d"]["notes"] == [f"cue {CUE:+.2%} x{rc['cue_weight']}"]
    assert sorted(build(cfg, rc, "2026-11-27T14:29:00+00:00")) == sorted(holiday)
    opened = build(cfg, rc, "2026-11-27T14:30:00+00:00")
    assert sorted(opened) == [f"{wed}-AAPL-5d", f"{wed}-MSFT-5d"]
    assert all("late:" not in " ".join(r["notes"]) for r in opened.values())
    closed = build(cfg, rc, "2026-11-27T18:00:00+00:00")      # the early close
    assert sorted(closed) == sorted(opened)
    assert all("late: 2026-11-27 closed before made_at" in r["notes"] for r in closed.values())


def test_context_and_report_label_a_mid_session_1d_range_late(market):
    """An old-code range row for 1 day made after the open (14:00 UTC) is labelled late, the 5-day
    one made then is not."""
    root, cfg_dir, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")
    snapshot(root, "2026-10-05T11:00:00+00:00")
    rows = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    for r in rows.values():
        r["made_at"] = "2026-10-05T14:00:00+00:00"
    jsonl(root, "ranges", AS_OF, [r for r in rows.values() if r["ticker"] == "AAPL" or r["horizon_days"] == 5])
    r = run("context.py", root, cfg_dir)
    assert r.returncode == 0, r.stderr
    sec = r.stdout.split("## Price ranges published", 1)[1].split("\n## ", 1)[0]
    late = {" | ".join(x.split(" | ")[:2]): x.rstrip(" |").endswith("late: not a forecast, never scored")
            for x in sec.splitlines() if x.startswith("| AAPL") or x.startswith("| MSFT")}
    assert late == {"| AAPL | 1": True, "| AAPL | 5": False, "| MSFT | 5": False}
    jsonl(root, "regime", AS_OF, [{"id": str(AS_OF), "as_of_date": str(AS_OF), "session_date": str(DAY),
                                   "computed_at": "2026-10-05T11:05:00+00:00", "regime": "CALM",
                                   "vol_level": 15.0, "vol_change_1d": 0.0, "bench_ret_5d": 0.0,
                                   "bench_vol_10d": 0.1, "major_event": False, "major_event_names": [],
                                   "stress": False, "notes": []}])
    r = run("report.py", root, cfg_dir, "--force")
    assert r.returncode == 0, r.stderr
    text = (root / "reports" / MARKET / f"{DAY}.md").read_text()
    line = {t: next(x for x in text.splitlines() if x.startswith(f"| {t} |")) for t in ("AAPL", "MSFT")}
    assert "late: not a forecast, never scored" in line["AAPL"] and "late:" not in line["MSFT"]
    assert "1 stock(s) have ranges made after the session they target had closed (a late run; " \
           "for a next-day range, after it had opened)" in text


def test_ranges_cli_in_session_flag(market):
    root, cfg_dir, _, _ = market
    snapshot(root, "2026-10-05T11:00:00+00:00")
    out = json.loads(run("ranges.py", root, cfg_dir, "--now", "2026-10-05T14:00:00+00:00").stdout)
    assert (out["written"], out["late"], out["in_session"]) == (2, False, True)
    out = json.loads(run("ranges.py", root, cfg_dir, "--now", "2026-10-05T11:30:00+00:00").stdout)
    assert (out["written"], out["late"], out["in_session"]) == (2, False, False)   # 1d ids now; 5d already written
    out = json.loads(run("ranges.py", root, cfg_dir, "--now", "2026-10-05T20:30:00+00:00").stdout)
    assert (out["late"], out["in_session"]) == (True, False)


def test_scoring_skips_1d_records_made_after_the_open(market):
    """1-day range and call made mid-session (14:00 UTC, after the 13:30 open) are never scored;
    the 5-day range made at the same time is not late (its cut-off is the close)."""
    root, cfg_dir, cfg, rc = market
    quotes(root, "2026-10-05T10:55:00+00:00")
    snapshot(root, "2026-10-05T11:00:00+00:00")
    rows = build(cfg, rc, "2026-10-05T11:30:00+00:00")
    for r in rows.values():
        if r["ticker"] == "MSFT":
            r["made_at"] = "2026-10-05T14:00:00+00:00"            # as an old mid-session run wrote it
    jsonl(root, "ranges", AS_OF, list(rows.values()))
    jsonl(root, "predictions", AS_OF, [
        {"id": f"{AS_OF}-{t}-1d", "made_at": made, "as_of_date": str(AS_OF), "ticker": t, "horizon_days": 1,
         "direction": "up", "confidence": 0.6, "rationale": "test", "evidence_ids": ["x"],
         "prompt_version": "test"}
        for t, made in (("AAPL", "2026-10-05T11:30:00+00:00"), ("MSFT", "2026-10-05T14:00:00+00:00"))])
    days = [AS_OF - timedelta(days=i) for i in range(60) if (AS_OF - timedelta(days=i)).weekday() < 5][::-1]
    write_bars(root, {"AAPL": [150 + i * 0.1 for i in range(len(days) + 1)],
                      "MSFT": [300 - i * 0.1 for i in range(len(days) + 1)],
                      "BENCH": [100.0] * (len(days) + 1)}, days + [DAY])
    r = run("score_predictions.py", root, cfg_dir)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["late_skipped"] == {"calls": 1, "ranges": 1}       # MSFT 1d call and range
    assert (out["scored"], out["ranges_scored"]) == (1, 1)         # AAPL 1d; 5d targets have no bar yet
    assert out["ranges_open"] == 2                                 # both 5d ranges, MSFT's included
    con = common.connect(MARKET)
    assert [x for (x,) in con.execute("SELECT range_id FROM range_outcomes").fetchall()] == [f"{AS_OF}-AAPL-1d"]
    assert [x for (x,) in con.execute("SELECT prediction_id FROM outcomes").fetchall()] == [f"{AS_OF}-AAPL-1d"]
