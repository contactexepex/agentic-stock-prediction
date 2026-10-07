"""News de-duplication (owner decisions Q45-Q47; docs/DESIGN.md section 3, "News de-duplication";
marketbrief/analytics/news_dedup.py, collectors/news.py, collectors/news_history.py, core.database.connect and the
news views in sql/views.sql): one article is stored once per market, an edited headline at the same link is a
news_updates row, the same story from different outlets stays separate, and stored duplicates are hidden on read
with their ids aliased to the item."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import feedparser
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import common  # noqa: E402
from marketbrief.analytics import news_dedup as nd  # noqa: E402
from marketbrief.analytics.news_sources import load_sources  # noqa: E402
from marketbrief.collectors import news as cn  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402

UTC = timezone.utc
MARKETS = ("dedupin", "dedupus")
NOW = datetime(2026, 10, 7, 6, 17, tzinfo=UTC)
GN = "https://news.google.com/rss/articles/"


def watchlist(market: str) -> dict:
    return {"market": market, "tickers": {"HDFCBANK": {"name": "HDFC Bank"}},
            "news": {"google_news": {"base": "https://news.google.com/rss/search", "window": "1d",
                                     "params": {"hl": "en-IN"}},
                     "categories": {"macro": ["RBI policy"]}}}


def item(title: str, link: str, source: str, host: str | None, pub: datetime) -> dict:
    return {"title": title, "link": link, "source": source, "host": host, "pub": pub}


def feed_xml(items: list[dict]) -> str:
    body = "".join(
        f"<item><title>{escape(i['title'])} - {escape(i['source'])}</title><link>{escape(i['link'])}</link>"
        f"<pubDate>{i['pub'].strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>"
        + (f'<source url="https://{i["host"]}">{escape(i["source"])}</source>' if i["host"]
           else f"<source>{escape(i['source'])}</source>")
        + "</item>"
        for i in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{body}</channel></rss>'


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(common, "ROOT", tmp_path)
    return tmp_path


def collect(monkeypatch, capsys, now: datetime, items: list[dict], market: str = MARKETS[0]) -> dict:
    """One collect_news run at `now` whose every feed answers `items` (the first feed only; the rest empty)."""
    answered = []

    def fake_fetch(url):
        answered.append(url)
        return feedparser.parse(feed_xml(items if len(answered) == 1 else []))

    monkeypatch.setattr(cn, "fetch_feed", fake_fetch)
    monkeypatch.setattr(cn, "now_utc", lambda: now)
    monkeypatch.setenv("MB_NOW", now.isoformat())
    assert cn.NewsCollector(watchlist(market)).collect() == 0
    return json.loads(capsys.readouterr().out)


def stored(root: Path, kind: str, market: str = MARKETS[0]) -> list[dict]:
    return [json.loads(line) for path in sorted((root / "data" / market / kind).glob("**/*.jsonl"))
            for line in path.read_text().splitlines() if line.strip()]


def write_rows(root: Path, kind: str, day: date, rows: list[dict], market: str = MARKETS[0]) -> None:
    path = root / "data" / market / kind / f"{day:%Y}" / f"{day:%m}" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in rows))


def news_row(news_id: str, title: str, seen: str, *, source: str, domain: str | None, url: str) -> dict:
    return {"id": news_id, "title": title, "url": url, "source": source, "published_at": seen,
            "first_seen_at": seen, "feed": "gnews:test", "category": "company", "tickers": ["HDFCBANK"],
            "primary_tickers": ["HDFCBANK"], "mentioned_tickers": [], "tag_confidence": "high",
            "source_domain": domain, "tag_version": 2}


# ---------- outlet keys and links ----------

def test_outlet_canonicalization():
    keys = nd.OutletKeys(load_sources())
    assert nd.strip_host("amp.scmp.com") == "scmp.com" and nd.strip_host("WWW.M.Example.com:443") == "example.com"
    assert nd.strip_host("m.com") == "m.com"                                 # nothing with a dot would remain
    # one outlet under two hosts, its labels and a host-like label
    assert keys.key("The Economic Times", "m.economictimes.com") == "economictimes.indiatimes.com"
    assert keys.key("The Economic Times", "economictimes.indiatimes.com") == "economictimes.indiatimes.com"
    assert keys.key("ET Markets", None) == "economictimes.indiatimes.com"     # configured name, no host
    assert keys.key("South China Morning Post", "amp.scmp.com") == keys.key("South China Morning Post", "scmp.com")
    assert keys.key("Business Today", None) == keys.key("businesstoday.in", None) == "businesstoday.in"
    assert keys.key("BBC", "bbc.co.uk") == keys.key("BBC", "bbc.com") == "bbc.com"     # same_as in the config
    assert keys.key("Yahoo Finance UK", "uk.finance.yahoo.com") == "finance.yahoo.com"
    # never two outlets as one: the same label on two unrelated hosts, unknown labels
    assert keys.key("The Week", "theweek.in") != keys.key("The Week", "theweek.com")
    assert keys.key("Daily Excelsior", None) == "label:daily excelsior" != keys.key("DT Next", None)
    assert keys.key("Reuters", "reuters.com") != keys.key("Investing.com", "investing.com")
    assert nd.same_outlet_possible("label:daily excelsior", "dailyexcelsior.com")
    assert not nd.same_outlet_possible("theweek.in", "theweek.com")
    # without the allowlist only the prefixes are stripped
    bare = nd.OutletKeys(None)
    assert bare.key("x", "m.economictimes.com") == "economictimes.com" and bare.key("Mint", None) == "label:mint"


def test_link_keys():
    assert nd.link_key(GN + "CBMiAAA?oc=5") == nd.link_key(GN + "CBMiAAA") == "news.google.com/rss/articles/CBMiAAA"
    assert nd.link_key("https://www.bbc.co.uk/news/articles/c1/?utm_source=x&at_medium=y#top") == \
        "bbc.co.uk/news/articles/c1?at_medium=y"
    assert nd.link_key("https://example.com/a?id=1") != nd.link_key("https://example.com/a?id=2")
    assert nd.link_key(None) is None and nd.link_key("not a url") is None


# ---------- the collector ----------

def test_same_outlet_two_labels_is_stored_once(root, monkeypatch, capsys):
    title = "HDFC Bank names new CFO"
    first = collect(monkeypatch, capsys, NOW, [item(title, GN + "a1", "Business Today", "www.businesstoday.in", NOW)])
    assert first["new_items"] == 1
    # four hours later the same headline under the outlet's other label and host, behind another link
    later = NOW + timedelta(hours=4)
    out = collect(monkeypatch, capsys, later, [item(title, GN + "a2", "businesstoday.in", "m.businesstoday.in", later),
                                               item(title, "https://www.businesstoday.in/x", "Business Today", None,
                                                    later)])
    assert out["new_items"] == 0 and out["duplicates_skipped"] == {"same_title": 2} and out["headline_updates"] == 0
    assert len(stored(root, "news")) == 1 and stored(root, "news_updates") == []


@pytest.mark.usefixtures("root")
def test_same_story_from_two_outlets_is_kept_twice(monkeypatch, capsys):
    title = "HDFC Bank names new CFO"
    out = collect(monkeypatch, capsys, NOW, [item(title, GN + "b1", "Reuters", "www.reuters.com", NOW),
                                             item(title, GN + "b2", "Mint", "www.livemint.com", NOW),
                                             item(title, GN + "b3", "The Week", "www.theweek.in", NOW),
                                             item(title, GN + "b4", "The Week", "www.theweek.com", NOW)])
    assert out["new_items"] == 4 and out["duplicates_skipped"] == {}
    assert len(connect(MARKETS[0]).execute("SELECT * FROM news").fetchall()) == 4


def test_edited_headline_is_one_item_plus_an_update(root, monkeypatch, capsys):
    link, rise, fall = GN + "CBMiOIL", "Oil prices rise as storms threaten supply", "Oil prices fall as IEA acts"
    collect(monkeypatch, capsys, NOW, [item(rise, link + "?oc=5", "Reuters", "www.reuters.com", NOW)])
    later = NOW + timedelta(hours=4)
    out = collect(monkeypatch, capsys, later, [item(fall, link + "?oc=5", "Reuters", "www.reuters.com", NOW),
                                               item(fall, link, "Reuters", "www.reuters.com", NOW),
                                               item("Oil slips", link, "Reuters", "www.reuters.com", NOW)])
    # more copies of the link in the same run: one headline update per item and run, the first
    assert out["new_items"] == 0 and out["headline_updates"] == 1 and out["duplicates_skipped"] == {"within_run": 2}
    news, updates = stored(root, "news"), stored(root, "news_updates")
    assert len(news) == 1 and len(updates) == 1 and set(updates[0]) == set(SCHEMAS["news_updates"][1])
    assert updates[0]["news_id"] == news[0]["id"] and updates[0]["title"] == fall
    assert updates[0]["seen_at"] == later.isoformat()
    con = connect(MARKETS[0])
    # as of a time: the headline seen by then, never a later one
    title_at = "SELECT title FROM news_asof(?::TIMESTAMPTZ)"
    assert con.execute(title_at, [NOW.isoformat()]).fetchall() == [(rise,)]
    assert con.execute(title_at, [(later - timedelta(minutes=1)).isoformat()]).fetchall() == [(rise,)]
    assert con.execute(title_at, [later.isoformat()]).fetchall() == [(fall,)]
    assert con.execute("SELECT count(*) FROM news_asof(?::TIMESTAMPTZ)", [(NOW - timedelta(hours=1)).isoformat()]
                       ).fetchone()[0] == 0
    assert con.execute("SELECT id, title FROM news").fetchall() == [(news[0]["id"], fall)]   # the clock: MB_NOW
    # the headline flips back: recorded again; the same headline again: nothing
    back = later + timedelta(hours=4)
    out = collect(monkeypatch, capsys, back, [item(rise, link, "Reuters", "www.reuters.com", NOW)])
    assert out["headline_updates"] == 1 and out["new_items"] == 0
    out = collect(monkeypatch, capsys, back + timedelta(hours=4), [item(rise, link, "Reuters", "www.reuters.com", NOW)])
    assert out["headline_updates"] == 0 and out["duplicates_skipped"] == {"same_link": 1}
    assert connect(MARKETS[0]).execute("SELECT title FROM news").fetchall() == [(rise,)]


def test_rerun_of_the_same_run_stores_nothing_new(root, monkeypatch, capsys):
    items = [item("HDFC Bank names new CFO", GN + "r1", "Mint", "www.livemint.com", NOW),
             item("HDFC Bank raises deposit rates", GN + "r2", "Reuters", "www.reuters.com", NOW)]
    assert collect(monkeypatch, capsys, NOW, items)["new_items"] == 2
    news_bytes = [path.read_bytes() for path in sorted((root / "data").rglob("news/**/*.jsonl"))]
    out = collect(monkeypatch, capsys, NOW + timedelta(minutes=5), items)
    assert out["new_items"] == 0 and out["headline_updates"] == 0 and out["duplicates_skipped"] == {"same_link": 2}
    assert [path.read_bytes() for path in sorted((root / "data").rglob("news/**/*.jsonl"))] == news_bytes
    assert not (root / "data" / MARKETS[0] / "news_updates").exists()


def test_once_per_market(root, monkeypatch, capsys):
    article = [item("RBI keeps rates unchanged", GN + "m1", "Reuters", "www.reuters.com", NOW)]
    for market in MARKETS:
        assert collect(monkeypatch, capsys, NOW, article, market)["new_items"] == 1
    for market in MARKETS:   # never twice within a market
        out = collect(monkeypatch, capsys, NOW + timedelta(hours=4), article, market)
        assert out["new_items"] == 0 and len(stored(root, "news", market)) == 1
    assert stored(root, "news", MARKETS[0])[0]["id"] == stored(root, "news", MARKETS[1])[0]["id"]


def test_match_window_is_nine_days(root, monkeypatch, capsys):
    """The 7-day catch-up cap plus 2 days: a link seen 10 days later is a new item (published_at none: kept)."""
    link = "https://www.livemint.com/markets/live"
    write_rows(root, "news", (NOW - timedelta(days=10)).date(), [news_row(
        "old1", "Markets live: Sensex opens flat", (NOW - timedelta(days=10)).isoformat(), source="Mint",
        domain=None, url=link)])
    write_rows(root, "news", (NOW - timedelta(days=8)).date(), [news_row(
        "old2", "Markets live: Nifty slips", (NOW - timedelta(days=8)).isoformat(), source="Mint", domain=None,
        url="https://www.livemint.com/markets/live2")])
    feed = feed_xml([]).replace("<channel><title>T</title>", "<channel><title>T</title>"
                                f"<item><title>Markets live: Nifty rises</title><link>{link}</link></item>"
                                "<item><title>Markets live: Nifty rallies</title>"
                                "<link>https://www.livemint.com/markets/live2</link></item>")
    monkeypatch.setattr(cn, "fetch_feed", lambda _url: feedparser.parse(feed))
    monkeypatch.setattr(cn, "now_utc", lambda: NOW)
    monkeypatch.setenv("MB_NOW", NOW.isoformat())
    cfg = {**watchlist(MARKETS[0]), "news": {"outlets": [{"name": "Livemint", "url": "https://www.livemint.com/rss"}]}}
    assert cn.NewsCollector(cfg).collect() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["new_items"] == 1 and out["headline_updates"] == 1          # live2 (8 days) is an update
    assert [row["title"] for row in stored(root, "news")][-1] == "Markets live: Nifty rises"
    con = connect(MARKETS[0])
    assert con.execute("SELECT count(*) FROM news").fetchone()[0] == 3 and \
        con.execute("SELECT count(*) FROM news_aliases").fetchone()[0] == 0


# ---------- stored duplicates on read ----------

def test_existing_duplicates_are_hidden_and_aliased(root):
    day = date(2026, 10, 5)
    rows = [
        news_row("c1", "Titan shares fall 5% after Q2 update", "2026-10-05T04:00:00+00:00", source="BusinessLine",
                 domain=None, url="https://www.thehindubusinessline.com/markets/titan/article1.ece"),
        # the same link four hours later, edited headline (stored before de-duplication existed)
        news_row("d1", "Titan shares fall 4% after Q2 update", "2026-10-05T08:00:00+00:00", source="BusinessLine",
                 domain=None, url="https://www.thehindubusinessline.com/markets/titan/article1.ece"),
        # the same headline from the same outlet under another label and host
        news_row("c2", "HDFC Bank names new CFO", "2026-10-05T04:00:00+00:00", source="The Economic Times",
                 domain="economictimes.indiatimes.com", url=GN + "x1"),
        news_row("d2", "HDFC Bank names new CFO", "2026-10-05T04:10:00+00:00", source="ET Markets", domain=None,
                 url="https://m.economictimes.com/hdfc/articleshow/1.cms"),
        # the same headline from another outlet: kept
        news_row("k1", "HDFC Bank names new CFO", "2026-10-05T04:20:00+00:00", source="Reuters",
                 domain="reuters.com", url=GN + "x2"),
    ]
    write_rows(root, "news", day, rows)
    write_rows(root, "news_enriched", day, [{"id": "d2", "analyzed_at": "2026-10-05T05:00:00+00:00", "relevance": 0.5,
                                             "sentiment": 0.2, "materiality": "high", "summary": "s"}])
    write_rows(root, "news_articles", day, [{"id": "d1", "fetched_at": "2026-10-05T09:00:00+00:00",
                                             "access": "full", "domain": "thehindubusinessline.com"}])
    write_rows(root, "news_verified", day, [{
        "id": "v1", "as_of": "2026-10-05T09:00:00+00:00", "level": "cluster", "cluster_id": "HDFCBANK-d2",
        "ticker": "HDFCBANK", "status": "corroborated", "status_ids": ["d2", "k1"],
        "id_statuses": ["corroborated", "corroborated"]}])
    write_rows(root, "news_clusters", day, [{
        "id": "HDFCBANK-d2@1", "as_of": "2026-10-05T05:00:00+00:00", "cluster_id": "HDFCBANK-d2",
        "ticker": "HDFCBANK", "news_ids": ["d2", "k1"], "n_items": 2, "inputs_until": "2026-10-05T05:00:00+00:00"}])
    con = connect(MARKETS[0])
    assert sorted(con.execute("SELECT id FROM news").fetchall()) == [("c1",), ("c2",), ("k1",)]
    assert con.execute("SELECT id, canonical_id, match FROM news_aliases ORDER BY id").fetchall() == [
        ("d1", "c1", "link"), ("d2", "c2", "title")]
    assert con.execute("SELECT count(*) FROM news_stored").fetchone()[0] == 5          # nothing deleted
    # the edited headline is the item's latest headline, from the time it was seen
    assert con.execute("SELECT title FROM news WHERE id = 'c1'").fetchone()[0] == "Titan shares fall 4% after Q2 update"
    assert con.execute("SELECT title FROM news_asof(TIMESTAMPTZ '2026-10-05 07:00:00+00') WHERE id = 'c1'"
                       ).fetchone()[0] == "Titan shares fall 5% after Q2 update"
    # a cited duplicate id still resolves (old predictions, clusters, claims)
    assert con.execute("SELECT canonical_id, title FROM news_lookup WHERE id = 'd2'").fetchone() == (
        "c2", "HDFC Bank names new CFO")
    # readers keyed by news id: enrichment, article, status and cluster membership reach the item
    assert con.execute("SELECT materiality FROM enriched_latest WHERE id = 'c2'").fetchone() == ("high",)
    assert con.execute("SELECT id FROM news_enriched_asof(TIMESTAMPTZ '2026-10-06 00:00:00+00') ORDER BY id"
                       ).fetchall() == [("c2",), ("d2",)]
    assert con.execute("SELECT access FROM news_articles_asof(TIMESTAMPTZ '2026-10-06 00:00:00+00') WHERE id = 'c1'"
                       ).fetchone() == ("full",)
    assert con.execute("SELECT status FROM news_status_ids_asof(TIMESTAMPTZ '2026-10-06 00:00:00+00') "
                       "WHERE news_id = 'c2'").fetchone() == ("corroborated",)
    assert con.execute("SELECT news_ids FROM news_clusters_latest").fetchone()[0] == ["c2", "k1"]


def test_no_look_ahead_in_the_aliases(root):
    """A row is assigned only against rows stored before it: an item stays visible until a duplicate of it exists,
    and a later row never hides an earlier one."""
    url = "https://www.livemint.com/markets/a1"
    write_rows(root, "news", date(2026, 10, 5), [
        news_row("e1", "Early headline", "2026-10-05T04:00:00+00:00", source="Mint", domain="livemint.com", url=url),
        news_row("e2", "Later headline", "2026-10-05T12:00:00+00:00", source="Mint", domain="livemint.com", url=url)])
    con = connect(MARKETS[0])
    assert con.execute("SELECT id, canonical_id FROM news_aliases").fetchall() == [("e2", "e1")]
    morning = "TIMESTAMPTZ '2026-10-05 05:00:00+00'"
    assert con.execute(f"SELECT id, title FROM news_asof({morning})").fetchall() == [("e1", "Early headline")]
    assert con.execute(f"SELECT id, title FROM news_lookup_asof({morning})").fetchall() == [("e1", "Early headline")]
    assert con.execute(f"SELECT count(*) FROM news_title_asof({morning})").fetchone()[0] == 1
    # a row stored earlier in time than the item it would duplicate is never hidden behind it
    rows = [("x2", "T", "Mint", "livemint.com", url, datetime(2026, 10, 5, 9, tzinfo=UTC)),
            ("x1", "T", "Mint", "livemint.com", url, datetime(2026, 10, 5, 8, tzinfo=UTC))]
    assigned = nd.assign(sorted(rows, key=lambda row: (row[5], row[0])), nd.OutletKeys(None))
    assert assigned == [("x1", "x1", None), ("x2", "x1", "link")]


def test_light_run_commits_the_updates_folder():
    from marketbrief.constants.validation import NEWS_COLLECT_KINDS

    assert "news_updates" in NEWS_COLLECT_KINDS and "news_updates" in SCHEMAS


# ---------- headline updates: as of a time, and scored again ----------

SEEN, UPDATED, MADE = "2026-10-05T02:00:00+00:00", "2026-10-06T16:00:00+00:00", "2026-10-06T10:00:00+00:00"


def enrichment(news_id: str, analyzed_at: str, summary: str) -> dict:
    return {"id": news_id, "analyzed_at": analyzed_at, "relevance": 0.6, "sentiment": 0.2, "novelty": 0.5,
            "materiality": "high", "event_type": "other", "urgency": "low", "geopolitical": False,
            "priced_in": False, "summary": summary, "prompt_version": "news-v10"}


def write_updated_item(root: Path) -> None:
    """Item a1 seen Monday 02:00 ("Old headline"), enriched 03:00; its headline changed Tuesday 16:00."""
    write_rows(root, "news", date(2026, 10, 5), [news_row("a1", "Old headline", SEEN, source="Mint",
                                                          domain="livemint.com", url=GN + "a1")])
    write_rows(root, "news_updates", date(2026, 10, 6), [{
        "id": "u1", "news_id": "a1", "title": "New headline", "seen_at": UPDATED, "url": GN + "a1", "source": "Mint",
        "source_domain": "livemint.com", "published_at": SEEN, "feed": "gnews:test"}])
    write_rows(root, "news_enriched", date(2026, 10, 5), [enrichment("a1", "2026-10-05T03:00:00+00:00", "old")])


def test_past_evidence_shows_the_headline_at_made_at(root):
    """Spot-check and reflector evidence read a cited item as of the call's made_at, never a later headline."""
    from marketbrief.pipeline import spotcheck
    from marketbrief.pipeline.lessons import facts

    write_updated_item(root)
    con = connect(MARKETS[0])
    rows = spotcheck.evidence_rows(con, ["a1"], MADE)
    assert [(row["id"], row["text"], row.get("enriched_summary")) for row in rows] == [("a1", "Old headline", "old")]
    assert spotcheck.evidence_rows(con, ["a1"], "2026-10-06T17:00:00+00:00")[0]["text"] == "New headline"
    assert [row["text"] for row in facts.evidence(con, ["a1"], MADE)] == ["Old headline"]


