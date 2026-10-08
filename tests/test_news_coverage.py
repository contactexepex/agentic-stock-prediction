"""News coverage (docs/DESIGN.md section 3, "News timing"): the news collector's catch-up window
(marketbrief/collectors/news_window.py: Monday after Friday, after a holiday, after a failed run, the 7-day
cap, a first run; Google News `when:` and per-day re-asks), the analyst's input window since the last
enrichment (marketbrief/pipeline/news_pending.py, validate.py --stage news, claims.py), the news-only
light run (scripts/collect_news_only.py, validate.py --stage news_collect) and the news categories in config."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import feedparser
import pandas as pd
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
from marketbrief.collectors import news as cn  # noqa: E402
from marketbrief.collectors import news_window as nw  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.pipeline import claim_sources, news_light_run, news_pending  # noqa: E402
from marketbrief.pipeline.validate import cli  # noqa: E402

UTC = timezone.utc
MARKET = "covmkt"
WATCHLIST = {
    "market": MARKET,
    "tickers": {"HDFCBANK": {"name": "HDFC Bank"}},
    "news": {
        "google_news": {"base": "https://news.google.com/rss/search", "window": "1d",
                        "params": {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"}},
        "categories": {"macro": ["RBI policy"]},
    },
}


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def write_rows(root: Path, kind: str, day: date, rows: list[dict], market: str = MARKET) -> Path:
    path = root / "data" / market / kind / f"{day:%Y}" / f"{day:%m}" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in rows))
    return path


def run_row(ran_at: str, ok: bool = True) -> dict:
    return {"id": f"{MARKET}-{ran_at}", "ran_at": ran_at, "ok": ok, "window_hours": 24.0}


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(common, "ROOT", tmp_path)
    return tmp_path


# ---------- the catch-up window ----------

def test_first_run_keeps_the_defaults():
    win = nw.catch_up_window(None, utc("2026-10-05T02:30:00+00:00"), "1d")
    assert (win.google_when, win.hours, win.max_age, win.reason) == ("1d", 24.0, timedelta(days=3), "first_run")
    assert win.summary()["since"] is None


def test_monday_after_friday_reaches_back_over_the_weekend():
    # India pre-open runs Friday 02:30 UTC and Monday 02:30 UTC: 72 h + 1 h margin
    win = nw.catch_up_window(utc("2026-10-02T02:30:00+00:00"), utc("2026-10-05T02:30:00+00:00"), "1d")
    assert win.google_when == "73h" and win.hours == 73.0
    assert win.max_age == timedelta(hours=73)          # wider than the 3-day floor
    assert win.reason == "since_last_run"


def test_day_after_a_holiday_reaches_back_over_it():
    # Friday run, Monday holiday (the pre-open run stops before collecting), Tuesday run: 96 h + 1 h
    win = nw.catch_up_window(utc("2026-10-02T12:15:00+00:00"), utc("2026-10-06T12:15:00+00:00"), "1d")
    assert win.google_when == "97h" and win.max_age == timedelta(hours=97)


def test_short_gap_never_narrows_below_the_defaults():
    # a light run 6 hours after the last one still asks a day and keeps 3 days of items
    win = nw.catch_up_window(utc("2026-10-05T00:00:00+00:00"), utc("2026-10-05T06:00:00+00:00"), "1d")
    assert (win.google_when, win.hours, win.max_age) == ("1d", 24.0, timedelta(days=3))
    # partial hours round up
    assert nw.catch_up_window(utc("2026-10-04T00:00:00+00:00"), utc("2026-10-05T06:20:00+00:00")).google_when == "32h"


def test_window_is_capped_at_seven_days():
    win = nw.catch_up_window(utc("2026-09-20T00:00:00+00:00"), utc("2026-10-05T02:30:00+00:00"), "1d")
    assert win.google_when == "168h" and win.hours == 168.0 and win.max_age == timedelta(days=7)


def test_when_values():
    assert nw.when_hours("1d") == 24.0 and nw.when_hours("12h") == 12.0 and nw.when_hours("3d") == 72.0
    with pytest.raises(ValueError):
        nw.when_hours("1w")                            # Google News answers nothing for when:1w


def test_after_a_failed_run_the_window_starts_at_the_last_success(root):
    write_rows(root, "news_runs", date(2026, 10, 5), [run_row("2026-10-05T02:30:00+00:00", ok=True)])
    write_rows(root, "news_runs", date(2026, 10, 6), [run_row("2026-10-06T02:30:00+00:00", ok=False)])
    win = nw.window_for(MARKET, utc("2026-10-07T02:30:00+00:00"))
    assert win.since == utc("2026-10-05T02:30:00+00:00") and win.google_when == "49h"
    assert win.reason == "since_last_run"


def test_window_ignores_runs_after_now_and_falls_back_to_stored_news(root):
    write_rows(root, "news", date(2026, 10, 2), [{"id": "a", "first_seen_at": "2026-10-02T02:31:00+00:00"},
                                                  {"id": "b", "first_seen_at": "2026-10-02T02:30:00+00:00"}])
    win = nw.window_for(MARKET, utc("2026-10-05T02:30:00+00:00"))
    assert win.reason == "since_last_news" and win.since == utc("2026-10-02T02:31:00+00:00")
    assert win.google_when == "73h"


def test_no_successful_run_reaches_back_the_whole_cap(root):
    write_rows(root, "news_runs", date(2026, 10, 4), [run_row("2026-10-04T02:30:00+00:00", ok=False)])
    win = nw.window_for(MARKET, utc("2026-10-05T02:30:00+00:00"))
    assert win.reason == "no_recent_success" and win.google_when == "168h"


@pytest.mark.usefixtures("root")
def test_first_run_without_any_stored_data():
    assert nw.window_for(MARKET, utc("2026-10-05T02:30:00+00:00")).reason == "first_run"


def test_run_ok():
    assert nw.run_ok(google_queries=10, google_failed=5, feeds=12, failed=5)
    assert not nw.run_ok(google_queries=10, google_failed=6, feeds=12, failed=6)
    assert not nw.run_ok(google_queries=0, google_failed=0, feeds=3, failed=3)
    assert nw.run_ok(google_queries=0, google_failed=0, feeds=0, failed=0)


def test_slice_days_cover_the_window_in_pacific_days():
    now = utc("2026-10-05T02:30:00+00:00")
    assert nw.slice_days(nw.catch_up_window(None, now), now) == []
    days = nw.slice_days(nw.catch_up_window(utc("2026-10-02T02:30:00+00:00"), now), now)
    # issue #51: the window starts 2026-10-02T01:30Z = 10-01 18:30 PDT and now is 10-04 19:30 PDT; the old slices
    # also asked 09-30 and 10-05 (Pacific), days that hold nothing the run keeps
    assert days == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4)]
    later = utc("2026-10-05T16:00:00+00:00")                       # 09:00 PDT; window from 10-02 13:30Z = 06:30 PDT
    days = nw.slice_days(nw.catch_up_window(utc("2026-10-02T14:30:00+00:00"), later), later)
    assert days == [date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4), date(2026, 10, 5)]


def test_google_news_urls_carry_the_window():
    google = WATCHLIST["news"]["google_news"]
    jobs = cn.build_jobs(WATCHLIST["news"], WATCHLIST, "73h")
    queries = [parse_qs(urlparse(job["url"]).query)["q"][0] for job in jobs]
    assert queries == ['"HDFC Bank" stock when:73h', "RBI policy when:73h"]
    assert parse_qs(urlparse(cn.google_news_url("x", google)).query)["q"][0] == "x when:1d"   # config default
    sliced = cn.slice_job(jobs[1], google, date(2026, 10, 3))
    assert parse_qs(urlparse(sliced["url"]).query)["q"][0] == "RBI policy after:2026-10-03 before:2026-10-04"
    assert sliced["feed"] == jobs[1]["feed"] and sliced["slice"] == "2026-10-03"


# ---------- the collector with the window ----------

def slug(title: str) -> str:
    """One article link per headline (a link shared by two headlines is one article with an edited headline)."""
    return "-".join(title.lower().split())


def feed_xml(items: list[tuple[str, datetime]]) -> str:
    body = "".join(
        f"<item><title>{title} - Mint</title><link>https://news.google.com/rss/articles/{slug(title)}</link>"
        f"<pubDate>{stamp.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>"
        f'<source url="https://www.livemint.com">Mint</source></item>'
        for title, stamp in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{body}</channel></rss>'


def run_collector(monkeypatch, capsys, now: datetime, answer) -> tuple[dict, list[str]]:
    asked: list[str] = []

    def fake_fetch(url):
        asked.append(url)
        return feedparser.parse(answer(url))

    monkeypatch.setattr(cn, "fetch_feed", fake_fetch)
    monkeypatch.setattr(cn, "now_utc", lambda: now)
    monkeypatch.setenv("MB_NOW", now.isoformat())
    assert cn.NewsCollector(WATCHLIST).collect() == 0
    return json.loads(capsys.readouterr().out), asked


def stored(root: Path, kind: str) -> list[dict]:
    return [json.loads(line) for path in sorted((root / "data" / MARKET / kind).glob("**/*.jsonl"))
            for line in path.read_text().splitlines() if line.strip()]


def test_collector_keeps_old_items_only_inside_a_wide_window(root, monkeypatch, capsys):
    now = utc("2026-10-05T02:30:00+00:00")
    old = ("HDFC Bank raises deposit rates", now - timedelta(days=4))     # Thursday: outside 3 days
    fresh = ("HDFC Bank opens new branches", now - timedelta(hours=2))
    out, asked = run_collector(monkeypatch, capsys, now, lambda _url: feed_xml([old, fresh]))
    assert out["window"]["reason"] == "first_run" and out["new_items"] == 1
    assert all("when%3A1d" in url for url in asked)
    runs = stored(root, "news_runs")
    assert len(runs) == 1 and runs[0]["ok"] and set(runs[0]) == set(SCHEMAS["news_runs"][1])
    assert runs[0]["google_when"] == "1d" and runs[0]["google_queries"] == 2 and runs[0]["since"] is None

    # the next run comes five days later (runs failed or did not happen): it reaches back to the last success
    later = now + timedelta(days=5)
    old2 = ("HDFC Bank names new CFO", later - timedelta(days=4, hours=12))   # outside 3 days, inside the window
    out, asked = run_collector(monkeypatch, capsys, later, lambda _url: feed_xml([old2]))
    assert out["window"]["reason"] == "since_last_run" and out["window"]["google_when"] == "121h"
    assert out["window"]["since"] == "2026-10-05T02:30:00+00:00"
    assert all("when%3A121h" in url for url in asked) and out["new_items"] == 1
    assert [row["title"] for row in stored(root, "news")] == [fresh[0], old2[0]]
    assert len(stored(root, "news_runs")) == 2


def test_collector_asks_per_day_when_a_query_fills_the_cap(root, monkeypatch, capsys):
    now = utc("2026-10-05T02:30:00+00:00")
    write_rows(root, "news_runs", date(2026, 10, 2), [run_row("2026-10-02T02:30:00+00:00")])
    full = [(f"HDFC Bank item {index}", now - timedelta(hours=index % 60)) for index in range(100)]
    extra = [("HDFC Bank item found by day", now - timedelta(hours=50))]

    def answer(url):
        query = parse_qs(urlparse(url).query)["q"][0]
        if "after:" in query:
            return feed_xml(extra)
        return feed_xml(full if "HDFC" in query else [])

    out, asked = run_collector(monkeypatch, capsys, now, answer)
    sliced = [parse_qs(urlparse(url).query)["q"][0] for url in asked if "after%3A" in url]
    # the Pacific days 10-01..10-04 of the window (issue #51: no empty day before or after it)
    assert len(sliced) == 4 and all(query.startswith('"HDFC Bank"') and "when:" not in query for query in sliced)
    assert out["sliced_queries"] == 4 and out["google_queries"] == 2
    assert out["new_items"] == 101                     # the per-day answer added the item the cap hid
    run = stored(root, "news_runs")[-1]
    assert run["sliced_queries"] == 4 and run["ok"]


@pytest.mark.usefixtures("root")
def test_failed_google_queries_make_the_run_not_ok(monkeypatch, capsys):
    now = utc("2026-10-05T02:30:00+00:00")
    monkeypatch.setattr(cn, "RETRY_PAUSE_SECONDS", 0)
    out, _ = run_collector(monkeypatch, capsys, now, lambda url: "<html>" if "HDFC" in url else feed_xml([]))
    assert out["google_failed"] == 1 and out["ok"]                         # 1 of 2 failed: still ok
    later = now + timedelta(hours=6)
    monkeypatch.setattr(cn, "fetch_with_retry", lambda _url: (feedparser.parse("<html>"), 500))
    monkeypatch.setattr(cn, "now_utc", lambda: later)
    monkeypatch.setenv("MB_NOW", later.isoformat())
    assert cn.NewsCollector(WATCHLIST).collect() == 1
    assert not json.loads(capsys.readouterr().out)["ok"]
    # the next run reaches back to the last successful one
    assert nw.window_for(MARKET, later + timedelta(hours=6)).since == now


def test_articles_keep_items_a_catch_up_run_brought_in(root):
    from types import SimpleNamespace

    from marketbrief.collectors import article_candidates

    src = SimpleNamespace(sel={"lookback_hours": 24, "max_age_hours": 48})
    now = pd.Timestamp("2026-10-05T03:00:00+00:00")
    assert article_candidates.max_age_hours(connect(MARKET), src, now) == 48.0
    write_rows(root, "news_runs", date(2026, 10, 5), [{**run_row("2026-10-05T02:30:00+00:00"), "window_hours": 73.0}])
    write_rows(root, "news_runs", date(2026, 10, 1), [{**run_row("2026-10-01T02:30:00+00:00"), "window_hours": 168.0}])
    assert article_candidates.max_age_hours(connect(MARKET), src, now) == 73.0     # runs in the lookback only


# ---------- the analyst's window: since the last enrichment ----------

def news_row(news_id: str, first_seen: str, **extra) -> dict:
    return {"id": news_id, "title": f"HDFC Bank {news_id}", "url": f"https://news.google.com/rss/articles/{news_id}",
            "source": "Mint", "published_at": first_seen, "first_seen_at": first_seen,
            "feed": 'gnews:"HDFC Bank" share', "category": "company", "tickers": ["HDFCBANK"], **extra}


def enriched(news_id: str, analyzed_at: str) -> dict:
    return {"id": news_id, "analyzed_at": analyzed_at, "relevance": 0.5, "sentiment": 0.1, "novelty": 0.5,
            "materiality": "low", "event_type": "other", "urgency": "low", "geopolitical": False,
            "priced_in": False, "summary": "A short summary.", "prompt_version": "news-v10"}


@pytest.fixture
def weekend(root):
    """Friday's pre-open run enriched f1; light runs stored f2 (Friday evening) and s1 (Saturday); Monday's
    pre-open run stored m1. An item older than the last enriched one (o1) was skipped by Friday's analyst."""
    write_rows(root, "news", date(2026, 10, 1), [news_row("o1", "2026-10-01T02:00:00+00:00")])
    write_rows(root, "news", date(2026, 10, 2), [news_row("f1", "2026-10-02T02:30:00+00:00"),
                                                 news_row("f2", "2026-10-02T20:00:00+00:00")])
    write_rows(root, "news", date(2026, 10, 3), [news_row("s1", "2026-10-03T08:00:00+00:00")])
    write_rows(root, "news", date(2026, 10, 5), [news_row("m1", "2026-10-05T02:30:00+00:00")])
    write_rows(root, "announcements", date(2026, 10, 3), [{
        "id": "nse-ann-1", "ticker": "HDFCBANK", "company": "HDFC Bank", "published_at": "2026-10-03T10:00:00+00:00",
        "category": "Outcome of Board Meeting", "subject": "Board meeting outcome", "url": "https://nsearchives.nseindia.com/a.pdf",
        "source": "nse", "first_seen_at": "2026-10-03T10:05:00+00:00"}])
    write_rows(root, "news_enriched", date(2026, 10, 2), [enriched("f1", "2026-10-02T02:40:00+00:00")])
    return root


