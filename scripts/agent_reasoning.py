#!/usr/bin/env python3
"""Persist the day's debate (bull case, bear case, forecaster verdict per ticker): validate F | add F [--valid-only].
The logic lives in marketbrief/model/reasoning.py (its docstring has the details)."""
from __future__ import annotations

import sys

from marketbrief.model.reasoning import main

if __name__ == "__main__":
    sys.exit(main())
