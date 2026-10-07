"""Results digests (WS6), US: a results release is an SEC item 2.02 date kept by results_filter; its text is the 8-K
main document and EX-99 exhibits (real Tesla 8-K fixtures, stored through primary_texts); numbers come from the
first 10-Q of the quarter (pending until it is filed, never a later restatement); the earnings call is
`transcript_unavailable` unless the company filed prepared remarks with the SEC.

SCRATCH TEST DATA: the fundamentals rows are hand-made (fictional values for TSLA's quarters); the 8-K documents
and submissions are the real fixtures in tests/fixtures/sec (README there). The agent records below are written in
the results-analyst's role, quoting the stored exhibit text."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import common  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.results import cli as results_cli  # noqa: E402
from marketbrief.results.digest import Scope, due_releases, load_settings  # noqa: E402
from marketbrief.sources.sec_client import archive_url  # noqa: E402

MARKET = "rdus"
NOW = "2026-10-05T20:00:00+00:00"
SINCE = pd.Timestamp("2026-09-28", tz="UTC")
MARKET_YAML = """
market: rdus
name: Results digest test market (US)
calendar: XNYS
timezone: America/New_York
currency: USD
symbols:
  SPY: {yahoo: SPY, role: benchmark, name: S&P 500 ETF}
sectors:
  Autos: [TSLA]
tickers:
  TSLA: {name: Tesla}
