#!/usr/bin/env python3
"""Build the daily report skeleton and the Slack draft for one market.

Thin entry point; the code is in marketbrief/presentation/report/cli.py (`--help` shows its description)."""
import sys

from marketbrief.presentation.report.cli import main

if __name__ == "__main__":
    sys.exit(main())
