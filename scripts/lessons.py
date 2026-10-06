#!/usr/bin/env python3
"""Reflection log: one short lesson per settled call, read by later forecasts.

Thin entry point; the code is in marketbrief/pipeline/lessons/cli.py (`--help` shows its description)."""

import sys

from marketbrief.pipeline.lessons.cli import main

if __name__ == "__main__":
    sys.exit(main())
