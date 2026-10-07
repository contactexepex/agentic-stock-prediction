"""Results digests (WS6), India: detection from NSE filings and announcements, numbers as filed with the release
(a later revision is not used), the consensus point stored before the release, the price reaction, NSE attachment
texts (archive host only; PDFs need a configured parser), the gate and `add`.

SCRATCH TEST DATA: hand-made rows for a fictional company (Alpha Industries, ticker AAA). The attachment text is
written by this test and served through the NSE client's replay folder; the agent records below are written in the
results-analyst's role, quoting that stored text."""

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
from marketbrief.pipeline.validate.row_checks import check_rows  # noqa: E402
from marketbrief.results import cli as results_cli  # noqa: E402
from marketbrief.results.digest import Scope, due_releases, load_settings  # noqa: E402
from marketbrief.results.payload import stock_results_payload  # noqa: E402
from marketbrief.sources.nse_client import Nse  # noqa: E402

MARKET = "rdin"
NOW = "2026-08-10T13:00:00+00:00"
MARKET_YAML = """
market: rdin
name: Results digest test market (India)
calendar: XBOM
timezone: Asia/Kolkata
currency: INR
symbols:
  NIFTY50: {yahoo: "^NSEI", role: benchmark, name: Nifty 50}
sectors:
  Metals: [AAA]
tickers:
  AAA: {name: Alpha Industries}
news: {}
filings: none
"""
ARCHIVE = "https://nsearchives.nseindia.com/corporate/"
ATTACHMENT = (
    "Alpha Industries Limited\n"
    "Revenue from operations rose 25% to Rs 1,000 crore in the quarter ended June 30, 2026.\n"
    "The Board expects capacity utilisation to improve in the second half of the year.\n"
    "An exceptional loss of Rs 12 crore relates to the closure of the Pune plant.\n"
)
RESULTS_FILE = "AAA_07082026_results.txt"
RELEASE = "AAA-results-2026-06-30"
CONCALL = "AAA-concall-nse-ann-2"
TEXT_ID = f"nse-ann-1:{RESULTS_FILE}"


def fin(basis, period, values, filed, seen="2026-08-07T12:30:00+00:00", seq="1"):
    (start, end), (revenue, net, eps) = period, values
    return {
        "id": f"nse-fin-AAA-{basis}-{start}-{end}-{seq}",
        "ticker": "AAA",
        "basis": basis,
        "period_type": "quarterly",
        "period_start": start,
        "period_end": end,
        "revenue": revenue,
        "revenue_item": "RevenueFromOperations",
        "total_income": revenue * 1.02,
        "profit_before_tax": net * 1.3,
        "net_profit": net,
        "profit_to_owners": net,
        "eps_basic": eps,
        "eps_diluted": eps,
        "audited": "Un-Audited",
        "taxonomy": "Ind AS",
        "filing_type": "Original",
        "filed_at": filed,
        "url": f"{ARCHIVE}x{seq}.xml",
        "seq_id": seq,
        "first_seen_at": seen,
    }


def ann(ann_id, category, subject, url, published):
    return {
        "id": ann_id,
        "ticker": "AAA",
        "company": "Alpha Industries Limited",
        "published_at": published,
        "category": category,
        "subject": subject,
        "url": url,
        "source": "nse_announcements",
        "first_seen_at": published,
    }


