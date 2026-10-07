#!/usr/bin/env python3
"""Records built on a wrong split/bonus adjustment, per correction.

Thin entry point; the code is in marketbrief/pipeline/adjustment_records.py (`--help` shows its description)."""

import sys

from marketbrief.pipeline.adjustment_records import main

if __name__ == "__main__":
    sys.exit(main())
