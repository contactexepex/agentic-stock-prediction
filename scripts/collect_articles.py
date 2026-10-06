#!/usr/bin/env python3
"""Read the article pages behind material headlines (news verification phase A).

Thin entry point; the code is in marketbrief/collectors/articles.py (`--help` shows its description)."""
import sys

from marketbrief.collectors.articles import main

if __name__ == "__main__":
    sys.exit(main())
