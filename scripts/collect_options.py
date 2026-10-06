#!/usr/bin/env python3
"""Snapshot near-the-money implied volatility from option chains.

Thin entry point; the code is in marketbrief/collectors/options.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.options import main

if __name__ == "__main__":
    sys.exit(main())
