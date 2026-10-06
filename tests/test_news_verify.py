"""News verification phase A (marketbrief/analytics/news_sources.py, collect_articles.py, news_clusters.py and the
news_clusters_asof macro). Offline: article pages are trimmed real pages in
tests/fixtures/articles/ (provenance in its README), Google News decoding and HTTP are fakes, and
every test runs with sockets disabled, so nothing here can reach the network."""
from __future__ import annotations

import json
import socket
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ai_replay  # noqa: E402
from marketbrief.collectors import articles as collect_articles  # noqa: E402
import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.analytics import article_extraction, article_pages, cluster_items  # noqa: E402
from marketbrief.analytics import news_clusters, news_sources, text_measures  # noqa: E402
from marketbrief.sources import google_news_decoder  # noqa: E402
import validate  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "articles"
URLS = {
    "aol": "https://www.aol.com/articles/chevron-elevates-cfo-head-oil-132520000.html",
    "bnn": "https://www.bnnbloomberg.ca/markets/oil/2026/10/05/chevron-names-jeff-gustavson-as-next-cfo/",
    "yahoo": "https://finance.yahoo.com/markets/stocks/articles/tesla-delivered-22-141-more-154841680.html",
    "mint_premium": "https://www.livemint.com/industry/banking/anup-bagchi-hdfc-bank-rbi-private-banks-bank-ceos-"
                    "banking-leadership-kaizad-bharucha-succession-plan-11790914216055.html",
    "bs_jio": "https://www.business-standard.com/companies/news/jio-platforms-likely-to-launch-ipo-on-october-21-"
              "seeks-to-raise-3-8-bn-126100500424_1.html",
    "mint_jio": "https://www.livemint.com/market/stock-market-news/jio-platforms-to-launch-3-8-billion-ipo-on-"
                "october-21-set-to-be-india-s-biggest-listing-report-11791196582417.html",
}
PAGES = {URLS["aol"]: "aol_chevron", URLS["bnn"]: "bnn_chevron", URLS["yahoo"]: "yahoo_tikr_tesla",
         URLS["mint_premium"]: "mint_hdfc_premium", URLS["bs_jio"]: "bs_jio", URLS["mint_jio"]: "mint_jio"}


