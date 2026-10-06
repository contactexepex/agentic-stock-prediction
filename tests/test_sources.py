"""Offline tests for the free-source collectors (issue #9): collect_macro.py (Treasury, FRED,
Cboe), collect_shorts.py (FINRA short volume and short interest), collect_flows_india.py (NSDL
FPI, NSE index closes), the new RSS outlets in collect_news.py and the context sections in
macro_context.py. Fixtures in tests/fixtures/sources are trimmed REAL responses fetched on
2026-10-05 (provenance in tests/fixtures/sources/README). A fake client stands in for the network;
collectors run in-process against a temporary MB_ROOT with the real market configs."""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.collectors import collector_store, flows_parsing, macro_parsing, news_wire, shorts_parsing  # noqa: E402
from marketbrief.collectors import flows_india as cfi  # noqa: E402
from marketbrief.collectors import macro as cm  # noqa: E402
from marketbrief.collectors import news as cn  # noqa: E402
from marketbrief.collectors import shorts as cs  # noqa: E402
import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402
from marketbrief.sources.free_source_client import FreeSourceClient  # noqa: E402
from marketbrief.utils.numbers import parse_accounting_amount  # noqa: E402
from marketbrief.pipeline import macro_sections as macro_context  # noqa: E402
from marketbrief.sources.errors import FetchError  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "sources"
TODAY = date(2026, 10, 5)        # Monday; previous US session Fri 2026-10-02, India Thu 2026-10-01 (2 Oct holiday)
NOW = "2026-10-06T01:00:00+00:00"


class FakeClient:
    """routes: list of (url substring, fixture file name | Exception). Unmatched URLs answer 404."""

    def __init__(self, routes):
        self.routes, self.calls, self.requests = routes, [], 0

    def get(self, url, *, data=None, headers=None):
        self.calls.append(url)
        self.requests += 1
        for key, target in self.routes:
            if key in url:
                if isinstance(target, Exception):
                    raise target
                return target if isinstance(target, bytes) else (FIX / target).read_bytes()
        raise FetchError(url, "HTTP 404 from test", status=404)

    def json(self, url, **kw):
        return json.loads(self.get(url, **kw))


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "root"
    (r / "data").mkdir(parents=True)
    monkeypatch.setattr(common, "ROOT", r)
    return r


