"""Copy a market's data and per-page read models into the warehouse (MotherDuck database market_brief, or
the local DuckDB file of config/warehouse.yaml): one schema per market (india, us) with the mirrored tables,
schema rm with the per-page read models keyed (market, page_key) and rm.builds, and meta.sync_runs with one
row per run (docs/ARCHITECTURE.md section 4). Reads data/ through DuckDB as of the run's clock (MB_NOW-aware);
the warehouse is a derived copy that a run rebuilds from the repo. Optional and non-blocking: the static
reports and Slack never depend on it.
Needs MOTHERDUCK_TOKEN for MotherDuck (never printed); --local writes the local file instead."""

from __future__ import annotations

import json
import sys

from marketbrief.constants.warehouse import KIND_DAILY, KIND_NEWS
from marketbrief.core import cli
from marketbrief.warehouse.connection import WarehouseError
from marketbrief.warehouse.sync import sync_market


def main() -> int:
    """CLI: --market india|us [--full] [--dry-run] [--local] [--kind daily|news]. Exit 1 when the sync failed or
    a page failed validation (its old row stays); 0 otherwise, a kill-switch skip included."""
    parser = cli.market_arg(__doc__)
    parser.add_argument("--full", action="store_true", help="drop the market's schema and read models, then rebuild")
    parser.add_argument("--dry-run", action="store_true", help="count rows and build the payloads; write nothing")
    parser.add_argument("--local", action="store_true", help="write the local DuckDB file even when the token is set")
    parser.add_argument(
        "--kind", choices=[KIND_DAILY, KIND_NEWS], default=KIND_DAILY, help="the build's label in rm.builds"
    )
    args = parser.parse_args()
    cfg = cli.require_market(args)
    try:
        summary = sync_market(cfg, full=args.full, dry_run_only=args.dry_run, force_local=args.local, kind=args.kind)
    except WarehouseError as exc:
        print(json.dumps({"market": cfg["market"], "ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, default=str))
    failed = not summary.get("skipped") and (not summary.get("build_ok", True) or summary.get("invalid_pages"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
