#!/usr/bin/env python3
"""Collect NSE announcements, results, FII/DII flows and delivery data.

Thin entry point; the code is in marketbrief/collectors/nse_india.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.nse_india import main

if __name__ == "__main__":
    sys.exit(main())
