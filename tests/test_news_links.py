"""Issue #478: only https:// news links are stored. Business Wire's feed gives http:// links; the collector stores
them with https:// (config/news_sources.yaml `https_links: true`, nothing requested) and skips every other
non-https entry, so one such entry never fails the news gate (NEWS_SOURCE) and with it the run."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import common  # noqa: E402
from marketbrief.analytics.news_sources import Sources, load_sources  # noqa: E402
from marketbrief.collectors import news as cn  # noqa: E402
from marketbrief.collectors.news_links import secure_link  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.pipeline.validate.gate_result import Result  # noqa: E402
from marketbrief.pipeline.validate.news_checks import check_news_sources  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "sources" / "businesswire_earnings_jpm.rss"
NOW = datetime(2026, 10, 13, 22, 10, tzinfo=timezone.utc)
MARKET = "linksus"
JPM_HTTP = ("http://www.businesswire.com/news/home/20261013832435/en/"
            "JPMorganChase-Reports-Third-Quarter-2026-Financial-Results/?feedref=abc")
WIRE = {"name": "Business Wire Earnings", "url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEF9YXA==",
        "category": "company", "watchlist_only": True}


def watchlist(outlets: list[dict]) -> dict:
    return {"market": MARKET, "tickers": {"JPM": {
        "name": "JPMorgan", "aliases": ["JPMorgan Chase", "J.P. Morgan", "Jamie Dimon", "JPM"],
        "wire_names": ["JPMorgan Chase", "JPMorgan", "J.P. Morgan"]}}, "news": {"outlets": outlets}}


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(cn, "now_utc", lambda: NOW)
    monkeypatch.setenv("MB_NOW", NOW.isoformat())
    return tmp_path


def collect(monkeypatch, capsys, cfg: dict, feed: str) -> dict:
    monkeypatch.setattr(cn, "fetch_feed", lambda _url: feedparser.parse(feed))
    assert cn.NewsCollector(cfg).collect() == 0
    return json.loads(capsys.readouterr().out)


def stored(root: Path, kind: str) -> list[dict]:
    return [json.loads(line) for path in sorted((root / "data" / MARKET / kind).glob("**/*.jsonl"))
            for line in path.read_text().splitlines() if line.strip()]


def gate(cfg: dict) -> Result:
    res = Result()
    check_news_sources(res, cfg, connect(MARKET), NOW.date())
    return res


def test_secure_link_rules():
    src = load_sources()
    assert src.lookup("www.businesswire.com")[1].get("https_links") is True
    assert secure_link(JPM_HTTP, src) == JPM_HTTP.replace("http://", "https://", 1)   # path and query kept
    assert secure_link("HTTP://WWW.BusinessWire.com:80/news/x?a=1#f", src) == "https://www.businesswire.com/news/x?a=1#f"
    https = "https://www.reuters.com/markets/x"
    assert secure_link(https, src) == https                                           # https: unchanged
    for refused in ("http://www.prnewswire.com/news-releases/x.html",   # vetted, but no https_links
                    "http://example.com/x",                             # not on the allowlist
                    "http://www.businesswire.com:8080/news/x",          # explicit port
                    "http://user:pw@www.businesswire.com/news/x",       # credentials
                    "ftp://www.businesswire.com/news/x", "javascript:alert(1)", "", None,
                    "https://user@www.reuters.com/x", "https:///no-host"):
        assert secure_link(refused, src) is None, refused
    assert secure_link(JPM_HTTP, None) is None                                        # no allowlist: no upgrade
    assert secure_link(JPM_HTTP, Sources({"domains": {"businesswire.com": {"tier": "primary"}}})) is None


def test_business_wire_item_is_stored_with_https_and_passes_the_gate(root, monkeypatch, capsys):
    """The real feed of 2026-10-13 (every link http://): the JPMorganChase release is stored with https:// and the
    news gate passes; before the fix the same entry was stored with http:// and blocked NEWS_SOURCE."""
    cfg = watchlist([WIRE])
    out = collect(monkeypatch, capsys, cfg, FIXTURE.read_text())
    assert (out["new_items"], out["upgraded_to_https"], out["skipped_not_https"]) == (1, 1, 0)
    assert out["skipped_off_watchlist"] == 2                  # the other two releases name no watchlist company
    [row] = stored(root, "news")
    assert row["tickers"] == ["JPM"] and row["feed"] == "Business Wire Earnings"
    assert row["url"].startswith("https://www.businesswire.com/news/home/20261013832435/en/JPMorganChase-Reports-")
    assert gate(cfg).failures == []
    # the same feed again (http:// links, now stored as https://): a duplicate by its link, nothing new
    out = collect(monkeypatch, capsys, cfg, FIXTURE.read_text())
    assert out["new_items"] == 0 and out["duplicates_skipped"] == {"same_link": 1}
    assert len(stored(root, "news")) == 1


def test_other_http_links_are_skipped_not_stored(root, monkeypatch, capsys):
    """An outlet whose domain has no `https_links` (PR Newswire here) and gives an http:// link: the entry is
    skipped and listed, the rest of the run is stored, and the gate passes."""
    feed = FIXTURE.read_text().replace("http://www.businesswire.com/", "http://www.prnewswire.com/")
    cfg = watchlist([{**WIRE, "name": "PR Newswire", "url": "https://www.prnewswire.com/rss/news-releases-list.rss"}])
    good = ("<item><title>JPMorgan Chase Declares Common Stock Dividend</title>"
            "<link>https://www.prnewswire.com/news-releases/jpm-dividend-302000000.html</link>"
            "<pubDate>Tue, 13 Oct 2026 20:00:00 GMT</pubDate></item>")
    out = collect(monkeypatch, capsys, cfg, feed.replace("</channel>", good + "</channel>"))
    assert (out["new_items"], out["upgraded_to_https"], out["skipped_not_https"]) == (1, 0, 1)
    [example] = out["not_https_examples"]
    assert example["feed"] == "PR Newswire" and len(example["link"]) == 120
    assert example["link"].startswith("http://www.prnewswire.com/news/home/20261013832435/en/JPMorganChase-")
    [row] = stored(root, "news")
    assert row["url"].startswith("https://") and "dividend" in row["url"]
    assert stored(root, "news_updates") == []
    assert gate(cfg).failures == []
