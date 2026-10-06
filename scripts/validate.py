#!/usr/bin/env python3
"""Deterministic gate of the daily run, per stage.

Thin entry point; the code is in marketbrief/pipeline/validate/cli.py (`--help` shows its description)."""

import sys

from marketbrief.pipeline.validate.cli import main

if __name__ == "__main__":
    sys.exit(main())
