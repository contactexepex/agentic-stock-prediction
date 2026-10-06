#!/usr/bin/env python3
"""Connection map: status, edges, hits, add, attempt.

Thin entry point; the code is in marketbrief/graph/cli.py (`--help` shows its description)."""
import sys

from marketbrief.graph.cli import main

if __name__ == "__main__":
    sys.exit(main())