news: {}
filings: sec
"""
SEC = REPO / "tests" / "fixtures" / "sec"
CIK, TSLA_8K, OTHER_8K = 1318605, "0001628280-26-064366", "0001628280-26-063820"
TSLA_DIR = "https://www.sec.gov/Archives/edgar/data/1318605/000162828026064366/"
FILING = {
    "id": TSLA_8K,
    "ticker": "TSLA",
    "cik": "1318605",
    "form": "8-K",
    "filing_date": "2026-10-02",
    "accepted_at": "2026-10-02T13:04:26+00:00",
    "description": "8-K",
    "url": TSLA_DIR + "tsla-20261002.htm",
    "first_seen_at": "2026-10-03T14:29:05+00:00",
}
RELEASE, CONCALL = "TSLA-results-2026-10-02", "TSLA-concall-2026-10-02"
EXHIBIT = f"{TSLA_8K}:exhibit991111111.htm"
QUOTE = (
    "In the third quarter, we produced over 464,000 vehicles, delivered over 486,000 vehicles and deployed "
    "13.7 GWh of energy storage products."
)
Q10, Q10_LATER = "0001628280-26-070000", "0001628280-27-070000"


def fund(concept, value, period, filing, prev=None, fiscal=(2026, "Q3")):
    (start, end), (accession, accepted) = period, filing
    return {
        "id": f"{accession}-{concept}-{end}",
        "ticker": "TSLA",
        "cik": "1318605",
        "concept": concept,
        "tag": concept,
        "tag_rank": 0,
        "unit": "USD",
        "period_start": start,
        "period_end": end,
        "period": "quarter",
        "fiscal_year": fiscal[0],
        "fiscal_period": fiscal[1],
        "form": "10-Q",
        "accession": accession,
        "filing_date": accepted[:10],
        "accepted_at": accepted,
        "value": value,
        "prev_value": prev,
        "first_seen_at": accepted,
    }


def quarter(values, period, filing, fiscal, prev=None):
    names = ("revenue", "net_income", "eps_diluted", "operating_income")
    return [
        fund(name, value, period, filing, prev and prev[i], fiscal)
        for i, (name, value) in enumerate(zip(names, values))
    ]


class Env:
    def __init__(self, tmp: Path, monkeypatch):
        self.root, self.cfg, self.mp = tmp / "repo", tmp / "config", monkeypatch
        (self.cfg / "markets").mkdir(parents=True)
        (self.cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
        for name in ("results.yaml", "settings.yaml", "events.yaml", "ranges.yaml"):
            (self.cfg / name).write_text((REPO / "config" / name).read_text())
        monkeypatch.setattr(common, "ROOT", self.root)
        monkeypatch.setattr(common, "CONFIG", self.cfg)
        fixtures = tmp / "sec"
        fixtures.mkdir()
        (fixtures / "tickers.json").write_text(json.dumps({"0": {"cik_str": CIK, "ticker": "TSLA", "title": "Tesla"}}))
        urls = {
            "https://www.sec.gov/files/company_tickers.json": "tickers.json",
            f"https://data.sec.gov/submissions/CIK{CIK:010d}.json": str(SEC / "submissions_tsla_trimmed.json"),
            TSLA_DIR + "index.json": str(SEC / "8k_index_tsla_0001628280-26-064366.json"),
            TSLA_DIR + "tsla-20261002.htm": str(SEC / "8k_tsla-20261002.htm"),
            TSLA_DIR + "exhibit991111111.htm": str(SEC / "8k_tsla_exhibit991111111.htm"),
        }
        for accession in (TSLA_8K, OTHER_8K):
            urls[archive_url(CIK, accession, f"{accession}.hdr.sgml")] = str(SEC / f"hdr_tsla_8k_{accession}.sgml")
        urls[archive_url(CIK, "0001104659-26-106432", "0001104659-26-106432.hdr.sgml")] = str(
            SEC / "hdr_tsla_form4_0001104659-26-106432.sgml"
        )
        (fixtures / "urls.json").write_text(json.dumps(urls))
        monkeypatch.setenv("MB_SEC_FIXTURES", str(fixtures))
        monkeypatch.setenv("SEC_USER_AGENT", "test test@example.com")
        monkeypatch.setenv("MB_NOW", NOW)

    def write(self, kind: str, rows: list[dict], day: str = "2026-10-03"):
        path = self.root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.writelines(json.dumps(row) + "\n" for row in rows)

    def rows(self, kind: str) -> list[dict]:
        return [
            json.loads(line)
            for path in sorted((self.root / "data" / MARKET / kind).glob("**/*.jsonl"))
            for line in path.read_text().splitlines()
            if line.strip()
        ]

    def cli(self, capsys, *args, code=0) -> dict:
        self.mp.setattr(sys, "argv", ["results_digest", "--market", MARKET, *args])
        assert results_cli.main() == code
        return json.loads(capsys.readouterr().out)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    e.write(
        "events",
        [
            {
                "id": "TSLA-earnings-2026-10-02",
                "date": "2026-10-02",
                "type": "earnings",
                "ticker": "TSLA",
                "name": "Tesla earnings",
                "source": "sec_history",
                "first_seen_at": "2026-10-03T04:00:00+00:00",
                "timing": "before_open",
            },
            {
                "id": "TSLA-earnings-2026-10-21",
                "date": "2026-10-21",
                "type": "earnings",
                "ticker": "TSLA",
                "name": "Tesla earnings",
                "source": "yfinance",
                "first_seen_at": "2026-10-03T04:00:00+00:00",
            },
        ],
    )
    e.write(
        "earnings_estimates",
        [  # collected after the release only: no consensus before it
            {
                "id": "TSLA-2026-10-02",
                "ticker": "TSLA",
                "report_date": "2026-10-02",
                "report_at": "2026-10-02T12:00:00+00:00",
                "eps_estimate": 0.40,
                "reported_eps": 0.50,
                "surprise_pct": 25.0,
                "source": "yfinance",
                "collected_at": "2026-10-03T05:00:00+00:00",
            }
        ],
    )
    e.write(
        "fundamentals",
        [
            *quarter(
                (2.25e10, 1.0e9, 0.30, 1.2e9),
                ("2026-04-01", "2026-06-30"),
                ("0001628280-26-050000", "2026-07-23T20:05:00+00:00"),
                (2026, "Q2"),
            ),
            *quarter(
                (2.0e10, 1.2e9, 0.36, 1.5e9),
                ("2025-07-01", "2025-09-30"),
                ("0001628280-25-070000", "2025-10-23T20:05:00+00:00"),
                (2025, "Q3"),
            ),
        ],
        day="2026-07-23",
    )
    # the quarter's own 10-Q (after the release), and a later 10-Q restating it as a comparative
    e.write(
        "fundamentals",
        quarter(
            (2.5e10, 1.5e9, 0.45, 1.8e9), ("2026-07-01", "2026-09-30"), (Q10, "2026-10-22T20:05:00+00:00"), (2026, "Q3")
        ),
        day="2026-10-23",
    )
    e.write(
        "fundamentals",
        quarter(
            (2.55e10, 1.4e9, 0.42, 1.7e9),
            ("2026-07-01", "2026-09-30"),
            (Q10_LATER, "2027-10-21T20:05:00+00:00"),
            (2027, "Q3"),
            prev=(2.5e10, 1.5e9, 0.45, 1.8e9),
        ),
        day="2027-10-22",
    )
    frame = pd.DataFrame(
        [
            {
                "date": day,
                "ticker": ticker,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "adj_close": close,
                "volume": 1000,
                "collected_at": "2026-10-05T21:00:00+00:00",
            }
            for ticker, day, close in [
                ("TSLA", "2026-10-01", 400.0),
                ("TSLA", "2026-10-02", 392.0),
                ("SPY", "2026-10-01", 600.0),
                ("SPY", "2026-10-02", 603.0),
            ]
        ]
    )
    path = e.root / "data" / MARKET / "prices" / "2026" / "10" / "2026-10-02.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return e


def record() -> dict:
    return {
        "release_id": RELEASE,
        "kind": "results",
        "prompt_version": "results-v1",
        "bullets": [
            {
                "topic": "headline_numbers",
                "text": "Tesla delivered over 486,000 vehicles and deployed 13.7 GWh of storage.",
                "quote": QUOTE,
                "source_id": EXHIBIT,
            }
        ],
    }


def write_records(env: Env, records: list) -> Path:
    path = env.root / "work" / "results_digest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_release_text_numbers_pending_and_transcript_unavailable(env, capsys):
    env.write("filings", [FILING])
    s = env.cli(capsys, "prepare", "--since", "2026-09-28")
    by_id = {r["release_id"]: r for r in s["releases"]}
    assert set(by_id) == {RELEASE, CONCALL}  # the yfinance date in the future is no release
    assert by_id[RELEASE]["status"] == "ok" and by_id[RELEASE]["numbers_status"] == "pending_report"
    assert by_id[RELEASE]["release_at"] == "2026-10-02T13:04:26+00:00"  # the 2.02 filing's acceptance
    assert by_id[CONCALL]["status"] == "transcript_unavailable"
    assert s["texts"]["filings"] == 1 and s["texts"]["documents"] == 2
    texts = {t["id"]: t for t in env.rows("primary_texts")}
    assert set(texts) == {f"{TSLA_8K}:tsla-20261002.htm", EXHIBIT} and QUOTE in texts[EXHIBIT]["text"]
    found = {
        f.release.id: f
        for f in due_releases(connect(MARKET), load_market(MARKET), Scope(pd.Timestamp(NOW), SINCE), load_settings())[0]
    }[RELEASE]
    assert found.consensus["status"] == "none_before_release" and found.consensus["consensus_eps"] is None
    assert found.consensus["note"] == "context only"
    assert (found.reaction["window"], found.reaction["move_pct"], found.reaction["excess_pct"]) == (
        ["2026-10-02"],
        -2.0,
        -2.5,
    )

    bad = record()
    bad["bullets"] = [{**bad["bullets"][0], "text": "Tesla delivered over 490,000 vehicles."}]
    s = env.cli(capsys, "validate", str(write_records(env, [bad])), code=1)
    assert "['490,000']" in s["errors"][0]["errors"][0]
    s = env.cli(capsys, "add", str(write_records(env, [record()])))
    assert (s["valid"], s["without_text"], s["appended"]) == (1, 1, 2)
    rows = {r["id"]: r for r in env.rows("results_digests")}
    assert rows[RELEASE]["release_time_basis"] == "sec_accepted_at" and rows[RELEASE]["numbers"] == {}
    assert rows[CONCALL]["status"] == "transcript_unavailable"
    assert env.cli(capsys, "prepare", "--no-fetch", "--since", "2026-09-28")["due"] == 0

    # the 10-Q is filed: the release is due again with its numbers, the earlier bullets offered for reuse
    env.mp.setenv("MB_NOW", "2026-10-25T12:00:00+00:00")
    s = env.cli(capsys, "prepare", "--no-fetch", "--since", "2026-09-28")
    assert [(r["release_id"], r["numbers_status"]) for r in s["releases"]] == [(RELEASE, "ok")]
    line = json.loads((env.root / "work" / "results_inputs.jsonl").read_text().splitlines()[0])
    assert line["stored_bullets"][0]["quote"] == QUOTE
    numbers = line["numbers"]
    assert (numbers["revenue"], numbers["revenue_yoy_pct"], numbers["revenue_qoq_pct"]) == (2.5e10, 25.0, 11.11)
    assert (numbers["eps_diluted"], numbers["eps_yoy_pct"], numbers["filing_ids"]) == (0.45, 25.0, [Q10])


def test_later_restatement_is_not_used(env):
    env.write("filings", [FILING])
    env.mp.setenv("MB_NOW", "2027-11-01T12:00:00+00:00")
    found = {
        f.release.id: f
        for f in due_releases(
            connect(MARKET), load_market(MARKET), Scope(pd.Timestamp("2027-11-01T12:00:00Z"), SINCE), load_settings()
        )[0]
    }[RELEASE]
    assert found.numbers_as_of == pd.Timestamp("2026-10-22T20:05:00Z")
    assert (found.numbers["revenue"], found.numbers["eps_diluted"]) == (2.5e10, 0.45)


@pytest.mark.usefixtures("env")
def test_previous_quarter_is_never_taken_for_the_new_one():
    """Before the quarter's 10-Q, the Q2 report (ended 94 days before the release) is known: still pending."""
    found = {
        f.release.id: f
        for f in due_releases(connect(MARKET), load_market(MARKET), Scope(pd.Timestamp(NOW), SINCE), load_settings())[0]
    }[RELEASE]
    assert found.numbers_status == "pending_report" and found.numbers == {}