NOW_MONDAY = pd.Timestamp("2026-10-05T02:45:00+00:00")


@pytest.mark.usefixtures("weekend")
def test_pending_covers_everything_since_the_last_enrichment():
    con = connect(MARKET)
    since, rows = news_pending.pending_rows(con, NOW_MONDAY)
    assert since == pd.Timestamp("2026-10-02T02:30:00+00:00")       # the newest enriched item's first_seen_at
    assert [row["id"] for row in rows] == ["f2", "s1", "m1", "nse-ann-1"]   # news, then announcements
    assert {row["kind"] for row in rows} == {"news", "announcement"}
    assert "o1" not in {row["id"] for row in rows}                  # before the window: not asked again


def test_pending_keeps_a_skipped_item_of_the_newest_enriched_run(weekend):
    """Issue #51: a collector run stamps all its items with one first_seen_at; f1b came in Friday's run with f1,
    the analyst enriched f1 only, so f1b (first seen at since) stays pending until it is scored."""
    write_rows(weekend, "news", date(2026, 10, 2), [news_row("f1b", "2026-10-02T02:30:00+00:00")])
    con = connect(MARKET)
    since, rows = news_pending.pending_rows(con, NOW_MONDAY)
    assert since == pd.Timestamp("2026-10-02T02:30:00+00:00")
    assert [row["id"] for row in rows] == ["f1b", "f2", "s1", "m1", "nse-ann-1"]     # f1 is scored: not again
    assert {"f1", "f1b"} <= news_pending.window_ids(con, NOW_MONDAY)[1]


