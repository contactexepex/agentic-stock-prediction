#!/usr/bin/env python3
"""Intraday checks of the watchlist and of every open paper trade against the day's ranges, targets and calls, the
alerts feed, and the deviation explainer's gate.

Thin entry point; the code is in marketbrief/intraday/cli.py (`--help` shows its description)."""
import sys

from marketbrief.intraday.cli import main

if __name__ == "__main__":
    sys.exit(main())
