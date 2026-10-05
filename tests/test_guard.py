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
