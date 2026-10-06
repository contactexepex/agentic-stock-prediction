"""News ticker tagging (scripts/news_tags.py): plain-text summaries (no tag from news.google.com
links), precise names with per-ticker exclusions, Google News dedupe by title + source domain,
and the re-tag on read of stored rows (the `news` view over `news_stored`)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from news_tags import TAG_VERSION, Tagger, item_id, plain_text, source_domain  # noqa: E402

GNEWS_SUMMARY = ('<a href="https://news.google.com/rss/articles/CBMigAFBVV95cUxOZ2JWNUhN?oc=5" '
                 'target="_blank">{title}</a>&nbsp;&nbsp;<font color="#6f6f6f">{source}</font>')


@pytest.fixture(scope="module")
def us():
    return Tagger(load_market("us"))


@pytest.fixture(scope="module")
def india():
    return Tagger(load_market("india"))


def gnews(tagger: Tagger, title: str, source: str = "Barron's") -> set[str]:
    return tagger.tag_item(title, GNEWS_SUMMARY.format(title=title, source=source), source)


def test_plain_text_drops_html_urls_and_outlet():
    title = "Nvidia stock hits record"
    assert plain_text(GNEWS_SUMMARY.format(title=title, source="Barron's"), "Barron's") == title
    assert plain_text("See news.google.com and https://www.google.com/x for more") == "See and for more"


def test_google_news_link_does_not_tag_googl(us):
    """Every Google News summary links news.google.com: that alone must not tag GOOGL."""
    assert gnews(us, "Nvidia stock hits record as supplier revenue booms") == {"NVDA"}
    assert gnews(us, "Fed holds rates steady", source="Reuters") == set()
    assert us.tag("read it on news.google.com today") == set()


@pytest.mark.parametrize("title", [
    "Alphabet shares jump as Google Cloud revenue beats estimates",
    "Google unveils new Gemini model",
    "GOOGL stock: what analysts expect from Alphabet's Q3",
])
def test_real_alphabet_headline_tags_googl(us, title):
    assert "GOOGL" in gnews(us, title)


@pytest.mark.parametrize("title,expected", [
    ("Kotak Mahindra Bank's net advances climb 25% YoY; deposits grow 23% in Q2", set()),
    ("Top stocks in focus tomorrow: Trent, Kotak Mahindra Bank, Vedanta", set()),
    ("Tech Mahindra wins $500 million deal", set()),
    ("Mahindra & Mahindra September auto sales rise 18%", {"M&M"}),
    ("M&M shares hit record high after SUV launch", {"M&M"}),
    ("Mahindra and Mahindra to invest Rs 1,000 crore in EV plant", {"M&M"}),
    ("M&M Financial Services disbursements up 5%", set()),
    ("SML Mahindra declares dividend at AGM", set()),
    ("Mahindra SUV sales rise 21% in CY2026", {"M&M"}),
    ("Kotak Mahindra Bank and Mahindra & Mahindra in focus", {"M&M"}),
])
def test_mahindra_precision(india, title, expected):
    assert gnews(india, title, source="ET Markets") & {"M&M"} == expected


@pytest.mark.parametrize("title,expected", [
    ("UP Rajya Sabha elections: BJP releases list of 8 candidates", set()),   # query hit, no mention
    ("ITC Hotels shares rise 3%", set()),
    ("ITC shares rise after cigarette tax clarity", {"ITC"}),
    ("L&T Finance Q2 disbursements jump", set()),
    ("L&T bags order worth Rs 5,000 crore", {"LT"}),
    ("Reliance Industries, Tata Steel lead Sensex gains", {"RELIANCE", "TATASTEEL"}),
    ("Dr Reddy’s gets USFDA nod", {"DRREDDY"}),
])
def test_india_names(india, title, expected):
    assert gnews(india, title, source="Mint") == expected


@pytest.mark.parametrize("title,expected", [
    ("Progressive policies dominate the debate", set()),
    ("Progressive Corp reports September results", {"PGR"}),
    ("Elon Musk's SpaceX valuation soars", set()),
    ("Supreme Court revisits Chevron deference", set()),
    ("Chevron raises dividend", {"CVX"}),
    ("New meta-analysis questions supplement benefits", set()),
])
def test_us_ambiguous_words(us, title, expected):
    assert gnews(us, title, source="AP") == expected


def test_item_id_uses_source_domain():
    assert source_domain("https://www.businesstoday.in/") == "businesstoday.in"
    assert source_domain("https://businesstoday.in") == "businesstoday.in"
    t = "HDFC Bank shares slip 2% despite CEO clarity"
    assert item_id(t, "Business Today", "businesstoday.in") == item_id(t + " ", "businesstoday.in", "businesstoday.in")
    assert item_id(t, "Business Today", None) != item_id(t, "businesstoday.in", None)


# ---------- collector: dedupe and stored fields ----------

MARKET = "tagmkt"
MARKET_YAML = """
market: tagmkt
name: Tag test market
calendar: XNSE
timezone: Asia/Kolkata
currency: INR
symbols: {}
sectors:
  Banks: [HDFCBANK]
  Autos: [M&M]
