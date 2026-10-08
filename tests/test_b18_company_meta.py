"""B18 (Wave 5): `tickers:` removed from config/markets/*.yaml. The companies come from B1's watchlist events (the
seed of 2026-10-07 holds the 20 config companies per market); the config keeps their per-company metadata under
`company_meta:` (marketbrief/lifecycle/, docs/ws/b18.md). B1's tests/test_lifecycle_company_meta.py proves the
loader gives byte-identical outputs from either key. Offline. Run: pytest -q tests/test_b18_company_meta.py"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.lifecycle.events import stored_events  # noqa: E402


@pytest.mark.parametrize("market", ["india", "us"])
def test_real_configs_hold_metadata_not_the_company_list(market):
    doc = yaml.safe_load((REPO / "config" / "markets" / f"{market}.yaml").read_text())
    assert "tickers" not in doc and len(doc["company_meta"]) == 20
    seeded = sorted(row["ticker"] for row in stored_events(market) if row.get("channel") == "seed")
    assert seeded == sorted(doc["company_meta"])                 # every metadata entry is a seeded company
    cfg = load_market(market)
    assert "company_meta" not in cfg and set(cfg["tickers"]) >= set(seeded) - {
        row["ticker"] for row in stored_events(market) if row.get("event") == "delete"}
