#!/usr/bin/env python3
"""Collect recent SEC filings of the watchlist tickers.

Thin entry point; the code is in marketbrief/collectors/filings.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.filings import main

if __name__ == "__main__":
    sys.exit(main())
