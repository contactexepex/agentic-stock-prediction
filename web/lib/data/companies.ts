// The companies page (B11; docs/ws/b11.md): rm.companies, page_key `_`, a 2.0 page payload (serve mode page).
import { definePage } from "./handler.ts";

export const COMPANIES_PAGE = definePage({ table: "companies", serve: "page" });
