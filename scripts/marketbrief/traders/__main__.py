"""`python -m marketbrief.traders` (with scripts/ on PYTHONPATH): the traders' command line (cli.py)."""
import sys

from marketbrief.traders.cli import main

if __name__ == "__main__":
    sys.exit(main())
