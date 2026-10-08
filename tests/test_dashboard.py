"""The decision-support dashboard (scripts/dashboard.py, marketbrief/presentation/dashboard/): its numbers equal
the source views, nothing stored after the cut-off or dated after the as-of reaches it, empty data still builds,
the page is self-contained, the vendored library matches its pinned SHA-256, and the Slack thread attaches it.

The data is a copy of the repo's stored US data (append-only, so rows stored by the fixed cut-off never change),
plus synthetic rows: scored calls and ranges before the cut-off, and rows of every kind after it."""

from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
import notify_slack as ns  # noqa: E402
from marketbrief.analytics import scoring  # noqa: E402
from marketbrief.constants.dashboard import MSG_PAPER_ONLY, MSG_SKILL_SHOWN  # noqa: E402
from marketbrief.core import database  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.pipeline.evidence_status import EvidenceStatuses  # noqa: E402
from marketbrief.presentation.dashboard import cli as dash_cli  # noqa: E402
from marketbrief.presentation.dashboard import model_info, page  # noqa: E402
from marketbrief.presentation.dashboard.assemble import gather_dashboard  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CUTOFF = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)
LATER = "2026-10-07T20:00:00+00:00"
LATE_NEWS = "feedfacefeedface"


def own_kind(root: Path, kind: str) -> None:
    """Replace the kind's files linked to the repo's data/us (data_tree) by copies before anything is written to it."""
    folder = root / "data" / "us" / kind
    folder.mkdir(parents=True, exist_ok=True)
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            content = path.read_bytes()
            path.unlink()
            path.write_bytes(content)


def append(root: Path, kind: str, day: str, rows: list[dict]) -> None:
    own_kind(root, kind)
    path = root / "data" / "us" / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def scored_rows(root: Path) -> None:
    """Calls on both scoring bases and ranges, all scored before the cut-off, one range scored after it."""
    preds, outs = [], []
    for i, (basis, hit, ret) in enumerate(
        [
            ("close_to_close", True, 0.01),
            ("close_to_close", False, -0.02),
            ("open_to_close", True, 0.004),
            ("open_to_close", True, -0.001),
            ("open_to_close", False, 0.003),
        ]
    ):
        pid = f"2026-09-2{i}-JPM-1d"
        preds.append(
            {
                "id": pid,
                "made_at": f"2026-09-2{i}T08:00:00+00:00",
                "as_of_date": f"2026-09-2{i}",
                "ticker": "JPM",
                "horizon_days": 1,
                "direction": "up",
                "confidence": 0.55 + 0.05 * i,
                "evidence_ids": [],
                "prompt_version": "test",
            }
        )
        outs.append(
            {
                "prediction_id": pid,
                "scored_at": "2026-10-01T21:00:00+00:00",
                "target_date": "2026-09-30",
                "actual_return": ret,
                "hit": hit,
                "label_basis": basis,
            }
        )
    append(root, "predictions", "2026-09-29", preds)
    append(root, "outcomes", "2026-10-01", outs)
    ranges, routs = [], []
    for h, hit50, hit80, scored in (
        (1, True, True, "2026-10-02T21:00:00+00:00"),
        (5, False, True, "2026-10-02T21:00:00+00:00"),
        (1, False, False, LATER),
    ):
        rid = f"2026-10-0{1 if scored != LATER else 2}-JPM-{h}d"
        ranges.append(
            {
                "id": rid,
                "made_at": "2026-10-01T09:00:00+00:00",
                "as_of_date": rid[:10],
                "ticker": "JPM",
                "horizon_days": h,
                "base_close": 100.0,
                "lo50": 98.0,
                "hi50": 102.0,
                "lo80": 96.0,
                "hi80": 104.0,
                "target_date": "2026-10-02",
                "notes": [],
                "inputs": [],
            }
        )
        routs.append(
            {
                "range_id": rid,
                "scored_at": scored,
                "target_date": "2026-10-02",
                "actual_close": 101.0,
                "hit50": hit50,
                "hit80": hit80,
            }
        )
    # an N+1 range (decision 37, horizon_label n_plus_k) scored on the same date: never pooled with the old 1-day
    ranges.append(
        {
            **ranges[0],
            "id": "2026-09-30-JPM-1d",
            "as_of_date": "2026-09-30",
            "horizon_label": "n_plus_k",
            "entry_date": "2026-10-01",
            "exit_date": "2026-10-02",
        }
    )
    routs.append({**routs[0], "range_id": "2026-09-30-JPM-1d", "hit80": False})
    append(root, "ranges", "2026-10-01", ranges)
    append(root, "range_outcomes", "2026-10-02", routs)
    # an old open-to-close 5-day call (D+4 window, legacy_5d_d4): its own basis key, never pooled with N+k calls
    append(root, "predictions", "2026-09-29", [{**preds[2], "id": "2026-09-22-JPM-5d", "horizon_days": 5}])
    append(
        root,
        "outcomes",
        "2026-10-01",
        [{**outs[2], "prediction_id": "2026-09-22-JPM-5d", "horizon_label": "legacy_5d_d4"}],
    )