tickers:
  HDFCBANK: {name: HDFC Bank}
  M&M: {name: Mahindra & Mahindra, aliases: [M&M, Mahindra], news_exclude: ['Kotak Mahindra\\w*']}
news:
  outlets:
    - {name: Fixture, url: '%s', category: general}
"""


def _item(title: str, source: str, src_url: str, i: int) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    summary = GNEWS_SUMMARY.format(title=title, source=source).replace("&", "&amp;").replace("<", "&lt;")
    return (f"<item><title>{title} - {source}</title><link>https://news.google.com/rss/articles/x{i}</link>"
            f"<description>{summary}</description><pubDate>{now}</pubDate>"
            f'<source url="{src_url}">{source}</source></item>')


def _run(root: Path, cfg: Path) -> dict:
    env = {**os.environ, "MB_ROOT": str(root), "MB_CONFIG": str(cfg), "MB_MARKET": MARKET}
    r = subprocess.run([sys.executable, str(SCRIPTS / "collect_news.py")], cwd=SCRIPTS, env=env,
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_collector_dedupes_source_labels_and_tags_plain_text(tmp_path):
    root, cfg = tmp_path / "repo", tmp_path / "config"
    (root / "data").mkdir(parents=True)
    (cfg / "markets").mkdir(parents=True)
    t1 = "HDFC Bank shares slip 2% despite CEO clarity"
    t2 = "Kotak Mahindra Bank deposits grow 23% in Q2"
    feed = tmp_path / "feed.xml"
    feed.write_text('<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
                    + _item(t1, "Business Today", "https://www.businesstoday.in", 0)
                    + _item(t1, "businesstoday.in", "https://businesstoday.in/", 1)
                    + _item(t2, "Mint", "https://www.livemint.com", 2)
                    + "</channel></rss>")
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML % feed)
    for name in ("ranges.yaml", "settings.yaml", "events.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    assert _run(root, cfg)["new_items"] == 2           # one article under two source labels
    rows = [json.loads(l) for f in (root / "data" / MARKET / "news").glob("**/*.jsonl")
            for l in f.read_text().splitlines()]
    by_title = {r["title"]: r for r in rows}
    assert set(by_title) == {t1, t2}
    assert by_title[t1]["tickers"] == ["HDFCBANK"] and by_title[t1]["source_domain"] == "businesstoday.in"
    assert by_title[t2]["tickers"] == []               # "Kotak Mahindra" is not M&M
    assert all(r["tag_version"] == TAG_VERSION for r in rows)
    assert set(rows[0]) == set(SCHEMAS["news"][1])
    assert _run(root, cfg)["new_items"] == 0           # second run: all seen


def test_collector_same_title_from_two_domains_is_two_rows(tmp_path):
    root, cfg = tmp_path / "repo", tmp_path / "config"
    (cfg / "markets").mkdir(parents=True)
    t = "HDFC Bank shares slip 2% despite CEO clarity"
    feed = tmp_path / "feed.xml"
    feed.write_text('<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
                    + _item(t, "Business Today", "https://www.businesstoday.in", 0)
                    + _item(t, "Mint", "https://www.livemint.com", 1) + "</channel></rss>")
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML % feed)
    for name in ("ranges.yaml", "settings.yaml", "events.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    assert _run(root, cfg)["new_items"] == 2
    rows = [json.loads(l) for f in (root / "data" / MARKET / "news").glob("**/*.jsonl")
            for l in f.read_text().splitlines()]
    assert sorted(r["source_domain"] for r in rows) == ["businesstoday.in", "livemint.com"]
    assert len({r["id"] for r in rows}) == 2


def test_collector_skips_items_stored_under_the_old_id(tmp_path):
    """Rows stored before ids used the source domain (title + source label) are not re-collected."""
    from news_tags import article_id
    root, cfg = tmp_path / "repo", tmp_path / "config"
    (cfg / "markets").mkdir(parents=True)
    t = "HDFC Bank shares slip 2% despite CEO clarity"
    feed = tmp_path / "feed.xml"
    feed.write_text('<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
                    + _item(t, "Business Today", "https://www.businesstoday.in", 0) + "</channel></rss>")
    (cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML % feed)
    for name in ("ranges.yaml", "settings.yaml", "events.yaml"):
        (cfg / name).write_text((REPO / "config" / name).read_text())
    today = datetime.now(timezone.utc).date()
    p = root / "data" / MARKET / "news" / f"{today:%Y}" / f"{today:%m}" / f"{today}.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"id": article_id(t, "Business Today"), "title": t, "tickers": ["HDFCBANK"]}) + "\n")
    assert _run(root, cfg)["new_items"] == 0


# ---------- re-tag on read ----------

def test_news_view_retags_old_rows_without_editing_them(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    d = tmp_path / "data" / "us" / "news" / "2026" / "10"
    d.mkdir(parents=True)
    rows = [
        # old Google News row: GOOGL from the news.google.com link in its summary
        {"id": "a", "title": "Nvidia stock hits record", "feed": 'gnews:"Nvidia" stock', "tickers": ["GOOGL", "NVDA"]},
        # old query-only tag: never names the company
        {"id": "b", "title": "Stocks to watch this week", "feed": 'gnews:"Walmart" stock', "tickers": ["GOOGL", "WMT"]},
        {"id": "c", "title": "Alphabet beats estimates", "feed": "gnews:oil prices", "tickers": ["GOOGL"]},
        # press-release wire: stored tags kept
        {"id": "d", "title": "Results release", "feed": "PR Newswire", "tickers": ["MRK"]},
        # tagged by the current tagger: unchanged
        {"id": "e", "title": "Stocks to watch", "feed": "gnews:x", "tickers": ["CAT"], "tag_version": TAG_VERSION},
    ]
    f = d / "2026-10-05.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    before = f.read_bytes()
    con = connect("us")
    got = dict(con.execute("SELECT id, tickers FROM news ORDER BY id").fetchall())
    assert got == {"a": ["NVDA"], "b": [], "c": ["GOOGL"], "d": ["MRK"], "e": ["CAT"]}
    stored = dict(con.execute("SELECT id, tickers FROM news_stored ORDER BY id").fetchall())
    assert stored["a"] == ["GOOGL", "NVDA"] and stored["b"] == ["GOOGL", "WMT"]
    by_ticker = con.execute("SELECT ticker, count(*) FROM news_ticker_day GROUP BY 1 ORDER BY 1").fetchall()
    assert by_ticker == [("CAT", 1), ("GOOGL", 1), ("MRK", 1), ("NVDA", 1)]
    assert f.read_bytes() == before                     # data files are never edited


# ---------- headline first: primary vs mentioned, tag_confidence (issue #29) ----------

def test_title_match_ignores_summary(us):
    """A company in the title is primary; the summary is not read when the title names one."""
    tags = us.classify_item("Nvidia stock hits record", "<p>Analysts compare it with Apple and Tesla.</p>", "AP")
    assert tags == {"tickers": ["NVDA"], "primary_tickers": ["NVDA"], "mentioned_tickers": [],
                    "tag_confidence": "high"}


def test_summary_only_match_is_mentioned_low(us):
    tags = us.classify_item("Chip stocks rally into the close",
                            '<p>Gains were led by <a href="https://news.google.com/x">Nvidia</a>.</p>', "AP")
    assert tags == {"tickers": ["NVDA"], "primary_tickers": [], "mentioned_tickers": ["NVDA"],
                    "tag_confidence": "low"}
    # a summary that is only a Google News link + outlet tags nothing (no source name, no URL)
    assert us.classify_item("Markets wrap", GNEWS_SUMMARY.format(title="Markets wrap", source="Google Finance"),
                            "Google Finance")["tickers"] == []


@pytest.mark.parametrize("title,primary,mentioned,conf", [
    ("Walmart and Costco raise wages", ["COST", "WMT"], [], "low"),            # several title companies
    ("Amazon vs. Alphabet: which AI cloud stock is better?", [], ["GOOGL"], "low"),   # comparison
    ("Nvidia versus Apple: the trillion-dollar race", [], ["AAPL", "NVDA"], "low"),
    ("Nvidia, Okta and Cognex on CNBC's Final Trades", [], ["NVDA"], "low"),   # list
    ("Why did NVDA, HPE, CRWD stocks rise to 52-week highs?", [], ["NVDA"], "low"),
    ("Accenture beats; peers Apple, Tesla and Nvidia rally", [], ["AAPL", "NVDA", "TSLA"], "low"),
    ("Alphabet (NASDAQ:GOOGL) posts negative free cash flow", ["GOOGL"], [], "high"),
    ("JPMorgan raises Tesla price target", ["TSLA"], ["JPM"], "low"),          # broker acts on Tesla
])
def test_roles(us, title, primary, mentioned, conf):
    tags = us.classify(title)
    assert (tags["primary_tickers"], tags["mentioned_tickers"], tags["tag_confidence"]) == (primary, mentioned, conf)
    assert tags["tickers"] == sorted(primary + mentioned)


@pytest.mark.parametrize("title,primary,mentioned", [
    # analyst actions: the bank acts on another company
    ("JPMorgan cuts target for Aon stock to $400", [], ["JPM"]),
    ("Bank of America Upgrades DraftKings to Buy With $27 Price Target", [], ["BAC"]),
    ("Aon price target raised by JPMorgan", [], ["JPM"]),
    ("JPMorgan keeps Overweight rating on Snowflake", [], ["JPM"]),
    ("BofA initiates coverage of Rivian with Neutral", [], ["BAC"]),
    ("Tesla price target raised by JPMorgan", ["TSLA"], ["JPM"]),
    # holdings
    ("36,399 Shares of Global Partners LP $GLP Bought by Bank of America Corp", [], ["BAC"]),
    ("JPMorgan Chase & Co. boosts stake in Vistra", [], ["JPM"]),
    ("Nvidia takes stake in Intel", [], ["NVDA"]),
    # venues
    ("Crown Castle to present at Bank of America 2026 conference", [], ["BAC"]),
    ("Charity gala held at Bank of America Plaza", [], ["BAC"]),
    # broker research arm, "at BofA", comments
    ("BofA Securities sees upside in Snowflake", [], ["BAC"]),
    ("Strategist at BofA says small caps are cheap", [], ["BAC"]),
    ("JPMorgan sees S&P 500 at 8,000 by year-end", [], ["JPM"]),
    ("Equities can withstand higher yields, says JPMorgan", [], ["JPM"]),
    ("JPMorgan's October stock picks diversify across sectors", [], ["JPM"]),
    ("Fifth Third stock faces JPMorgan target cut to USD 58", [], ["JPM"]),
    ("JPMorgan keeps Buy on Sabesp stock at USD 35.00", [], ["JPM"]),
    ("DraftKings jumps 5% after Bank of America upgrade", [], ["BAC"]),
    ("Bank of America buys 74,760 shares in Capital City Bank Group stock", [], ["BAC"]),
    ("JPMorgan reports 2.93% voting rights in Adtran Networks stock", [], ["JPM"]),
    ("JPMorgan price target raised to $350 at Wells Fargo", ["JPM"], []),
    # the company itself is the subject
    ("JPMorgan raises dividend after third-quarter profit beat", ["JPM"], []),
    ("JPMorgan says its trading revenue jumped", ["JPM"], []),
    ("JPMorgan stock price target raised by Wells Fargo", ["JPM"], []),
    ("Layoffs at JPMorgan hit 500 staff", ["JPM"], []),
    ("Tesla cuts prices; analysts trim price targets", ["TSLA"], []),
    ("Costco downgraded from Hold to Sell due to high valuation", ["COST"], []),
])
def test_actor_or_holder_is_mentioned(us, title, primary, mentioned):
    tags = us.classify(title)
    assert (tags["primary_tickers"], tags["mentioned_tickers"]) == (primary, mentioned)
    if not primary:
        assert tags["tag_confidence"] == "low"


def test_actor_on_an_indian_stock_is_not_us_primary(us, india):
    title = "Bajaj Finance share price target raised by JPMorgan"
    assert us.classify(title)["primary_tickers"] == [] and us.classify(title)["mentioned_tickers"] == ["JPM"]
    assert india.classify(title)["tickers"] == []


@pytest.mark.parametrize("title,expected", [
    ("Weaker tourism trends are hitting these stocks (DAL:NYSE)", ["DAL"]),
    ("Airline (DAL) shares fall on fuel costs", ["DAL"]),
    ("Airline (NYSE: DAL) shares fall", ["DAL"]),
    ("Airline (dal) recipes", []),                         # symbols are case-sensitive
    ("GM plans new EV plant in Michigan", ["GM"]),
    ("GM crops spark debate in parliament", []),
    ("Hotel names new GM of operations", []),
])
def test_symbols_and_gm(us, title, expected):
    assert us.classify(title)["tickers"] == expected


def test_semicolon_is_not_a_list(india):
    tags = india.classify("Buy HDFC Bank; target of Rs 950: ICICI Securities")
    assert tags["primary_tickers"] == ["HDFCBANK"] and tags["tag_confidence"] == "high"


def test_india_list_title_is_mentioned(india):
    tags = india.classify("Stocks to Watch Today, October 5: HDFC Bank, Kotak Mahindra Bank, Ola Electric")
    assert tags["primary_tickers"] == [] and tags["mentioned_tickers"] == ["HDFCBANK"]
    assert tags["tag_confidence"] == "low"
    tags = india.classify("HDFC Bank shares slip 2% despite CEO clarity")
    assert tags["primary_tickers"] == ["HDFCBANK"] and tags["tag_confidence"] == "high"


def test_news_view_roles_and_ticker_day(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    d = tmp_path / "data" / "us" / "news" / "2026" / "10"
    d.mkdir(parents=True)
    ts = "2026-10-05T12:00:00+00:00"
    rows = [
        {"id": "a", "title": "Nvidia stock hits record", "feed": "gnews:x", "tickers": ["GOOGL", "NVDA"],
         "published_at": ts},
        {"id": "b", "title": "Amazon vs. Alphabet: which AI cloud stock?", "feed": "gnews:x", "tickers": ["GOOGL"],
         "published_at": ts},
        {"id": "c", "title": "Chip stocks rally", "feed": "gnews:x", "tickers": ["NVDA"], "primary_tickers": [],
         "mentioned_tickers": ["NVDA"], "tag_confidence": "low", "tag_version": TAG_VERSION, "published_at": ts},
    ]
    (d / "2026-10-05.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    con = connect("us")
    got = {r[0]: r[1:] for r in con.execute(
        "SELECT id, primary_tickers, mentioned_tickers, tag_confidence FROM news ORDER BY id").fetchall()}
    assert got == {"a": (["NVDA"], [], "high"), "b": ([], ["GOOGL"], "low"), "c": ([], ["NVDA"], "low")}
    td = con.execute("SELECT id, ticker, role, tag_confidence FROM news_ticker_day ORDER BY id").fetchall()
    assert td == [("a", "NVDA", "primary", "high"), ("b", "GOOGL", "mentioned", "low"),
                  ("c", "NVDA", "mentioned", "low")]