def test_a_changed_headline_is_scored_again(root, monkeypatch):
    """news_pending queues an item whose headline changed in the window after its enrichment; the news gate accepts
    the new enrichment; once stored, the item is no longer pending and readers pair the new headline with it."""
    import pandas as pd

    from marketbrief.core.settings import load_validate_config
    from marketbrief.pipeline import news_pending
    from marketbrief.pipeline.validate import gate_result
    from marketbrief.pipeline.validate.news_checks import stage_news

    write_updated_item(root)
    now = pd.Timestamp("2026-10-06T18:00:00+00:00")
    monkeypatch.setenv("MB_NOW", now.isoformat())
    con = connect(MARKETS[0])
    since, rows = news_pending.pending_rows(con, now)
    # the window starts at the newest enriched item (a1, Monday): a1 itself is in it only through its update
    assert since == pd.Timestamp(SEEN)
    assert [(row["id"], row["title"], row["headline_updated_at"]) for row in rows] == [("a1", "New headline", UPDATED)]
    # until it is scored again, readers show the headline and the latest enrichment as of the same clock
    assert con.execute("SELECT title, summary FROM news JOIN enriched_latest USING (id)").fetchall() == [
        ("New headline", "old")]
    # the analyst's file with a newer enrichment of a1 passes the gate (no ENRICH_ALREADY_STORED / UNKNOWN_ID)
    path = root / "enriched.jsonl"
    path.write_text(json.dumps(enrichment("a1", "2026-10-06T18:00:00+00:00", "new")) + "\n")
    res = gate_result.Result()
    stage_news(res, None, con, None, now, now.date(), load_validate_config(), path)
    assert res.failures == [] and res.warnings == []
    write_rows(root, "news_enriched", date(2026, 10, 6), [enrichment("a1", "2026-10-06T18:00:00+00:00", "new")])
    con = connect(MARKETS[0])
    assert news_pending.pending_rows(con, now)[1] == []
    assert con.execute("SELECT title, summary FROM news JOIN enriched_latest USING (id)").fetchall() == [
        ("New headline", "new")]
    assert con.execute("SELECT title, sentiment FROM news_ticker_day").fetchall() == [("New headline", 0.2)]
    # as of a time before the update: the old headline with the old enrichment
    assert con.execute("SELECT n.title, e.summary FROM news_asof(TIMESTAMPTZ '2026-10-06 12:00:00+00') n "
                       "JOIN news_enriched_asof(TIMESTAMPTZ '2026-10-06 12:00:00+00') e USING (id)").fetchall() == [
        ("Old headline", "old")]
    # an item enriched after its last update is not scored again
    res = gate_result.Result()
    stage_news(res, None, con, None, now, now.date(), load_validate_config(), path)
    assert [failure["code"] for failure in res.failures] == ["ENRICH_ALREADY_STORED"]


def test_recent_rows_ignore_files_after_the_clock(root, monkeypatch):
    from marketbrief.collectors.news_window import recent_rows

    write_rows(root, "news", date(2026, 10, 6), [{"id": "x1"}])
    write_rows(root, "news", date(2026, 10, 8), [{"id": "x2"}])
    monkeypatch.setenv("MB_NOW", "2026-10-07T06:00:00+00:00")
    assert [row["id"] for row in recent_rows(MARKETS[0], "news")] == ["x1"]
    monkeypatch.setenv("MB_NOW", "2026-10-08T06:00:00+00:00")
    assert [row["id"] for row in recent_rows(MARKETS[0], "news")] == ["x1", "x2"]
