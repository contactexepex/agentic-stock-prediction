#!/usr/bin/env python3
"""Fetch the long daily history the signal-model backtest reads with --history into work/model_history/
(gitignored; never data/).

Thin entry point; the code is in marketbrief/model/history_cache.py (`--help` shows its description)."""
import sys

from marketbrief.model.history_cache import main

if __name__ == "__main__":
    sys.exit(main())
