#!/usr/bin/env python3
"""Collect RSS headlines and tag them with watchlist tickers.

Thin entry point; the code is in marketbrief/collectors/news.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.news import main

if __name__ == "__main__":
    sys.exit(main())
