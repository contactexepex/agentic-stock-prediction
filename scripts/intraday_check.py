#!/usr/bin/env python3
"""Intraday checks of the watchlist against the day's ranges and calls, and the deviation explainer's gate.

Thin entry point; the code is in marketbrief/intraday/cli.py (`--help` shows its description)."""
import sys

from marketbrief.intraday.cli import main

if __name__ == "__main__":
    sys.exit(main())