def test_pending_without_enrichment_is_today_and_capped_at_seven_days(root):
    write_rows(root, "news", date(2026, 10, 5), [news_row("m1", "2026-10-05T02:30:00+00:00")])
    write_rows(root, "news", date(2026, 10, 4), [news_row("y1", "2026-10-04T20:00:00+00:00")])
    con = connect(MARKET)
    assert news_pending.enrichment_since(con, NOW_MONDAY) == pd.Timestamp("2026-10-05T00:00:00+00:00")
    assert [row["id"] for row in news_pending.pending_rows(con, NOW_MONDAY)[1]] == ["m1"]
    write_rows(root, "news", date(2026, 9, 1), [news_row("old", "2026-09-01T02:30:00+00:00")])
    write_rows(root, "news_enriched", date(2026, 9, 1), [enriched("old", "2026-09-01T02:40:00+00:00")])
    con = connect(MARKET)
    assert news_pending.enrichment_since(con, NOW_MONDAY) == NOW_MONDAY - pd.Timedelta(days=7)


def test_pending_script_writes_the_analyst_input(weekend, monkeypatch):
    monkeypatch.setenv("MB_NOW", NOW_MONDAY.isoformat())
    out = weekend / "work" / "news_pending.jsonl"
    summary = news_pending.write_pending(MARKET, out)
    assert (summary["news"], summary["announcements"]) == (3, 1)
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert {line["id"] for line in lines} == {"f2", "s1", "m1", "nse-ann-1"}
    assert all(line["first_seen_at"].endswith("+00:00") for line in lines)


