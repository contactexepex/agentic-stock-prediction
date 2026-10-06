#!/usr/bin/env python3
"""Collect daily OHLCV bars from Yahoo (with the NSE bhavcopy fallback for India).

Thin entry point; the code is in marketbrief/collectors/prices.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.prices import main

if __name__ == "__main__":
    sys.exit(main())
