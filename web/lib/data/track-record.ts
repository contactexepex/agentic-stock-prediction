// The Track record page (B13, docs/ws/b13.md): rm.track_record, page_key `_`, served by
// GET /api/v1/markets/{market}/track-record (api/paths/track-record.yaml; contract 2.0). Scoring bases never pooled.
import { definePage } from "./handler.ts";

export const TRACK_RECORD_PAGE = definePage({ table: "track_record", serve: "page" });