def validate_news(root: Path, monkeypatch, rows: list[dict]) -> dict:
    monkeypatch.setenv("MB_NOW", NOW_MONDAY.isoformat())
    path = root / "work" / "enriched.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    cfg = {"market": MARKET, "calendar": "XNSE", "timezone": "Asia/Kolkata", "tickers": WATCHLIST["tickers"],
           "symbols": {}, "sectors": {}}
    monkeypatch.setattr(cli, "run_status", lambda _cfg: {
        "session_date": "2026-10-05", "previous_session": "2026-10-01", "late_run": False, "in_session": False,
        "trading_day": True})
    return cli.run(cfg, "news", {"enriched": path})


def test_news_gate_accepts_weekend_items_and_blocks_older_ones(weekend, monkeypatch):
    stamp = "2026-10-05T02:44:00+00:00"
    out = validate_news(weekend, monkeypatch, [enriched(i, stamp) for i in ("f2", "s1", "nse-ann-1", "m1")])
    assert out["ok"], out["failures"]
    assert out["info"]["news"]["since"] == "2026-10-02T02:30:00+00:00"
    assert not [w for w in out["warnings"] if w["code"] == "ENRICH_MISSING"]
    out = validate_news(weekend, monkeypatch, [enriched(i, stamp) for i in ("s1", "o1")])
    codes = {f["code"]: f for f in out["failures"]}
    assert "ENRICH_UNKNOWN_ID" in codes and "o1" in codes["ENRICH_UNKNOWN_ID"]["detail"]
    missing = next(w for w in out["warnings"] if w["code"] == "ENRICH_MISSING")
    assert "f2" in missing["detail"] and "m1" in missing["detail"]
    out = validate_news(weekend, monkeypatch, [enriched("f1", stamp)])
    assert "ENRICH_ALREADY_STORED" in {f["code"] for f in out["failures"]}


