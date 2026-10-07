"""News verification phase B end to end on the phase A test market (tests/test_news_verify.py): primary
texts from real SEC 8-K fixtures, the claim gate (claims.py prepare | validate | add), the status rows
(news_status.py) and the as-of macros without look-ahead.

SCRATCH TEST DATA: the claim records below are written by this test in the claim-checker's role (no
agent runs here). Every quote is copied from the stored article extracts, titles or fixture filing
text at run time, so the gate checks real stored text."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.collectors import articles as collect_articles  # noqa: E402
from marketbrief.analytics import news_clusters  # noqa: E402
import test_news_verify as nvt  # noqa: E402
from marketbrief.pipeline.validate import row_checks  # noqa: E402
from marketbrief.analytics.claim_rules import normalise  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.pipeline.claim_inputs import input_records  # noqa: E402
from marketbrief.pipeline.claim_sources import current_clusters, sources_by_cluster  # noqa: E402
from marketbrief.pipeline.evidence_status import EvidenceStatuses  # noqa: E402
from marketbrief.analytics.prediction_rules import check_news_status  # noqa: E402
from marketbrief.pipeline import claims as claims_cli  # noqa: E402
from marketbrief.pipeline import news_status as status_cli  # noqa: E402
from marketbrief.sources.primary_text import html_to_text  # noqa: E402

MARKET, NOW = nvt.MARKET, nvt.NOW                      # 2026-10-05T20:00Z
LATER = "2026-10-05T21:00:00+00:00"
SEC = REPO / "tests" / "fixtures" / "sec"
TSLA_8K, CVX_8K = "0001628280-26-064366", "0000093410-26-000188"
TSLA_DIR = "https://www.sec.gov/Archives/edgar/data/1318605/000162828026064366/"
CVX_DIR = "https://www.sec.gov/Archives/edgar/data/93410/000009341026000188/"
URLS = {TSLA_DIR + "index.json": "8k_index_tsla_0001628280-26-064366.json",
        TSLA_DIR + "tsla-20261002.htm": "8k_tsla-20261002.htm",
        TSLA_DIR + "exhibit991111111.htm": "8k_tsla_exhibit991111111.htm",
        CVX_DIR + "index.json": "8k_index_cvx_0000093410-26-000188.json",
        CVX_DIR + "cvx-20260930.htm": "8k_cvx-20260930.htm"}
FILINGS = [
    {"id": TSLA_8K, "ticker": "TSLA", "cik": "1318605", "form": "8-K", "filing_date": "2026-10-02",
     "accepted_at": "2026-10-02T13:04:26+00:00", "description": "8-K", "url": TSLA_DIR + "tsla-20261002.htm",
     "first_seen_at": "2026-10-05T14:29:05+00:00"},
    {"id": CVX_8K, "ticker": "CVX", "cik": "93410", "form": "8-K", "filing_date": "2026-10-05",
     "accepted_at": "2026-10-05T13:01:20+00:00", "description": "8-K", "url": CVX_DIR + "cvx-20260930.htm",
     "first_seen_at": "2026-10-05T14:29:05+00:00"},
]
TSLA_MINT = "Tesla Q3 deliveries hit 486,532 vehicles, beating estimates"
TSLA_WRONG = "Tesla Q3 deliveries hit 480K vehicles"
JIO_COPY = "Jio Platforms to launch $3.8 billion IPO on October 21, sources say"      # an unvetted copy


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    nvt.no_network.__wrapped__(monkeypatch)


@pytest.fixture
def env(tmp_path, monkeypatch, capsys):
    e = nvt.Env(tmp_path, monkeypatch)
    e.write("news", nvt.base_news())
    e.write("news", [nvt.news_row(30, TSLA_MINT, "TSLA", source="Mint", domain="livemint.com",
                                  pub="2026-10-03T13:30:00+00:00", seen="2026-10-03T14:00:00+00:00"),
                     nvt.news_row(31, TSLA_WRONG, "TSLA", source="TradingKey", domain="tradingkey.com",
                                  pub="2026-10-04T09:00:00+00:00", seen="2026-10-04T09:30:00+00:00"),
                     nvt.news_row(32, JIO_COPY, "RELIANCE", source="Dubious Daily", domain="dubiousdaily.xyz",
                                  conf="low")])
    e.write("filings", FILINGS)
    fixtures = tmp_path / "sec"
    fixtures.mkdir()
    (fixtures / "urls.json").write_text(json.dumps({u: str(SEC / f) for u, f in URLS.items()}))
    monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures))
    monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
    e.run(collect_articles, capsys)
    e.run(news_clusters, capsys)
    return e


def cli(env, capsys, *args, code=0) -> dict:
    env.mp.setattr(sys, "argv", ["claims", "--market", MARKET, *args])
    assert claims_cli.main() == code
    return json.loads(capsys.readouterr().out)


def run_status(env, capsys) -> dict:
    env.mp.setattr(sys, "argv", ["news_status", "--market", MARKET])
    assert status_cli.main() == 0
    return json.loads(capsys.readouterr().out)


def inputs(env) -> dict:
    lines = (env.root / "work" / "claim_inputs.jsonl").read_text().splitlines()
    return {r["cluster_id"]: r for r in map(json.loads, lines)}


TSLA_C, CVX_C, JIO_C = "TSLA-n30", "CVX-n01", "RELIANCE-n13"


def claim(cluster_id, fact, source, quote, **kw) -> dict:
    rec = {"cluster_id": cluster_id, "fact_key": fact, "claim_type": "earnings_guidance", "subject": "the company",
           "predicate": "states the fact", "quote": quote, "quote_source_id": source, "attribution": "on_record",
           "prompt_version": "claims-v3"}
    rec.update(kw)
    return rec


def write_claims(env, recs) -> Path:
    p = env.root / "work" / "claims.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return p


def test_html_to_text_reads_the_exhibit_table():
    text = html_to_text((SEC / "8k_tsla_exhibit991111111.htm").read_bytes())
    assert "delivered over 486,000 vehicles" in text and "Total 464,391 486,532" in normalise(text)
    main = html_to_text((SEC / "8k_tsla-20261002.htm").read_bytes())
    assert main.startswith("tsla-20261002\nUNITED STATES") and "FALSE0001318605" not in main  # hidden XBRL dropped


def test_prepare_selects_material_clusters_and_stores_primary_text(env, capsys):
    s = cli(env, capsys, "prepare")
    got = inputs(env)
    assert {TSLA_C, CVX_C, JIO_C} <= set(got) and s["selected"] == len(got) == s["eligible"] == 10
    assert set(got[TSLA_C]["origin_groups"][0]) == {"origin", "news_ids", "verified", "promotional", "opinion",
                                                    "unread_vetted"}
    fetched = s["primary_texts"]
    assert fetched["filings"] == 2 and fetched["documents"] == 3 and not fetched["failed"]
    texts = {r["id"]: r for r in env.rows("primary_texts")}
    assert set(texts) == {f"{TSLA_8K}:tsla-20261002.htm", f"{TSLA_8K}:exhibit991111111.htm",
                          f"{CVX_8K}:cvx-20260930.htm"}
    assert texts[f"{TSLA_8K}:exhibit991111111.htm"]["doc_type"] == "EX-99"
    assert all(r["available_at"] == FILINGS[0]["accepted_at"] for k, r in texts.items() if k.startswith(TSLA_8K))
    tsla = got[TSLA_C]
    assert {i["id"] for i in tsla["items"]} == {"n30", "n31"} and tsla["primary_sources"][0]["id"] == TSLA_8K
    assert [p["id"] for p in got[CVX_C]["primary_sources"]] == [CVX_8K] and got[JIO_C]["primary_sources"] == []
    assert next(i for i in got[CVX_C]["items"] if i["id"] == "n01")["extract"]          # the stored extract
    assert "486,532" in tsla["primary_sources"][0]["text"]
    # a rerun stores no text twice
    s2 = cli(env, capsys, "prepare")
    assert s2["primary_texts"]["filings"] == 0 and len(env.rows("primary_texts")) == 3


def test_claim_gate_rules(env, capsys):
    cli(env, capsys, "prepare")
    tsla = TSLA_C
    ok = claim(tsla, "q3-deliveries", TSLA_8K, "Total 464,391 486,532", value_num=486532, unit="count",
               predicate="delivered 486,532 vehicles", attribution="company_statement")
    bad = [
        claim(tsla, "q3-deliveries", TSLA_8K, "Total 464,391 486,533", value_num=486533, unit="count"),  # a digit
        claim(tsla, "q3-deliveries", "n30", TSLA_MINT, value_num=486000, unit="count"),        # value not in quote
        claim(tsla, "q3-deliveries", "n30", TSLA_MINT, predicate="delivered 22,141 more"),      # number not in quote
        claim(tsla, "q3-deliveries", "n30", TSLA_MINT, value_num=486532, unit="pct"),            # wrong unit marker
        claim(tsla, "q3", "n31", TSLA_MINT),                                                     # not n31 text
        claim("TSLA-nope", "q3", "n30", TSLA_MINT),                                              # unknown cluster
        claim(tsla, "q3", "nX9", TSLA_MINT),                                                     # not in the cluster
        claim(tsla, "Q3!", "n30", TSLA_MINT, claim_type="news", attribution="blog"),             # enums, slug
        claim(tsla, "q3", "n30", TSLA_MINT, invented_field=1),
        claim(tsla, "q3", "n30", " ".join(["word"] * 41)),
    ]
    out = cli(env, capsys, "validate", str(write_claims(env, [ok, *bad])), code=1)
    errors = {e["line"]: " ".join(e["errors"]) for e in out["errors"]}
    assert out["valid"] == 1 and set(errors) == set(range(2, 12))
    assert "verbatim" in errors[2] and "not a number stated in the quote" in errors[3]
    assert "numbers in predicate not in the quote: ['22141']" in errors[4] and "not a number stated" in errors[5]
    assert "verbatim" in errors[6] and "not a current cluster" in errors[7] and "not an item" in errors[8]
    assert "fact_key" in errors[9] and "claim_type" in errors[9] and "attribution" in errors[9]
    assert "unknown field" in errors[10] and "at most 40 words" in errors[11]
    # add is all or nothing; --valid-only appends the valid record and lists the dropped lines
    assert cli(env, capsys, "add", str(write_claims(env, [ok, *bad])), code=1)["appended"] == 0
    added = cli(env, capsys, "add", str(write_claims(env, [ok, bad[0]])), "--valid-only")
    assert added["appended"] == 1 and added["dropped"] == [2]
    row = env.rows("news_claims")[0]
    assert row["id"] == f"{tsla}|q3-deliveries|{TSLA_8K}" and row["source_kind"] == "filing"
    assert row["quote_field"] == "primary" and row["value_text"] == "486,532" and row["extracted_at"] == NOW
    assert row["source_available_at"] == NOW                               # the text was stored (fetched) at NOW
    again = cli(env, capsys, "validate", str(write_claims(env, [ok])), code=1)
    assert "already stored" in again["errors"][0]["errors"][0]


def extract_quote(env, news_id: str, words: int = 12) -> str:
    art = {r["id"]: r for r in env.rows("news_articles")}[news_id]
    return " ".join(art["extract"][0].split()[:words])


def scenario_claims(env) -> list[dict]:
    tsla, cvx, jio = TSLA_C, CVX_C, JIO_C
    cvx_quote = "the Board elected Jeff B. Gustavson to the position of Chief Financial Officer of Chevron"
    return [
        claim(tsla, "q3-deliveries", TSLA_8K, "Total 464,391 486,532", value_num=486532, unit="count",
              period="Q3 2026", attribution="company_statement"),
        claim(tsla, "q3-deliveries", "n30", TSLA_MINT, value_num=486532, unit="count", period="Q3"),
        claim(tsla, "q3-deliveries", "n31", TSLA_WRONG, value_num=480000, unit="count", period="Q3"),
        claim(cvx, "cfo", CVX_8K, cvx_quote, claim_type="mgmt_change", attribution="company_statement"),
        claim(cvx, "cfo", "n01", extract_quote(env, "n01"), claim_type="mgmt_change"),
        claim(jio, "jio-ipo", "n13", extract_quote(env, "n13"), claim_type="rumour", attribution="sources_say"),
    ]


def statuses_asof(ts: str) -> dict:
    con = connect(MARKET)
    rows = con.execute("SELECT cluster_id, coalesce(claim_id, '*'), status FROM news_verified_asof(?::TIMESTAMPTZ) "
                       "ORDER BY 1, 2", [ts]).fetchall()
    return {(t, c): s for t, c, s in rows}


def test_status_end_to_end_and_no_look_ahead(env, capsys):
    cli(env, capsys, "prepare")
    first = run_status(env, capsys)                                      # T1 = NOW: no claims yet
    assert first["claims"] == 0 and first["written"] == first["clusters"]
    before = statuses_asof(NOW)
    assert before[(CVX_C, "*")] == "single_source" and before[(JIO_C, "*")] == "rumour"
    env.set_now(LATER)                                                   # claims extracted at T2
    assert cli(env, capsys, "add", str(write_claims(env, scenario_claims(env))))["appended"] == 6
    second = run_status(env, capsys)
    # a rerun of prepare skips the checked rows; a new row of the cluster would list what is stored
    assert cli(env, capsys, "prepare")["already_checked"] == 3
    con, now = connect(MARKET), pd.Timestamp(LATER)
    rows = [c for c in current_clusters(con, now, 72) if c["cluster_id"] == TSLA_C]
    record = input_records(con, load_market(MARKET), rows, sources_by_cluster(con, rows, now), {}, now)[0]
    assert record["stored_claims"] == [{"fact_key": "q3-deliveries", "quote_source_id": q}
                                       for q in (TSLA_8K, "n30", "n31")]
    after = statuses_asof(LATER)
    assert after[(TSLA_C, "*")] == after[(TSLA_C, "q3-deliveries")] == "confirmed_primary"
    assert after[(CVX_C, "*")] == after[(CVX_C, "cfo")] == "confirmed_primary"
    assert after[(JIO_C, "jio-ipo")] == after[(JIO_C, "*")] == "rumour"
    assert second["facts_by_status"] == {"confirmed_primary": 2, "rumour": 1}
    con = connect(MARKET)
    ids = dict(con.execute("SELECT news_id, status FROM news_status_ids_asof(?::TIMESTAMPTZ) WHERE ticker = 'TSLA'",
                           [LATER]).fetchall())
    # n31's "480K" is quoted from a headline: never compared (headlines drop hedges), so no mismatch;
    # TradingKey is a listed promotional (vendor) domain, so its own status is promotional
    assert ids["n31"] == "promotional" and ids["n30"] == "confirmed_primary" and ids["n06"] == "promotional"
    row = con.execute("SELECT * FROM news_verified_asof(?::TIMESTAMPTZ) "
                      "WHERE cluster_id = 'TSLA-n30' AND level = 'cluster'",
                      [LATER]).df().iloc[0]
    assert list(row["mismatch_ids"]) == [] and json.loads(row["conflicts"]) == []
    assert {r["quote_field"] for r in env.rows("news_claims") if r["quote_source_id"] in ("n30", "n31")} == {"title"}
    # confirmed_at: when the filing was public (SEC acceptance), not when its text was stored (NOW)
    assert pd.Timestamp(row["confirmed_at"]) == pd.Timestamp(FILINGS[0]["accepted_at"])
    # an unvetted copy of the Jio rumour stays a rumour, so a call citing it is blocked
    jio_ids = dict(con.execute("SELECT news_id, status FROM news_status_ids_asof(?::TIMESTAMPTZ) "
                               "WHERE ticker = 'RELIANCE'", [LATER]).fetchall())
    assert "n32" in env.rows("news_clusters")[-1]["unvetted_ids"] or any(
        "n32" in r["unvetted_ids"] for r in env.rows("news_clusters"))
    assert jio_ids["n32"] == jio_ids["n13"] == "rumour"
    found = EvidenceStatuses(con).of("n32", "RELIANCE", LATER)
    rec = {"evidence_ids": ["n32"], "confidence": 0.6, "range_widen": None}
    assert [c for c, _ in check_news_status(rec, [found])] == ["NEWS_STATUS_MAIN", "NEWS_STATUS_BLOCKED"]
    # no look-ahead: as of T1 the claims (extracted at T2) are invisible, also to a recomputation at T1
    assert statuses_asof(NOW) == before
    env.set_now(NOW)
    redo = run_status(env, capsys)
    assert redo["claims"] == 0 and redo["written"] == 0 and redo["events_by_status"] == first["events_by_status"]
    # every stored row's inputs are no later than its as_of; the rows fit their schemas
    for r in env.rows("news_verified"):
        assert r["inputs_until"] <= r["as_of"]
    for kind in ("news_claims", "news_verified", "primary_texts"):
        assert row_checks.check_rows(kind, env.rows(kind), False, pd.Timestamp(LATER), timedelta(minutes=5)) == []


def test_prepare_without_sec_user_agent_or_with_no_fetch_stores_no_text(env, capsys):
    env.mp.delenv("SEC_USER_AGENT")
    s = cli(env, capsys, "prepare")
    assert s["primary_texts"]["skipped"].startswith("SEC_USER_AGENT not set") and not env.rows("primary_texts")
    assert inputs(env)[TSLA_C]["primary_without_text"] == [TSLA_8K]
    assert cli(env, capsys, "prepare", "--no-fetch")["primary_texts"] == {"skipped": "--no-fetch"}


def test_primary_only_fact_does_not_make_its_filing_main_evidence(env, capsys):
    """An event confirmed by nothing its outlets say: a filing quoted only for a side fact neither
    confirms the event nor becomes citable main evidence (NEWS_STATUS_MAIN)."""
    cli(env, capsys, "prepare")
    env.set_now(LATER)
    side = claim(CVX_C, "board-meeting", CVX_8K, "On September 30, 2026, the Board of Directors",
                 attribution="company_statement")
    story = claim(CVX_C, "cfo-story", "n01", extract_quote(env, "n01"), claim_type="mgmt_change")
    assert cli(env, capsys, "add", str(write_claims(env, [side, story])))["appended"] == 2
    run_status(env, capsys)
    after = statuses_asof(LATER)
    assert after[(CVX_C, "board-meeting")] == "confirmed_primary" and after[(CVX_C, "*")] == "single_source"
    con = connect(MARKET)
    assert EvidenceStatuses(con).of(CVX_8K, "CVX", LATER) == "unverified"
    rec = {"evidence_ids": [CVX_8K], "confidence": 0.9, "range_widen": None}
    assert [c for c, _ in check_news_status(rec, ["unverified"])] == ["NEWS_STATUS_MAIN", "NEWS_STATUS_CONFIDENCE"]


def test_late_primary_text_is_not_citable_or_counted_before_it_was_stored(env, capsys):
    env.set_now(LATER)
    cli(env, capsys, "prepare")                                          # filing text stored at T2
    tsla = TSLA_C
    primary = claim(tsla, "q3-deliveries", TSLA_8K, "Total 464,391 486,532", value_num=486532, unit="count")
    env.set_now(NOW)                                                     # T1: the text was not stored yet
    out = cli(env, capsys, "validate", str(write_claims(env, [primary])), code=1)
    assert "not an item or stored primary source" in out["errors"][0]["errors"][0]
    # a stored claim whose source became available after T1 is ignored by a status run at T1
    row = {**primary, "id": f"{tsla}|q3-deliveries|{TSLA_8K}", "cluster_row_id": "x", "ticker": "TSLA",
           "stance": "affirms", "value_text": "486,532", "quote_field": "primary", "source_kind": "filing",
           "news_ids": [], "source_available_at": LATER, "extracted_at": NOW, "method_version": "nv-b1",
           "period": None, "effective_date": None}
    outlet = {**row, "id": f"{tsla}|q3-deliveries|n30", "quote": TSLA_MINT, "quote_source_id": "n30",
              "quote_field": "title", "source_kind": "article", "news_ids": ["n30"],
              "source_available_at": "2026-10-03T14:00:00+00:00"}       # the outlet statement was there at T1
    env.write("news_claims", [row, outlet])
    s = run_status(env, capsys)
    assert s["claims"] == 1 and statuses_asof(NOW)[(TSLA_C, "*")] != "confirmed_primary"
    env.set_now(LATER)
    s = run_status(env, capsys)
    assert s["claims"] == 2 and statuses_asof(LATER)[(TSLA_C, "*")] == "confirmed_primary"
    assert statuses_asof(NOW)[(TSLA_C, "*")] != "confirmed_primary"   # the T1 row is unchanged history


def test_context_section_and_call_lines(env, capsys):
    from marketbrief.presentation import news_events
    cli(env, capsys, "prepare")
    env.set_now(LATER)
    cli(env, capsys, "add", str(write_claims(env, scenario_claims(env))))
    run_status(env, capsys)
    con = connect(MARKET)
    title, body = news_events.context_section(con)
    assert title.startswith("News events and verification status")
    first = body.splitlines()[0]          # issue #39: how many shown events may be main evidence now
    assert first.startswith("Events that may be a call's main evidence now (confirmed_primary or corroborated): ")
    assert first.endswith(": 2 of 8 shown (CVX, TSLA).")
    assert news_events.main_evidence_line([{"ticker": "INFY", "status": "single_source"}]) == (
        "Events that may be a call's main evidence now (confirmed_primary or corroborated): 0 of 1 shown. "
        "With none, every news-based call fails the forecast gate today: abstain or wait.")
    tsla = next(line for line in body.splitlines() if line.startswith("| TSLA |") and "486,532" in line)
    assert "| confirmed_primary |" in tsla and TSLA_8K in tsla and "2026-10-02 13:04 |" in tsla   # confirmed
    cols = [c.strip() for c in tsla.split("|")]
    assert cols[8] == f"{TSLA_8K}, n30"                                  # cite: the filing, then n30
    jio = next(line for line in body.splitlines() if line.startswith("| RELIANCE |"))
    assert "rumour" in jio and [c.strip() for c in jio.split("|")][8] == "–"   # a rumour is never cited
    env.write("predictions", [{"id": "2026-10-05-TSLA-5d", "made_at": LATER, "as_of_date": "2026-10-05",
                               "ticker": "TSLA", "horizon_days": 5, "direction": "up", "confidence": 0.6,
                               "rationale": "x", "evidence_ids": [TSLA_8K, "n30", "n31"], "prompt_version": "t"}])
    lines = news_events.call_status_lines(connect(MARKET), "2026-10-05")
    assert lines[2] == f"- TSLA 5d up: {TSLA_8K} confirmed_primary, n30 confirmed_primary, n31 promotional"


def test_text_stored_during_prepare_is_in_its_input(env, capsys, monkeypatch):
    """A live run's clock moves while filings are fetched: text stored at t1 > the run's start t0
    must still be in the input (sources are read as of after the fetch)."""
    later = pd.Timestamp(NOW) + pd.Timedelta(seconds=7)
    times = iter([pd.Timestamp(NOW), later])
    monkeypatch.setattr(claims_cli, "now_floor", lambda: next(times))
    monkeypatch.setattr(claims_cli, "utc_now", lambda: later.isoformat())
    cli(env, capsys, "prepare")
    tsla = inputs(env)[TSLA_C]
    assert tsla["primary_without_text"] == [] and tsla["primary_sources"][0]["id"] == TSLA_8K
