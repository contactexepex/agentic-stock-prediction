#!/usr/bin/env python3
"""Publish today's price ranges per ticker and horizon for one market.

Thin entry point; the code is in marketbrief/analytics/range_publication.py (`--help` shows its description)."""
import sys

from marketbrief.analytics.range_publication import main

if __name__ == "__main__":
    sys.exit(main())
