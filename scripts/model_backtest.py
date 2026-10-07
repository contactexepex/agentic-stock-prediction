#!/usr/bin/env python3
"""Walk-forward, out-of-sample backtest of the signal model; writes JSON and HTML into --out.

Thin entry point; the code is in marketbrief/model/backtest.py (`--help` shows its description)."""
import sys

from marketbrief.model.backtest import main

if __name__ == "__main__":
    sys.exit(main())
