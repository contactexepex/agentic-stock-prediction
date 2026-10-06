#!/usr/bin/env python3
"""Weekly review of ranges and calls with input ablations and proposed config changes.

Thin entry point; the code is in marketbrief/pipeline/review/cli.py (`--help` shows its description)."""
import sys

from marketbrief.pipeline.review.cli import main

if __name__ == "__main__":
    sys.exit(main())
