// The News page's own computations (design/mockups/09-news/notes.md "Shown but computed by the page"): the market
// movers, the filters, the pages, the day groups and the per-company rail. Presentation only: the server selects the
// window (rm.news, B11); nothing here reads a clock other than the payload's cut-off.

/** The owner's rules of 2026-10-08 (design/mockups/_shared/shell.js). */
export const NEWS_MOVERS_MAX = 10;
export const NEWS_PAGE_SIZE = 10;
export const NEWS_RECENT_HOURS = 24;
/** The sentiment words: positive above +0.05, negative below -0.05, flat between (shell.js). */
export const SENTIMENT_FLAT_BAND = 0.05;
/** Owner decision 2026-10-08: Home shows the top 5 market movers; the News page the rest (01-home template). */
export const HOME_NEWS_MAX = 5;
/** The statuses that may be the main evidence of a call (DESIGN.md 3b). */
export const CAN_CARRY = ["confirmed_primary", "corroborated"] as const;

export interface NewsEnrichment {
  event_type: string | null;
  materiality: "high" | "medium" | "low" | null;
  sentiment: number | null;
  geopolitical?: boolean | null;
}

export interface NewsItem {
  id: string;
  tickers: string[];
  primary_tickers: string[];
  title: string;
  source: string | null;
  source_domain: string | null;
  url: string | null;
  published_at: string | null;
  first_seen_at: string;
  status: string | null;
  independent_origins: number | null;
  scope?: "company" | "market";
  category?: string | null;
  summary?: string | null;
  market_moving?: boolean;
  enrichment: NewsEnrichment;
}

export interface RailCompany {
  ticker: string;
  name: string;
  state: string;
  open_trades: number;
}

export type NewsFilter = "all" | "24h" | "market" | "moving" | "carry" | "company";

/** Words for the news analyst's event types (09-news template). */
export const KIND: Record<string, string> = {
  earnings: "results", macro: "rates & macro", product: "product", legal: "legal", sector: "sector",
  analyst: "analyst", ma: "deal", flows: "flows", commodity: "commodities", geopolitics: "geopolitics",
  index: "index move", regulation: "regulation", other: "other",
};
const MATERIALITY_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

export const canCarry = (n: NewsItem): boolean => (CAN_CARRY as readonly string[]).includes(n.status ?? "");
export const isMarketWide = (n: NewsItem): boolean => n.scope === "market";

/** Hours from an ISO time to the cut-off (never the viewer's clock). */
export function hoursBefore(cutoff: string, iso: string | null): number {
  if (!iso) return Number.POSITIVE_INFINITY;
  return (Date.parse(cutoff) - Date.parse(iso)) / 36e5;
}

/** "n h before the cut-off" from the outlet's publish time. */
export function agoWords(cutoff: string, iso: string | null): string {
  if (!iso) return "publish time not stored";
  const h = hoursBefore(cutoff, iso);
  if (h < 1) return "under an hour before the cut-off";
  if (h < NEWS_RECENT_HOURS) return `${Math.floor(h)} h before the cut-off`;
  const days = Math.floor(h / NEWS_RECENT_HOURS);
  return `${days} day${days === 1 ? "" : "s"} before the cut-off`;
}

/** The kind word: a market-wide story's category when it is not company or general, else the event type in words. */
export function kindWord(n: NewsItem): string {
  if (isMarketWide(n) && n.category && n.category !== "company" && n.category !== "general") return n.category;
  const t = n.enrichment.event_type;
  return t == null ? "unscored" : (KIND[t] ?? t);
}

function moverScore(n: NewsItem): number {
  return (n.market_moving ? 1000 : 0) + (isMarketWide(n) ? 100 : 0) + (n.enrichment.event_type === "earnings" ? 50 : 0)
    + (MATERIALITY_RANK[n.enrichment.materiality ?? ""] ?? 0) * 10 + (canCarry(n) ? 5 : 0);
}

/**
 * The market movers: a story qualifies when the engine's market_moving flag is set, or it is market-wide, a results
 * story or scored high materiality; ranked flagged first, then market-wide, results, materiality, newest; the same
 * headline stored twice shows once; at most `max`.
 */
export function movers(items: readonly NewsItem[], max: number = NEWS_MOVERS_MAX): NewsItem[] {
  const ranked = items
    .filter((n) => n.market_moving || n.enrichment.materiality === "high" || isMarketWide(n) || n.enrichment.event_type === "earnings")
    .map((n, index) => ({ n, index, score: moverScore(n) }))
    .sort((a, b) => b.score - a.score || b.n.first_seen_at.localeCompare(a.n.first_seen_at) || a.index - b.index)
    .map((x) => x.n);
  const seen = new Set<string>();
  const out: NewsItem[] = [];
  for (const n of ranked) {
    if (seen.has(n.title)) continue;
    seen.add(n.title);
    out.push(n);
    if (out.length === max) break;
  }
  return out;
}