def n_plus_k_rows(root: Path) -> None:
    """N+2 and N+3 ranges and model scores of the as-of date (B10 rows: horizon_label, entry and exit dates)."""
    for h, exit_day in ((2, "2026-10-09"), (3, "2026-10-12")):
        window = {"horizon_label": "n_plus_k", "entry_date": "2026-10-07", "exit_date": exit_day}
        append(
            root,
            "ranges",
            "2026-10-06",
            [
                {
                    "id": f"2026-10-06-JPM-{h}d",
                    "made_at": "2026-10-06T22:00:00+00:00",
                    "as_of_date": "2026-10-06",
                    "session_date": "2026-10-07",
                    "ticker": "JPM",
                    "horizon_days": h,
                    "base_close": 300.0,
                    "center": 0.0,
                    "lo50": 295.0,
                    "hi50": 305.0,
                    "lo80": 290.0,
                    "hi80": 310.0,
                    "target_date": exit_day,
                    "notes": [],
                    "inputs": [],
                    **window,
                }
            ],
        )
        append(
            root,
            "model_scores",
            "2026-10-06",
            [
                {
                    "id": f"2026-10-06-JPM-{h}d",
                    "as_of_date": "2026-10-06",
                    "ticker": "JPM",
                    "horizon_days": h,
                    "prob_up": 0.52,
                    "prob_model": 0.52,
                    "base_rate": 0.5,
                    "calibrated": False,
                    "label_convention": "open_to_close",
                    "trained_until": "2026-09-30",
                    "computed_at": "2026-10-06T22:00:00+00:00",
                    "model_id": f"test-{h}d",
                    "contributions": {"groups": {"baseline": 0.0}},
                    **window,
                }
            ],
        )


def earlier_adjustment(root: Path) -> None:
    """A split record detected before the cut-off: the page applies it, as the ohlc view does."""
    split = {
        "id": "BAC-test",
        "ticker": "BAC",
        "ex_date": "2026-09-01",
        "factor": 0.5,
        "detected_at": "2026-10-01T06:00:00+00:00",
    }
    append(root, "adjustments", "2026-10-01", [split])


