#!/usr/bin/env python3
"""Daily range calibration for one market.

Thin entry point; the code is in marketbrief/analytics/calibration.py (`--help` shows its description)."""
import sys

from marketbrief.analytics.calibration import main

if __name__ == "__main__":
    sys.exit(main())
