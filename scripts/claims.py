#!/usr/bin/env python3
"""Claims of news events (news verification phase B): prepare | validate F | add F [--valid-only].
The logic lives in marketbrief/pipeline/claims.py (its docstring has the details)."""
from __future__ import annotations

import sys

from marketbrief.pipeline.claims import main

if __name__ == "__main__":
    sys.exit(main())
