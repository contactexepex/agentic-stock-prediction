#!/usr/bin/env python3
"""Print the context pack of one market.

Thin entry point; the code is in marketbrief/pipeline/context.py (`--help` shows its description)."""

import sys

from marketbrief.pipeline.context import main

if __name__ == "__main__":
    sys.exit(main())
