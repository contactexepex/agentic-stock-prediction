#!/usr/bin/env python3
"""Connection map: status, edges, hits, add, attempt.

Thin entry point; the code is in marketbrief/graph/connection_map.py (`--help` shows its description)."""
import sys

from marketbrief.graph.connection_map import main

if __name__ == "__main__":
    sys.exit(main())
