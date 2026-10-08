#!/usr/bin/env python3
"""Check a market's stored read models against the API contract and the approved mockups.

Thin entry point; the code is in marketbrief/warehouse/contract_cli.py (`--help` shows its description)."""

import sys

from marketbrief.warehouse.contract_cli import main

if __name__ == "__main__":
    sys.exit(main())
