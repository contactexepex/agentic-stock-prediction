#!/usr/bin/env python3
"""Compute the daily indicator snapshot and market regime for one market.

Thin entry point; the code is in marketbrief/analytics/features.py (`--help` shows its description)."""
import sys

from marketbrief.analytics.features import main

if __name__ == "__main__":
    sys.exit(main())
