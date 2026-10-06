#!/usr/bin/env python3
"""Collect Form 4 insider transactions.

Thin entry point; the code is in marketbrief/collectors/insiders.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.insiders import main

if __name__ == "__main__":
    sys.exit(main())