/** Items published in the last NEWS_RECENT_HOURS before the cut-off (the owner's decision: by the outlet's time). */
export const isRecent = (cutoff: string, n: NewsItem): boolean => hoursBefore(cutoff, n.published_at) < NEWS_RECENT_HOURS;

export function filterNews(items: readonly NewsItem[], filter: NewsFilter, cutoff: string, ticker: string | null): NewsItem[] {
  switch (filter) {
    case "24h": return items.filter((n) => isRecent(cutoff, n));
    case "market": return items.filter(isMarketWide);
    case "moving": return items.filter((n) => n.market_moving === true);
    case "carry": return items.filter(canCarry);
    case "company": return ticker ? items.filter((n) => n.tickers.includes(ticker)) : items.slice();
    default: return items.slice();
  }
}

export interface Paged<T> { page: number; pages: number; items: T[] }

/** One page of `size`; the page number is clamped to the pages there are (at least 1). */
export function paginate<T>(items: readonly T[], page: number, size: number = NEWS_PAGE_SIZE): Paged<T> {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pages);
  return { page: current, pages, items: items.slice((current - 1) * size, current * size) };
}

/** Minutes east of UTC from the market's `session.local_time` ("...+05:30"). */
export function offsetMinutes(localTime: string | null | undefined): number {
  const m = /([+-])(\d\d):(\d\d)$/.exec(localTime ?? "");
  return m ? (m[1] === "-" ? -1 : 1) * (60 * Number(m[2]) + Number(m[3])) : 0;
}

/** The market-local calendar date (YYYY-MM-DD) of an ISO time. */
export function localDate(iso: string, offset: number): string {
  return new Date(Date.parse(iso) + offset * 60000).toISOString().slice(0, 10);
}

export interface DayGroup { date: string; today: boolean; count: number; items: NewsItem[] }

/**
 * The feed's day groups for one page: the local date of `first_seen_at`; `count` is the number of stories of that day
 * among all filtered items (not only this page), as the mockup shows.
 */
export function dayGroups(page: readonly NewsItem[], all: readonly NewsItem[], cutoff: string, offset: number): DayGroup[] {
  const today = localDate(cutoff, offset);
  const counts = new Map<string, number>();
  for (const n of all) { const d = localDate(n.first_seen_at, offset); counts.set(d, (counts.get(d) ?? 0) + 1); }
  const groups: DayGroup[] = [];
  for (const n of page) {
    const d = localDate(n.first_seen_at, offset);
    const last = groups[groups.length - 1];
    if (last && last.date === d) last.items.push(n);
    else groups.push({ date: d, today: d === today, count: counts.get(d) ?? 0, items: [n] });
  }
  return groups;
}

export type Tone = "up" | "flat" | "down";
export function tone(sentiment: number | null | undefined): Tone {
  if (sentiment == null) return "flat";
  return sentiment > SENTIMENT_FLAT_BAND ? "up" : sentiment < -SENTIMENT_FLAT_BAND ? "down" : "flat";
}

export interface RailRow { company: RailCompany; count: number; up: number; flat: number; down: number; latest: NewsItem }

/** The "By company" rail: each company with a story in the window, most stories first, then by ticker. */
export function companyRail(companies: readonly RailCompany[], items: readonly NewsItem[]): RailRow[] {
  const rows: RailRow[] = [];
  for (const company of companies) {
    const own = items.filter((n) => n.tickers.includes(company.ticker));
    if (!own.length) continue;
    const tones = own.map((n) => tone(n.enrichment.sentiment));
    const up = tones.filter((t) => t === "up").length;
    const down = tones.filter((t) => t === "down").length;
    rows.push({ company, count: own.length, up, down, flat: own.length - up - down, latest: own[0] });
  }
  return rows.sort((a, b) => b.count - a.count || a.company.ticker.localeCompare(b.company.ticker));
}

/** The companies offered by the feed's company filter: those with a story in the window, in payload order. */
export const companiesWithNews = (companies: readonly RailCompany[], items: readonly NewsItem[]): RailCompany[] =>
  companies.filter((c) => items.some((n) => n.tickers.includes(c.ticker)));

/** The note under the filters shows when more than half of the stories have no summary line. */
export function missingSummaries(items: readonly NewsItem[]): number | null {
  const missing = items.filter((n) => !n.summary).length;
  return missing > items.length / 2 ? missing : null;
}

export const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;
export const stories = (n: number): string => plural(n, "story", "stories");
