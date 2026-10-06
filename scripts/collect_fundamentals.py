#!/usr/bin/env python3
"""Collect SEC XBRL company facts (quarterly, half-yearly, annual).

Thin entry point; the code is in marketbrief/collectors/fundamentals.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.fundamentals import main

if __name__ == "__main__":
    sys.exit(main())
