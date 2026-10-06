#!/usr/bin/env python3
"""Weekly spot-check sample for the judge.

Thin entry point; the code is in marketbrief/pipeline/spotcheck.py (`--help` shows its description)."""
import sys

from marketbrief.pipeline.spotcheck import main

if __name__ == "__main__":
    sys.exit(main())