def later_rows(root: Path) -> None:
    """One row of each kind stored after the cut-off: none of them may reach the page."""
    append(
        root,
        "features",
        "2026-10-07",
        [
            {
                "id": "2026-10-07-JPM",
                "as_of_date": "2026-10-07",
                "ticker": "JPM",
                "computed_at": LATER,
                "close": 999.0,
                "rsi_14": 99.0,
                "quality": "OK",
            }
        ],
    )
    append(
        root,
        "model_scores",
        "2026-10-07",
        [
            {
                "id": "2026-10-06-JPM-1d",
                "as_of_date": "2026-10-06",
                "ticker": "JPM",
                "horizon_days": 1,
                "prob_up": 0.99,
                "computed_at": LATER,
                "model_id": "later",
                "contributions": {},
            }
        ],
    )
    append(
        root,
        "agent_reasoning",
        "2026-10-07",
        [
            {
                "id": "2026-10-06-JPM",
                "as_of_date": "2026-10-06",
                "ticker": "JPM",
                "bull_case": "LATER BULL",
                "bear_case": "x",
                "verdict": "x",
                "written_at": LATER,
                "made_at": LATER,
            }
        ],
    )
    append(
        root,
        "news",
        "2026-10-07",
        [
            {
                "id": LATE_NEWS,
                "title": "Later JPM news",
                "url": "https://example.com/x",
                "source": "Test",
                "published_at": "2026-10-07T04:00:00+00:00",
                "first_seen_at": LATER,
                "tickers": ["JPM"],
            }
        ],
    )
    append(root, "reviews", "2026-10-07", [{"id": "2026-W41", "computed_at": LATER, "model_skill": True, "detail": {}}])
    append(root, "replays", "2026-10-07", [{"id": "later", "computed_at": LATER, "n_days": 5}])
    own_kind(root, "prices")
    prices = root / "data" / "us" / "prices" / "2026" / "10" / "2026-10-07.csv"
    # CRLF line ends as collect_prices.py writes them (DuckDB's multi-file reader skips a file whose ends differ)
    prices.write_bytes(
        b"date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n"
        + f"2026-10-07,JPM,500.0,510.0,490.0,505.0,505.0,1000,{LATER}\r\n".encode()
        + f"2026-10-05,JPM,700.0,710.0,690.0,705.0,705.0,1000,{LATER}\r\n".encode()  # a past bar re-collected later
    )
    later = {"id": "JPM-later", "ticker": "JPM", "ex_date": "2026-10-07", "factor": 0.5, "detected_at": LATER}
    append(root, "adjustments", "2026-10-07", [later])
    next_quarter = {
        "id": "JPM-next-q",
        "date": "2027-01-14",
        "type": "earnings",
        "ticker": "JPM",
        "name": "JPM earnings",
        "source": "yahoo",
        "first_seen_at": "2026-10-14T05:00:00+00:00",
    }
    append(root, "events", "2026-10-14", [next_quarter])


# The stored data the checks were written against: day files named after this date are left out, so a later
# routine commit to data/us never changes what the fixture sees (every stored file is named <YYYY-MM-DD>.<ext>)
DATA_SNAPSHOT_DAY = "2026-10-07"


def data_tree(root: Path) -> None:
    """root/data/us with every stored day file up to DATA_SNAPSHOT_DAY linked to the repo's file, read only; a kind's
    files are copied the first time the fixture writes to it (own_kind). Issue #48: the fixture copied all of
    data/us, about 12 MB, at every run."""
    source = REPO / "data" / "us"
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.stem <= DATA_SNAPSHOT_DAY:
            link = root / "data" / "us" / path.relative_to(source)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(path)


def repo_data_status() -> str:
    """`git status` of the repo's data/us: the linked tree must never write through to it."""
    return subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "data/us"],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("dash")
    before = repo_data_status()
    data_tree(root)
    scored_rows(root)
    earlier_adjustment(root)
    later_rows(root)
    n_plus_k_rows(root)
    saved = common.ROOT
    common.ROOT = root
    try:
        con = database.connect("us")
        cfg = load_market("us")
        yield {"root": root, "con": con, "cfg": cfg, "data": gather_dashboard(cfg, con, CUTOFF)}
    finally:
        common.ROOT = saved
    assert repo_data_status() == before, "the dashboard fixture wrote into the repo's data/us"


def company(data: dict, ticker: str) -> dict:
    return next(c for c in data["companies"] if c["ticker"] == ticker)


