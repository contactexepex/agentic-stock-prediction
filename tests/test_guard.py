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
CUE = 0.02


def jsonl(root: Path, kind: str, day: date, rows: list[dict]) -> None:
    p = common.day_file(MARKET, kind, day)
    with p.open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def quotes(ts: str) -> list[dict]:
    return [{"symbol": t, "yahoo": t, "ts": ts, "price": 1.0, "prev_close": 1.0, "change_pct": CUE,
             "collected_at": ts} for t in ("AAPL", "MSFT")]


@pytest.fixture
def market(tmp_path, monkeypatch):
    root, _ = setup(tmp_path)
    monkeypatch.setattr(common, "ROOT", root)
    days = [AS_OF - timedelta(days=i) for i in range(60) if (AS_OF - timedelta(days=i)).weekday() < 5][::-1]
    write_bars(root, {"AAPL": [150 + i * 0.1 for i in range(len(days))],
                      "MSFT": [300 - i * 0.1 for i in range(len(days))],
                      "BENCH": [100.0] * len(days)}, days)
    feats = [{"id": f"{AS_OF}-{t}", "as_of_date": str(AS_OF), "ticker": t, "computed_at": "2026-10-05T11:00:00+00:00",
              "close": 100.0, "ewma_vol": 0.25, "quality": "OK", "cue_change_pct": CUE, "warnings": []}
             for t in ("AAPL", "MSFT")]
    jsonl(root, "features", AS_OF, feats)
    jsonl(root, "regime", AS_OF, [{"id": str(AS_OF), "as_of_date": str(AS_OF), "session_date": "2026-10-05",
                                   "computed_at": "2026-10-05T11:00:00+00:00", "regime": "CALM"}])
    cfg = {**US, "market": MARKET, "tickers": {"AAPL": {}, "MSFT": {}}}
    rc = common.load_ranges_config()
    return root, cfg, rc


def test_ranges_pre_open_unchanged(market):
    root, cfg, rc = market
    jsonl(root, "quotes", date(2026, 10, 5), quotes("2026-10-05T10:55:00+00:00"))   # pre-market cue
    rows = {r["id"]: r for r in ranges.build(cfg, rc, common.connect(MARKET), "2026-10-05T11:30:00+00:00")}
    assert sorted(rows) == [f"{AS_OF}-{t}-{h}d" for t in ("AAPL", "MSFT") for h in (1, 5)]
    for r in rows.values():
        assert r["notes"] == [f"cue {CUE:+.2%} x{rc['cue_weight']}"]
        assert r["center"] == round(min(rc["cue_weight"] * math.log1p(CUE), rc["max_center_shift_sigma"] * r["sigma_h"]), 6)
    assert rows[f"{AS_OF}-AAPL-1d"]["target_date"] == "2026-10-05"


def test_ranges_late_run_skips_closed_targets_and_late_cues(market):
    root, cfg, rc = market
    jsonl(root, "quotes", date(2026, 10, 5), quotes("2026-10-05T20:25:00+00:00"))   # after the 20:00 close
    rows = ranges.build(cfg, rc, common.connect(MARKET), "2026-10-05T20:40:00+00:00")
    assert sorted(r["id"] for r in rows) == [f"{AS_OF}-AAPL-5d", f"{AS_OF}-MSFT-5d"]   # 1d target closed
    for r in rows:
        assert r["center"] == 0.0
        assert "late: 2026-10-05 closed before made_at" in r["notes"]
        assert "cue ignored: quoted after 2026-10-05 close" in r["notes"]
        assert not any(n.startswith("cue ") and "ignored" not in n for n in r["notes"])


def test_ranges_cue_after_close_ignored_even_if_run_is_on_time(market):
    root, cfg, rc = market
    # a quote stamped after the first target session's close never feeds that session's range
    jsonl(root, "quotes", date(2026, 10, 5), quotes("2026-10-05T20:05:00+00:00"))
    rows = ranges.build(cfg, rc, common.connect(MARKET), "2026-10-05T19:00:00+00:00")
    assert len(rows) == 4
    for r in rows:
        assert r["center"] == 0.0 and r["notes"] == ["cue ignored: quoted after 2026-10-05 close"]


def test_ranges_after_every_target_closed(market):
    _, cfg, rc = market
    assert ranges.build(cfg, rc, common.connect(MARKET), "2026-10-12T21:00:00+00:00") == []
