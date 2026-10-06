#!/usr/bin/env python3
"""Collect company events: earnings, ex-dividend and past results releases.

Thin entry point; the code is in marketbrief/collectors/events.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.events import main

if __name__ == "__main__":
    sys.exit(main())
