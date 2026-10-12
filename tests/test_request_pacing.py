"""Request spacing and polite stops for the free data sources (marketbrief/sources/pacing.py, yahoo_pacing.py,
marketbrief/collectors/news_fetch.py): the interval is enforced between calls, a rate-limit answer stops the
source for the rest of the run and lists what was not asked, a stopped news run is not `ok` (so the next catch-up
window reaches back over it), every Yahoo call site goes through the pacer, and a static check fails when a new
module talks to an external data host outside the paced clients. Fake clocks and sleeps: nothing waits."""
from __future__ import annotations

import ast
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
from marketbrief.collectors import news as cn  # noqa: E402
from marketbrief.collectors import news_window as nw  # noqa: E402
from marketbrief.collectors import prices as collect_prices  # noqa: E402
from marketbrief.collectors import quotes as collect_quotes  # noqa: E402
from marketbrief.collectors.news_fetch import NewsPacing, google_block  # noqa: E402
from marketbrief.sources import yahoo_pacing  # noqa: E402
from marketbrief.sources.pacing import PoliteStop, RequestPacer  # noqa: E402
from test_collectors import env, run_main  # noqa: E402,F401  (the collectors' test root and fake yfinance)

UTC = timezone.utc


class FakeTime:
    """A monotonic clock that only moves when the code sleeps or the test advances it."""

    def __init__(self):
        self.now, self.sleeps = 100.0, []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


# ---------- the pacer ----------

def test_pacer_keeps_the_interval_between_request_starts():
    fake = FakeTime()
    pacer = RequestPacer(1.5, clock=fake.clock, sleep=fake.sleep)
    assert pacer.wait() == 0.0                     # the first request never waits
    fake.now += 0.4                                # a fast answer
    assert pacer.wait() == pytest.approx(1.1)      # waits out the rest of the 1.5 s
    fake.now += 2.0                                # a slow answer already spaced the next request
    assert pacer.wait() == 0.0
    assert fake.sleeps == [1.1] and pacer.requests == 3 and pacer.waited == pytest.approx(1.1)


def test_zero_interval_never_sleeps_and_the_stop_lists_each_item_once():
    fake = FakeTime()
    pacer = RequestPacer(0, clock=fake.clock, sleep=fake.sleep)
    assert [pacer.wait() for _ in range(3)] == [0.0, 0.0, 0.0] and fake.sleeps == []
    stop = PoliteStop()
    stop.trip("first")
    stop.trip("second")
    stop.skip("A")
    stop.skip("A")
    stop.skip("B")
    assert stop.stopped and stop.reason == "first" and stop.skipped == ["A", "B"]


# ---------- Google News ----------

def parsed(status=200, href="https://news.google.com/rss/search?q=x", content_type="application/xml", entries=()):
    return feedparser.FeedParserDict(status=status, href=href, headers={"content-type": content_type},
                                     entries=list(entries), bozo=False)


def test_google_block_recognises_rate_limit_answers_only():
    assert google_block(parsed(429), 429) == "http_429"
    assert google_block(parsed(503), 503) == "http_503"
    assert google_block(parsed(href="https://www.google.com/sorry/index?continue=x"), 200) == "captcha_page"
    assert google_block(parsed(content_type="text/html; charset=UTF-8"), 200) == "html_instead_of_rss"
    assert google_block(parsed(500), 500) is None                     # an ordinary failure: retried once as before
    assert google_block(parsed(404), 404) is None
    assert google_block(parsed(content_type="text/html", entries=[{"title": "t"}]), 200) is None
    assert google_block(parsed(), 200) is None


