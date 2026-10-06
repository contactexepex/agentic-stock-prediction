#!/usr/bin/env python3
"""Historical replay of everything rule-based (no AI) for one market.

Thin entry point; the code is in marketbrief/replay/rule_replay/cli.py (`--help` shows its description)."""

import sys

from marketbrief.replay.rule_replay.cli import main

if __name__ == "__main__":
    sys.exit(main())
