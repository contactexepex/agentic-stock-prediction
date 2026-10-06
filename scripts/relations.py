#!/usr/bin/env python3
"""Relationship risk flags of one market as JSON.

Thin entry point; the code is in marketbrief/analytics/relation_flags.py (`--help` shows its description)."""
import sys

from marketbrief.analytics.relation_flags import main

if __name__ == "__main__":
    sys.exit(main())