def page(name: str) -> str:
    return (FIX / f"{name}.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"network access attempted: {a[:2]}")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(scope="module")
def src():
    return news_sources.load_sources()


def parse(name: str, src: news_sources.Sources) -> dict:
    url = next(u for u, n in PAGES.items() if n == name)
    return article_extraction.parse_article(page(name), url, src, src.lookup(article_pages.host_of(url))[1])


# ---------- allowlist and fetching ----------

def test_url_check(src):
    assert article_pages.url_check(URLS["bnn"], src)[0]
    assert article_pages.url_check("https://m.economictimes.com/markets/x.cms", src)[:2] == (True, "ok")
    ok, why, _ = article_pages.url_check("http://www.bnnbloomberg.ca/x", src)
    assert not ok and "not https" in why
    ok, why, _ = article_pages.url_check("https://www.marketbeat.com/x", src)
    assert not ok and "not on the allowlist" in why
    ok, why, dom = article_pages.url_check("https://www.reuters.com/x", src)     # listed, refuses cloud traffic
    assert not ok and dom == "reuters.com"
    assert not article_pages.url_check("https://www.bnnbloomberg.ca:8443/x", src)[0]
    assert not article_pages.url_check("https://evilbnnbloomberg.ca/x", src)[0]   # suffix match is per label


class FakeResponse:
    def __init__(self, status=200, html="", location=None):
        self.status_code, self._html = status, html
        self.headers = {"content-type": "text/html; charset=utf-8"}
        if location:
            self.headers["location"] = location
        self.is_redirect = location is not None
        self.encoding = "utf-8"

    def iter_content(self, n):
        b = self._html.encode("utf-8")
        for i in range(0, len(b), n):
            yield b[i:i + n]

    def close(self):
        pass


class FakeSession:
    def __init__(self, routes: dict):
        self.routes, self.calls = routes, []

    def get(self, url, **kw):
        assert kw.get("verify") is True and kw.get("allow_redirects") is False
        self.calls.append(url)
        r = self.routes.get(url)
        if r is None:
            return FakeResponse(404)
        if isinstance(r, tuple):
            return FakeResponse(r[0], location=r[1])
        return FakeResponse(200, page(r))

    def close(self):
        pass


def test_fetch_never_requests_http_or_unlisted(src):
    s = FakeSession({"https://www.livemint.com/r": (302, "https://unlisted.example.org/x"),
                     "https://www.livemint.com/h": (301, "http://www.livemint.com/x"),
                     URLS["bnn"]: "bnn_chevron"})
    assert article_pages.fetch_page(s, "http://www.livemint.com/a", src).skipped and s.calls == []
    assert article_pages.fetch_page(s, "https://www.marketbeat.com/a", src).skipped and s.calls == []
    r = article_pages.fetch_page(s, "https://www.livemint.com/r", src)       # redirect to an unlisted host: not followed
    assert r.html is None and "not on the allowlist" in r.skipped and s.calls == ["https://www.livemint.com/r"]
    r = article_pages.fetch_page(s, "https://www.livemint.com/h", src)       # redirect to http://: not followed
    assert r.html is None and "not https" in r.skipped and s.calls[-1] == "https://www.livemint.com/h"
    r = article_pages.fetch_page(s, URLS["bnn"], src)
    assert r.status == 200 and "Chevron" in r.html and r.requests == 1


# ---------- extraction ----------

def test_extraction_order_jsonld_then_trafilatura_then_newspaper(monkeypatch, src):
    called = []

    def fake(name, n):
        def f(html, url):
            called.append(name)
            return "x" * n
        return f
    ld = '<script type="application/ld+json">{"@type": "NewsArticle", "articleBody": "%s"}</script>'
    long_body, short_body = "Long body sentence. " * 60, "Short."
    monkeypatch.setitem(article_extraction.EXTRACTORS, "trafilatura", fake("trafilatura", 50))
    monkeypatch.setitem(article_extraction.EXTRACTORS, "newspaper", fake("newspaper", 900))
    a = article_extraction.parse_article(f"<html><head>{ld % long_body}</head><body></body></html>", "https://x.test", src)
    assert a["extractor"] == "jsonld" and a["access"] == "full" and called == []
    a = article_extraction.parse_article(f"<html><head>{ld % short_body}</head><body></body></html>", "https://x.test", src)
    assert a["extractor"] == "newspaper" and called == ["trafilatura", "newspaper"] and a["access"] == "full"
    called.clear()
    monkeypatch.setitem(article_extraction.EXTRACTORS, "trafilatura", fake("trafilatura", 600))
    a = article_extraction.parse_article("<html><body><p>x</p></body></html>", "https://x.test", src)
    assert a["extractor"] == "trafilatura" and called == ["trafilatura"] and a["access"] == "partial"  # < full_chars
    # per-domain order (config `extract`)
    called.clear()
    a = article_extraction.parse_article("<html><body><p>x</p></body></html>", "https://x.test", src,
                         {"extract": ["newspaper", "trafilatura"]})
    assert called == ["newspaper"] and a["extractor"] == "newspaper"


def test_real_pages_extraction(src):
    bnn, aol = parse("bnn_chevron", src), parse("aol_chevron", src)
    assert bnn["extractor"] == "jsonld" and bnn["byline"] == "Reuters Staff" and bnn["access"] == "full"
    assert aol["extractor"] == "trafilatura" and aol["provider"] == "Reuters"
    assert aol["date_published"] == "2026-10-05T13:25:20+00:00"
    assert src.detect_wire(byline=bnn["byline"], provider=bnn["provider"], text=bnn["text"]) == ("Reuters", "byline")
    assert src.detect_wire(byline=aol["byline"], provider=aol["provider"], text=aol["text"]) == ("Reuters", "provider")


def test_paywall_reads_description_only(src):
    a = parse("mint_hdfc_premium", src)
    assert a["access"] == "paywalled" and a["extractor"] == "description"
    assert a["text"].startswith("Anup Bagchi’s appointment as HDFC Bank CEO adds to a recent string")
    html = page("mint_hdfc_premium")
    assert "Announced late on 1 October" in html            # the paywalled part is in the page ...
    assert "Announced late on 1 October" not in a["text"]   # ... and never read


def test_vendor_content_is_promotional(src):
    a = parse("yahoo_tikr_tesla", src)
    assert a["provider"] == "TIKR"
    assert src.is_promotional(name=a["provider"]) == "provider TIKR"
    assert src.is_promotional(name="24/7 Wall St") and src.is_promotional(name="The Motley Fool")
    assert src.is_promotional(name="Reuters") is None


def test_reuters_copy_detected_by_shingles(src):
    """AOL (provider Reuters) and BNN Bloomberg (byline Reuters Staff) carry one Reuters story:
    6-shingle containment 0.958 on the full pages, about 0.90 on the trimmed fixtures."""
    a, b = text_measures.shingles(parse("aol_chevron", src)["text"]), text_measures.shingles(parse("bnn_chevron", src)["text"])
    assert text_measures.containment_exact(a, b) >= 0.85
    est = text_measures.estimated_containment(text_measures.minhash_hex(a), len(a), text_measures.minhash_hex(b), len(b))
    assert est >= 0.5


def test_mint_rewrite_only_caught_by_attribution(src):
    mint, bs = parse("mint_jio", src), parse("bs_jio", src)
    a, b = text_measures.shingles(mint["text"]), text_measures.shingles(bs["text"])
    assert text_measures.containment_exact(a, b) < 0.5                     # wording alone misses the rewrite
    assert text_measures.estimated_containment(text_measures.minhash_hex(a), len(a), text_measures.minhash_hex(b), len(b)) < 0.5
    assert src.detect_wire(byline=mint["byline"], provider=mint["provider"], text=mint["text"]) == ("Reuters", "attribution")
    assert src.detect_wire(byline=bs["byline"], text=bs["text"]) == ("Reuters", "byline")
    assert text_measures.sources_say(mint["text"]) and text_measures.sources_say(bs["text"])


@pytest.mark.parametrize("text,wire", [
    ("HOUSTON, Oct 5 (Reuters) - Chevron said", ("Reuters", "dateline")),
    ("Mumbai, Oct 5 (PTI) The company said", ("PTI", "dateline")),
    ("The bank plans a listing, according to a Bloomberg News report.", ("Bloomberg", "attribution")),
    ("The CEO told PTI on Monday that orders rose.", ("PTI", "attribution")),
    ("Shares rose 2%. (With inputs from PTI)", ("PTI", "attribution")),
    ("Prices rose, the company said in a statement.", (None, None)),
])
def test_wire_in_text(src, text, wire):
    assert src.wire_in_text(text) == wire


def test_wire_in_title_and_source(src):
    assert src.detect_wire(title="Chevron elevates CFO to head oil and gas operations By Reuters") == ("Reuters", "title")
    assert src.detect_wire(title="Jio Platforms IPO: $3.8 Billion Issue Set To Launch October 21, Reuters Reports") == ("Reuters", "title")
    assert src.detect_wire(title="Chevron names new CFO", source="Reuters") == ("Reuters", "source")
    assert src.detect_wire(title="Chevron names new CFO", source="BNN Bloomberg") == (None, None)


def test_numbers_and_extract(src):
    assert text_measures.numbers("raise about $3.8 billion; Rs 5,77,094 crore; up 24.7%; 486,532 cars in 2026; Q3 FY26") == \
        ["3.8e+09 usd", "5.77094e+12 inr", "24.7 pct", "486532"]
    assert text_measures.distinctive(text_measures.numbers("HDFC Bank shares rise 2% after Q3")) == set()
    assert text_measures.distinctive(text_measures.numbers("Jio seeks to raise $3.8 bn")) == {"3.8e+09 usd"}
    ext = text_measures.key_sentences(parse("bnn_chevron", src)["text"], ["Chevron"])
    assert 1 <= len(ext) <= 3 and all(len(s.split()) <= 40 for s in ext)


# ---------- collector (in-process, fake decoder and HTTP) ----------

MARKET = "nvmkt"
NOW = "2026-10-05T20:00:00+00:00"
MARKET_YAML = """
market: nvmkt
name: News verification test market
calendar: XNYS
timezone: America/New_York
currency: USD
symbols: {}
sectors:
  Energy: [CVX]
  Autos: [TSLA]
  Conglomerates: [RELIANCE]
tickers:
  CVX: {name: Chevron}
  TSLA: {name: Tesla}
  RELIANCE: {name: Reliance Industries, aliases: [Jio Platforms]}
news: {}
"""


def gn(i: int) -> str:
    return f"https://news.google.com/rss/articles/CBMi{i:04d}?oc=5"


def news_row(i: int, title: str, ticker: str, *, source: str, domain: str | None, url: str | None = None,
             conf: str = "high", seen: str = "2026-10-05T19:00:00+00:00", pub: str = "2026-10-05T14:00:00+00:00") -> dict:
    return {"id": f"n{i:02d}", "title": title, "url": url or gn(i), "source": source, "published_at": pub,
            "first_seen_at": seen, "feed": "gnews:test", "category": "company", "tickers": [ticker],
            "primary_tickers": [ticker], "mentioned_tickers": [], "tag_confidence": conf,
            "source_domain": domain, "tag_version": 2}


CVX_AOL = "Chevron elevates CFO to lead oil and gas operations"
CVX_BNN = "Chevron names Jeff Gustavson as next CFO"
JIO_BS = "Jio Platforms likely to launch IPO on October 21, seeks to raise $3.8 bn"
JIO_MINT = "Jio Platforms to launch $3.8 billion IPO on October 21, set to be India's biggest listing: Report"
JIO_BT = "Jio Platforms IPO: $3.8 Billion Issue Set To Launch October 21, Reuters Reports"


def base_news() -> list[dict]:
    return [
        news_row(1, CVX_BNN, "CVX", source="BNN Bloomberg", domain="bnnbloomberg.ca"),
        news_row(2, CVX_AOL, "CVX", source="AOL.com", domain="aol.com"),
        news_row(3, "Chevron names Gustavson CFO as Bonner moves to oil unit", "CVX", source="SuaraGarut.ID",
                 domain="suaragarut.id"),
        news_row(4, "Chevron CFO Bonner to lead oil business", "CVX", source="BNN Bloomberg", domain=None,
                 url="http://www.bnnbloomberg.ca/chevron-cfo"),
        news_row(5, "Chevron names Jeff Gustavson next CFO", "CVX", source="Reuters", domain="reuters.com"),
        news_row(6, "Tesla Delivered 22,141 More Vehicles Than It Built in Q3", "TSLA", source="Yahoo Finance",
                 domain="finance.yahoo.com"),
        news_row(7, "Tesla Q3 deliveries: what the numbers mean", "TSLA", source="Mint", domain="livemint.com"),
        news_row(8, "Tesla CFO comments on Q3 deliveries", "TSLA", source="Mint", domain="livemint.com"),
        news_row(9, "Tesla recalls vehicles in Q3 probe", "TSLA", source="Mint", domain="livemint.com"),
        news_row(10, "Tesla quarter deliveries record", "TSLA", source="Mint", domain="livemint.com"),
        news_row(11, "Chevron CFO change: what it means", "CVX", source="Barron's", domain="barrons.com", conf="low"),
        news_row(12, CVX_BNN, "CVX", source="BNN Bloomberg", domain=None),   # same article, older label-only row
        news_row(13, JIO_BS, "RELIANCE", source="Business Standard", domain="business-standard.com"),
        news_row(14, JIO_MINT, "RELIANCE", source="Mint", domain="livemint.com"),
        news_row(15, JIO_BT, "RELIANCE", source="Business Today", domain=None, conf="low"),
        news_row(16, JIO_BT, "RELIANCE", source="businesstoday.in", domain=None, conf="low"),
    ]


DECODED = {gn(1): URLS["bnn"], gn(2): URLS["aol"], gn(6): URLS["yahoo"],
           gn(7): "https://evil.example.com/tesla",          # decoded to an unlisted host
           gn(8): "http://www.livemint.com/tesla-cfo",       # decoded to plain http
           gn(9): "https://www.livemint.com/r",              # redirects off the allowlist
           gn(13): URLS["bs_jio"], gn(14): URLS["mint_jio"]}   # gn(10): decoder fails


class Env:
    def __init__(self, tmp: Path, monkeypatch):
        self.root, self.cfg, self.mp = tmp / "repo", tmp / "config", monkeypatch
        (self.cfg / "markets").mkdir(parents=True)
        (self.cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
        for name in ("news_sources.yaml", "validate.yaml", "ranges.yaml", "settings.yaml", "events.yaml"):
            (self.cfg / name).write_text((REPO / "config" / name).read_text())
        ns = self.cfg / "news_sources.yaml"   # no pacing against the fakes
        ns.write_text(ns.read_text().replace("pause_seconds: 1.5", "pause_seconds: 0"))
        monkeypatch.setattr(common, "ROOT", self.root)
        monkeypatch.setattr(common, "CONFIG", self.cfg)
        self.decoded_links: list[str] = []
        self.session = FakeSession({**{u: n for u, n in PAGES.items()},
                                    "https://www.livemint.com/r": (302, "https://unlisted.example.org/x")})

        def decoder(links, _src):
            self.decoded_links += links
            return [{"success": True, "decoded_url": DECODED[x]} if x in DECODED else
                    {"success": False, "message": "fake decode failure"} for x in links]
        monkeypatch.setattr(collect_articles, "DECODER", decoder)
        monkeypatch.setattr(collect_articles, "SESSION_FACTORY", lambda: self.session)
        self.set_now(NOW)

    def set_now(self, t: str):
        self.mp.setenv("MB_NOW", t)

    def write(self, kind: str, rows: list[dict], day: str = "2026-10-05"):
        p = self.root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def run(self, module, capsys) -> dict:
        self.mp.setattr(sys, "argv", [module.__name__, "--market", MARKET])
        assert module.main() == 0
        return json.loads(capsys.readouterr().out)

    def rows(self, kind: str) -> list[dict]:
        return [json.loads(l) for f in sorted((self.root / "data" / MARKET / kind).glob("**/*.jsonl"))
                for l in f.read_text().splitlines() if l.strip()]


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    e.write("news", base_news())
    return e


def test_collect_articles(env, capsys, src):
    s = env.run(collect_articles, capsys)
    rows = {r["id"]: r for r in env.rows("news_articles")}
    access = {k: r["access"] for k, r in rows.items()}
    assert access == {
        "n01": "full", "n02": "full", "n03": "skipped_unlisted", "n04": "skipped_unlisted", "n05": "blocked",
        "n06": "full", "n07": "skipped_unlisted", "n08": "skipped_unlisted", "n09": "skipped_unlisted",
        "n10": "undecoded", "n12": "full", "n13": "full", "n14": "full"}
    assert "n11" not in rows and "n15" not in rows               # low tag confidence: not selected
    # only allowlisted, fetchable https pages were requested; unlisted / reuters / http never
    assert sorted(env.session.calls) == sorted([URLS["bnn"], URLS["aol"], URLS["yahoo"], "https://www.livemint.com/r",
                                                URLS["bs_jio"], URLS["mint_jio"]])
    assert gn(3) not in env.decoded_links and gn(5) not in env.decoded_links and gn(12) not in env.decoded_links
    assert rows["n12"]["note"].startswith("same article as n01") and rows["n12"]["minhash"] == rows["n01"]["minhash"]
    assert rows["n09"]["final_url"] == "https://unlisted.example.org/x" and rows["n09"]["http_status"] is None
    assert rows["n05"]["http_status"] is None and "not requested" in rows["n05"]["note"]
    assert rows["n01"]["origin_wire"] == "Reuters" and rows["n02"]["origin_evidence"] == "provider"
    assert rows["n06"]["promotional"] == "provider TIKR"
    assert rows["n14"]["origin_evidence"] == "attribution" and rows["n14"]["sources_say"] is True
    assert s["by_access"]["full"] == 6 and s["requests"]["fetch"] == 6 and s["copied_same_article"] == 1
    # no article text stored: at most 3 sentences of <= 40 words; the schema and gate accept the rows
    for r in rows.values():
        assert len(r["extract"] or []) <= 3 and all(len(x.split()) <= 40 for x in r["extract"] or [])
        assert set(r) == set(SCHEMAS["news_articles"][1])
    full_text = parse("bnn_chevron", src)["text"]
    assert len(json.dumps(rows["n01"])) < len(full_text) + 1500     # extract + numbers + 1024-hex signature
    now = pd.Timestamp(NOW)
    assert validate.check_rows("news_articles", list(rows.values()), False, now, timedelta(minutes=5)) == []
    res = validate.Result()
    validate.check_articles(res, load_market(MARKET), date(2026, 10, 5))
    assert res.failures == [] and res.warnings == []
    # idempotent: a rerun writes nothing and requests nothing
    n_calls, n_lines = len(env.session.calls), len(env.rows("news_articles"))
    s2 = env.run(collect_articles, capsys)
    assert s2["written"] == 0 and len(env.session.calls) == n_calls and len(env.rows("news_articles")) == n_lines


def test_validate_flags_bad_article_rows(env, capsys):
    env.run(collect_articles, capsys)
    bad = {**env.rows("news_articles")[0], "id": "bad1", "extract": ["one two three"] * 4}
    bad2 = {**env.rows("news_articles")[0], "id": "bad2", "access": "full", "http_status": 200,
            "final_url": "http://www.bnnbloomberg.ca/x"}
    env.write("news_articles", [bad, bad2])
    res = validate.Result()
    validate.check_articles(res, load_market(MARKET), date(2026, 10, 5))
    assert [w["code"] for w in res.warnings] == ["ARTICLE_ROWS"] and "2 news_articles rows" in res.warnings[0]["detail"]


# ---------- clusters ----------

FILINGS = [
    {"id": "0000093410-26-000188", "ticker": "CVX", "cik": "93410", "form": "8-K", "filing_date": "2026-10-05",
     "accepted_at": "2026-10-05T13:01:20+00:00", "description": "8-K", "url": "https://www.sec.gov/x",
     "first_seen_at": "2026-10-05T14:00:00+00:00"},
    {"id": "0000093410-26-000190", "ticker": "CVX", "cik": "93410", "form": "4", "filing_date": "2026-10-05",
     "accepted_at": "2026-10-05T15:00:00+00:00", "description": "4", "url": "https://www.sec.gov/y",
     "first_seen_at": "2026-10-05T16:00:00+00:00"},
    {"id": "0000093410-26-000199", "ticker": "CVX", "cik": "93410", "form": "8-K", "filing_date": "2026-10-06",
     "accepted_at": "2026-10-06T01:00:00+00:00", "description": "8-K later", "url": "https://www.sec.gov/z",
     "first_seen_at": "2026-10-06T01:30:00+00:00"},
]


def clusters_by_ticker(rows: list[dict]) -> dict:
    return {r["ticker"]: r for r in rows}


def test_clusters_origins_duplicates_primaries(env, capsys):
    env.run(collect_articles, capsys)
    env.write("news", [news_row(20, "Chevron elevates CFO to head oil and gas operations By Reuters", "CVX",
                                source="Investing.com", domain="investing.com", conf="low")])
    env.write("filings", FILINGS)
    # unvetted outlet, once with its domain and once label-only (an older row): one outlet, never counted
    env.write("news", [news_row(21, "Chevron names Jeff Gustavson as new CFO", "CVX", source="The CSR Universe",
                                domain="thecsruniverse.com", conf="low"),
                       news_row(22, "Chevron names Jeff Gustavson CFO, Bonner to oil", "CVX", source="The CSR Universe",
                                domain=None, conf="low")])
    s = env.run(news_clusters, capsys)
    rows = env.rows("news_clusters")
    cvx = [r for r in rows if r["ticker"] == "CVX" and "n01" in r["news_ids"]][0]
    # AOL (provider Reuters), BNN (byline Reuters Staff), Investing ("By Reuters"), Reuters itself: one origin
    assert set(cvx["news_ids"]) >= {"n01", "n02", "n05", "n20", "n21", "n22"} and "n12" in cvx["duplicate_ids"]
    groups = {g["origin"]: g for g in cvx["origin_groups"]}
    assert set(groups["wire:Reuters"]["news_ids"]) >= {"n01", "n02", "n05", "n20"} and groups["wire:Reuters"]["vetted"]
    assert set(groups["outlet:thecsruniverse.com"]["news_ids"]) == {"n21", "n22"}
    assert groups["outlet:thecsruniverse.com"]["vetted"] is False and "outlet:label:the csr universe" not in groups
    assert cvx["origins"] == ["wire:Reuters"] and cvx["independent_origins"] == 1 and "single_source" in cvx["flags"]
    # n03 (suaragarut.id, unvetted) joins through the CSR Universe headlines; all three are informational
    assert cvx["unvetted_ids"] == ["n03", "n21", "n22"] and s["unvetted_domains"]["thecsruniverse.com"] == 2
    assert cvx["primary_ids"] == ["0000093410-26-000188"]        # not the Form 4, not the 8-K after as_of
    assert "duplicates_removed" in cvx["flags"]
    jio = [r for r in rows if r["ticker"] == "RELIANCE"][0]
    assert set(jio["news_ids"]) == {"n13", "n14", "n15"} and jio["duplicate_ids"] == ["n16"]
    assert jio["origins"] == ["wire:Reuters"] and jio["independent_origins"] == 1 and jio["unvetted_ids"] == []
    assert {"single_source", "sources_say", "duplicates_removed"} <= set(jio["flags"])
    tsla = [r for r in rows if r["ticker"] == "TSLA" and "n06" in r["news_ids"]][0]
    assert "promotional_provider" in tsla["flags"] and tsla["independent_origins"] == 0
    assert all(r["as_of"] == NOW and r["inputs_until"] <= NOW for r in rows)
    assert s["written"] == len(rows)
    assert validate.check_rows("news_clusters", rows, False, pd.Timestamp(NOW), timedelta(minutes=5)) == []
    # rerun at the same time: nothing changed, nothing appended
    assert env.run(news_clusters, capsys)["written"] == 0 and len(env.rows("news_clusters")) == len(rows)


def test_title_links():
    cfg = {"tickers": {"TSLA": {"name": "Tesla"}}}
    drop = cluster_items.drop_tokens(cfg, "TSLA")
    a, b = text_measures.title_tokens("Tesla stock rises", drop), text_measures.title_tokens("Tesla stock falls", drop)
    assert not (a & b)                                           # company name and 'stock' never link titles
    a = text_measures.title_tokens("Chevron elevates CFO to lead oil and gas operations", {"chevron"})
    b = text_measures.title_tokens("Chevron elevates CFO to head oil and gas operations By Reuters", {"chevron"})
    assert len(a & b) / len(a | b) >= 0.5


def test_shared_round_amount_alone_does_not_link(src):
    """Live 2026-10-06: 'Nvidia Spent $20 Billion on Buybacks' and 'Nvidia's $20bn licensing deal with
    Groq faces lawsuit' share only the amount: two events. The Jio titles share the amount and words."""
    cfg = {"tickers": {"NVDA": {"name": "Nvidia"}, "RELIANCE": {"name": "Reliance Industries", "aliases": ["Jio Platforms"]}}}

    def item(i, ticker, title):
        return {"id": f"x{i}", "ticker": ticker, "title": title, "source": "s", "domain": f"d{i}.com", "tier": "tier2",
                "t": pd.Timestamp("2026-10-05T10:00:00+00:00"), "seen": pd.Timestamp("2026-10-05T11:00:00+00:00"),
                "wire": None, "wire_ev": None, "provider": None, "promo": None, "canon": None, "outlet_key": f"d{i}.com",
                "article": None, "fetched": None, "say": False, "nums": text_measures.distinctive(text_measures.numbers(title)),
                "vetted": True, "read": False, "opinion": False}
    nvda = news_clusters.cluster_ticker(
        [item(1, "NVDA", "Nvidia Spent $20 Billion on Buybacks Last Quarter. Here's What That Means for You"),
         item(2, "NVDA", "Nvidia's $20bn licensing deal with Groq faces lawsuit from jilted engineers")], cfg, src)
    assert sorted(c["n_items"] for c in nvda) == [1, 1]
    jio = news_clusters.cluster_ticker([item(3, "RELIANCE", JIO_BS), item(4, "RELIANCE", JIO_MINT)], cfg, src)
    assert [c["n_items"] for c in jio] == [2]


def test_clusters_asof_has_no_lookahead(env, capsys):
    env.run(collect_articles, capsys)
    env.run(news_clusters, capsys)                               # T1 = NOW
    t2 = "2026-10-06T02:00:00+00:00"
    late = news_row(30, "Chevron elevates CFO Bonner to lead oil and gas operations", "CVX", source="Fortune",
                    domain="fortune.com", seen="2026-10-06T01:00:00+00:00", pub="2026-10-06T00:30:00+00:00", conf="low")
    env.write("news", [late], day="2026-10-06")
    # an article fetched after T1 for a T1 item
    env.write("news_articles", [{**env.rows("news_articles")[0], "id": "n03", "fetched_at": "2026-10-06T01:30:00+00:00",
                                 "access": "full", "note": "late fetch"}], day="2026-10-06")
    # a rebuild as of T1 with the later rows on disk uses none of them: nothing changes
    assert env.run(news_clusters, capsys)["written"] == 0
    env.set_now(t2)
    env.run(news_clusters, capsys)
    con = connect(MARKET)

    def cvx_ids(ts: str) -> set:
        r = con.execute("SELECT news_ids FROM news_clusters_asof(CAST(? AS TIMESTAMPTZ)) WHERE ticker = 'CVX' "
                        "AND list_contains(news_ids, 'n01')", [ts]).fetchone()
        return set(r[0]) if r else set()
    assert "n30" not in cvx_ids(NOW) and "n30" in cvx_ids(t2)
    assert cvx_ids("2026-10-05T19:59:59+00:00") == set()         # nothing computed before T1
    assert con.execute("SELECT count(*) FROM news_articles_asof(CAST(? AS TIMESTAMPTZ)) WHERE note = 'late fetch'",
                       [NOW]).fetchone()[0] == 0
    # a stored row whose inputs postdate the query time is never returned, even with an early as_of
    t1_row = [r for r in env.rows("news_clusters") if r["ticker"] == "CVX" and r["as_of"] == NOW][0]
    env.write("news_clusters", [{**t1_row, "id": "bad-inputs", "as_of": "2026-10-05T20:30:00+00:00",
                                 "inputs_until": "2026-10-06T03:00:00+00:00"}],
              day="2026-10-06")
    env.write("news_clusters", [{**t1_row, "id": "bad-seen", "as_of": "2026-10-05T20:40:00+00:00",
                                 "news_ids": t1_row["news_ids"] + ["n30"]}], day="2026-10-06")
    con = connect(MARKET)
    ids = {r[0] for r in con.execute("SELECT id FROM news_clusters_asof(CAST(? AS TIMESTAMPTZ))",
                                     ["2026-10-05T23:00:00+00:00"]).fetchall()}
    assert "bad-inputs" not in ids and "bad-seen" not in ids and t1_row["id"] in ids
    assert con.execute("SELECT count(*) FROM news_clusters_latest").fetchone()[0] >= 1


def test_ai_replay_filters_new_kinds_by_time():
    cutoff = pd.Timestamp("2026-10-06T12:15:00+00:00")
    d = date(2026, 10, 5)
    assert ai_replay.keep_row("news_articles", {"fetched_at": "2026-10-06T12:00:00+00:00"}, d, cutoff)
    assert not ai_replay.keep_row("news_articles", {"fetched_at": "2026-10-06T12:30:00+00:00"}, d, cutoff)
    assert ai_replay.keep_row("news_clusters", {"as_of": "2026-10-06T12:00:00+00:00"}, d, cutoff)
    assert not ai_replay.keep_row("news_clusters", {"as_of": "2026-10-06T13:00:00+00:00"}, d, cutoff)


def test_late_fetched_article_is_ignored_before_its_fetch(env, capsys):
    """An article fetched after T1 that would change a cluster (here: show that a Fortune item is a
    Reuters copy, so the cluster has one origin, not two) is not used by a run as of T1."""
    env.run(collect_articles, capsys)
    env.write("news", [news_row(31, "Chevron elevates CFO Bonner to lead oil and gas operations", "CVX",
                                source="Fortune", domain="fortune.com", seen="2026-10-05T19:30:00+00:00", conf="low")])
    env.run(news_clusters, capsys)                               # T1 = NOW: Fortune is its own origin
    con = connect(MARKET)

    def fortune_group(ts: str) -> dict:
        groups = con.execute("SELECT origin_groups FROM news_clusters_asof(CAST(? AS TIMESTAMPTZ)) "
                             "WHERE ticker = 'CVX' AND list_contains(news_ids, 'n31')", [ts]).fetchone()[0]
        return next(g for g in json.loads(groups) if "n31" in g["news_ids"])
    # T1: Fortune's headline is unread, so it is an unverified vetted origin of its own
    assert fortune_group(NOW)["origin"] == "outlet:fortune.com" and fortune_group(NOW)["unread_vetted"]
    t2 = "2026-10-06T02:00:00+00:00"
    late = {**[r for r in env.rows("news_articles") if r["id"] == "n01"][0], "id": "n31", "ticker": "CVX",
            "fetched_at": "2026-10-06T01:00:00+00:00", "final_url": "https://fortune.com/2026/10/05/chevron-cfo/",
            "domain": "fortune.com", "note": "late fetch"}
    env.write("news_articles", [late], day="2026-10-06")
    assert env.run(news_clusters, capsys)["written"] == 0       # rebuilt as of T1: the late article is unseen
    env.set_now(t2)
    assert env.run(news_clusters, capsys)["written"] >= 1
    con = connect(MARKET)
    assert fortune_group(NOW)["origin"] == "outlet:fortune.com"      # the T1 state is unchanged
    assert fortune_group(t2)["origin"] == "wire:Reuters"             # after the fetch: a Reuters copy


def test_clusters_asof_drops_ids_that_moved(env):
    env.write("news_clusters", [
        {"id": "X@1", "as_of": "2026-10-05T19:00:00+00:00", "cluster_id": "CVX-n01", "ticker": "CVX",
         "news_ids": ["n01", "n02"], "n_items": 2, "inputs_until": "2026-10-05T19:00:00+00:00"},
        {"id": "Y@2", "as_of": "2026-10-05T19:30:00+00:00", "cluster_id": "CVX-n02", "ticker": "CVX",
         "news_ids": ["n02", "n05"], "n_items": 2, "inputs_until": "2026-10-05T19:30:00+00:00"}])
    con = connect(MARKET)
    got = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT cluster_id, news_ids, n_items, moved_ids FROM news_clusters_asof(CAST(? AS TIMESTAMPTZ))",
        ["2026-10-05T20:00:00+00:00"]).fetchall()}
    assert got == {"CVX-n01": (["n01"], 1, ["n02"]), "CVX-n02": (["n02", "n05"], 2, [])}
    got = {r[0]: r[1] for r in con.execute("SELECT cluster_id, news_ids FROM news_clusters_asof("
                                           "CAST(? AS TIMESTAMPTZ))", ["2026-10-05T19:10:00+00:00"]).fetchall()}
    assert got == {"CVX-n01": ["n01", "n02"]}


