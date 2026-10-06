#!/usr/bin/env python3
"""Collect US macro series (Treasury, FRED, Cboe).

Thin entry point; the code is in marketbrief/collectors/macro.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.macro import main

if __name__ == "__main__":
    sys.exit(main())
