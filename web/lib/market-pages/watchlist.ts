// The Watchlist page's own computations (design/mockups/02-watchlist/notes.md "Shown but computed by the page"): one
// row per active company with its agreement, range, open trades and flagged checks at the selected horizon; sorting,
// filtering and the KPI counts. Presentation only.

export interface FamilyCount { buy: number; of: number }
export interface Agreement {
  ticker: string;
  rank: number;
  horizon_days: number;
  buy: number;
  of: number;
  by_family: { rule: FamilyCount; baseline: FamilyCount; ai: FamilyCount };
  avg_prob_up: number | null;
}
export type AgreementMap = Record<string, Agreement[]>;
export interface Company {
  ticker: string;
  name: string;
  sector: string;
  state: string;
  state_since?: string | null;
  last_close: number | null;
  change_pct: number | null;
}
export interface OpenTrade { trade_id: string; ticker: string; unrealised_pnl: number | null }
export interface TradeCheck { trade_id: string; ticker: string; check_at: string; flagged: boolean; flags: string[] }
export interface PredictionRange { ticker: string; horizon_days: number }

export interface WatchlistRow<C extends Company = Company, R extends PredictionRange = PredictionRange> {
  company: C;
  agreement: Agreement | null;
  range: R | null;
  trades: OpenTrade[];
  unrealised: number;
  checks: TradeCheck[];
  flagged: TradeCheck[];
}

export const agreementAt = (agreement: AgreementMap, horizon: number, ticker: string): Agreement | null =>
  (agreement[String(horizon)] ?? []).find((a) => a.ticker === ticker) ?? null;

/** A sum of nullable money amounts (a null amount counts as 0). */
export const sumMoney = (values: readonly (number | null | undefined)[]): number =>
  values.reduce<number>((s, v) => s + (v ?? 0), 0);

export function watchlistRows<C extends Company, R extends PredictionRange>(p: {
  companies: readonly C[];
  agreement: AgreementMap;
  ranges: readonly R[];
  open_trades: readonly OpenTrade[];
  trade_checks: readonly TradeCheck[];
}, horizon: number): WatchlistRow<C, R>[] {
  return p.companies.filter((c) => c.state === "active").map((company) => {
    const trades = p.open_trades.filter((t) => t.ticker === company.ticker);
    const checks = p.trade_checks.filter((x) => x.ticker === company.ticker);
    return {
      company,
      agreement: agreementAt(p.agreement, horizon, company.ticker),
      range: p.ranges.find((r) => r.ticker === company.ticker && r.horizon_days === horizon) ?? null,
      trades,
      unrealised: sumMoney(trades.map((t) => t.unrealised_pnl)),
      checks,
      flagged: checks.filter((x) => x.flagged),
    };
  });
}

export type SortKey = "agreement" | "change" | "name" | "open" | "last";
type Key = (number | string)[];
const SORT: Record<SortKey, (r: WatchlistRow) => Key> = {
  agreement: (r) => [r.agreement ? r.agreement.buy : -1, r.agreement?.avg_prob_up ?? 0],
  change: (r) => [r.company.change_pct ?? Number.NEGATIVE_INFINITY],
  name: (r) => [r.company.name],
  open: (r) => [r.trades.length, r.unrealised],
  last: (r) => [r.company.last_close ?? Number.NEGATIVE_INFINITY],
};
function compareKeys(x: Key, y: Key): number {
  for (let i = 0; i < x.length; i++) {
    if (x[i] < y[i]) return -1;
    if (x[i] > y[i]) return 1;
  }
  return 0;
}
/** The direction a column sorts in when first chosen: names A to Z, numbers largest first. */
export const defaultDirection = (key: SortKey): 1 | -1 => (key === "name" ? 1 : -1);

export function sortRows<T extends WatchlistRow>(rows: readonly T[], key: SortKey, direction: 1 | -1): T[] {
  return rows.slice().sort((a, b) => direction * compareKeys(SORT[key](a), SORT[key](b)) || a.company.ticker.localeCompare(b.company.ticker));
}

/** Sector chip (null = all) and the symbol-or-name text filter, case-insensitive. */
export function filterRows<T extends WatchlistRow>(rows: readonly T[], sector: string | null, query: string): T[] {
  const q = query.trim().toLowerCase();
  return rows.filter((r) => (!sector || r.company.sector === sector)
    && (!q || r.company.ticker.toLowerCase().includes(q) || r.company.name.toLowerCase().includes(q)));
}

export function sectorsOf(rows: readonly WatchlistRow[]): { sector: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of rows) counts.set(r.company.sector, (counts.get(r.company.sector) ?? 0) + 1);
  return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([sector, count]) => ({ sector, count }));
}

/** The company most strategies would buy at the horizon (the agreement sort's first row), or null when none buys. */
export function mostAgreed<T extends WatchlistRow>(rows: readonly T[]): T | null {
  const top = sortRows(rows, "agreement", -1)[0];
  return top && top.agreement && top.agreement.buy > 0 ? top : null;
}

/** The horizon words of the table head: N+1 = the next session's close. */
export function horizonWords(k: number): string {
  const ordinal = ["", "1st", "2nd", "3rd", "4th", "5th"][k] ?? `${k}th`;
  return k === 1 ? "the next session’s close" : `the close of the ${ordinal} session after the open`;
}

/** The distinct flags of a company's flagged checks, in first-seen order. */
export const distinctFlags = (checks: readonly TradeCheck[]): string[] => [...new Set(checks.flatMap((c) => c.flags))];