def test_filing_found_through_submissions_when_not_stored(env, capsys):
    s = env.cli(capsys, "prepare", "--since", "2026-09-28")
    assert {r["release_id"]: r["status"] for r in s["releases"]}[RELEASE] == "ok"
    assert {t["primary_id"] for t in env.rows("primary_texts")} == {TSLA_8K}  # the 2.02 filing only


def test_prepared_remarks_filed_with_the_sec_make_a_call_digest(env, capsys):
    env.write("filings", [FILING])
    env.write(
        "primary_texts",
        [
            {
                "id": "0001628280-26-064400:ex992.htm",
                "primary_id": "0001628280-26-064400",
                "ticker": "TSLA",
                "source": "sec",
                "form": "8-K",
                "doc": "ex992.htm",
                "doc_type": "EX-99",
                "url": TSLA_DIR + "ex992.htm",
                "available_at": "2026-10-03T13:00:00+00:00",
                "fetched_at": "2026-10-03T14:00:00+00:00",
                "text": "Prepared remarks of the Chief Financial Officer. "
                "Demand for Model Y stayed strong in the quarter.",
                "chars": 96,
                "truncated": False,
                "content_hash": "x",
                "method_version": "test",
            }
        ],
    )
    s = env.cli(capsys, "prepare", "--no-fetch", "--since", "2026-09-28")
    assert {r["release_id"]: r["status"] for r in s["releases"]}[CONCALL] == "ok"
    call = {
        "release_id": CONCALL,
        "kind": "concall",
        "prompt_version": "results-v1",
        "bullets": [
            {
                "topic": "commentary",
                "text": "The CFO said demand for Model Y stayed strong.",
                "quote": "Demand for Model Y stayed strong in the quarter.",
                "source_id": "0001628280-26-064400:ex992.htm",
            }
        ],
    }
    wrong_kind = {**call, "kind": "results"}
    assert (
        "does not match release"
        in env.cli(capsys, "validate", str(write_records(env, [wrong_kind])), code=1)["errors"][0]["errors"][0]
    )
    s = env.cli(capsys, "add", str(write_records(env, [call])))
    # with --no-fetch the 8-K text is not fetched, so the results release has nothing to quote: text_unavailable
    assert (s["valid"], s["without_text"], s["missing"], s["appended"]) == (1, 1, [], 2)
    stored = {r["id"]: r for r in env.rows("results_digests")}
    assert stored[CONCALL]["status"] == "ok" and stored[CONCALL]["bullets"][0]["source_kind"] == "filing"
    assert stored[CONCALL]["numbers_status"] == "unavailable" and stored[RELEASE]["status"] == "text_unavailable"