def test_numbers_equal_the_source_views(built):
    con, data, jpm = built["con"], built["data"], company(built["data"], "JPM")
    assert data["as_of"] == "2026-10-06" and len(data["companies"]) == len(built["cfg"]["tickers"])
    # each bar's newest collection by the cut-off (JPM has no split record known by then)
    bars = con.execute(
        "SELECT date, open, close FROM (SELECT DISTINCT ON (date) * FROM prices WHERE ticker = 'JPM' AND "
        "collected_at <= ? ORDER BY date, collected_at DESC) WHERE date <= DATE '2026-10-06' "
        "AND date > DATE '2026-10-06' - INTERVAL 380 DAY ORDER BY date",
        [CUTOFF],
    ).fetchall()
    assert len(jpm["bars"]) == len(bars) and jpm["bars"][-1][0] == "2026-10-06"
    assert jpm["last"]["close"] == round(bars[-1][2], 4) and jpm["last"]["prev_close"] == round(bars[-2][2], 4)
    assert jpm["last"]["gap"] == pytest.approx(round(bars[-1][1], 4) / round(bars[-2][2], 4) - 1)
    for r in jpm["ranges"]:
        lo80, hi80, base = con.execute(
            "SELECT lo80, hi80, base_close FROM ranges_latest WHERE id = ?", [f"2026-10-06-JPM-{r['h']}d"]
        ).fetchone()
        assert (r["lo80"], r["hi80"], r["base_close"]) == (lo80, hi80, base)
        assert r["up80"] == pytest.approx(hi80 / base - 1) and r["down80"] == pytest.approx(lo80 / base - 1)
    for m in jpm["model"]:
        # model_scores_latest's pick among the rows stored by the cut-off (the view itself sees the later row)
        prob, groups = con.execute(
            "SELECT prob_up, contributions->'groups' FROM model_scores WHERE id = ? AND "
            "computed_at <= ? ORDER BY computed_at DESC, prob_up, model_id LIMIT 1",
            [m["id"], CUTOFF],
        ).fetchone()
        assert m["prob_up"] == prob and m["baseline_points"] == json.loads(groups)["baseline"]
    # N+k: the close of D+k (stored exit_date; N+1 stored before B10 is the same window); an old 5-day score keeps
    # its D+4 exit (legacy_5d_d4)
    assert {m["h"]: (m["entry"], m["exit"], m["horizon_label"], m["name"]) for m in jpm["model"]} == {
        1: ("2026-10-07", "2026-10-08", "n_plus_k", "N+1: sell at the close of D+1"),
        2: ("2026-10-07", "2026-10-09", "n_plus_k", "N+2: sell at the close of D+2"),
        3: ("2026-10-07", "2026-10-12", "n_plus_k", "N+3: sell at the close of D+3"),
        5: ("2026-10-07", "2026-10-13", "legacy_5d_d4", "Buy today, sell within 5 days"),
    }
    assert data["plan"] == {
        "entry": "2026-10-07",
        "horizons": [1, 2, 3, 4, 5],
        "exits": {"1": "2026-10-08", "2": "2026-10-09", "3": "2026-10-12", "4": "2026-10-13", "5": "2026-10-14"},
        "exit_1d": "2026-10-08",
        "exit_5d": "2026-10-14",
        "sessions": ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14"],
    }
    assert [(r["h"], r["horizon_label"], r["name"]) for r in jpm["ranges"]] == [
        (1, "legacy_cc", "Next session"),
        (2, "n_plus_k", "N+2"),
        (3, "n_plus_k", "N+3"),
        (5, "legacy_cc", "5 sessions"),
    ]
    bull = con.execute(
        "SELECT bull_case FROM agent_reasoning WHERE ticker = 'JPM' AND written_at <= ? "
        "ORDER BY written_at DESC LIMIT 1",
        [CUTOFF],
    ).fetchone()[0]
    assert jpm["reasoning"]["bull"] == bull
    rsi = con.execute(
        "SELECT rsi_14 FROM features_latest WHERE ticker = 'JPM' AND as_of_date = '2026-10-06'"
    ).fetchone()[0]
    assert jpm["indicators"]["rsi_14"] == rsi
    # company_events as of the cut-off: the newest earnings row first seen by then
    earn = con.execute(
        "SELECT date FROM events WHERE ticker = 'JPM' AND type = 'earnings' AND first_seen_at <= ? "
        "AND NOT ends_with(coalesce(source, ''), '_history') ORDER BY first_seen_at DESC, date LIMIT 1",
        [CUTOFF],
    ).fetchone()[0]
    assert earn.isoformat() > data["as_of"] and jpm["earnings"] == earn.isoformat()
    statuses = EvidenceStatuses(con)
    assert jpm["news"] and all(n["status"] == statuses.of(n["id"], "JPM", CUTOFF.isoformat()) for n in jpm["news"])
    sector = next(s for s in data["overview"]["sectors"] if s["sector"] == "Banks")
    rets = [x["ret_1d"] for x in sector["stocks"]]
    assert sector["move_1d"] == pytest.approx(sum(rets) / len(rets))


