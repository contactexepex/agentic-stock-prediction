#!/usr/bin/env python3
"""The paper portfolio (WS4): add-trade | cancel-trade | positions | pnl | request-company | list | signals |
paper-follow. Research only: a paper trade is a record, never an order. The logic lives in
marketbrief/portfolio/ (cli.py has the usage)."""
from __future__ import annotations

import sys

from marketbrief.portfolio.cli import main

if __name__ == "__main__":
    sys.exit(main())
