"""Shared pieces of the golden seed stand-ins: paths, scripted constants and stable numbers."""
from __future__ import annotations

import os
import sys
import zlib
from datetime import date
from pathlib import Path

import yaml

CODE = Path(__file__).resolve().parents[2]
FIXTURES = CODE / "tests" / "fixtures"
sys.path.insert(0, str(CODE / "scripts"))

HISTORY_ROWS = {"5d": 5, "1mo": 22, "3mo": 66, "1y": 252, "2y": 504}
SPLIT_EX_DATE = date(2026, 9, 30)
STALE_AFTER = date(2026, 9, 30)
SESSION_TIMES = {"india": ("Asia/Kolkata", "09:15"), "us": ("America/New_York", "09:30")}
TOPICS = ("Q3 results beat estimates", "announces share buyback", "CEO steps down", "wins large order",
          "faces regulatory probe", "raises guidance for the year", "plans acquisition of rival", "dividend declared",
          "profit falls on weak demand", "launches new product line")
NEWS_OUTLET_COUNT = 12


def crc(text: str) -> int:
    """A stable number for a name or URL."""
    return zlib.crc32(text.encode())


def market_config(market: str) -> dict:
    """The market's config as the collectors load it (MB_CONFIG)."""
    from marketbrief.core.market_config import load_market
    return load_market(market)


def listed_outlets() -> list[str]:
    """Allowlisted outlet domains whose pages may be fetched, in a fixed order."""
    sources = yaml.safe_load((Path(os.environ["MB_CONFIG"]) / "news_sources.yaml").read_text())
    domains = [d for d, meta in sources["domains"].items() if (meta or {}).get("tier") != "primary"
               and (meta or {}).get("fetch") is not False]
    return sorted(domains)[:NEWS_OUTLET_COUNT * 3]