def test_nothing_after_the_cut_off_or_the_as_of(built):
    data, jpm = built["data"], company(built["data"], "JPM")
    # the later rows are really there: today's views see them
    con = built["con"]
    assert con.execute("SELECT max(date) FROM ohlc WHERE ticker = 'JPM'").fetchone()[0].isoformat() == "2026-10-07"
    assert con.execute("SELECT max(as_of_date) FROM features_latest").fetchone()[0].isoformat() == "2026-10-07"
    assert data["as_of"] == "2026-10-06" and all(b[0] <= data["as_of"] for b in jpm["bars"])
    assert all(m["prob_up"] != 0.99 for m in jpm["model"]) and jpm["reasoning"]["bull"] != "LATER BULL"
    assert LATE_NEWS not in {n["id"] for n in jpm["news"]} and jpm["indicators"]["rsi_14"] != 99.0
    assert all(n["ts"] <= CUTOFF.isoformat() for c in data["companies"] for n in c["news"])
    assert data["skill"]["state"] == "paper" and data["skill"]["review"]["id"] == "2026-W40"
    assert data["track"]["replay"] is None
    # the range scored later is left out; N+1 and the old 1-day window are two rows
    assert [r["inside80"]["n"] for r in data["track"]["ranges"]] == [1, 1, 1]


def test_bars_earnings_and_splits_as_of_the_cut_off(built):
    con, jpm, bac = built["con"], company(built["data"], "JPM"), company(built["data"], "BAC")
    # today's views see the later rows; the page does not
    seen_now = con.execute("SELECT date FROM company_events WHERE ticker = 'JPM' AND type = 'earnings'").fetchone()[0]
    assert seen_now.isoformat() == "2027-01-14" and jpm["earnings"] not in (None, "2027-01-14")
    view_close = con.execute("SELECT close FROM ohlc WHERE ticker = 'JPM' AND date = '2026-10-05'").fetchone()[0]
    stored = con.execute(
        "SELECT close FROM prices WHERE ticker = 'JPM' AND date = '2026-10-05' AND collected_at <= ? "
        "ORDER BY collected_at DESC LIMIT 1",
        [CUTOFF],
    ).fetchone()[0]
    page_close = next(b[4] for b in jpm["bars"] if b[0] == "2026-10-05")
    assert view_close == 705 * 0.5 and page_close == round(stored, 4) and page_close != round(view_close, 4)
    # a split record known by the cut-off is applied to the bars before its ex-date only
    raw = dict(
        con.execute(
            "SELECT date::VARCHAR, close FROM prices WHERE ticker = 'BAC' AND date IN ('2026-08-31', '2026-09-01') "
            "AND collected_at <= ?",
            [CUTOFF],
        ).fetchall()
    )
    bars = {b[0]: b[4] for b in bac["bars"]}
    assert bars["2026-08-31"] == round(raw["2026-08-31"] * 0.5, 4)
    assert bars["2026-09-01"] == round(raw["2026-09-01"], 4)


HOSTILE = ["Comment <!--<script> trick", "</script><script>alert(1)</script>", "a & b > c \u2028 \u2029"]


