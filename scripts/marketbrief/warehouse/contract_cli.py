"""Check the stored read models of a market against the contract (scripts/api_contract.py): every registered
contract case (rm_registry) served as the route serves it, validated against its 200 schema and compared in shape
with its approved mockup. Reads the warehouse read-only: MotherDuck with MOTHERDUCK_TOKEN (never printed), else
or with --local the local DuckDB file of config/warehouse.yaml. Exit 1 when a problem is found."""

from __future__ import annotations

import json
import sys

from marketbrief.core import cli
from marketbrief.core.clock import clock
from marketbrief.warehouse.connection import connect_warehouse
from marketbrief.warehouse.contract import check_market
from marketbrief.warehouse.errors import WarehouseError


def main() -> int:
    """CLI: --market india|us [--local]."""
    parser = cli.market_arg(__doc__)
    parser.add_argument("--local", action="store_true", help="read the local DuckDB file even when the token is set")
    args = parser.parse_args()
    cfg = cli.require_market(args)
    try:
        warehouse = connect_warehouse(read_only=True, force_local=args.local)
        result = check_market(warehouse, cfg["market"], clock())
        warehouse.close()
    except WarehouseError as exc:
        print(json.dumps({"market": cfg["market"], "ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({**result, "ok": not result["problems"]}, indent=2))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
