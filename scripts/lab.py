#!/usr/bin/env python3
"""The strategy lab (B2): predict | pick | settle | news-impact | summary | backtest | pick-study. Research only:
a paper trade is a record, never an order. The logic lives in marketbrief/lab/ (cli.py has the usage)."""
from __future__ import annotations

import sys

from marketbrief.lab.cli import main

if __name__ == "__main__":
    sys.exit(main())