def test_stored_text_cannot_break_the_page():
    data = {"name": "T", "x": HOSTILE}
    payload = page.json_script(data)
    assert json.loads(payload) == data and not re.search("[<>&\u2028\u2029]", payload)
    with pytest.raises(ValueError):
        page.script_safe("var a = '<!--';")


def test_track_record_per_basis_never_pooled(built):
    track = built["data"]["track"]
    by_basis = {b["key"]: b["all"] for b in track["calls"]}
    assert set(by_basis) == {"close_to_close", "open_to_close", "open_to_close legacy_5d_d4"}
    assert by_basis["open_to_close legacy_5d_d4"]["n"] == 1
    horizons_of = {b["key"]: {k: v["name"] for k, v in b["by_horizon"].items()} for b in track["calls"]}
    assert horizons_of == {
        "close_to_close": {"1d legacy_cc": "1 day"},
        "open_to_close": {"1d": "N+1"},
        "open_to_close legacy_5d_d4": {"5d legacy_5d_d4": "5 days"},
    }
    assert (by_basis["close_to_close"]["n"], by_basis["close_to_close"]["hits"]) == (2, 1)
    assert (by_basis["open_to_close"]["n"], by_basis["open_to_close"]["hits"]) == (3, 2)
    assert by_basis["open_to_close"]["always_up"] == pytest.approx(2 / 3, abs=1e-4)
    lo, hi = scoring.wilson(2, 3)
    assert (by_basis["open_to_close"]["wilson_lo"], by_basis["open_to_close"]["wilson_hi"]) == (lo, hi)
    ranges = {r["key"]: r for r in track["ranges"]}
    assert [(r["key"], r["name"]) for r in track["ranges"]] == [
        ("1d", "N+1"),
        ("1d legacy_cc", "Next session"),
        ("5d legacy_cc", "5 sessions"),
    ]
    old = ranges["1d legacy_cc"]
    assert (old["inside80"]["n"], old["inside80"]["hits"], old["inside50"]["hits"]) == (1, 1, 1)
    assert (ranges["1d"]["inside80"]["n"], ranges["1d"]["inside80"]["hits"]) == (1, 0)
    assert (ranges["5d legacy_cc"]["inside80"]["hits"], ranges["5d legacy_cc"]["inside50"]["hits"]) == (1, 0)


def test_empty_market_builds(tmp_path):
    saved = common.ROOT
    common.ROOT = tmp_path
    try:
        data = gather_dashboard(load_market("india"), database.connect("india"), CUTOFF)
        html = page.build_page(data)
    finally:
        common.ROOT = saved
    assert data["as_of"] is None and data["companies"] == [] and data["backtest"] is None
    assert data["skill"]["label"] == MSG_PAPER_ONLY and data["track"] == {
        "calls": [],
        "ranges": [],
        "replay": None,
        "min_sample": 10,
    }
    assert "India (NSE) dashboard" in html


