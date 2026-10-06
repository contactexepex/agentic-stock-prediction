#!/usr/bin/env python3
"""Collect NSDL FPI flows and NSE index closes.

Thin entry point; the code is in marketbrief/collectors/flows_india.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.flows_india import main

if __name__ == "__main__":
    sys.exit(main())
