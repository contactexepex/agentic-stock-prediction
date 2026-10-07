#!/usr/bin/env python3
"""Re-estimation report of the signal model's news coefficient from live outcomes (prints only).

Thin entry point; the code is in marketbrief/model/news_update.py (`--help` shows its description)."""
import sys

from marketbrief.model.news_update import main

if __name__ == "__main__":
    sys.exit(main())
