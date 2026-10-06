#!/usr/bin/env python3
"""Group news items about the same event and count independent origins.

Thin entry point; the code is in marketbrief/analytics/news_clusters.py (`--help` shows its description)."""
import sys

from marketbrief.analytics.news_clusters import main

if __name__ == "__main__":
    sys.exit(main())