def test_same_outlet_copy_keeps_its_own_origin(src):
    """Two stories of one outlet that share text (boilerplate, reused paragraphs) are not merged into
    the agency origin one of them cites; a copy at another outlet is."""
    a = " ".join(parse("bnn_chevron", src)["text"].split()[:60])
    b, c = parse("mint_jio", src)["text"], parse("bs_jio", src)["text"] + " " + parse("yahoo_tikr_tesla", src)["text"]

    def art(text):
        sh = text_measures.shingles(text)
        return {"shingle_count": len(sh), "minhash": text_measures.minhash_hex(sh), "access": "full"}
    arts = {1: art(a), 2: art(a + " " + c), 3: art(a + " " + b)}   # 2 and 3 share only text a: no copy
    cfg = {"tickers": {"HDFCBANK": {"name": "HDFC Bank"}}}

    def item(i, outlet, wire, title):
        return {"id": f"m{i}", "ticker": "HDFCBANK", "title": title, "source": outlet, "domain": outlet, "tier": "tier1",
                "vetted": True, "read": True, "opinion": False,
                "t": pd.Timestamp("2026-10-05T10:00:00+00:00") + pd.Timedelta(minutes=i),
                "seen": pd.Timestamp("2026-10-05T11:00:00+00:00"), "wire": wire, "wire_ev": None, "provider": None,
                "promo": None, "canon": None, "outlet_key": outlet, "article": arts[i], "fetched": None, "say": False,
                "nums": set()}
    out = news_clusters.cluster_ticker([
        item(1, "moneycontrol.com", "Reuters", "HDFC Bank shares fall after CEO pick"),
        item(2, "moneycontrol.com", None, "Brokerages bullish on HDFC Bank after Bagchi appointment"),
        item(3, "livemint.com", None, "HDFC Bank names Anup Bagchi CEO")], cfg, src)
    assert len(out) == 1
    groups = {g["origin"]: g["news_ids"] for g in out[0]["origin_groups"]}
    assert groups == {"wire:Reuters": ["m1", "m3"], "outlet:moneycontrol.com": ["m2"]}


