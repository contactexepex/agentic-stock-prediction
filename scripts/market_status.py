#!/usr/bin/env python3
"""Print whether the market trades today and the session being predicted.

Thin entry point; the code is in marketbrief/pipeline/market_status.py (`--help` shows its description)."""
import sys

from marketbrief.pipeline.market_status import main

if __name__ == "__main__":
    sys.exit(main())
