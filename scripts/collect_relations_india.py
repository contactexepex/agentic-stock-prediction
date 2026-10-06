#!/usr/bin/env python3
"""Collect NSE insider trades, bulk and block deals, shareholding and pledges.

Thin entry point; the code is in marketbrief/collectors/relations_india.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.relations_india import main

if __name__ == "__main__":
    sys.exit(main())