def test_attribution_only_in_the_lede(src):
    lede = "Shares rose on Monday. The bank named a new chief. Analysts welcomed the pick. "
    assert src.wire_in_text("Reuters reported the bank plans a listing. " + lede) == ("Reuters", "attribution")
    assert src.wire_in_text(lede + "Earlier, Reuters reported the bank plans a listing.") == (None, None)
    assert src.wire_in_text(lede + "More text here. (With inputs from PTI)") == ("PTI", "attribution")


def test_clean_splits_glued_sentences():
    assert text_measures.sentences(text_measures.clean_text("He wrote a post.HDFC Bank shares fell.The index rose.")) == \
        ["He wrote a post.", "HDFC Bank shares fell.", "The index rose."]


def test_decoder_only_talks_to_google(monkeypatch, src):
    import httpx
    with pytest.raises(httpx.RequestError):
        google_news_decoder.google_only(httpx.Request("POST", "https://evil.example.com/batchexecute"))
    with pytest.raises(httpx.RequestError):
        google_news_decoder.google_only(httpx.Request("GET", "http://news.google.com/rss/articles/x"))
    google_news_decoder.google_only(httpx.Request("POST", "https://news.google.com/_/DotsSplashUi/data/batchexecute"))

    sent = []

    class FakeDecoder:   # stands in for googlenewsdecoder.GoogleDecoder: its client follows a redirect
        def __init__(self, **kw):
            def handler(request):
                sent.append(str(request.url))
                if request.url.host == "news.google.com":
                    return httpx.Response(302, headers={"location": "https://evil.example.com/next"})
                return httpx.Response(200, text="ok")
            self.client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.client.close()

        def decode_google_news_urls(self, links, interval=None):
            out = []
            for x in links:
                try:
                    self.client.post(x)
                    out.append({"success": True, "decoded_url": "https://x"})
                except httpx.HTTPError as e:
                    out.append({"success": False, "message": str(e)})
            return out
    import googlenewsdecoder
    monkeypatch.setattr(googlenewsdecoder, "GoogleDecoder", FakeDecoder)
    res = google_news_decoder.decode_google(["https://news.google.com/rss/articles/abc"], src)
    assert res[0]["success"] is False and "refused" in res[0]["message"]
    assert sent == ["https://news.google.com/rss/articles/abc"]      # the redirect off Google was never sent