MARKET = "pacemkt"
WATCHLIST = {
    "market": MARKET,
    "tickers": {"HDFCBANK": {"name": "HDFC Bank"}, "INFY": {"name": "Infosys"}},
    "news": {
        "google_news": {"base": "https://news.google.com/rss/search", "window": "1d", "pause_seconds": 1.5,
                        "params": {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"}},
        "categories": {"macro": ["RBI policy"]},
        "outlet_pause_seconds": 0.5,
        "outlets": [{"name": "Outlet A", "url": "https://outlet-a.example/rss"},
                    {"name": "Outlet B", "url": "https://outlet-b.example/rss"}],
    },
}


def feed_xml(items: list[tuple[str, datetime]]) -> str:
    body = "".join(f"<item><title>{t}</title><link>https://x.example/{i}</link>"
                   f"<pubDate>{p.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
                   for i, (t, p) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{body}</channel></rss>'


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(common, "ROOT", tmp_path)
    return tmp_path


def stored_runs(root: Path) -> list[dict]:
    return [json.loads(line) for path in sorted((root / "data" / MARKET / "news_runs").glob("**/*.jsonl"))
            for line in path.read_text().splitlines() if line.strip()]


def run_news(monkeypatch, capsys, now: datetime, answer, fake: FakeTime | None = None):
    asked: list[str] = []

    def fake_fetch(url):
        asked.append(url)
        result = answer(url)
        return result if isinstance(result, feedparser.FeedParserDict) else feedparser.parse(result)

    monkeypatch.setattr(cn, "fetch_feed", fake_fetch)
    monkeypatch.setattr(cn, "now_utc", lambda: now)
    monkeypatch.setenv("MB_NOW", now.isoformat())
    collector = cn.NewsCollector(WATCHLIST)
    if fake is not None:
        collector.pacing = NewsPacing(WATCHLIST["news"], clock=fake.clock, sleep=fake.sleep)
    code = collector.collect()
    return code, json.loads(capsys.readouterr().out), asked


@pytest.mark.usefixtures("root")
def test_google_and_outlet_requests_are_spaced(monkeypatch, capsys):
    now = datetime(2026, 10, 5, 2, 30, tzinfo=UTC)
    fake = FakeTime()
    code, out, asked = run_news(monkeypatch, capsys, now, lambda _url: feed_xml([("HDFC Bank news", now)]), fake)
    assert code == 0 and out["google_stopped"] is None and out["google_skipped"] == []
    assert len(asked) == 5                         # 3 Google News queries, then 2 outlet feeds
    # the clock stands still between requests, so each gap is waited in full: 1.5 s (Google), 0.5 s (outlets)
    assert fake.sleeps == [1.5, 1.5, 0.5]


def test_a_429_stops_google_news_for_the_run_and_the_run_is_not_ok(root, monkeypatch, capsys):
    before = datetime(2026, 10, 4, 22, 30, tzinfo=UTC)
    _, out, _ = run_news(monkeypatch, capsys, before, lambda _url: feed_xml([]))
    assert out["ok"] and stored_runs(root)[-1]["ok"]

    now = before + timedelta(hours=4)
    limited = feedparser.FeedParserDict(status=429, href="https://news.google.com/rss/search", headers={},
                                        entries=[], bozo=True, bozo_exception="HTTP Error 429")
    code, out, asked = run_news(
        monkeypatch, capsys, now, lambda url: limited if "news.google.com" in url else feed_xml([("Outlet item", now)]))
    google_asked = [url for url in asked if "news.google.com" in url]
    assert len(google_asked) == 1                  # the 429 is not retried, and nothing else is sent to Google
    assert out["google_stopped"] == 'http_429 at gnews:"HDFC Bank" stock'
    assert out["google_skipped"] == ['gnews:"Infosys" stock', "gnews:RBI policy"]
    assert [f["status"] for f in out["failed"]] == [429]
    assert len(asked) == 3 and out["new_items"] == 1          # the outlet feeds (other hosts) are still read
    assert code == 0 and out["ok"] is False
    run = stored_runs(root)[-1]
    assert run["ok"] is False and run["google_stopped"].startswith("http_429") and run["google_skipped"] == 2
    assert run["google_queries"] == 1 and run["google_failed"] == 1

    # the next run reaches back to the last successful run, over the queries the stopped run did not ask
    later = now + timedelta(hours=4)
    window = nw.window_for(MARKET, later)
    assert window.since == before and window.reason == "since_last_run"   # not the stopped run's ran_at
    assert window.google_when == "1d" and window.max_age >= later - before  # 9 h since then: the 1d floor


@pytest.mark.usefixtures("root")
def test_a_captcha_page_mid_run_skips_the_remaining_queries(monkeypatch, capsys):
    now = datetime(2026, 10, 5, 2, 30, tzinfo=UTC)
    calls = {"google": 0}

    def answer(url):
        if "news.google.com" not in url:
            return feed_xml([])
        calls["google"] += 1
        if calls["google"] == 1:
            return feed_xml([("HDFC Bank news", now)])
        return parsed(href="https://www.google.com/sorry/index?continue=x", content_type="text/html")

    _, out, _ = run_news(monkeypatch, capsys, now, answer)
    assert calls["google"] == 2 and out["google_queries"] == 2 and out["google_failed"] == 1
    assert out["google_stopped"].startswith("captcha_page") and out["google_skipped"] == ["gnews:RBI policy"]
    assert out["ok"] is False and out["new_items"] == 1


def test_stopped_slices_are_listed_with_their_day():
    pacing = NewsPacing({})
    job = {"feed": "gnews:q", "slice": "2026-10-03"}
    assert not pacing.skip_if_stopped(job)
    assert pacing.check(job, parsed(503), 503)
    assert pacing.skip_if_stopped(job) and pacing.skip_if_stopped({"feed": "gnews:r"})
    assert pacing.summary() == {"google_stopped": "http_503 at gnews:q 2026-10-03",
                                "google_skipped": ["gnews:q 2026-10-03", "gnews:r"]}
    assert (pacing.google.min_interval, pacing.outlets.min_interval) == (1.5, 0.5)   # the defaults


# ---------- Yahoo ----------

class YFRateLimitError(Exception):
    """Stands in for yfinance.exceptions.YFRateLimitError (matched by class name)."""


def fake_yfinance(limited: set[str], asked: list[str]):
    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.plain = "value"

        def history(self, **_window):
            asked.append(self.symbol)
            if self.symbol in limited:
                raise YFRateLimitError("Too Many Requests. Rate limited. Try after a while.")
            return pd.DataFrame()

        @property
        def calendar(self):
            asked.append(f"{self.symbol}:calendar")
            return {}

    return types.SimpleNamespace(Ticker=Ticker)


def test_yahoo_calls_are_spaced_and_a_rate_limit_stops_the_rest():
    fake, asked = FakeTime(), []
    pacer = yahoo_pacing.YahooPacer(RequestPacer(0.5, clock=fake.clock, sleep=fake.sleep))
    yf = yahoo_pacing.PacedYfinance(fake_yfinance({"B"}, asked), pacer)
    yf.Ticker("A").history(period="5d")
    assert yf.Ticker("A").calendar == {}            # a property is a Yahoo request too: paced
    assert yf.Ticker("A").plain == "value"          # a plain value is no request: not paced
    with pytest.raises(YFRateLimitError):
        yf.Ticker("B").history(period="5d")
    for symbol in ("C", "D"):
        with pytest.raises(yahoo_pacing.YahooStoppedError):
            yf.Ticker(symbol).history(period="5d")
    with pytest.raises(yahoo_pacing.YahooStoppedError):
        _ = yf.Ticker("C").calendar
    assert asked == ["A", "A:calendar", "B"]        # nothing was sent after the rate limit
    assert fake.sleeps == [0.5, 0.5]                # between the three requests sent
    assert pacer.report() == {"yahoo_stopped": "rate_limited at B (YFRateLimitError)", "yahoo_skipped": ["C", "D"]}
    with pytest.raises(AttributeError):
        _ = yf.download                             # only Ticker: no other door to Yahoo
    with pytest.raises(AttributeError):
        _ = yf.Ticker("E").missing                  # getattr(ticker, name, None) keeps working


def test_rate_limit_detection():
    assert yahoo_pacing.is_rate_limit(YFRateLimitError())
    assert yahoo_pacing.is_rate_limit(RuntimeError("429 Client Error: Too Many Requests for url"))
    assert not yahoo_pacing.is_rate_limit(RuntimeError("no data for symbol, possibly delisted"))
    assert not yahoo_pacing.is_rate_limit(RuntimeError("timeout after 4290 ms"))


@pytest.mark.usefixtures("env")
def test_prices_collector_stops_after_a_rate_limit_and_reports_the_skipped(monkeypatch, capsys):
    asked: list[str] = []

    def limited_fake(limited):
        module = types.ModuleType("yfinance")
        module.Ticker = fake_yfinance(limited, asked).Ticker
        return module

    from test_collectors import MARKET as COLLECTOR_MARKET  # noqa: N811
    from marketbrief.core.market_config import load_market

    cfg_targets = list(collect_prices.PriceCollector(load_market(COLLECTOR_MARKET), "1mo").targets.values())
    monkeypatch.setitem(sys.modules, "yfinance", limited_fake({cfg_targets[1]}))
    code, out = run_main(collect_prices, monkeypatch, capsys)
    assert asked == cfg_targets[:2]                 # stopped after the second symbol's 429
    assert out["yahoo_stopped"] == f"rate_limited at {cfg_targets[1]} (YFRateLimitError)"
    assert out["yahoo_skipped"] == cfg_targets[2:]
    failed = {entry["yahoo"]: entry["error"] for entry in out["failed"]}
    assert set(failed) == set(cfg_targets)          # no bar is invented: every symbol is a gap for the gate
    assert all("stopped for this run" in failed[symbol] for symbol in cfg_targets[2:])
    assert out["new_bars"] == 0 and code == 1


@pytest.mark.usefixtures("env")
def test_quotes_summary_has_no_yahoo_keys_without_a_rate_limit(monkeypatch, capsys):
    asked: list[str] = []
    module = types.ModuleType("yfinance")
    module.Ticker = fake_yfinance(set(), asked).Ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)
    _, out = run_main(collect_quotes, monkeypatch, capsys)
    assert asked and "yahoo_stopped" not in out and "yahoo_skipped" not in out


# ---------- static checks: no external data call bypasses the paced clients ----------

# Network libraries, and the only modules under scripts/ allowed to import them. A data client imports one of
# these only inside a paced client; the services that are no data source (Slack, Neo4j, the app's revalidation,
# the MotherDuck extension download) are listed with their reason. A new import fails here until it is paced and
# listed (the review then sees it).
NETWORK_MODULES = ("yfinance", "feedparser", "requests", "httpx", "googlenewsdecoder", "urllib.request",
                   "http.client", "socket", "urllib3", "aiohttp", "curl_cffi", "pycurl", "duckdb_http")
ALLOWED_IMPORTS = {
    "scripts/marketbrief/sources/yahoo_pacing.py": {"yfinance"},          # YahooPacer (settings.yaml yahoo)
    "scripts/marketbrief/sources/rss.py": {"feedparser"},                 # called only by news.fetch_with_retry
    "scripts/marketbrief/sources/article_fetch.py": {"requests"},         # Pacer, articles.py
    "scripts/marketbrief/sources/google_news_decoder.py": {"httpx", "googlenewsdecoder"},  # interval + Pacer
    "scripts/marketbrief/sources/http.py": {"urllib.request"},            # HttpClient (pause / min_interval)
    "scripts/marketbrief/sources/nse_client.py": {"urllib.request"},      # cookie opener of the paced Nse client
    "scripts/marketbrief/sources/free_source_client.py": {"http.client"},  # exception types only
    "scripts/marketbrief/warehouse/extension.py": {"urllib.request"},     # not a data source (MotherDuck extension)
    "scripts/marketbrief/warehouse/revalidate.py": {"http.client"},       # not a data source (the app), exceptions
    "scripts/marketbrief/collectors/news.py": {"socket"},                 # default timeout only
    "scripts/marketbrief/alerts/cli.py": {"http.client"},                 # not a data source (Slack), exceptions
}
# Functions that send a request without their own pacing, and the only places allowed to call them (each paces).
GATED_CALLS = {
    "fetch_feed": {"scripts/marketbrief/collectors/news.py"},             # inside fetch_with_retry's pacer call
    "get_article_page": {"scripts/marketbrief/analytics/article_pages.py"},  # fetch_page: caller + per-hop Pacer
    "decode_google": {"scripts/marketbrief/collectors/articles.py"},      # after the Pacer's wait
    "fetch_page": {"scripts/marketbrief/collectors/articles.py"},         # after the Pacer's wait
}
# HttpClient subclasses that are no data source (no spacing required).
UNPACED_SERVICE_CLIENTS = {"SlackHttp", "Neo4jClient", "RevalidateHttp", "ExtensionDownloader"}


def script_modules():
    for path in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path.relative_to(REPO).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def imported_network_modules(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
                "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
            names = [str(node.args[0].value)]
        for name in names:
            for module in NETWORK_MODULES:
                if name == module or name.startswith(module + "."):
                    found.add(module)
    return found


def test_network_libraries_are_imported_only_by_the_paced_clients():
    offenders = {}
    for name, tree in script_modules():
        extra = imported_network_modules(tree) - ALLOWED_IMPORTS.get(name, set())
        if extra:
            offenders[name] = sorted(extra)
    assert offenders == {}, f"new network access outside the paced clients: {offenders}"
    assert yahoo_pacing.paced_yfinance.__module__ == "marketbrief.sources.yahoo_pacing"


def test_unpaced_request_functions_are_called_only_from_paced_places():
    offenders = []
    for name, tree in script_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "attr", getattr(node.func, "id", None))
                if called in GATED_CALLS and name not in GATED_CALLS[called]:
                    offenders.append(f"{name}:{node.lineno} calls {called}")
    assert offenders == []


def test_every_data_http_client_sets_a_spacing():
    seen = set()
    for name, tree in script_modules():
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            if "HttpClient" not in {getattr(base, "id", getattr(base, "attr", None)) for base in cls.bases}:
                continue
            seen.add(cls.name)
            if cls.name in UNPACED_SERVICE_CLIENTS:
                continue
            policies = [call for call in ast.walk(cls) if isinstance(call, ast.Call)
                        and getattr(call.func, "id", None) == "HttpPolicy"]
            keywords = {kw.arg for call in policies for kw in call.keywords}
            assert policies and keywords & {"pause", "min_interval"}, f"{name}::{cls.name} sends unpaced requests"
    assert {"Nse", "Edgar", "FreeSourceClient"} <= seen
    for name, tree in script_modules():                 # no bare HttpClient(...) outside the subclasses
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "HttpClient"]
        assert not calls, f"{name} builds an HttpClient without a paced subclass"


def test_every_yahoo_call_site_gets_the_paced_module():
    """Each module that asks Yahoo receives the module from paced_yfinance (main functions, the intraday fetcher,
    onboarding's sources); the fixture stand-in (offline) is the only other yfinance-shaped module."""
    users = {name for name, tree in script_modules()
             if any(isinstance(n, ast.Name) and n.id == "paced_yfinance" for n in ast.walk(tree))}
    assert users >= {
        "scripts/marketbrief/collectors/prices.py", "scripts/marketbrief/collectors/quotes.py",
        "scripts/marketbrief/collectors/events.py", "scripts/marketbrief/collectors/options.py",
        "scripts/marketbrief/model/history_cache.py", "scripts/marketbrief/intraday/quotes.py",
        "scripts/marketbrief/lifecycle/sources.py",
    }