def test_page_is_self_contained(built):
    html = page.build_page(built["data"])
    assert not re.search(r"<script[^>]*\bsrc=", html, re.I) and not re.search(r"<link\b", html, re.I)
    assert not re.search(r"@import|@font-face|url\(\s*['\"]?https?:", html, re.I)
    assert not re.search(r"\b(?:src|srcset|poster|data)\s*=\s*['\"]https?:", html, re.I)
    assert html.count("<script") == 3 and html.count("</script>") == 3  # data, library, app: nothing closes early
    assert "Research only, not investment advice." in html and MSG_PAPER_ONLY in html
    payload = re.search(r'<script id="mb-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(payload)["as_of"] == "2026-10-06"
    for c in json.loads(payload)["companies"]:  # the only http(s) text in the data: plain news links
        assert all(n["url"] is None or re.match(r"^https?://\S+$", n["url"]) for n in c["news"])


def test_vendored_library_matches_its_notice():
    notice = (page.HERE / "vendor" / "NOTICE").read_text()
    digest = hashlib.sha256(page.vendor_path().read_bytes()).hexdigest()
    assert digest == page.pinned_sha256()
    assert (
        "version 5.2.1" in notice
        and "https://registry.npmjs.org/lightweight-charts/-/lightweight-charts-5.2.1.tgz" in notice
    )
    assert "Apache License" in (page.HERE / "vendor" / "LICENSE").read_text()


def test_skill_label_follows_the_review():
    assert model_info.skill_status(None)["label"] == MSG_PAPER_ONLY
    no = {"id": "w", "computed_at": "2026-10-07T00:00:00+00:00", "model_skill": False, "detail": "{}"}
    assert model_info.skill_status(no)["state"] == "paper"
    assert model_info.skill_status({**no, "model_skill": None})["label"] == MSG_PAPER_ONLY
    assert model_info.skill_status({**no, "model_skill": True})["label"] == MSG_SKILL_SHOWN


def test_cli_writes_the_page_and_lists_it_for_slack(built, tmp_path, monkeypatch):
    root = built["root"]
    monkeypatch.setattr(common, "ROOT", root)
    monkeypatch.setenv("MB_NOW", CUTOFF.isoformat())
    (root / "work").mkdir(exist_ok=True)
    manifest = root / "work" / "slack_us_files.json"
    manifest.write_text(json.dumps({"market": "us", "html": "reports/us/2026-10-07.html", "images": []}))
    out = dash_cli.run(built["cfg"])
    assert out["html"] == "reports/us/dashboard.html" and (root / out["html"]).exists()
    assert json.loads(manifest.read_text())["dashboard"] == "reports/us/dashboard.html"
    steps = ns.thread_plan("summary\n", json.loads(manifest.read_text()), root)
    assert [s["step"] for s in steps] == ["summary", "dashboard"]
    assert steps[-1]["files"] == [{"path": "reports/us/dashboard.html", "title": "Dashboard"}]
    other = dash_cli.run(built["cfg"], tmp_path)  # --out: the manifest is left alone
    assert other["slack_files"] is None and (tmp_path / "dashboard.html").exists()


def _node_playwright() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return root if root and (Path(root) / "playwright").exists() else None


RENDER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  let b;
  try { b = await chromium.launch(); }
  catch (e) { b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'}); }
  const out = {dialogs: 0};
  for (const [w, h] of [[1280, 900], [375, 812]]) {
    const errors = [], requests = [];
    const p = await b.newPage({viewport: {width: w, height: h}});
    p.on('pageerror', e => errors.push(e.message));
    p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    p.on('request', r => { if (!r.url().startsWith('file:') && !r.url().startsWith('data:')) requests.push(r.url()); });
    p.on('dialog', d => { out.dialogs += 1; d.dismiss(); });
    await p.goto('file://' + process.argv[2]); await p.waitForTimeout(300);
    out.parsed = await p.evaluate(() => {
      try { return Array.isArray(JSON.parse(document.getElementById('mb-data').textContent).companies); }
      catch (e) { return false; }
    });
    out.switch = await p.evaluate(
      () => Array.from(document.querySelectorAll('#markets a')).map(a => a.getAttribute('href')));
    const rows = await p.locator('#wl-body tr').count();
    await p.click('#wl-body button.tick[data-t="JPM"]'); await p.waitForTimeout(500);
    const canvases = await p.locator('#chart-box canvas').count();
    const fan = await p.locator('#chart-box svg.fan polygon').count();
    out.stock_text = await p.textContent('#view-stock');
    const range = async () => p.evaluate(() => window.MB.chart().timeScale().getVisibleRange().from);
    await p.click('[data-span="1W"]'); await p.waitForTimeout(200); const week = await range();
    await p.click('[data-span="1Y"]'); await p.waitForTimeout(200); const year = await range();
    await p.click('#st-next'); await p.waitForTimeout(300);
    const next = await p.evaluate(() => window.MB.state.ticker);
    const texts = {};
    for (const view of ['track', 'how', 'overview']) {
      await p.evaluate(v => window.MB.go(v), view); await p.waitForTimeout(200);
      texts[view] = await p.textContent('#view-' + view);
    }
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    out[w] = {errors, requests, rows, canvases, fan, week, year, next, overflow, texts};
  }
  console.log(JSON.stringify(out)); await b.close();
})();
"""


def test_dashboard_renders_in_a_browser(built, tmp_path):
    root = _node_playwright()
    if root is None:
        pytest.skip("node + playwright not installed")
    data = copy.deepcopy(built["data"])  # hostile stored text in headlines and agent reasoning
    jpm = company(data, "JPM")
    for item, title in zip(jpm["news"], HOSTILE, strict=False):
        item["title"] = title
    jpm["reasoning"]["bull"] = HOSTILE[0] + " " + HOSTILE[1]
    data["pages_url"] = "https://reports.example/"   # issue #48: the market switch is absolute on the owner's site
    f = tmp_path / "dashboard.html"
    f.write_text(page.build_page(data))
    js = tmp_path / "render.js"
    js.write_text(RENDER_JS)
    r = subprocess.run(
        ["node", str(js), str(f)], capture_output=True, text=True, timeout=180, env={**os.environ, "NODE_PATH": root}
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().split("\n")[-1])  # not splitlines(): the text holds U+2028
    banks = built["cfg"]["sectors"]["Banks"]
    assert out["parsed"] is True and out["dialogs"] == 0
    assert out["switch"] == ["https://reports.example/india/dashboard.html"]
    assert all(text in out["stock_text"] for text in HOSTILE[:2])  # shown as plain text, never parsed as HTML
    for width in ("1280", "375"):
        o = out[width]
        assert o["errors"] == [] and o["requests"] == [] and o["overflow"] is False, o
        assert o["rows"] == len(built["cfg"]["tickers"]) and o["canvases"] > 0 and o["fan"] == 2
        assert o["week"] == "2026-09-29" and o["year"] < "2025-10-10" and o["next"] == banks[banks.index("JPM") + 1]
    # every configured horizon N+k is on the page, the old windows keep their names (B10)
    assert "N+2: sell at the close of D+2" in out["stock_text"] and "Buy today, sell within 5 days" in out["stock_text"]
    assert "N+3" in out["stock_text"] and "5 sessions" in out["stock_text"]
    texts = out["1280"]["texts"]
    assert "N+5: sold at the close of D+5 (Wed 14 Oct)" in texts["how"]
    assert (
        "P(up) N+1" in texts["overview"]
        and "P(up) N+5" in texts["overview"]
        and "N+4: sell at the close of" in texts["overview"]
    )
    assert "N+1" in texts["track"] and "Next session" in texts["track"] and "open→close D+4 (legacy)" in texts["track"]


def test_safe_url_encodes_quotes_and_brackets():
    """Issue #48: a stored link keeps working, but a quote or angle bracket can never end an HTML attribute."""
    from view_data import safe_url

    assert safe_url(" https://a.example/x?y=1 ") == "https://a.example/x?y=1"
    assert safe_url('https://a.example/"onmouseover=alert(1)') == "https://a.example/%22onmouseover=alert(1)"
    assert safe_url("https://a.example/it's<b>`") == "https://a.example/it%27s%3Cb%3E%60"
    assert safe_url("javascript:alert(1)") is None and safe_url("https://a b") is None and safe_url(None) is None


def test_cli_page_carries_pages_url(built, monkeypatch):
    """The page payload names config/settings.yaml's pages_url, which the market switch links to (issue #48)."""
    from marketbrief.core.settings import load_settings

    monkeypatch.setattr(common, "ROOT", built["root"])
    monkeypatch.setenv("MB_NOW", CUTOFF.isoformat())
    dash_cli.run(built["cfg"])
    html = (built["root"] / "reports" / "us" / "dashboard.html").read_text()
    payload = json.loads(re.search(r'<script id="mb-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert payload["pages_url"] == load_settings()["pages_url"]