def _item(i, title, *, outlet, vetted, read=False, wire=None, ev=None, promo=None, opinion=False):
    return {"id": f"v{i}", "ticker": "CVX", "title": title, "source": outlet, "domain": outlet, "tier": "tier2",
            "vetted": vetted, "read": read, "opinion": opinion,
            "t": pd.Timestamp("2026-10-05T10:00:00+00:00") + pd.Timedelta(minutes=i),
            "seen": pd.Timestamp("2026-10-05T11:00:00+00:00"), "wire": wire, "wire_ev": ev, "provider": None,
            "promo": promo, "canon": None, "outlet_key": outlet, "article": None, "fetched": None, "say": False,
            "nums": set()}


CVX_CFG = {"tickers": {"CVX": {"name": "Chevron"}}}


def test_unvetted_site_never_creates_an_agency_origin(src):
    title = "Chevron names Jeff Gustavson next CFO, Reuters reports"
    assert src.detect_wire(title=title, source="Dubious Daily", domain="dubiousdaily.xyz") == ("Reuters", "title")
    alone = news_clusters.cluster_ticker([_item(1, title, outlet="dubiousdaily.xyz", vetted=False,
                                                wire="Reuters", ev="title")], CVX_CFG, src)[0]
    assert alone["origins"] == [] and alone["independent_origins"] == 0 and alone["unvetted_ids"] == ["v1"]
    assert "no_vetted_origin" in alone["flags"] and "single_source" not in alone["flags"]
    # it may join an existing agency group, which counts once, because of the vetted read copy
    joined = news_clusters.cluster_ticker([
        _item(1, title, outlet="dubiousdaily.xyz", vetted=False, wire="Reuters", ev="title"),
        _item(2, "Chevron names Jeff Gustavson next CFO", outlet="bnnbloomberg.ca", vetted=True, read=True,
              wire="Reuters", ev="byline")], CVX_CFG, src)[0]
    assert joined["origins"] == ["wire:Reuters"] and joined["independent_origins"] == 1


