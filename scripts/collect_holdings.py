#!/usr/bin/env python3
"""Collect quarterly 13F holdings of large institutional filers.

Thin entry point; the code is in marketbrief/collectors/holdings.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.holdings import main

if __name__ == "__main__":
    sys.exit(main())
