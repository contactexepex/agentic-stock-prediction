#!/usr/bin/env python3
"""Collect Schedule 13D and 13G stakes.

Thin entry point; the code is in marketbrief/collectors/stakes.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.stakes import main

if __name__ == "__main__":
    sys.exit(main())
