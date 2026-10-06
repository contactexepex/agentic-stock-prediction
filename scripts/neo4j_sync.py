#!/usr/bin/env python3
"""Copy a market's data and results into Neo4j (optional projection).

Thin entry point; the code is in marketbrief/graph/neo4j/cli.py (`--help` shows its description)."""

import sys

from marketbrief.graph.neo4j.cli import main

if __name__ == "__main__":
    sys.exit(main())
