"""The context pack lists the previous run's judge FAILs that its own report could not list
(issue #4: a failed monthly graph-builder run is judged after the brief is posted), so the next
run copies them into data_quality."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.core.clock import utc_today  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.storage import append_jsonl, day_file  # noqa: E402
from marketbrief.pipeline import context  # noqa: E402
from test_pipeline import MARKET, run, setup  # noqa: E402

TODAY = date(2026, 10, 7)


def verdict(day: date, agent: str, rnd: int, v: str, at: str, summary: str = "s", dropped=None) -> dict:
    return {"id": f"{day}-{agent}-{rnd}-{at[11:19].replace(':', '')}", "run_date": str(day), "agent": agent,
            "round": rnd, "verdict": v, "summary": summary, "dropped": dropped, "recorded_at": at}


def write(rows: list[dict]) -> None:
    for r in rows:
        append_jsonl(day_file(MARKET, "judgments", date.fromisoformat(r["run_date"])), [r])


def fails(today: date = TODAY) -> list[tuple]:
    con = connect(MARKET)
    return [(str(d), a, r, s) for d, a, r, s, *_ in
            con.execute(context.JUDGE_FAILS_SQL, [today, today, context.JUDGE_LOOKBACK_DAYS]).fetchall()]


@pytest.fixture
def root(tmp_path, monkeypatch):
    root, _ = setup(tmp_path)
    monkeypatch.setattr(common, "ROOT", root)
    return root


def test_lists_the_step_14_fail_of_the_previous_run_only(root):
    prev, older = date(2026, 10, 6), date(2026, 10, 5)
    write([
        verdict(older, "graph-builder", 2, "FAIL", "2026-10-05T03:30:00+00:00", "older run, already listed"),
        verdict(prev, "news-analyst", 1, "FAIL", "2026-10-06T02:50:00+00:00", "id unsupported"),
        verdict(prev, "news-analyst", 2, "FAIL", "2026-10-06T02:55:00+00:00", "still unsupported",
                "news brief"),                                   # final FAIL, but before the report
        verdict(prev, "report", 1, "PASS", "2026-10-06T03:10:00+00:00"),
        verdict(prev, "slack", 1, "PASS", "2026-10-06T03:11:00+00:00"),
        verdict(prev, "graph-builder", 1, "FAIL", "2026-10-06T03:20:00+00:00", "edge source missing"),
        verdict(prev, "graph-builder", 2, "FAIL", "2026-10-06T03:25:00+00:00", "two edges uncited",
                "all graph edges"),
        verdict(TODAY, "news-analyst", 1, "FAIL", "2026-10-07T02:50:00+00:00", "today's own"),
    ])
    assert fails() == [("2026-10-06", "graph-builder", 2, "two edges uncited")]
    con = connect(MARKET)
    table = context.judge_fails(con, TODAY)
    assert "| 2026-10-06 | graph-builder | 2 | two edges uncited | all graph edges |" in table


def test_a_fail_fixed_in_the_retry_is_not_listed(root):
    prev = date(2026, 10, 6)
    write([verdict(prev, "slack", 1, "PASS", "2026-10-06T03:11:00+00:00"),
           verdict(prev, "graph-builder", 1, "FAIL", "2026-10-06T03:20:00+00:00"),
           verdict(prev, "graph-builder", 2, "PASS", "2026-10-06T03:25:00+00:00")])
    assert fails() == []


def test_a_run_that_never_reached_its_report_lists_every_final_fail(root):
    prev = date(2026, 10, 6)
    write([verdict(prev, "news-analyst", 1, "FAIL", "2026-10-06T02:50:00+00:00", "a"),
           verdict(prev, "bull-researcher", 1, "PASS", "2026-10-06T03:00:00+00:00"),
           verdict(prev, "bear-researcher", 2, "FAIL", "2026-10-06T03:01:00+00:00", "b")])
    assert fails() == [("2026-10-06", "news-analyst", 1, "a"), ("2026-10-06", "bear-researcher", 2, "b")]


def test_lookback_and_weekend_gap(root):
    friday = date(2026, 10, 2)                       # the previous run before Monday 2026-10-05
    write([verdict(friday, "slack", 1, "PASS", "2026-10-02T03:11:00+00:00"),
           verdict(friday, "graph-builder", 1, "FAIL", "2026-10-02T03:20:00+00:00", "x")])
    assert fails(date(2026, 10, 5)) == [("2026-10-02", "graph-builder", 1, "x")]
    assert fails(date(2026, 10, 9)) == [("2026-10-02", "graph-builder", 1, "x")]    # 7 days back
    assert fails(date(2026, 10, 10)) == []                                          # beyond 7 days


def test_context_pack_prints_the_section(tmp_path):
    root, cfg = setup(tmp_path)
    today = utc_today()
    prev = today - timedelta(days=1)
    p = root / "data" / MARKET / "judgments" / f"{prev:%Y}" / f"{prev:%m}" / f"{prev}.jsonl"
    p.parent.mkdir(parents=True)
    append_jsonl(p, [verdict(prev, "slack", 1, "PASS", f"{prev}T03:11:00+00:00"),
                            verdict(prev, "graph-builder", 2, "FAIL", f"{prev}T03:25:00+00:00",
                                    "uncited edges", "all graph edges")])
    r = run("context.py", root, cfg)
    assert r.returncode == 0, r.stderr
    sec = r.stdout.split("## Judge FAILs from the previous run not yet in a report", 1)[1]
    assert f"| {prev} | graph-builder | 2 | uncited edges | all graph edges |" in sec
    empty = run("context.py", *setup(tmp_path / "empty"))
    assert empty.returncode == 0, empty.stderr
    assert empty.stdout.split("## Judge FAILs from the previous run", 1)[1].strip().endswith("_none_")
