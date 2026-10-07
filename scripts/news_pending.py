#!/usr/bin/env python3
"""News and NSE announcements awaiting the news analyst: every id first seen since the last enrichment.

Thin entry point; the code is in marketbrief/pipeline/news_pending.py (`--help` shows its description)."""
import sys

from marketbrief.pipeline.news_pending import main

if __name__ == "__main__":
    sys.exit(main())
