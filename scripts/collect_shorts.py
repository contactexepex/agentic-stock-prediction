#!/usr/bin/env python3
"""Collect FINRA short-sale volume and short interest.

Thin entry point; the code is in marketbrief/collectors/shorts.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.shorts import main

if __name__ == "__main__":
    sys.exit(main())
