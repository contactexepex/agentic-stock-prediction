#!/usr/bin/env python3
"""Post the market's Slack notifications (morning picks, intraday alerts, close results, weekly report,
onboarding replies); thin entry point of marketbrief/alerts/cli.py (docs/ws/b6.md)."""
from __future__ import annotations

import sys

from marketbrief.alerts.cli import main

if __name__ == "__main__":
    sys.exit(main())
