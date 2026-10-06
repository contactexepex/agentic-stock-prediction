"""Seeded kinds for the golden run (tests/golden/golden.py): the pinned data has no rows of the
relationship, fundamentals, macro, short-selling, NSE, graph, options, price-source and SEC-time
kinds, so the modules, SQL views and Neo4j shapers that read them would only see empty tables.

The real collectors fill a separate scratch root (SEED_KINDS below) from the test fixtures:
- India, NSE: collect_relations_india.py and collect_nse_india.py replay tests/fixtures/nse/real
  (--replay, --today 2026-10-05, --full): insiders, holdings, announcements, financials, flows,
  delivery; then collect_relations_india.py replays tests/fixtures/nse/synthetic (dates set
  relative to 2026-10-05) for deals and insider trades of watchlist tickers (the real snapshot
  has none);
- US, SEC: collect_insiders, collect_stakes, collect_holdings and collect_fundamentals read
  tests/fixtures/sec through MB_SEC_FIXTURES (the urls.json map built here, as in
  tests/test_relationships.py and tests/test_fundamentals.py; the seed config tracks the fixture
  13F filer 9999200 instead of the real filers): insiders, stakes, holdings, fundamentals;
- free sources: tests/golden/seed_sources.py runs collect_macro, collect_shorts and
  collect_flows_india on tests/fixtures/sources (macro, shorts, short_interest, fpi, indices);
- graph.py add tests/fixtures/graph_edges.jsonl (India connection map; its 4th edge is invalid on
  purpose, so that step exits 1) and graph.py attempt (graph_runs);
- small rule-built rows for options (US), price_sources (India) and sec_times (US), whose
  collectors need Yahoo or the SEC header pages, and India financials of the quarter a year before
  the fixtures' latest one (INFY consolidated, HDFCBANK and SBILIFE standalone, 2025-04-01..06-30),
  so the year-over-year columns of the "Latest quarterly results" section have values;
- the fixture 13F tables are served with the AAPL common-share values multiplied by
  F13_VALUE_SCALE (a copy in the seed folder; tests/fixtures is unchanged), so the 13F section's
  value_bn is billions with two significant decimals instead of 0.0.
The seed root's data files are then copied into the golden root (never over an existing file).
- the collectors that need Yahoo, RSS feeds, article pages or SEC header pages (collect_prices,
  collect_quotes, collect_events, collect_news, collect_articles, collect_filings, collect_options,
  check_sec_times) run through tests/golden/seed_collectors.py (offline stand-ins for those services,
  at the third-party boundary) on a copy of the seed root (`collectors_<market>`: the seeded kinds, the
  pinned events and news, and the pinned prices up to PRICE_CUTOFF); their outputs are compared (the
  copy is kept in run/seed/collectors_<market>) but not copied into the golden root, so the later steps
  do not change.
Every seed step's exit code, stdout and stderr is logged and compared like any other step."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import yaml

CODE = Path(__file__).resolve().parents[2]
FIXTURES = CODE / "tests" / "fixtures"
SEC_FIXTURES = FIXTURES / "sec"
ARCHIVES = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
EDGAR = "https://www.sec.gov/Archives/edgar/data"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
NSE_DAY = date(2026, 10, 5)
SEED_CLOCKS = {"india": "2026-10-05T02:00:00+00:00", "us": "2026-10-05T12:00:00+00:00"}
SEED_KINDS = {
    "india": ("insiders", "deals", "holdings", "announcements", "financials", "flows", "delivery",
              "fpi", "indices", "graph", "graph_runs", "price_sources"),
    "us": ("insiders", "stakes", "holdings", "fundamentals", "macro", "shorts", "short_interest",
           "options", "sec_times"),
}
APPLE_CIK, BOFA_CIK, FILER_CIK = 320193, 70858, 9999200
PRICE_CUTOFF = "2026-09-29"   # the collectors' copy holds the pinned bars up to this day; Yahoo's stand-in has all
COLLECTOR_SCRIPTS = ("collect_prices.py", "collect_quotes.py", "collect_events.py", "collect_news.py",
                      "collect_articles.py", "collect_filings.py", "collect_options.py", "check_sec_times.py")
COLLECTOR_COPIED_KINDS = ("events", "news")   # pinned kinds the collectors' copy starts with
F13_VALUE_SCALE = 1000164   # AAPL latest 25000 + 12500 -> 37,506,150,000 USD = 37.51 bn
# year-ago quarter (2025-04-01..2025-06-30) of the fixtures' 2026 Q1 results: ticker, basis, revenue,
# net profit (INR), eps, filed (UTC)
YEAR_AGO_RESULTS = (("INFY", "consolidated", 422790000000.0, 63680000000.0, 15.37, "2025-07-17T11:05:00+00:00"),
                    ("HDFCBANK", "standalone", 711030000000.0, 161750000000.0, 21.15, "2025-07-19T10:40:00+00:00"),
                    ("SBILIFE", "standalone", 186410000000.0, 5940000000.0, 5.93, "2025-07-25T11:30:00+00:00"))


def submissions(name: str, filings: list[tuple]) -> dict:
    """An SEC submissions JSON: filings = (accession, form, filing date, primary document, report date)."""
    columns = ["accessionNumber", "form", "filingDate", "primaryDocument", "reportDate"]
    recent = {c: [f[i] for f in filings] for i, c in enumerate(columns)}
    recent["acceptanceDateTime"] = [f"{f[2]}T21:00:00.000Z" for f in filings]
    recent["primaryDocDescription"] = [f[1] for f in filings]
    return {"name": name, "filings": {"recent": recent}}


def sec_fixture_map(target: Path) -> None:
    """urls.json and the submissions files for Apple (Form 4, 13D/13G, 10-Q/10-K), Bank of America
    (10-Q) and the fixture 13F filer."""
    target.mkdir(parents=True)
    filed, older = "2026-10-02", "2026-09-05"
    apple = [("0001140361-26-038307", "4", filed, "xslF345X06/form4.xml", ""),
             ("0009999001-26-000001", "4", filed, "xslF345X05/doc4.xml", ""),
             ("0002100119-26-000139", "SCHEDULE 13G", filed, "xslSCHEDULE_13G_X02/primary_doc.xml", ""),
             ("0009999100-26-000001", "SCHEDULE 13D", filed, "xslSCHEDULE_13D_X02/primary_doc.xml", ""),
             ("0000320193-26-000020", "10-Q", "2026-07-31", "doc.htm", "2026-06-27"),
             ("0000320193-26-000013", "10-Q", "2026-05-01", "doc.htm", "2026-03-28"),
             ("0000320193-26-000006", "10-Q", "2026-01-30", "doc.htm", "2025-12-27"),
             ("0000320193-25-000079", "10-K", "2025-10-31", "doc.htm", "2025-09-27")]
    bofa = [("0000070858-26-000394", "10-Q", "2026-07-31", "doc.htm", "2026-06-30"),
            ("0000070858-26-000249", "10-Q", "2026-05-01", "doc.htm", "2026-03-31")]
    filer = [("0009999200-26-000002", "13F-HR", filed, "xslForm13F_X02/primary_doc.xml", "2026-09-30"),
             ("0009999200-26-000001", "13F-HR", older, "xslForm13F_X02/primary_doc.xml", "2026-06-30")]
    urls = {"https://www.sec.gov/files/company_tickers.json": "tickers.json"}
    (target / "tickers.json").write_text(json.dumps({"0": {"cik_str": APPLE_CIK, "ticker": "AAPL", "title": "Apple"},
                                                     "1": {"cik_str": BOFA_CIK, "ticker": "BAC", "title": "BofA"}}))
    for cik, name, filings in ((APPLE_CIK, "Apple Inc.", apple), (BOFA_CIK, "BANK OF AMERICA", bofa),
                               (FILER_CIK, "EXAMPLE CAPITAL", filer)):
        (target / f"sub_{cik}.json").write_text(json.dumps(submissions(name, filings)))
        urls[ARCHIVES.format(cik=cik)] = f"sub_{cik}.json"
    urls.update({
        f"{EDGAR}/320193/000114036126038307/form4.xml": str(SEC_FIXTURES / "form4_sale.xml"),
        f"{EDGAR}/320193/000999900126000001/doc4.xml": str(SEC_FIXTURES / "form4_buy.xml"),
        f"{EDGAR}/320193/000210011926000139/primary_doc.xml": str(SEC_FIXTURES / "schedule13g.xml"),
        f"{EDGAR}/320193/000999910026000001/primary_doc.xml": str(SEC_FIXTURES / "schedule13d.xml"),
        FACTS.format(cik=APPLE_CIK): str(SEC_FIXTURES / "companyfacts_aapl.json"),
        FACTS.format(cik=BOFA_CIK): str(SEC_FIXTURES / "companyfacts_bac.json"),
    })
    for folder, table in (("9999200/000999920026000002", "13f_table_latest.xml"),
                          ("9999200/000999920026000001", "13f_table_previous.xml")):
        urls[f"{EDGAR}/{folder}/index.json"] = str(SEC_FIXTURES / "13f_index.json")
        urls[f"{EDGAR}/{folder}/primary_doc.xml"] = str(SEC_FIXTURES / "13f_cover.xml")
        urls[f"{EDGAR}/{folder}/infotable.xml"] = str(scaled_13f_table(SEC_FIXTURES / table, target / table))
    (target / "urls.json").write_text(json.dumps(urls, indent=1))


def seed_config(golden_root: Path, seed_root: Path) -> None:
    """The pinned config, with the US 13F filers replaced by the fixture filer."""
    shutil.copytree(golden_root / "config", seed_root / "config")
    path = seed_root / "config" / "markets" / "us.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["relationships"]["holdings"]["filers"] = {FILER_CIK: "Example Capital"}
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


def rule_rows(seed_root: Path) -> None:
    """Rows of the kinds whose collectors need Yahoo or SEC header pages."""
    def write(market: str, kind: str, day: str, rows: list[dict]) -> None:
        path = seed_root / "data" / market / kind / day[:4] / day[5:7] / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    us_now = SEED_CLOCKS["us"]
    write("us", "options", "2026-10-05", [
        {"id": f"{ticker}-2026-10-05", "ticker": ticker, "collected_at": us_now, "expiry": "2026-10-16",
         "days_to_expiry": 11, "spot": spot, "strike": strike, "call_iv": iv + 0.01, "put_iv": iv - 0.01,
         "atm_iv": iv, "straddle": round(spot * iv * 0.17, 2), "straddle_pct": round(iv * 17, 2), "source": "golden"}
        for ticker, spot, strike, iv in (("AAPL", 255.0, 255.0, 0.28), ("JPM", 310.0, 310.0, 0.24),
                                         ("NVDA", 187.0, 187.5, 0.45))])
    write("us", "sec_times", "2026-10-05", [
        {"accession": "0001140361-26-038307", "cik": str(APPLE_CIK), "accepted_at": "2026-10-02T17:00:00Z",
         "json_accepted_at": "2026-10-02T21:00:00Z", "source": "golden", "checked_at": us_now}])
    write("india", "financials", "2025-07-25", [
        {"id": f"nse-fin-{ticker}-{basis}-2025-04-01-2025-06-30-golden", "ticker": ticker, "basis": basis,
         "period_type": "quarterly", "period_start": "2025-04-01", "period_end": "2025-06-30", "revenue": revenue,
         "net_profit": profit, "eps_basic": eps, "eps_diluted": eps, "audited": "Unaudited", "filing_type": "Original",
         "filed_at": filed, "seq_id": "golden", "first_seen_at": "2025-07-25T12:00:00+00:00"}
        for ticker, basis, revenue, profit, eps, filed in YEAR_AGO_RESULTS])
    write("india", "price_sources", "2026-10-01", [
        {"id": "nse-bhav-2026-10-01-INFY", "date": "2026-10-01", "ticker": "INFY", "source": "nse_bhavcopy",
         "url": "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_01102026.csv",
         "filled_at": SEED_CLOCKS["india"]}])


def scaled_13f_table(source: Path, target: Path) -> Path:
    """A copy of a fixture 13F table with each APPLE INC common-share line's <value> times F13_VALUE_SCALE."""
    def scale(block: re.Match) -> str:
        text = block.group(0)
        if "<nameOfIssuer>APPLE INC</nameOfIssuer>" not in text or "<titleOfClass>COM</titleOfClass>" not in text:
            return text
        return re.sub(r"<value>(\d+)</value>", lambda m: f"<value>{int(m.group(1)) * F13_VALUE_SCALE}</value>", text)
    target.write_text(re.sub(r"<infoTable>.*?</infoTable>", scale, source.read_text(), flags=re.S))
    return target


