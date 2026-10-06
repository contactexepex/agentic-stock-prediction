#!/usr/bin/env python3
"""Check stored SEC acceptance times against the SGML headers.

Thin entry point; the code is in marketbrief/collectors/sec_times.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.sec_times import main

if __name__ == "__main__":
    sys.exit(main())
