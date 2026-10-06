"""Command-line plumbing shared by the entry-point scripts: the --market argument."""

from __future__ import annotations

import argparse
import os

from marketbrief.constants.environment import ENV_MARKET
from marketbrief.constants.messages import MSG_MARKET_REQUIRED
from marketbrief.core.market_config import load_market, market_names


def market_arg(description: str | None = None) -> argparse.ArgumentParser:
    """An argument parser that has --market (default $MB_MARKET)."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--market",
        default=os.environ.get(ENV_MARKET),
        help="market config name, e.g. india or us (default: $MB_MARKET)",
    )
    return parser


def require_market(args) -> dict:
    """The parsed --market's config; exits with the available markets when none was given."""
    if not args.market:
        raise SystemExit(MSG_MARKET_REQUIRED.format(available=market_names()))
    return load_market(args.market)
