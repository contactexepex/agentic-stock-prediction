// The app's route layout (B7, Wave 4): every page lives under its market, /{market}/<page>, in the route group
// web/app/(cockpit)/[market]/ (the group adds no URL segment). One entry per page of docs/SPEC.md section 6 with its
// mockup, its owner session and its endpoint. Pure; the shell, the market switch and the tests read it.
import { MARKETS, TICKER_PATTERN, type Market } from "../data/constants.ts";

export interface PageRoute {
  key: string;
  label: string;
  /** Material Symbols id without the ms- prefix (design/system/icons.svg). */
  icon: string;
  /** Path after /{market}; "" is the market's home. */
  segment: string;
  /** The approved mockup's folder ("" for the component gallery, which has none). */
  mockup: string;
  owner: "B7" | "B8" | "B14" | "B15" | "B16";
  /** The read endpoint under /api/v1/markets/{market}/ ("" when the page has none). */
  endpoint: string;
  /** Shown in the sidebar (the per-stock pages are reached from a company). */
  nav: boolean;
}

export const PAGES: readonly PageRoute[] = [
  { key: "home", label: "Home", icon: "home", segment: "", mockup: "01-home", owner: "B14", endpoint: "home", nav: true },
  { key: "watchlist", label: "Watchlist", icon: "format_list_bulleted", segment: "watchlist", mockup: "02-watchlist", owner: "B14", endpoint: "watchlist", nav: true },
  { key: "company", label: "Company", icon: "apartment", segment: "stocks/[ticker]", mockup: "03-company", owner: "B15", endpoint: "stocks/{ticker}", nav: false },
  { key: "strategies", label: "Stock strategies", icon: "layers", segment: "stocks/[ticker]/strategies", mockup: "04-stock-strategies", owner: "B15", endpoint: "stocks/{ticker}/strategies", nav: false },
  { key: "lab", label: "Strategy lab", icon: "science", segment: "strategy-lab", mockup: "05-strategy-lab", owner: "B16", endpoint: "strategies", nav: true },
  { key: "compare", label: "Rule vs AI", icon: "layers", segment: "rule-vs-ai", mockup: "06-rule-vs-ai", owner: "B16", endpoint: "compare", nav: true },
  { key: "portfolios", label: "Paper portfolios", icon: "account_balance_wallet", segment: "paper-portfolios", mockup: "07-paper-portfolios", owner: "B16", endpoint: "portfolios", nav: true },
  { key: "track", label: "Track record", icon: "query_stats", segment: "track-record", mockup: "08-track-record", owner: "B16", endpoint: "track-record", nav: true },
  { key: "news", label: "News", icon: "newspaper", segment: "news", mockup: "09-news", owner: "B14", endpoint: "news", nav: true },
  { key: "companies", label: "Companies", icon: "apartment", segment: "companies", mockup: "10-companies", owner: "B14", endpoint: "companies", nav: true },
  { key: "assistant", label: "Assistant", icon: "bolt", segment: "assistant", mockup: "11-assistant", owner: "B8", endpoint: "", nav: true },
  { key: "help", label: "Help", icon: "help", segment: "help", mockup: "12-help", owner: "B7", endpoint: "", nav: true },
  /* Not a page of SPEC section 6: the shared components drawn with labelled sample values, for the page sessions and
     the UI harness. Not in the navigation. */
  { key: "gallery", label: "Component gallery", icon: "construction", segment: "gallery", mockup: "", owner: "B7", endpoint: "", nav: false },
];

/** The phone bar's first four pages (the mockups' default; "More" opens the drawer). */
export const PHONE_BAR = ["home", "watchlist", "lab", "compare"] as const;

export const DEFAULT_MARKET: Market = "india";

export function isMarket(value: unknown): value is Market {
  return typeof value === "string" && (MARKETS as readonly string[]).includes(value);
}

export function pageByKey(key: string): PageRoute {
  const page = PAGES.find((p) => p.key === key);
  if (!page) throw new Error(`unknown page ${key}`);
  return page;
}

/** The URL of a page of a market: pagePath("us", "watchlist") = "/us/watchlist". */
export function pagePath(market: Market, key: string, params: { ticker?: string; date?: string } = {}): string {
  let segment = pageByKey(key).segment;
  if (segment.includes("[ticker]")) segment = segment.replace("[ticker]", encodeURIComponent(params.ticker ?? ""));
  return segment ? `/${market}/${segment}` : `/${market}`;
}

export const companyPath = (market: Market, ticker: string) => pagePath(market, "company", { ticker });
export const stockStrategiesPath = (market: Market, ticker: string) => pagePath(market, "strategies", { ticker });
/** The per-day call history of a company (B15, /stocks/{t}/lifecycle/{date}). */
export const lifecyclePath = (market: Market, ticker: string, date: string) =>
  `${companyPath(market, ticker)}/lifecycle/${encodeURIComponent(date)}`;

/** The page a pathname shows: the longest matching segment pattern, else home. */
export function pageOfPath(pathname: string): PageRoute {
  const rest = pathname.split("/").filter(Boolean).slice(1);
  let best = PAGES[0];
  let bestLength = -1;
  for (const page of PAGES) {
    const parts = page.segment ? page.segment.split("/") : [];
    const matches = parts.length <= rest.length && parts.every((part, i) => part.startsWith("[") || part === rest[i]);
    const exact = parts.length === rest.length || (page.key === "company" && rest[2] === "lifecycle");
    if (matches && exact && parts.length > bestLength) {
      best = page;
      bestLength = parts.length;
    }
  }
  return best;
}

/** The market of a pathname, or null. */
export function marketOfPath(pathname: string): Market | null {
  const first = pathname.split("/").filter(Boolean)[0];
  return isMarket(first) ? first : null;
}

/** Where the market switch goes: the same page in the other market. A per-stock page has no counterpart (a ticker
 *  belongs to one market), so it goes to the other market's watchlist. */
export function switchMarketPath(pathname: string, to: Market): string {
  const parts = pathname.split("/").filter(Boolean);
  if (!isMarket(parts[0])) return `/${to}`;
  if (parts[1] === "stocks") return pagePath(to, "watchlist");
  return "/" + [to, ...parts.slice(1)].join("/");
}

/** The API path of a page's read: apiPath("india", "stocks/{ticker}", {ticker: "TCS"}). */
export function apiPath(market: Market, endpoint: string, params: { ticker?: string; date?: string } = {}): string {
  if (endpoint.includes("{ticker}") && !TICKER_PATTERN.test(params.ticker ?? "")) throw new Error("invalid ticker");
  const filled = endpoint
    .replace("{ticker}", encodeURIComponent(params.ticker ?? ""))
    .replace("{date}", encodeURIComponent(params.date ?? ""));
  return `/api/v1/markets/${market}/${filled}`;
}
