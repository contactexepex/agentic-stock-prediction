#!/usr/bin/env python3
"""Walk-forward backtest of the range formula (no AI) on stored bars.

Thin entry point; the code is in marketbrief/replay/backtest/cli.py (`--help` shows its description)."""

import sys

from marketbrief.replay.backtest.cli import main

if __name__ == "__main__":
    sys.exit(main())