def test_pending_lists_watchlist_items_first(weekend):
    """Issue #46: untagged items are `background` and come after the watchlist items (each group oldest first)."""
    write_rows(weekend, "news", date(2026, 10, 3), [news_row("bg1", "2026-10-03T07:00:00+00:00", tickers=[],
                                                            category="macro")])
    rows = news_pending.pending_rows(connect(MARKET), NOW_MONDAY)[1]
    assert [(row["id"], row["priority"]) for row in rows] == [
        ("f2", "watchlist"), ("s1", "watchlist"), ("m1", "watchlist"), ("nse-ann-1", "watchlist"),
        ("bg1", "background")]


def test_news_gate_warns_on_templated_watchlist_summaries(weekend, monkeypatch):
    """Issue #46: ENRICH_TEMPLATED when more than 30% of at least 20 watchlist records repeat another's summary."""
    stamp = "2026-10-05T02:44:00+00:00"
    ids = [f"w{index:02d}" for index in range(24)]
    write_rows(weekend, "news", date(2026, 10, 4), [news_row(i, "2026-10-04T08:00:00+00:00") for i in ids])
    write_rows(weekend, "news", date(2026, 10, 4), [news_row(f"b{index}", "2026-10-04T08:00:00+00:00", tickers=[])
                                                    for index in range(30)])
    background = [{**enriched(f"b{index}", stamp), "summary": "Market news, no watchlist impact."}
                  for index in range(30)]
    own = [{**enriched(i, stamp), "summary": f"HDFC Bank item {i} in its own words."} for i in ids]
    out = validate_news(weekend, monkeypatch, own + background)          # background may share a summary
    assert "ENRICH_TEMPLATED" not in {w["code"] for w in out["warnings"]}
    templated = [{**row, "summary": "Bank stock news;  low impact."} if index < 8 else row
                 for index, row in enumerate(own)]
    out = validate_news(weekend, monkeypatch, templated + background)    # 8 of 24 = 33% > 30%
    warning = next(w for w in out["warnings"] if w["code"] == "ENRICH_TEMPLATED")
    assert warning["detail"].startswith("8 of 24 watchlist records")
    out = validate_news(weekend, monkeypatch, templated[:19] + background)   # fewer than 20 watchlist records
    assert "ENRICH_TEMPLATED" not in {w["code"] for w in out["warnings"]}