class Env:
    def __init__(self, tmp: Path, monkeypatch):
        self.root, self.cfg, self.mp = tmp / "repo", tmp / "config", monkeypatch
        (self.cfg / "markets").mkdir(parents=True)
        (self.cfg / "markets" / f"{MARKET}.yaml").write_text(MARKET_YAML)
        for name in ("results.yaml", "settings.yaml", "events.yaml", "ranges.yaml"):
            (self.cfg / name).write_text((REPO / "config" / name).read_text())
        monkeypatch.setattr(common, "ROOT", self.root)
        monkeypatch.setattr(common, "CONFIG", self.cfg)
        self.replay = tmp / "nse_replay"
        self.replay.mkdir()
        (self.replay / RESULTS_FILE).write_text(ATTACHMENT)
        self.requested: list[str] = []
        env = self

        class RecordingNse(Nse):
            def send(self, url, **_kwargs):  # never reached with replay; recorded to prove it
                env.requested.append(url)
                raise AssertionError(f"network access attempted: {url}")

        monkeypatch.setattr(results_cli, "nse_client", lambda _cfg: RecordingNse(replay=self.replay))
        monkeypatch.setenv("MB_NOW", NOW)

    def write(self, kind: str, rows: list[dict], day: str = "2026-08-07"):
        path = self.root / "data" / MARKET / kind / day[:4] / day[5:7] / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.writelines(json.dumps(row) + "\n" for row in rows)

    def prices(self, rows: list[tuple[str, str, float]]):
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
                    "collected_at": "2026-08-10T12:30:00+00:00",
                }
                for ticker, day, close in rows
            ]
        )
        path = self.root / "data" / MARKET / "prices" / "2026" / "08" / "2026-08-10.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)

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
        "financials",
        [
            fin(
                "consolidated",
                ("2026-04-01", "2026-06-30"),
                (1.0e10, 1.5e9, 15.0),
                "2026-08-07T11:54:55+00:00",
                seq="11",
            ),
            fin(
                "standalone", ("2026-04-01", "2026-06-30"), (8.0e9, 1.2e9, 12.0), "2026-08-07T11:54:34+00:00", seq="12"
            ),
            fin(
                "consolidated", ("2025-04-01", "2025-06-30"), (8.0e9, 1.2e9, 12.0), "2025-08-08T10:00:00+00:00", seq="5"
            ),
            fin(
                "consolidated", ("2026-01-01", "2026-03-31"), (9.0e9, 1.0e9, 10.0), "2026-05-10T10:00:00+00:00", seq="9"
            ),
            # a revision of the previous quarter filed after the release: not new, and not used by its QoQ
            fin(
                "consolidated",
                ("2026-01-01", "2026-03-31"),
                (9.05e9, 1.0e9, 10.0),
                "2026-08-09T10:00:00+00:00",
                seen="2026-08-09T11:00:00+00:00",
                seq="13",
            ),
        ],
    )
    # a restatement of the released quarter, two months later
    e.write(
        "financials",
        [
            fin(
                "consolidated",
                ("2026-04-01", "2026-06-30"),
                (1.1e10, 1.6e9, 16.0),
                "2026-10-01T10:00:00+00:00",
                seen="2026-10-01T12:00:00+00:00",
                seq="20",
            )
        ],
        day="2026-10-01",
    )
    e.write(
        "announcements",
        [
            ann(
                "nse-ann-1",
                "Financial Result Updates",
                "Alpha Industries Limited has informed the Exchange about Financial Results for period ended "
                "June 30, 2026",
                ARCHIVE + RESULTS_FILE,
                "2026-08-07T12:05:00+00:00",
            ),
            ann(
                "nse-ann-4",
                "Press Release",
                "Alpha Industries results press release",
                "https://www.example.com/AAA_results.txt",
                "2026-08-07T12:10:00+00:00",
            ),
            ann(
                "nse-ann-3",
                "General Updates",
                "Alpha Industries Limited has informed the Exchange about an update",
                ARCHIVE + "AAA_update.txt",
                "2026-08-08T09:00:00+00:00",
            ),
            ann(
                "nse-ann-2",
                "Analysts/Institutional Investor Meet/Con. Call Updates",
                "Alpha Industries Limited has informed the Exchange about Transcript of earnings call",
                ARCHIVE + "AAA_transcript.pdf",
                "2026-08-09T09:00:00+00:00",
            ),
        ],
    )
    e.write(
        "earnings_estimates",
        [
            {
                "id": "AAA-2026-08-07",
                "ticker": "AAA",
                "report_date": "2026-08-07",
                "report_at": "2026-08-07T10:00:00+00:00",
                "eps_estimate": 13.0,
                "reported_eps": None,
                "surprise_pct": None,
                "source": "yfinance",
                "collected_at": "2026-08-01T05:00:00+00:00",
            },
            # collected after the release: a revised estimate and the reported EPS (outcomes, not the consensus)
            {
                "id": "AAA-2026-08-07",
                "ticker": "AAA",
                "report_date": "2026-08-07",
                "report_at": "2026-08-07T10:00:00+00:00",
                "eps_estimate": 14.0,
                "reported_eps": 15.6,
                "surprise_pct": 11.4,
                "source": "yfinance",
                "collected_at": "2026-08-07T12:30:00+00:00",
            },
        ],
    )
    e.prices(
        [
            ("AAA", "2026-08-06", 98.0),
            ("AAA", "2026-08-07", 100.0),
            ("AAA", "2026-08-10", 104.0),
            ("NIFTY50", "2026-08-06", 24900.0),
            ("NIFTY50", "2026-08-07", 25000.0),
            ("NIFTY50", "2026-08-10", 25250.0),
        ]
    )
    return e


