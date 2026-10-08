"""The report skeleton's company and horizon headers (B1 owns presentation/report/report_text.py for the company list
and the N+k headers handed over by B10; issue #120): the range line names the first horizon, the Today table's columns
are N+first and N+last of config/strategies.yaml, and only sectors with an active company get a section.
Run: pytest -q tests/test_b1_report_text.py"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.core.horizons import horizons  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.presentation.report.report_parts import ReportParts  # noqa: E402
from marketbrief.presentation.report.report_text import render_report  # noqa: E402

DAY = {"session": "2026-10-07", "last_target": "2026-10-06", "evidence_status": [], "as_of": "2026-10-06",
       "regime": pd.DataFrame()}


def parts(**overrides) -> ReportParts:
    """Report parts with empty tables and the given values."""
    values = {field.name: [] for field in dataclasses.fields(ReportParts)}
    values.update(img=lambda *_args: [], one_day_name="N+1", one_day_count=3, h80=2, h50=1, nh80=2, line5="",
                  market_line="", regime_line="", release_line="", n_late=0, session=DAY["session"], cur="$",
                  market="us", vol_name="VIX", reg=None)
    values.update(overrides)
    return ReportParts(**values)


def test_range_line_and_today_columns_name_the_horizons():
    row = ["AAPL", "Tech", "214", "210-218", "212-216", "200-230", "–", "–", ""]
    text = render_report(load_market("us"), DAY, parts(today_rows=[row]))
    first, last = horizons()[0], horizons()[-1]
    assert "N+1 ranges: **80% hit 2/3** (naive 2/3) · 50% hit 1/3" in text
    header = next(line for line in text.splitlines() if line.startswith("| Ticker | Sector | Close"))
    assert f"| N+{first} 80% | N+{first} 50% | N+{last} 80% |" in header
    assert "Next day" not in text and "5 days 80%" not in text


def test_sector_sections_only_for_sectors_with_an_active_company():
    cfg = load_market("us")
    cfg["active_tickers"] = [ticker for ticker in cfg["tickers"] if ticker not in ("DAL", "UAL")]
    text = render_report(cfg, DAY, parts())
    assert "### Airlines" not in text and "<!-- AGENT:sector:Airlines -->" not in text
    assert "### Banks" in text