@pytest.mark.usefixtures("weekend")
def test_claims_window_reaches_back_to_the_last_enrichment():
    con = connect(MARKET)
    clusters = {"window_hours": 72, "lookback_hours": 144}
    # Friday 02:30 to Tuesday 02:45 after a Monday holiday: 96.25 h + 1 h
    tuesday = pd.Timestamp("2026-10-06T02:45:00+00:00")
    assert claim_sources.claims_window_hours(con, tuesday, clusters) == pytest.approx(97.25)
    # a normal next-day run keeps the configured 72 h
    assert claim_sources.claims_window_hours(con, pd.Timestamp("2026-10-03T02:45:00+00:00"), clusters) == 72.0
    # at most the clusters' lookback
    assert claim_sources.claims_window_hours(con, pd.Timestamp("2026-10-09T02:45:00+00:00"), clusters) == 144.0


# ---------- the news-only light run ----------

AGENT_STEPS = ("claims.py", "lessons.py", "agent_reasoning.py", "report.py", "notify_slack.py", "collect_prices.py",
               "ranges.py", "features.py", "context.py", "score_predictions.py", "graph.py", "spotcheck.py")


def test_light_run_steps_are_news_only():
    allowed = {"collect_news.py", "collect_nse_india.py", "collect_articles.py", "news_clusters.py", "validate.py"}
    for market in ("india", "us"):
        scripts = [command[0] for _name, command in news_light_run.steps(market)]
        assert set(scripts) <= allowed and not set(scripts) & set(AGENT_STEPS)
        assert scripts[0] == "collect_news.py" and scripts[-1] == "validate.py"
    india = dict(news_light_run.steps("india"))
    assert india["collect_nse_india"] == ["collect_nse_india.py", "--only", "announcements"]
    assert "collect_nse_india" not in dict(news_light_run.steps("us"))
    assert dict(news_light_run.steps("us"))["validate_news_collect"] == ["validate.py", "--stage", "news_collect"]


