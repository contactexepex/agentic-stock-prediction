#!/usr/bin/env python3
"""The news-only light run: collect_news, (India) NSE announcements, collect_articles, news_clusters and the
news_collect gate; no prices, no agents, no Slack (routine/NEWS_PROMPT.md).

Thin entry point; the code is in marketbrief/pipeline/news_light_run.py (`--help` shows its description)."""
import sys

from marketbrief.pipeline.news_light_run import main

if __name__ == "__main__":
    sys.exit(main())