def synthetic_nse(target: Path) -> None:
    """tests/fixtures/nse/synthetic with each __Dn__ set to the IST date n days before NSE_DAY (NSE
    format), as tests/test_relations.py does relative to today: a big deal and insider sale."""
    target.mkdir(parents=True)
    for source in sorted((FIXTURES / "nse" / "synthetic").iterdir()):
        text = source.read_text()
        for days_back in range(31):
            text = text.replace(f"__D{days_back}__", f"{NSE_DAY - timedelta(days=days_back):%d-%b-%Y}")
        (target / source.name).write_text(text)


def sec_collectors_map(target: Path) -> None:
    """urls.json for the SEC-reading new collectors (filings, events, sec_times): Apple and Bank of America
    with 8-K item 2.02 filings and SGML header fixtures (Apple's acceptance times right, Bank of America's
    shifted by the New York offset, two stored accessions with headers)."""
    target.mkdir(parents=True)
    filed = "2026-10-02"
    apple = [("0001140361-26-038307", "4", filed, "xslF345X06/form4.xml", ""),
             ("0009999001-26-000001", "4", filed, "xslF345X05/doc4.xml", ""),
             ("0002100119-26-000139", "SCHEDULE 13G", filed, "xslSCHEDULE_13G_X02/primary_doc.xml", ""),
             ("0000320193-26-000030", "8-K", "2026-07-30", "doc8k.htm", ""),
             ("0000320193-26-000020", "10-Q", "2026-07-31", "doc.htm", "2026-06-27"),
             ("0000320193-26-000013", "10-Q", "2026-05-01", "doc.htm", "2026-03-28"),
             ("0000320193-25-000079", "10-K", "2025-10-31", "doc.htm", "2025-09-27")]
    bofa = [("0000070858-26-000394", "10-Q", "2026-07-31", "doc.htm", "2026-06-30"),
            ("0000070858-26-000300", "8-K", "2026-07-15", "doc8k.htm", ""),
            ("0000070858-26-000249", "10-Q", "2026-05-01", "doc.htm", "2026-03-31")]
    urls = {"https://www.sec.gov/files/company_tickers.json": "tickers.json"}
    (target / "tickers.json").write_text(json.dumps({"0": {"cik_str": APPLE_CIK, "ticker": "AAPL", "title": "Apple"},
                                                     "1": {"cik_str": BOFA_CIK, "ticker": "BAC", "title": "BofA"}}))
    for cik, name, filings in ((APPLE_CIK, "Apple Inc.", apple), (BOFA_CIK, "BANK OF AMERICA", bofa)):
        data = submissions(name, filings)
        data["filings"]["recent"]["items"] = ["2.02,9.01" if f[1] == "8-K" else "" for f in filings]
        (target / f"sub_{cik}.json").write_text(json.dumps(data))
        urls[ARCHIVES.format(cik=cik)] = f"sub_{cik}.json"
    headers = {(APPLE_CIK, "0001140361-26-038307"): "20261002170000",
               (APPLE_CIK, "0000320193-25-000079"): "20251031170000",
               (APPLE_CIK, "0009999001-26-000001"): "20261002130000",
               (APPLE_CIK, "0002100119-26-000139"): "20261002170000",
               (BOFA_CIK, "0000070858-26-000394"): "20260731130000",
               (BOFA_CIK, "0000070858-26-000249"): "20260501130000"}
    for (cik, accession), eastern in headers.items():
        name = f"hdr_{accession}.sgml"
        (target / name).write_text(f"<SEC-HEADER>\n<ACCEPTANCE-DATETIME>{eastern}\n</SEC-HEADER>\n")
        urls[f"{EDGAR}/{cik}/{accession.replace('-', '')}/{accession}.hdr.sgml"] = name
    (target / "urls.json").write_text(json.dumps(urls, indent=1))


