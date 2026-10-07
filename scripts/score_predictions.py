#!/usr/bin/env python3
"""Score open predictions and ranges whose horizon (the exit session of N+k, or a legacy window) has passed.

Thin entry point; the code is in marketbrief/pipeline/score_predictions.py (`--help` shows its description)."""

import sys

from marketbrief.pipeline.score_predictions import main

if __name__ == "__main__":
    sys.exit(main())
