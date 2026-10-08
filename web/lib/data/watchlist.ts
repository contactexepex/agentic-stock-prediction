// The watchlist page (B11; docs/ws/b11.md): rm.watchlist, page_key `_`, a 2.0 page payload (serve mode page).
import { definePage } from "./handler.ts";

export const WATCHLIST_PAGE = definePage({ table: "watchlist", serve: "page" });