def nse_replay_folder(target: Path) -> None:
    """The NSE replay files of the collectors: the real snapshot's results lists and bhavcopies plus a
    results-announcement list and an older results list for the three tickers that have results filings."""
    target.mkdir(parents=True)
    real = FIXTURES / "nse" / "real"
    for pattern in ("integrated-filing-results_*.json", "sec_bhavdata_full_*.csv"):
        for source in sorted(real.glob(pattern)):
            shutil.copyfile(source, target / source.name)
    for symbol in ("INFY", "HDFCBANK", "SBILIFE"):
        (target / f"corporate-announcements_{symbol}.json").write_text(json.dumps({"data": [
            {"desc": "Outcome of Board Meeting", "an_dt": "22-Jul-2026 15:10:00", "sort_date": "2026-07-22 15:10:00"},
            {"desc": "Analysts/Institutional Investor Meet/Con. Call Updates", "an_dt": "21-Jul-2026 10:00:00"}]}))
        (target / f"corporates-financial-results_{symbol}.json").write_text(json.dumps({"data": [
            {"toDate": "31-DEC-2024", "broadCastDate": "05-Feb-2025 17:30:00"},
            {"toDate": "30-SEP-2024", "broadCastDate": "04-Nov-2024 16:00:00"}]}))


def collectors_root(scratch: Path, seed_root: Path, golden_root: Path, market: str) -> Path:
    """A copy of the seed root for one market's collectors: the pinned events and news, and the pinned
    bars up to PRICE_CUTOFF (Yahoo's stand-in serves the later ones)."""
    target = scratch / f"collectors_{market}"
    shutil.copytree(seed_root, target)
    for kind in COLLECTOR_COPIED_KINDS:
        source = golden_root / "data" / market / kind
        if source.is_dir():
            shutil.copytree(source, target / "data" / market / kind, dirs_exist_ok=True)
    pinned_prices = golden_root / "data" / market / "prices"
    for path in sorted(pinned_prices.rglob("*.csv")):
        if path.stem <= PRICE_CUTOFF:
            destination = target / "data" / market / "prices" / path.relative_to(pinned_prices)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    return target