def test_unread_headlines_are_unverified_origins(src):
    c = news_clusters.cluster_ticker([
        _item(1, "Chevron names Jeff Gustavson next CFO", outlet="bnnbloomberg.ca", vetted=True, read=True,
              wire="Reuters", ev="byline"),
        _item(2, "Chevron names Jeff Gustavson as next CFO", outlet="marketscreener.com", vetted=True),
        _item(3, "Chevron names Jeff Gustavson next CFO: analysis", outlet="seekingalpha.com", vetted=True,
              read=True, opinion=True)], CVX_CFG, src)[0]
    assert c["origins"] == ["wire:Reuters"] and c["independent_origins"] == 1 and c["unread_vetted_origins"] == 1
    assert {"single_source", "origins_unverified", "opinion"} <= set(c["flags"])
    only_unread = news_clusters.cluster_ticker([
        _item(1, "Chevron names Jeff Gustavson as next CFO", outlet="marketscreener.com", vetted=True),
        _item(2, "Chevron names Jeff Gustavson next CFO", outlet="cnbc.com", vetted=True)], CVX_CFG, src)[0]
    assert only_unread["independent_origins"] == 0 and only_unread["unread_vetted_origins"] == 2
    assert "no_vetted_origin" in only_unread["flags"] and "origins_unverified" in only_unread["flags"]


