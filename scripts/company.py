#!/usr/bin/env python3
"""The watchlist's lifecycle commands (F8): add (with onboarding), deactivate, reactivate, set-amount, delete, list,
seed and import-inbox. Research only: a watchlist event is a record, never an order. The logic lives in
marketbrief/lifecycle/ (cli.py has the usage)."""
from __future__ import annotations

import sys

from marketbrief.lifecycle.cli import main

if __name__ == "__main__":
    sys.exit(main())
