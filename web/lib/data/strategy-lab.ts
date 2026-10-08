// The Strategy lab page (B13, docs/ws/b13.md): rm.strategies, page_key `_`, served by
// GET /api/v1/markets/{market}/strategies (api/paths/strategy-lab.yaml). Paper only.
import { definePage } from "./handler.ts";

export const STRATEGY_LAB_PAGE = definePage({ table: "strategies", serve: "page" });
