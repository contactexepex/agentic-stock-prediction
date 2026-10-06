#!/usr/bin/env python3
"""As-of replay harness for the AI agents (never runs an LLM itself).

Thin entry point; the code is in marketbrief/replay/ai_replay/cli.py (`--help` shows its description)."""
import sys

from marketbrief.replay.ai_replay.cli import main

if __name__ == "__main__":
    sys.exit(main())
