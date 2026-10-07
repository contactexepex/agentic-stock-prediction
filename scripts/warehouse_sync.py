#!/usr/bin/env python3
"""Copy a market's data and per-page read models into the warehouse (MotherDuck or the local file).

Thin entry point; the code is in marketbrief/warehouse/cli.py (`--help` shows its description)."""

import sys

from marketbrief.warehouse.cli import main

if __name__ == "__main__":
    sys.exit(main())
