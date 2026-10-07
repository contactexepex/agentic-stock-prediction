#!/usr/bin/env python3
"""Results digests (WS6): prepare | validate F | add F [--valid-only].
The logic lives in marketbrief/results/cli.py (its docstring has the details)."""

from __future__ import annotations

import sys

from marketbrief.results.cli import main

if __name__ == "__main__":
    sys.exit(main())