def collector_steps(market: str) -> list[tuple[str, str, list[str]]]:
    """(market, label, argv) of the Yahoo, RSS, article and SEC-header collectors through seed_collectors.py."""
    runner = str(CODE / "tests" / "golden" / "seed_collectors.py")
    return [(market, script.removesuffix(".py"), ["{python}", runner, market, script]) for script in COLLECTOR_SCRIPTS]


def seed_steps() -> list[tuple[str, str, list[str]]]:
    """(market, label, argv) in order; '{python}', '{seed_dir}' and '{fixtures}' are filled in by run_seed."""
    nse = ["--replay", "{fixtures}/nse/real", "--today", "2026-10-05", "--full"]
    return [
        ("india", "collect_relations_india", ["{python}", "collect_relations_india.py", *nse]),
        ("india", "collect_relations_india_synthetic",
         ["{python}", "collect_relations_india.py", "--replay", "{seed_dir}/nse_synthetic", "--today", "2026-10-05",
          "--only", "deals", "--only", "insiders"]),
        ("india", "collect_nse_india", ["{python}", "collect_nse_india.py", *nse]),
        ("india", "graph_add", ["{python}", "graph.py", "add", "{fixtures}/graph_edges.jsonl"]),
        ("india", "graph_attempt", ["{python}", "graph.py", "attempt", "--note", "golden seed"]),
        ("india", "seed_sources", ["{python}", str(CODE / "tests" / "golden" / "seed_sources.py"), "india"]),
        ("us", "collect_insiders", ["{python}", "collect_insiders.py"]),
        ("us", "collect_stakes", ["{python}", "collect_stakes.py"]),
        ("us", "collect_holdings", ["{python}", "collect_holdings.py"]),
        ("us", "collect_fundamentals", ["{python}", "collect_fundamentals.py"]),
        ("us", "seed_sources", ["{python}", str(CODE / "tests" / "golden" / "seed_sources.py"), "us"]),
    ]


