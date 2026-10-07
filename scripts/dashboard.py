#!/usr/bin/env python3
"""Build the decision-support dashboard reports/<market>/dashboard.html (--out DIR to write elsewhere).

Thin entry point; the code is in marketbrief/presentation/dashboard/. Research only, not investment advice."""

import sys

from marketbrief.presentation.dashboard.cli import main

if __name__ == "__main__":
    sys.exit(main())