def good_record() -> dict:
    return {
        "release_id": RELEASE,
        "kind": "results",
        "prompt_version": "results-v1",
        "bullets": [
            {
                "topic": "headline_numbers",
                "text": "Revenue from operations rose 25% to Rs 1,000 crore.",
                "quote": "Revenue from operations rose 25% to Rs 1,000 crore in the quarter ended June 30, 2026.",
                "source_id": TEXT_ID,
            },
            {
                "topic": "headline_numbers",
                "text": "Net profit grew 25.0% year on year; EPS of 15.0 against a consensus of 13.0 (surprise 20.0%).",
                "quote": "Alpha Industries Limited",
                "source_id": TEXT_ID,
            },
            {
                "topic": "one_off",
                "text": "An exceptional loss of Rs 12 crore relates to closing the Pune plant.",
                "quote": "An exceptional loss of Rs 12 crore relates to the closure of the Pune plant.",
                "source_id": TEXT_ID,
            },
            {
                "topic": "guidance",
                "text": "The Board expects capacity utilisation to improve in the second half.",
                "quote": "The Board expects capacity utilisation to improve in the second half of the year.",
                "source_id": TEXT_ID,
            },
        ],
    }


def write_records(env: Env, records: list) -> Path:
    path = env.root / "work" / "results_digest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_prepare_detects_new_releases_and_stores_archive_text_only(env, capsys):
    s = env.cli(capsys, "prepare")
    assert [r["release_id"] for r in s["releases"]] == [CONCALL, RELEASE]
    by_id = {r["release_id"]: r for r in s["releases"]}
    assert by_id[RELEASE]["status"] == "ok" and by_id[CONCALL]["status"] == "text_unavailable"
    assert s["for_agent"] == 1
    # off-archive and PDF attachments are never requested; the archive text attachment is read from the replay
    assert s["texts"]["not_read"] == {"nse-ann-4": "not_nse_archive", "nse-ann-2": "pdf_not_parsed"}
    assert env.requested == [] and s["texts"]["attachments"] == 1
    texts = env.rows("primary_texts")
    assert [(t["id"], t["source"], t["available_at"]) for t in texts] == [(TEXT_ID, "nse", "2026-08-07T12:05:00+00:00")]
    assert texts[0]["text"] == ATTACHMENT.strip() or texts[0]["text"] == ATTACHMENT
    inputs = [json.loads(line) for line in (env.root / "work" / "results_inputs.jsonl").read_text().splitlines()]
    assert [i["release_id"] for i in inputs] == [RELEASE]
    # the subjects of both results announcements are NSE's own text; only the archive attachment's text is stored
    assert {src["id"] for src in inputs[0]["sources"]} == {"nse-ann-1", "nse-ann-4", TEXT_ID}


def test_numbers_are_as_filed_with_the_release(env):
    cfg, settings = load_market(MARKET), load_settings()
    found = {
        f.release.id: f
        for f in due_releases(
            connect(MARKET), cfg, Scope(pd.Timestamp(NOW), pd.Timestamp("2026-08-01", tz="UTC")), settings
        )[0]
    }[RELEASE]
    numbers = found.numbers
    assert found.release.release_at == pd.Timestamp("2026-08-07T11:54:34Z")  # first filing of the quarter
    assert found.numbers_as_of == pd.Timestamp("2026-08-07T11:54:55Z")  # both bases, within the grace
    assert numbers["basis"] == "consolidated" and numbers["fiscal_label"] == "FY2027 Q1"
    assert (numbers["revenue"], numbers["net_profit"], numbers["eps_diluted"]) == (1.0e10, 1.5e9, 15.0)
    assert numbers["revenue_yoy_pct"] == 25.0 and numbers["net_profit_yoy_pct"] == 25.0
    assert numbers["revenue_qoq_pct"] == 11.11  # 9.0e9 as filed then, not the later 9.05e9 revision
    assert numbers["net_margin_pct"] == 15.0
    # MB_NOW two months later: the October restatement exists but the release's numbers do not change
    env.mp.setenv("MB_NOW", "2026-10-05T12:00:00+00:00")
    later = due_releases(
        connect(MARKET),
        cfg,
        Scope(pd.Timestamp("2026-10-05T12:00:00Z"), pd.Timestamp("2026-08-01", tz="UTC")),
        settings,
    )[0]
    restated = {f.release.id: f for f in later}[RELEASE].numbers
    assert (restated["revenue"], restated["eps_diluted"], restated["revenue_qoq_pct"]) == (1.0e10, 15.0, 11.11)