def run_seed(run_dir: Path, golden_root: Path, environment, scripts: Path, parallel: bool = False) -> None:
    """Fill a scratch seed root with the collectors, keep a copy in run_dir/seed/root, then copy
    SEED_KINDS into golden_root/data. The seed root lives outside the checkout (a temporary
    directory): the NSE --replay guard refuses any write target inside a repository. parallel: the
    two markets' step lists run at the same time (each list in order; they write different
    data/<market> folders)."""
    scratch = Path(tempfile.mkdtemp(prefix="mb-golden-seed-"))
    try:
        seed_root = scratch / "root"
        (seed_root / "data").mkdir(parents=True)
        (seed_root / ".scratch-ok").write_text("golden seed root\n")
        seed_config(golden_root, seed_root)
        sec_fixture_map(run_dir / "seed" / "sec")
        rule_rows(seed_root)
        synthetic_nse(run_dir / "seed" / "nse_synthetic")
        sec_collectors_map(run_dir / "seed" / "sec_collectors")
        nse_replay_folder(run_dir / "seed" / "nse_replay")
        run_seed_steps(run_dir, seed_root, environment, scripts, parallel)
        shutil.copytree(seed_root, run_dir / "seed" / "root")
        roots = {market: collectors_root(scratch, seed_root, golden_root, market) for market in SEED_CLOCKS}
        run_collector_steps(run_dir, roots, golden_root, environment, scripts, parallel)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    copy_seeded(run_dir / "seed" / "root", golden_root, run_dir / "steps" / "seed")


