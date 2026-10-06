#!/usr/bin/env python3
"""Snapshot the latest price of overnight and pre-open cues.

Thin entry point; the code is in marketbrief/collectors/quotes.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.quotes import main

if __name__ == "__main__":
    sys.exit(main())
