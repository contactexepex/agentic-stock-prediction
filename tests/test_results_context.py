"""Results digests (WS6) in the context pack: the section shows the active companies' digests of the window as stored
by now (MB_NOW-aware, no look-ahead) and is omitted when there is none.

SCRATCH TEST DATA: the hand-made India release of tests/test_results_india.py (fictional Alpha Industries, AAA),
digested through the CLI with that test's results-analyst record."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import test_results_india as india  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.results.context_section import context_section  # noqa: E402

env = india.env  # the India test's fixture (data, config, NSE replay, MB_NOW)


def section(cfg=None):
    return context_section(cfg or load_market(india.MARKET), connect(india.MARKET))


def test_section_shows_stored_digests_of_active_companies_as_of_now(env, capsys):
    assert section() is None  # nothing stored yet: the section is omitted, the pack is unchanged
    env.cli(capsys, "prepare")
    env.cli(capsys, "add", str(india.write_records(env, [india.good_record()])))
    title, body = section()
    assert title == "Results digests (last 10 days; context only, not a range or forecast input)"
    row = next(line for line in body.splitlines() if line.startswith("| AAA | 2026-08-07 | results"))
    assert "| FY2027 Q1 | 25.0 | 25.0 | 15.0 | 20.0 | 4.0 | ok | ok |" in row
    assert "| AAA | 2026-08-09 | concall |" in body and "text_unavailable" in body
    one_off = "- AAA results one_off: An exceptional loss of Rs 12 crore relates to closing the Pune plant."
    assert f"{one_off} [{india.TEXT_ID}]" in body

    # as of a time before the digests were stored, and after the window: omitted
    env.mp.setenv("MB_NOW", "2026-08-08T00:00:00+00:00")
    assert section() is None
    env.mp.setenv("MB_NOW", "2026-08-25T00:00:00+00:00")
    assert section() is None
    # a company that is no longer active is not shown
    env.mp.setenv("MB_NOW", india.NOW)
    assert section({**load_market(india.MARKET), "active_tickers": []}) is None