def run_seed_steps(run_dir: Path, seed_root: Path, environment, scripts: Path, parallel: bool = False) -> None:
    """Run seed_steps() on seed_root; logs in run_dir/steps/seed/ with the seed root's path as <SEED>."""
    log_dir = run_dir / "steps" / "seed"
    log_dir.mkdir(parents=True)

    def run_market(market: str) -> None:
        for step_market, label, command in seed_steps():
            if step_market == market:
                run_seed_step(run_dir, seed_root, environment, scripts, (market, label, command))
    if parallel:
        with ThreadPoolExecutor(max_workers=len(SEED_CLOCKS)) as pool:
            for future in [pool.submit(run_market, market) for market in SEED_CLOCKS]:
                future.result()
    else:
        for step in seed_steps():
            run_seed_step(run_dir, seed_root, environment, scripts, step)


def run_collector_steps(run_dir: Path, roots: dict[str, Path], golden_root: Path, environment,
                        scripts: Path, parallel: bool = False) -> None:
    """Run collector_steps() of each market on its own root (a collectors_root copy), then keep
    each copy in run_dir/seed/collectors_<market>."""

    def run_market(market: str) -> None:
        extra = {"MB_SEC_FIXTURES": str(run_dir / "seed" / "sec_collectors"),
                 "GOLDEN_NSE_REPLAY": str(run_dir / "seed" / "nse_replay"),
                 "GOLDEN_PRICE_SOURCE": str(golden_root / "data" / market / "prices")}
        for step in collector_steps(market):
            run_seed_step(run_dir, roots[market], environment, scripts, step, extra)
    if parallel:
        with ThreadPoolExecutor(max_workers=len(SEED_CLOCKS)) as pool:
            for future in [pool.submit(run_market, market) for market in SEED_CLOCKS]:
                future.result()
    else:
        for market in SEED_CLOCKS:
            run_market(market)
    for market, root in roots.items():
        shutil.copytree(root, run_dir / "seed" / f"collectors_{market}")


def run_seed_step(run_dir: Path, seed_root: Path, environment, scripts: Path, step: tuple,
                  extra_env: dict | None = None) -> None:
    """One seed step on seed_root; its log files are named <market>.<label>.<stream>."""
    market, label, command = step
    env = environment(seed_root, market, SEED_CLOCKS[market])
    env.update({"MB_SEC_FIXTURES": str(run_dir / "seed" / "sec"), "MB_NETGUARD_LOG": str(run_dir / "netguard.log"),
                "SEC_USER_AGENT": "market-brief golden golden@example.com", **(extra_env or {})})
    argv = [a.format(python=sys.executable, seed_dir=run_dir / "seed", fixtures=FIXTURES) for a in command]
    proc = subprocess.run(argv, cwd=scripts, env=env, capture_output=True, text=True, check=False)
    log_dir = run_dir / "steps" / "seed"
    for stream, text in (("stdout", proc.stdout), ("stderr", proc.stderr), ("exit", f"{proc.returncode}\n")):
        (log_dir / f"{market}.{label}.{stream}").write_text(text.replace(str(seed_root.parent), "<SEED>"))


def copy_seeded(seed_root: Path, golden_root: Path, log_dir: Path) -> None:
    """Copy each SEED_KINDS folder of seed_root/data into golden_root/data, never over a file."""
    for market, kinds in SEED_KINDS.items():
        for kind in kinds:
            source = seed_root / "data" / market / kind
            if not source.is_dir():
                raise SystemExit(f"seed produced no {market}/{kind} rows; see {log_dir}")
            for path in sorted(p for p in source.rglob("*") if p.is_file()):
                target = golden_root / "data" / market / kind / path.relative_to(source)
                if target.exists():
                    raise SystemExit(f"seed would overwrite {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
