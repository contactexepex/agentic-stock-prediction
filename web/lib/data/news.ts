// The news page (B11; docs/ws/b11.md): rm.news, page_key `_`, a 2.0 page payload (serve mode page).
import { definePage } from "./handler.ts";

export const NEWS_PAGE = definePage({ table: "news", serve: "page" });