def test_light_run_summary_and_commit_paths(root):
    for kind in ("news", "news_runs", "prices", "news_clusters"):
        (root / "data" / "us" / kind).mkdir(parents=True)
        if kind != "news_clusters":                                  # an empty folder is not listed
            (root / "data" / "us" / kind / "x.jsonl").write_text("{}\n")
    calls = []

    def runner(command, market, summary_path):
        calls.append((command[0], market))
        name = summary_path.stem
        body = {"collect_news": {"new_items": 4, "window": {"google_when": "1d"}},
                "validate_news_collect": {"ok": True, "failures": [], "warnings": []}}.get(name, {})
        summary_path.write_text(json.dumps(body))
        return 0

    (root / "work" / "steps").mkdir(parents=True)
    (root / "work" / "steps" / "collect_nse_india.json").write_text('{"market": "india"}')   # an earlier run's
    out = news_light_run.light_run("us", runner)
    assert [call[0] for call in calls] == ["collect_news.py", "collect_articles.py", "news_clusters.py", "validate.py"]
    assert out["validate_ok"] and out["new_items"] == 4 and out["window"] == {"google_when": "1d"}
    assert out["commit_paths"] == ["data/us/news", "data/us/news_runs"]          # never prices
    assert sorted(p.name for p in (root / "work" / "steps").iterdir()) == [
        "collect_articles.json", "collect_news.json", "news_clusters.json", "validate_news_collect.json"]


LIGHT_YAML = """
market: {market}
name: Light run test market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols: {{}}
sectors:
  Banks: [JPM]
tickers:
  JPM: {{name: JPMorgan}}
news:
  outlets:
    - {{name: Fixture, url: '{feed}', category: general}}
"""


SITE_PATCH = (
    "import os\n"
    "import feedparser\n"
    "_real_parse = feedparser.parse\n"
    "feedparser.parse = lambda url, *args, **kwargs: _real_parse(os.environ['LIGHT_RUN_FEED'])\n"
)


