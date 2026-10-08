// The home page (B11; docs/ws/b11.md): rm.home, page_key `_`, a 2.0 page payload (serve mode page).
import { definePage } from "./handler.ts";

export const HOME_PAGE = definePage({ table: "home", serve: "page" });