def test_items_vetted_read_and_opinion_from_stored_rows(env, capsys):
    env.run(collect_articles, capsys)
    env.write("news", [
        news_row(40, "Chevron CFO move: a contrarian take", "CVX", source="Seeking Alpha", domain="seekingalpha.com", conf="low"),
        news_row(41, "Chevron names new CFO", "CVX", source="Seeking Alpha", domain="seekingalpha.com", conf="low",
                 url="https://seekingalpha.com/news/4500000-chevron-names-new-cfo"),
        news_row(42, "Chevron names Jeff Gustavson next CFO, Reuters reports", "CVX", source="Dubious Daily",
                 domain="dubiousdaily.xyz", conf="low")])
    con = connect(MARKET)
    items = {i["id"]: i for i in cluster_items.load_items(con, load_market(MARKET), news_sources.load_sources(),
                                                          pd.Timestamp(NOW))}
    assert items["n40"]["opinion"] and not items["n41"]["opinion"]          # contributor piece vs news desk
    assert items["n42"]["wire"] == "Reuters" and not items["n42"]["vetted"]  # an agency named by an unvetted site
    assert items["n05"]["vetted"] and items["n01"]["read"] and not items["n05"]["read"]


def test_label_and_domain_keys_are_one_outlet(src):
    learned = news_sources.label_domains([("Pluang", None), ("pluang.com", "pluang.com"), ("The CSR Universe", "thecsruniverse.com"),
                                ("The CSR Universe", None), ("ad-hoc-news.de", None)])
    keys = {news_sources.outlet_key(news_sources.outlet_of(lab, src, learned), lab)
            for lab in ("Pluang", "pluang.com")}
    assert keys == {"pluang.com"}
    assert news_sources.outlet_key(news_sources.outlet_of("ad-hoc-news.de", src, learned), "ad-hoc-news.de") == "ad-hoc-news.de"
    assert news_sources.outlet_key(news_sources.outlet_of("The CSR Universe", src, learned), "The CSR Universe") == "thecsruniverse.com"
    assert news_sources.outlet_key(None, "Some Blog") == "label:some blog"