def test_light_run_end_to_end_appends_only(tmp_path):
    """scripts/collect_news_only.py twice on a feed read from a local file (a sitecustomize swaps feedparser.parse,
    nothing reaches the network): it writes only news kinds, every file of the first run is a prefix of the same
    file after the second (append-only), the second run's window starts at the first, and the gate passes."""
    root, cfg, market = tmp_path / "repo", tmp_path / "config", "lightmkt"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(SITE_PATCH)
    feed = tmp_path / "feed.xml"
    now = datetime.now(UTC)

    def write_feed(titles):
        items = "".join(
            f"<item><title>{title}</title><link>https://www.example.com/{slug(title)}</link>"
            f"<pubDate>{now.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
            for title in titles)
        feed.write_text(f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{items}</channel></rss>')

    (cfg / "markets" / f"{market}.yaml").write_text(
        LIGHT_YAML.format(market=market, feed="https://feeds.example.com/rss.xml"))
    for name in ("ranges.yaml", "settings.yaml", "events.yaml", "validate.yaml", "news_sources.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "LIGHT_RUN_FEED": str(feed),
           "PYTHONPATH": str(site)}
    env.pop("MB_NOW", None)

    def light():
        done = subprocess.run([sys.executable, str(SCRIPTS / "collect_news_only.py"), "--market", market],
                              cwd=SCRIPTS, env=env, capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stderr[-3000:] + done.stdout[-3000:]
        return json.loads(done.stdout)

    write_feed(["JPMorgan opens a new office", "Markets wait for the jobs report"])
    out = light()
    first = {path: path.read_bytes() for path in (root / "data").rglob("*") if path.is_file()}
    assert {path.relative_to(root / "data" / market).parts[0] for path in first} <= {
        "news", "news_runs", "news_articles", "news_clusters"}
    assert out["new_items"] == 2 and out["validate_ok"] and out["window"]["reason"] == "first_run"
    assert [step["step"] for step in out["steps"]] == [
        "collect_news", "collect_articles", "news_clusters", "validate_news_collect"]
    write_feed(["JPMorgan opens a new office", "JPMorgan hires a new CFO"])
    out = light()
    assert out["new_items"] == 1 and out["window"]["reason"] == "since_last_run" and out["validate_ok"]
    for path, content in first.items():
        assert path.read_bytes().startswith(content), path      # nothing rewritten, only appended
    assert out["failures"] == []
    folders = {path.relative_to(root).parent.parent.parent.as_posix() for path in (root / "data").rglob("*.jsonl")}
    assert set(out["commit_paths"]) == folders and {f"data/{market}/news", f"data/{market}/news_runs"} <= folders
    assert folders <= {f"data/{market}/{kind}" for kind in ("news", "news_runs", "news_articles", "news_clusters")}


def test_news_collect_gate_flags_a_missing_or_failed_run(root, monkeypatch):
    monkeypatch.setenv("MB_NOW", "2026-10-05T08:00:00+00:00")
    cfg = {"market": MARKET, "tickers": WATCHLIST["tickers"], "symbols": {}, "sectors": {}, "news": {}}
    monkeypatch.setattr(cli, "run_status", lambda _cfg: {
        "session_date": "2026-10-05", "previous_session": "2026-10-02", "late_run": False, "in_session": False,
        "trading_day": False})
    out = cli.run(cfg, "news_collect")
    assert "NOT_FETCHED" in {w["code"] for w in out["warnings"]}
    write_rows(root, "news_runs", date(2026, 10, 5), [{**run_row("2026-10-05T07:50:00+00:00", ok=False),
                                                       "window_hours": 24.0}])
    out = cli.run(cfg, "news_collect")
    warned = {w["code"] for w in out["warnings"]}
    assert "NEWS_RUN_NOT_OK" in warned and "NOT_FETCHED" not in warned and out["ok"]


# ---------- config: the added news topics ----------

ADDED = {
    "india": {"us_fed", "us_markets", "it_services", "pharma_usfda", "monsoon", "metals", "premarket"},
    "us": {"china", "europe", "japan", "semis_supply", "asia"},
}


@pytest.mark.parametrize("market", ["india", "us"])
def test_added_news_categories_are_small(market):
    categories = yaml.safe_load((REPO / "config" / "markets" / f"{market}.yaml").read_text())["news"]["categories"]
    assert ADDED[market] <= set(categories)
    for name in ADDED[market]:
        queries = categories[name]
        assert 1 <= len(queries) <= 3 and all(isinstance(query, str) and query.strip() for query in queries)
        assert not any("when:" in query for query in queries)      # the window is added by the collector


# ---------- the routine's step 7 and the light-run prompt ----------

def test_routine_step_7_uses_the_window_since_the_last_enrichment():
    text = (REPO / "routine" / "PROMPT.md").read_text()
    step7 = text[text.index("\n7. News:"):text.index("\n8. Debate:")]
    assert "python scripts/news_pending.py" in step7 and "work/news_pending.jsonl" in step7
    assert "today's `data/<market>/news/` file" not in step7
    analyst = (REPO / ".claude" / "agents" / "news-analyst.md").read_text()
    assert "work/news_pending.jsonl" in analyst and '"news-v12"' in analyst and "`background`" in analyst


def test_news_prompt_runs_no_agent_and_commits_data_only():
    text = (REPO / "routine" / "NEWS_PROMPT.md").read_text()
    assert "python scripts/collect_news_only.py" in text
    assert "notify_slack" not in text and "subagent" not in text
    assert "commit_paths" in text and "git pull --rebase origin main" in text
