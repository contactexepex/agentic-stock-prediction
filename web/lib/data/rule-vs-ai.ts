// The Rule vs AI page (B13, docs/ws/b13.md): rm.compare, page_key `_`, served by
// GET /api/v1/markets/{market}/compare (api/paths/rule-vs-ai.yaml). Research reviews included. Paper only.
import { definePage } from "./handler.ts";

export const RULE_VS_AI_PAGE = definePage({ table: "compare", serve: "page" });