def test_agency_evidence_verifies_an_unread_vetted_headline(src):
    """Issue #37: an unread headline from a vetted outlet that carries agency evidence (a "By Reuters"
    title on Investing.com, which refuses cloud traffic) is a verified origin, not an unread one."""
    c = news_clusters.cluster_ticker([
        _item(1, "Chevron elevates CFO to head oil and gas operations By Reuters", outlet="investing.com",
              vetted=True, wire="Reuters", ev="title")], CVX_CFG, src)[0]
    assert c["origins"] == ["wire:Reuters"] and c["independent_origins"] == 1 and c["unread_vetted_origins"] == 0


def test_agency_source_label_vets_an_item_without_an_allowlisted_domain(env):
    """Issue #37: the agency itself (its Google News source label) is vetted even when its domain is not
    allowlisted (afp.com)."""
    src = news_sources.load_sources()
    assert src.lookup("afp.com")[0] is None
    env.write("news", [news_row(43, "Chevron names Jeff Gustavson next CFO", "CVX", source="AFP", domain="afp.com")])
    items = {i["id"]: i for i in cluster_items.load_items(connect(MARKET), load_market(MARKET), src, pd.Timestamp(NOW))}
    assert items["n43"]["vetted"] and items["n43"]["wire"] == "AFP" and items["n43"]["wire_ev"] == "source"


def test_unvetted_item_inside_a_vetted_group_is_listed(src):
    """Issue #37: an unvetted item that joined a vetted agency group is still listed in unvetted_ids."""
    title = "Chevron names Jeff Gustavson next CFO, Reuters reports"
    c = news_clusters.cluster_ticker([
        _item(1, title, outlet="dubiousdaily.xyz", vetted=False, wire="Reuters", ev="title"),
        _item(2, "Chevron names Jeff Gustavson next CFO", outlet="bnnbloomberg.ca", vetted=True, read=True,
              wire="Reuters", ev="byline")], CVX_CFG, src)[0]
    assert c["independent_origins"] == 1 and c["unvetted_ids"] == ["v1"]


def test_label_letters_never_map_to_an_allowlisted_domain(src):
    """Issue #37: a label-only row whose letters equal an allowlisted domain's first part ("BNNBloomberg",
    not a configured name) is not mapped to that domain: vetting comes from a configured name or the
    row's own domain. An unlisted domain is still learned this way ("Pluang" -> pluang.com)."""
    pairs = [("BNNBloomberg", None), ("BNN Bloomberg", "bnnbloomberg.ca"), ("Pluang", None),
             ("pluang.com", "pluang.com")]
    assert src.lookup("bnnbloomberg.ca")[0] and src.domain_of_label("BNNBloomberg") is None
    assert news_sources.label_domains(pairs)["bnnbloomberg"] == "bnnbloomberg.ca"          # without the guard
    learned = news_sources.label_domains(pairs, src)
    assert "bnnbloomberg" not in learned and learned["pluang"] == "pluang.com"
