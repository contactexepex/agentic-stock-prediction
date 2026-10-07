#!/usr/bin/env python3
"""Daily signal-model scores: P(up) per ticker and horizon N+k with its explanation (routine step 5a).

Thin entry point; the code is in marketbrief/model/daily_scores.py (`--help` shows its description)."""
import sys

from marketbrief.model.daily_scores import main

if __name__ == "__main__":
    sys.exit(main())