def rows(root: Path, market: str, kind: str) -> list[dict]:
    return [json.loads(line) for f in sorted((root / "data" / market / kind).glob("**/*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]


def assert_schema(found: list[dict], kind: str) -> None:
    cols = set(SCHEMAS[kind][1])
    assert found, kind
    for r in found:
        assert set(r) == cols, (kind, set(r) ^ cols)


US_ROUTES = [
    ("daily-treasury-rates.csv/2026", "treasury_2026.csv"),
    ("id=BAMLH0A0HYM2", "fred_BAMLH0A0HYM2.csv"),
    ("id=T10YIE", "fred_T10YIE.csv"),
    ("id=BAMLC0A0CM", "fred_BAMLC0A0CM.csv"),
    ("2026-10-01_daily_options", "cboe_2026-10-01_daily_options.json"),
    ("2026-10-02_daily_options", "cboe_2026-10-02_daily_options.json"),
]


# ---------- parsing ----------

def test_treasury_parse_maps_tenors_and_dates():
    text = (FIX / "treasury_2026.csv").read_text()
    got = macro_parsing.parse_treasury(text, date(2026, 10, 1), NOW)
    by = {(r["series"], r["date"]): r["value"] for r in got}
    assert by[("UST_10Y", "2026-10-05")] == 5.31 and by[("UST_2Y", "2026-10-05")] == 4.84
    assert by[("UST_1.5M", "2026-10-02")] == 4.09 and by[("UST_30Y", "2026-10-01")] == 5.61
    assert min(r["date"] for r in got) == "2026-10-01"          # older rows dropped by `since`
    assert {r["series"] for r in got} >= {"UST_1M", "UST_3M", "UST_6M", "UST_1Y", "UST_5Y", "UST_20Y"}
    assert macro_parsing.tenor_series("Date") is None and macro_parsing.tenor_series("4 Mo") == "UST_4M"


def test_fred_parse_skips_missing_marker_and_reads_both_headers():
    got = macro_parsing.parse_fred((FIX / "fred_T10YIE.csv").read_text(), "T10YIE", date(2026, 9, 1), "pct", "BE", NOW)
    assert got and got[0] == {"id": "T10YIE-2026-09-21", "date": "2026-09-21", "series": "T10YIE", "name": "BE",
                              "value": 2.34, "unit": "pct", "source": "fred", "first_seen_at": NOW, "complete": True}
    old = "DATE,DGS10\n2026-10-01,4.10\n2026-10-02,.\n"
    assert [r["value"] for r in macro_parsing.parse_fred(old, "DGS10", date(2026, 1, 1), "pct", "x", NOW)] == [4.10]
    # a file for another id has no values for this one
    assert macro_parsing.parse_fred((FIX / "fred_T10YIE.csv").read_text(), "BAMLC0A0CM", date(2026, 1, 1), "pct", "x", NOW) == []


def test_cboe_parse_ratios():
    payload = json.loads((FIX / "cboe_2026-10-02_daily_options.json").read_text())
    wanted = {"TOTAL PUT/CALL RATIO": "CBOE_PC_TOTAL", "EQUITY PUT/CALL RATIO": "CBOE_PC_EQUITY",
              "SPX + SPXW PUT/CALL RATIO": "CBOE_PC_SPX", "NOT A RATIO": "X"}
    rows_, missing = macro_parsing.parse_cboe(payload, date(2026, 10, 2), wanted, NOW)
    assert {r["series"]: r["value"] for r in rows_} == {"CBOE_PC_TOTAL": 0.78, "CBOE_PC_EQUITY": 0.58, "CBOE_PC_SPX": 1.15}
    assert missing == ["NOT A RATIO"]                      # only the absent one, not the present ones
    assert all(r["complete"] is False for r in rows_)
    full, none_missing = macro_parsing.parse_cboe(payload, date(2026, 10, 2), {"TOTAL PUT/CALL RATIO": "CBOE_PC_TOTAL"}, NOW)
    assert none_missing == [] and full[0]["complete"] is True


def test_finra_volume_parse_and_trailer_check():
    cfg = load_market("us")
    text = (FIX / "CNMSshvol20261002.txt").read_text()
    got, problem = shorts_parsing.parse_volume(text, date(2026, 10, 2), shorts_parsing.finra_symbols(cfg), NOW)
    assert problem is None and len(got) == 20                    # AA and SPY are not on the watchlist
    aapl = next(r for r in got if r["ticker"] == "AAPL")
    assert aapl["short_volume"] == 5692524.485666 and aapl["total_volume"] == 10528296.53797
    assert aapl["short_pct"] == round(5692524.485666 / 10528296.53797 * 100, 2) and aapl["markets"] == "B,Q,N"
    truncated = "\n".join(text.splitlines()[:-1] + ["12465"])
    assert "trailer says 12465" in shorts_parsing.parse_volume(truncated, date(2026, 10, 2), shorts_parsing.finra_symbols(cfg), NOW)[1]
    assert "holds date 20261002" in shorts_parsing.parse_volume(text, date(2026, 10, 1), shorts_parsing.finra_symbols(cfg), NOW)[1]


def test_finra_short_interest_parse():
    cfg = load_market("us")
    got = shorts_parsing.parse_short_interest(json.loads((FIX / "finra_short_interest.json").read_text()), shorts_parsing.finra_symbols(cfg), NOW)
    assert len(got) == 40 and {r["settlement_date"] for r in got} == {"2026-08-31", "2026-09-15"}
    nvda = next(r for r in got if r["ticker"] == "NVDA" and r["settlement_date"] == "2026-08-31")
    assert nvda["short_interest"] == 298301619 and nvda["prev_short_interest"] == 285956804
    assert nvda["days_to_cover"] == 2.14 and nvda["change_pct"] == 4.32


def test_nsdl_fpi_parse():
    got, problem = flows_parsing.parse_fpi((FIX / "nsdl_fpi_latest.html").read_text(), NOW)
    assert problem is None and len(got) == 25
    by = {(r["asset_class"], r["route"]): r for r in got}
    eq = by[("Equity", "Stock Exchange")]
    assert (eq["gross_purchases_cr"], eq["gross_sales_cr"], eq["net_cr"], eq["net_usd_mn"]) == (12794.16, 22429.12, -9634.96, -1003.72)
    assert eq["usd_inr"] == 95.9927 and eq["reporting_date"] == "2026-10-05"
    assert by[("Equity", "Sub-total")]["net_cr"] == -9281.52
    assert by[("Debt-VRR", "Primary market & others")]["net_cr"] == -87.98
    assert by[("Mutual Funds", "Equity schemes")]["net_cr"] == 45.49
    assert by[("Total", "Total")]["net_cr"] == -9466.48
    assert len({r["id"] for r in got}) == 25
    assert flows_parsing.parse_fpi("<html>maintenance</html>", NOW)[1].startswith("report title")


def test_nse_index_parse():
    cfg = load_market("india")
    names = cfg["india_flows"]["indices"]["names"]
    got, missing, problem = flows_parsing.parse_indices((FIX / "ind_close_all_05102026.csv").read_text(), TODAY, names, NOW)
    assert problem is None and missing == [] and len(got) == len(names) == 14
    ins = next(r for r in got if r["index_name"] == "Nifty Insurance")
    assert ins["sector"] == "Insurance" and ins["open"] is None and ins["close"] == 1756.64 and ins["pe"] == 24.69
    gsec = next(r for r in got if r["index_name"] == "Nifty 10 yr Benchmark G-Sec")
    assert gsec["sector"] is None and gsec["pe"] is None and gsec["change_pct"] == -0.05
    assert "Nifty Media" not in {r["index_name"] for r in got}
    _, missing, problem = flows_parsing.parse_indices((FIX / "ind_close_all_05102026.csv").read_text(), date(2026, 10, 6),
                                            {**names, "Nifty Nothing": None}, NOW)
    assert missing == ["Nifty Nothing"] and "holds ['2026-10-05']" in problem


def test_number_parsing():
    assert parse_accounting_amount("(9634.96)") == -9634.96 and parse_accounting_amount("Rs.95.9927") == 95.9927
    assert parse_accounting_amount("-.88") == -0.88 and parse_accounting_amount("1,234.5") == 1234.5
    assert parse_accounting_amount("-") is None and parse_accounting_amount(".") is None and parse_accounting_amount("") is None


# ---------- collectors end to end: schema, dedupe, revisions, failures ----------

def us_cfg(cboe_lookback: int = 4) -> dict:
    """The real US config; the Cboe lookback shortened to the fixture sessions (10-01, 10-02, 10-05)."""
    cfg = load_market("us")
    cfg["macro"]["cboe"]["lookback_days"] = cboe_lookback
    return cfg


def test_macro_collect_schema_dedupe_and_revision(root):
    cfg = us_cfg()
    out = cm.collect(cfg, FakeClient(US_ROUTES), TODAY, NOW)
    assert out["failed"] == [] and out["sources_ok"] == 3
    got = rows(root, "us", "macro")
    assert_schema(got, "macro")
    assert out["new"]["macro"] == len(got) == len({r["id"] for r in got})
    assert {r["source"] for r in got} == {"treasury", "fred", "cboe"}
    # 2026-10-05 has no Cboe file yet: the latest session may lag, so it is a note
    assert any("2026-10-05" in n for n in out["notes"])
    # same answers again: nothing new
    assert cm.collect(cfg, FakeClient(US_ROUTES), TODAY, NOW)["new"]["macro"] == 0
    # a revised value is a new row; the view keeps the newest
    revised = (FIX / "treasury_2026.csv").read_bytes().replace(b"10/05/2026,4.05", b"10/05/2026,4.07")
    routes = [("daily-treasury-rates", revised), *US_ROUTES[1:]]
    assert cm.collect(cfg, FakeClient(routes), TODAY, "2026-10-06T02:00:00+00:00")["new"]["macro"] == 1
    con = connect("us")
    assert con.execute("SELECT value FROM macro_latest WHERE series = 'UST_1M'").fetchone()[0] == 4.07
    spread = con.execute("SELECT value, chg_1 FROM macro_latest WHERE series = 'UST_10Y_2Y'").fetchone()
    assert spread[0] == pytest.approx(5.31 - 4.84) and spread[1] == pytest.approx((5.31 - 4.84) - (5.28 - 4.83))


def test_macro_failures_are_listed(root):
    cfg = load_market("us")
    routes = [("daily-treasury-rates", FetchError("u", "egress proxy denied home.treasury.gov", host="home.treasury.gov")),
              ("fred.stlouisfed.org", FetchError("u", "fred.stlouisfed.org closed the connection without an HTTP answer")),
              ("2026-10-02_daily_options", "cboe_2026-10-02_daily_options.json")]
    out = cm.collect(cfg, FakeClient(routes), TODAY, NOW)
    sources_failed = [f["source"] for f in out["failed"]]
    assert "treasury" in sources_failed and out["allowlist_needed"] == ["home.treasury.gov"]
    assert {"fred:BAMLH0A0HYM2", "fred:BAMLC0A0CM", "fred:T10YIE"} <= set(sources_failed)
    # Cboe: 2026-10-01 and earlier sessions are past the publishing lag -> failures; 10-02 is stored
    cboe_failed = sorted(f["date"] for f in out["failed"] if f["source"] == "cboe")
    assert "2026-10-01" in cboe_failed and "2026-10-02" not in cboe_failed and "2026-10-05" not in cboe_failed
    assert out["sources_ok"] == 1


def test_macro_main_skips_other_market_and_exit_code(root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["collect_macro", "--market", "india"])
    assert cm.main() == 0 and "skipped" in json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "argv", ["collect_macro", "--market", "us"])
    monkeypatch.setattr(cm, "FreeSourceClient", lambda **kw: FakeClient([]))
    monkeypatch.setattr(cm, "utc_today", lambda: TODAY)
    assert cm.main() == 1                       # every source failed (all 404)
    out = json.loads(capsys.readouterr().out)
    assert out["sources_ok"] == 0 and out["failed"]


def test_shorts_collect_schema_dedupe_and_failures(root):
    cfg = load_market("us")
    routes = [("CNMSshvol20261001", "CNMSshvol20261001.txt"), ("CNMSshvol20261002", "CNMSshvol20261002.txt"),
              ("consolidatedShortInterest", "finra_short_interest.json")]
    client = FakeClient(routes)
    out = cs.collect(cfg, client, TODAY, NOW)
    assert out["new"] == {"shorts": 40, "short_interest": 40}
    assert_schema(rows(root, "us", "shorts"), "shorts")
    assert_schema(rows(root, "us", "short_interest"), "short_interest")
    # sessions before 2026-10-01 in the lookback have no file: failures; 10-05 (today) is a note
    failed_dates = {f.get("date") for f in out["failed"] if f["source"] == "finra_short_volume"}
    assert "2026-09-30" in failed_dates and "2026-10-05" not in failed_dates
    assert any("2026-10-05" in n for n in out["notes"])
    # stored sessions are not fetched again; nothing is appended twice
    client2 = FakeClient(routes)
    again = cs.collect(cfg, client2, TODAY, NOW)
    assert again["new"] == {"shorts": 0, "short_interest": 0}
    assert not any("CNMSshvol20261001" in u for u in client2.calls)
    con = connect("us")
    latest = con.execute("SELECT date, n_prior FROM shorts_latest WHERE ticker = 'NVDA'").fetchone()
    assert str(latest[0]) == "2026-10-02" and latest[1] == 1
    assert str(con.execute("SELECT settlement_date FROM short_interest_latest WHERE ticker = 'NVDA'").fetchone()[0]) == "2026-09-15"


def test_shorts_missing_ticker_and_api_failure(root):
    cfg = load_market("us")
    lines = [ln for ln in (FIX / "CNMSshvol20261002.txt").read_text().splitlines() if "|NVDA|" not in ln]
    cut = ("\n".join(lines[:-1] + [str(len(lines) - 2)]) + "\n").encode()
    routes = [("CNMSshvol20261002", cut),
              ("consolidatedShortInterest", FetchError("u", "HTTP 503 from api.finra.org", status=503))]
    out = cs.collect(cfg, FakeClient(routes), TODAY, NOW)
    errors = [f["error"] for f in out["failed"]]
    assert any("no row for watchlist tickers ['NVDA']" in e for e in errors)
    assert any(f["source"] == "finra_short_interest" and f.get("status") == 503 for f in out["failed"])
    assert out["new"]["short_interest"] is None and out["new"]["shorts"] == 19


def test_flows_india_collect_schema_dedupe_and_failures(root):
    cfg = load_market("india")
    routes = [("fpi.nsdl.co.in", "nsdl_fpi_latest.html")] + [
        (f"ind_close_all_{d}", f"ind_close_all_{d}.csv") for d in ("25092026", "29092026", "30092026", "01102026", "05102026")]
    out = cfi.collect(cfg, FakeClient(routes), TODAY, NOW)
    assert out["new"]["fpi"] == 25 and out["new"]["indices"] == 5 * 14
    assert_schema(rows(root, "india", "fpi"), "fpi")
    assert_schema(rows(root, "india", "indices"), "indices")
    # 2026-09-28 is a session with no fixture: before the lag cutoff -> listed as failed
    assert [f["date"] for f in out["failed"]] == ["2026-09-28"]
    again = cfi.collect(cfg, FakeClient(routes), TODAY, NOW)
    assert again["new"] == {"fpi": 0, "indices": 0}
    con = connect("india")
    nifty = con.execute("SELECT close, ret_1_pct, date_1 FROM indices_latest WHERE index_name = 'Nifty 50'").fetchone()
    assert nifty[0] == 22555.75 and str(nifty[2]) == "2026-10-01"
    assert nifty[1] == pytest.approx((22555.75 / 22421.95 - 1) * 100)
    # NSDL refused and NSE closed: both reported, exit code 1
    bad = [("fpi.nsdl.co.in", FetchError("u", "egress proxy denied fpi.nsdl.co.in", host="fpi.nsdl.co.in")),
           ("nsearchives", FetchError("u", "nsearchives.nseindia.com closed the connection"))]
    worse = cfi.collect(cfg, FakeClient(bad), date(2026, 10, 20), NOW)
    assert worse["new"] == {"fpi": None, "indices": None} and worse["allowlist_needed"] == ["fpi.nsdl.co.in"]


def test_flows_india_layout_change_is_a_failure(root):
    cfg = load_market("india")
    routes = [("fpi.nsdl.co.in", "treasury_2026.csv")]
    out = cfi.collect({**cfg, "india_flows": {"fpi": True}}, FakeClient(routes), TODAY, NOW)
    assert out["new"] == {"fpi": None} and "report title" in out["failed"][0]["error"]


def test_client_classifies_errors(monkeypatch):
    import urllib.error
    import urllib.request
    import http.client
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    def fake_open(req, timeout):
        calls.append(req.full_url)
        if "proxy" in req.full_url:
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        if "closed" in req.full_url:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    c = FreeSourceClient(pause=0)
    with pytest.raises(FetchError) as e:
        c.get("https://a.example/proxy")
    assert e.value.host == "a.example" and e.value.status is None
    with pytest.raises(FetchError) as e:
        c.get("https://b.example/closed")
    assert "without an HTTP answer 3 times" in e.value.error and len(calls) == 4   # 1 + 3 attempts
    with pytest.raises(FetchError) as e:
        c.get("https://b.example/other")                                         # host skipped this run
    assert "not requested" in e.value.error and len(calls) == 4
    with pytest.raises(FetchError) as e:
        c.get("https://c.example/missing")
    assert e.value.status == 403 and collector_store.not_published(e.value) and len(calls) == 5   # no retry on HTTP errors


# ---------- context sections ----------

def test_context_sections(root):
    us, india = us_cfg(), load_market("india")
    cm.collect(us, FakeClient(US_ROUTES), TODAY, NOW)
    cs.collect(us, FakeClient([("CNMSshvol20261002", "CNMSshvol20261002.txt"),
                               ("consolidatedShortInterest", "finra_short_interest.json")]), TODAY, NOW)
    secs = dict(macro_context.context_sections(us, connect("us")))
    macro = next(v for k, v in secs.items() if k.startswith("Macro & flows"))
    assert "| UST_10Y | Treasury par yield 10 Yr | 2026-10-05 | 5.31% | +3 bp | +7 bp | 2026-09-28 |" in macro
    assert "| UST_10Y_2Y | Treasury 10y minus 2y | 2026-10-05 | 0.47% |" in macro
    assert "| CBOE_PC_TOTAL | Cboe TOTAL PUT/CALL RATIO | 2026-10-02 | 0.78 | -0.12 |  |  |" in macro
    assert "BAMLH0A0HYM2" in macro and "UST_1.5M" not in macro      # only the main tenors are shown
    shorts = next(v for k, v in secs.items() if k.startswith("Short selling"))
    assert "| NVDA | 2026-10-02 |" in shorts and "| 2026-09-15 | 294.23 |" in shorts
    assert macro_context.context_sections(india, connect("india")) != []
    cfi.collect(india, FakeClient([("fpi.nsdl.co.in", "nsdl_fpi_latest.html"),
                                   ("ind_close_all_05102026", "ind_close_all_05102026.csv"),
                                   ("ind_close_all_01102026", "ind_close_all_01102026.csv")]), TODAY, NOW)
    isecs = dict(macro_context.context_sections(india, connect("india")))
    fpi = next(v for k, v in isecs.items() if "FPI" in k)
    assert "| 2026-10-05 | Equity | Sub-total | 13147.77 | 22429.29 | -9281.52 | -966.9 |" in fpi
    assert "Equity net over the last 1 stored reports (2026-10-05 to 2026-10-05): -9,282 cr." in fpi
    idx = next(v for k, v in isecs.items() if "NSE indices" in k)
    assert "| Nifty Insurance | Insurance | 2026-10-05 | 1756.64 | -0.44 |" in idx
    # sections only for the market whose config has the collector
    assert not any("FPI" in k for k in secs) and not any("Short" in k for k in isecs)


# ---------- news feeds ----------

def test_news_outlets_utc_dedupe_and_watchlist_only(root, monkeypatch, capsys, tmp_path):
    import feedparser
    from datetime import datetime, timezone
    cfg_dir = tmp_path / "config"
    (cfg_dir / "markets").mkdir(parents=True)
    import yaml
    doc = yaml.safe_load((REPO / "config" / "markets" / "us.yaml").read_text())
    doc["news"] = {"wire_exclude": doc["news"]["wire_exclude"], "outlets": [
        {"name": "Business Standard Markets", "url": "bs_markets.rss", "category": "general"},
        {"name": "BusinessLine Companies", "url": "businessline_companies.rss", "category": "company"},
        {"name": "PR Newswire", "url": "prnewswire_all.rss", "category": "company", "watchlist_only": True},
        {"name": "Business Wire Earnings", "url": "businesswire_earnings.rss", "category": "company", "watchlist_only": True},
        {"name": "GlobeNewswire Public Companies", "url": "globenewswire_public.rss", "category": "company",
         "watchlist_only": True}]}
    (cfg_dir / "markets" / "us.yaml").write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(common, "CONFIG", cfg_dir)
    real_parse = feedparser.parse
    monkeypatch.setattr(feedparser, "parse", lambda url, agent=None: real_parse(str(FIX / url)))
    monkeypatch.setattr(cn, "now_utc", lambda: datetime(2026, 10, 5, 22, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(cn, "utc_today", lambda: TODAY)
    monkeypatch.setattr(sys, "argv", ["collect_news", "--market", "us"])
    assert cn.main() == 0
    out = json.loads(capsys.readouterr().out)
    got = rows(root, "us", "news")
    assert_schema(got, "news")
    by_feed = {}
    for r in got:
        by_feed.setdefault(r["feed"], []).append(r)
    assert len(by_feed["Business Standard Markets"]) == 6 and len(by_feed["BusinessLine Companies"]) == 6
    # wires keep only items that name a watchlist company (wire_names, minus wire_exclude)
    wire_feeds = ("PR Newswire", "Business Wire Earnings", "GlobeNewswire Public Companies")
    wires = [r for f in wire_feeds for r in by_feed.get(f, [])]
    assert all(r["tickers"] for r in wires)
    assert out["skipped_off_watchlist"] == 18 - len(wires)
    # published_at is UTC: Business Standard's pubDate "Mon, 05 Oct 2026 20:39:25 +0530"
    bs = next(r for r in got if r["published_at"] == "2026-10-05T15:09:25+00:00")
    assert bs["source"] == "Business Standard Markets"
    assert all(r["published_at"].endswith("+00:00") for r in got)
    # same feeds again: everything is a duplicate
    assert cn.main() == 0
    assert json.loads(capsys.readouterr().out)["new_items"] == 0 and len(rows(root, "us", "news")) == len(got)


WIRE_CASES = [
    ("NVIDIA Announces Financial Results for Third Quarter Fiscal 2027", {"NVDA"}),
    ("JPMORGAN CHASE REPORTS THIRD-QUARTER 2026 NET INCOME", {"JPM"}),
    ("DELTA AIR LINES ANNOUNCES SEPTEMBER QUARTER 2026 FINANCIAL RESULTS", {"DAL"}),
    ("The Progressive Corporation Reports September Results", {"PGR"}),
    ("Merck & Co. to Hold Third-Quarter 2026 Sales and Earnings Conference Call", {"MRK"}),
    ("Meta Platforms, Inc. to Announce Third Quarter Results", {"META"}),
    ("Apple Hospitality REIT Reports Results of Operations", set()),
    ("New Meta-Analysis Shows Benefit of Early Treatment", set()),
    ("Phase 3 Trial in Progressive Supranuclear Palsy Meets Primary Endpoint", set()),
    ("Merck KGaA, Darmstadt, Germany, Opens New Facility", set()),
    ("The new app is available on iPhone and Android", set()),
    ("Acme Widgets wins award. Follow us on Facebook and Instagram", set()),
]


@pytest.mark.parametrize("text,expected", WIRE_CASES)
def test_news_wire_matching(text, expected):
    """watchlist_only feeds: case-insensitive whole-word wire_names, wire_exclude phrases removed."""
    cfg = load_market("us")
    pats, exclude = news_wire.wire_patterns(cfg), news_wire.wire_exclusions(cfg["news"])
    assert news_wire.wire_tickers(text, pats, exclude) == expected


# ---------- incomplete days are fetched again; the views prefer the complete version ----------

def test_incomplete_finra_day_is_refetched(root):
    cfg = us_cfg()
    cfg["shorts"]["daily_volume"]["lookback_days"] = 4          # sessions 10-01, 10-02, 10-05
    lines = [ln for ln in (FIX / "CNMSshvol20261002.txt").read_text().splitlines() if "|NVDA|" not in ln]
    cut = ("\n".join(lines[:-1] + [str(len(lines) - 2)]) + "\n").encode()
    first = cs.collect(cfg, FakeClient([("CNMSshvol20261001", "CNMSshvol20261001.txt"),
                                        ("CNMSshvol20261002", cut)]), TODAY, NOW)
    assert any("['NVDA']" in f["error"] for f in first["failed"])
    assert all(r["complete"] is False for r in rows(root, "us", "shorts") if r["date"] == "2026-10-02")
    # same incomplete file again: fetched again, reported again, nothing appended twice
    c2 = FakeClient([("CNMSshvol20261002", cut)])
    again = cs.collect(cfg, c2, TODAY, NOW)
    assert any("CNMSshvol20261002" in u for u in c2.calls) and not any("CNMSshvol20261001" in u for u in c2.calls)
    assert any("['NVDA']" in f["error"] for f in again["failed"]) and again["new"]["shorts"] == 0
    # the whole file arrives: every ticker is stored complete and the day is not fetched again
    c3 = FakeClient([("CNMSshvol20261002", "CNMSshvol20261002.txt")])
    fixed = cs.collect(cfg, c3, TODAY, NOW)
    assert fixed["new"]["shorts"] == 20 and not [f for f in fixed["failed"] if f.get("date") == "2026-10-02"]
    c4 = FakeClient([])
    cs.collect(cfg, c4, TODAY, NOW)
    assert not any("CNMSshvol20261002" in u for u in c4.calls)
    con = connect("us")
    assert con.execute("SELECT count(*), bool_and(complete) FROM shorts_daily WHERE date = '2026-10-02'").fetchone() == (20, True)


def test_truncated_finra_file_is_incomplete(root):
    cfg = us_cfg()
    cfg["shorts"]["daily_volume"]["lookback_days"] = 4
    text = (FIX / "CNMSshvol20261002.txt").read_text().splitlines()
    truncated = ("\n".join(text[:-1] + ["12465"]) + "\n").encode()
    out = cs.collect(cfg, FakeClient([("CNMSshvol20261002", truncated)]), TODAY, NOW)
    assert any("trailer says 12465" in f["error"] for f in out["failed"])
    c2 = FakeClient([("CNMSshvol20261002", "CNMSshvol20261002.txt")])
    assert cs.collect(cfg, c2, TODAY, NOW)["new"]["shorts"] == 20       # same values, now complete
    assert any("CNMSshvol20261002" in u for u in c2.calls)


def test_incomplete_index_and_cboe_days_are_refetched(root):
    india = load_market("india")
    india["india_flows"] = {"fpi": False, "indices": {**india["india_flows"]["indices"], "lookback_days": 1}}
    text = (FIX / "ind_close_all_05102026.csv").read_text().splitlines()
    partial = ("\n".join(ln for ln in text if not ln.startswith("Nifty Metal")) + "\n").encode()
    out = cfi.collect(india, FakeClient([("ind_close_all_05102026", partial)]), TODAY, NOW)
    assert any("['Nifty Metal']" in f["error"] for f in out["failed"]) and out["new"]["indices"] == 13
    c2 = FakeClient([("ind_close_all_05102026", "ind_close_all_05102026.csv")])
    assert cfi.collect(india, c2, TODAY, NOW)["new"]["indices"] == 14 and c2.calls
    c3 = FakeClient([])
    cfi.collect(india, c3, TODAY, NOW)
    assert c3.calls == []
    assert connect("india").execute("SELECT count(*), bool_and(complete) FROM indices_daily").fetchone() == (14, True)

    us = us_cfg()
    us["macro"] = {"treasury": False, "cboe": {**us["macro"]["cboe"], "lookback_days": 3}}   # 10-02, 10-05
    payload = json.loads((FIX / "cboe_2026-10-02_daily_options.json").read_text())
    payload["ratios"] = [r for r in payload["ratios"] if r["name"] != "EQUITY PUT/CALL RATIO"]
    out = cm.collect(us, FakeClient([("2026-10-02_daily_options", json.dumps(payload).encode())]), TODAY, NOW)
    assert [f["error"] for f in out["failed"]] == ["ratios missing from the file: ['EQUITY PUT/CALL RATIO']"]
    c2 = FakeClient([("2026-10-02_daily_options", "cboe_2026-10-02_daily_options.json")])
    assert cm.collect(us, c2, TODAY, NOW)["new"]["macro"] == 5 and c2.calls
    c3 = FakeClient([])
    cm.collect(us, c3, TODAY, NOW)
    assert not any("2026-10-02" in u for u in c3.calls)


def test_fpi_unreadable_numbers_and_missing_equity_are_failures(root):
    page = (FIX / "nsdl_fpi_latest.html").read_text()
    bad = page.replace("<td align='right'>108.28</td>", "<td align='right'>n/a</td>", 1)
    got, problem = flows_parsing.parse_fpi(bad, NOW)
    assert "1 table rows with unreadable numbers" in problem and "Debt-General Limit | Stock Exchange" in problem
    assert len(got) == 24
    # no Equity sub-total: reported as a failure, never a StopIteration
    no_equity = page.replace(">Equity<", ">Equities<")
    cfg = load_market("india")
    out = cfi.collect({**cfg, "india_flows": {"fpi": True}},
                      FakeClient([("fpi.nsdl.co.in", no_equity.encode())]), TODAY, NOW)
    assert "without an Equity sub-total" in out["failed"][0]["error"] and out["new"]["fpi"] > 0
