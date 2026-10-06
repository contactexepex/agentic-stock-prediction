#!/usr/bin/env python3
"""Verification status of this run's news events and their facts (news verification phase B).
The logic lives in marketbrief/pipeline/news_status.py (its docstring has the details)."""
from __future__ import annotations

import sys

from marketbrief.pipeline.news_status import main

if __name__ == "__main__":
    sys.exit(main())
