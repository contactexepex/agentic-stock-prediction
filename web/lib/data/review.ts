// The research reviews (B13, docs/ws/b13.md): rm.review, page_key `_`, served by
// GET /api/v1/markets/{market}/review (api/paths/review.yaml); also read by B5's read tools. Proposals are never applied.
import { definePage } from "./handler.ts";

export const REVIEW_PAGE = definePage({ table: "review", serve: "page" });