@pytest.mark.usefixtures("env")
def test_consensus_is_the_last_point_before_the_release():
    found = {
        f.release.id: f
        for f in due_releases(
            connect(MARKET),
            load_market(MARKET),
            Scope(pd.Timestamp(NOW), pd.Timestamp("2026-08-01", tz="UTC")),
            load_settings(),
        )[0]
    }[RELEASE]
    c = found.consensus
    assert (c["status"], c["consensus_eps"], c["consensus_collected_at"]) == (
        "before_release",
        13.0,
        "2026-08-01T05:00:00+00:00",
    )
    assert (c["reported_eps"], c["surprise_basis"], c["surprise_pct"]) == (15.6, "yahoo_reported_vs_consensus", 20.0)
    assert c["note"] == "context only"
    r = found.reaction
    assert (r["window"], r["base_date"], r["move_pct"], r["benchmark_move_pct"], r["excess_pct"]) == (
        ["2026-08-10"],
        "2026-08-07",
        4.0,
        1.0,
        3.0,
    )


def test_gate_and_add(env, capsys):
    env.cli(capsys, "prepare")
    bad = good_record()
    bad["bullets"] = [
        {**bad["bullets"][0], "quote": "Revenue rose 25% to Rs 1,000 crore"},  # not verbatim
        {**bad["bullets"][0], "text": "Revenue from operations rose 30% to Rs 1,000 crore."},  # wrong number
        {**bad["bullets"][0], "source_id": "nse-ann-99:AAA.txt"},  # invented source
        {**bad["bullets"][3], "text": "Investors should buy the stock before the second half."},
        {**bad["bullets"][3], "topic": "forecast"},
    ]
    invented = {**good_record(), "release_id": "AAA-results-2026-03-31"}
    s = env.cli(capsys, "validate", str(write_records(env, [bad, invented, "not json"])), code=1)
    errors = {e["line"]: " | ".join(e["errors"]) for e in s["errors"]}
    assert "bullet 1: quote not found verbatim" in errors[1]
    assert "bullet 2: numbers in text neither in the quote nor among the release's numbers: ['30%']" in errors[1]
    assert "bullet 3: source_id 'nse-ann-99:AAA.txt' is not a stored text" in errors[1]
    assert "must not predict prices or recommend trades (found 'buy')" in errors[1]
    assert "bullet 5: topic must be one of" in errors[1]
    assert "is not a current release with text to quote" in errors[2]
    assert set(errors) == {1, 2, 3} and s["valid"] == 0
    s = env.cli(capsys, "add", str(write_records(env, [bad])), code=1)
    assert s["appended"] == 0 and env.rows("results_digests") == []

    s = env.cli(capsys, "add", str(write_records(env, [good_record()])))
    assert (s["valid"], s["without_text"], s["appended"]) == (1, 1, 2)
    rows = {r["id"]: r for r in env.rows("results_digests")}
    assert rows[RELEASE]["status"] == "ok" and len(rows[RELEASE]["bullets"]) == 4
    assert rows[RELEASE]["bullets"][0]["source_kind"] == "attachment"
    assert rows[CONCALL]["status"] == "text_unavailable" and rows[CONCALL]["bullets"] == []
    assert rows[RELEASE]["inputs_until"] <= rows[RELEASE]["created_at"]
    # the daily run's validate gate accepts the new rows (schema types, ISO UTC timestamps)
    for kind in ("results_digests", "primary_texts"):
        assert check_rows(kind, env.rows(kind), False, pd.Timestamp(NOW), pd.Timedelta(minutes=5)) == []
    # stored: nothing is due again until an input changes
    s = env.cli(capsys, "prepare")
    assert (s["due"], s["already_stored"]) == (0, 2)
    payload = stock_results_payload(connect(MARKET), "AAA")
    assert payload["latest_results"]["numbers"]["revenue"] == 1.0e10
    assert payload["latest_concall"]["status"] == "text_unavailable"
    assert [h["id"] for h in payload["history"]] == [CONCALL, RELEASE]
    assert stock_results_payload(connect(MARKET), "AAA", as_of="2026-08-08T00:00:00+00:00")["latest_results"] is None


def test_pdf_attachment_with_a_configured_parser(env, capsys):
    pytest.importorskip("pypdf")
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure()
    fig.text(0.1, 0.5, "Moderator: Welcome to the Alpha Industries earnings call.")
    fig.savefig(env.replay / "AAA_transcript.pdf", format="pdf")
    conf = env.cfg / "results.yaml"
    conf.write_text(conf.read_text().replace("  pdf_parser: null", "  pdf_parser: pypdf"))
    s = env.cli(capsys, "prepare")
    assert {r["release_id"]: r["status"] for r in s["releases"]}[CONCALL] == "ok"
    texts = {t["id"]: t for t in env.rows("primary_texts")}
    assert "Welcome to the Alpha Industries earnings call" in texts["nse-ann-2:AAA_transcript.pdf"]["text"]
