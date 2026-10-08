// The Home page's own computations (design/mockups/01-home/notes.md "Shown but computed by the page"): the KPI counts
// and sums, the head-to-head grouping and cost lines, the cumulative profit per family, the alerts and the runs
// count. Presentation only.

/** Spec constant: two intraday checks per session (docs/SPEC.md section 7; shell.js INTRADAY_CHECKS_PER_SESSION). */
export const INTRADAY_CHECKS_PER_SESSION = 2;
/** Spec constant: the go-live bar's two months of forward paper trading (SPEC F7.2; shell.js GO_LIVE_MONTHS). */
export const GO_LIVE_MONTHS = 2;

export type Family = "rule" | "baseline" | "ai";
export const FAMILIES: Family[] = ["rule", "baseline", "ai"];
export type PickRule = "best_expected_gain" | "highest_probability";
export const PICK_RULES: PickRule[] = ["best_expected_gain", "highest_probability"];

export interface Candidate {
  horizon_days: number;
  prob_up: number | null;
  move_pct: number | null;
  loss_pct: number | null;
  costs_pct: number | null;
  expected_gain_pct: number | null;
  your_cost_pct?: number | null;
  expected_gain_your_pct?: number | null;
  cost_viable?: boolean | null;
}
export interface HeadToHeadPick {
  id: string;
  ticker: string;
  family: Family;
  pick_rule: PickRule;
  status: string;
  strategy_id: string | null;
  horizon_days: number | null;
  expected_gain_pct: number | null;
  amount: number | null;
  candidates: Candidate[] | null;
}

/** The candidate of the picked horizon, whose your-cost fields decide decision 51's flag. */
export const pickCandidate = (k: HeadToHeadPick): Candidate | null =>
  (k.candidates ?? []).find((c) => c.horizon_days === k.horizon_days) ?? null;
/** true / false = viable or not at the owner's cost; null = not stored. */
export const yourViable = (k: HeadToHeadPick): boolean | null => pickCandidate(k)?.cost_viable ?? null;
export const clearsMarketCosts = (k: HeadToHeadPick): boolean => (k.expected_gain_pct ?? 0) > 0;
/** The expected gain in money: expected_gain_pct x amount / 100 (notes.md). */
export const expectedGainMoney = (k: HeadToHeadPick): number | null =>
  k.expected_gain_pct == null || k.amount == null ? null : (k.expected_gain_pct * k.amount) / 100;

export interface PickSummary { picked: number; clearMarket: number; viableYours: number; yourKnown: number }
export function pickSummary(picks: readonly HeadToHeadPick[]): PickSummary {
  const picked = picks.filter((k) => k.status === "picked");
  return {
    picked: picked.length,
    clearMarket: picked.filter(clearsMarketCosts).length,
    viableYours: picked.filter((k) => yourViable(k) === true).length,
    yourKnown: picked.filter((k) => yourViable(k) != null).length,
  };
}
/** "n clears market costs · m viable at your cost" (the mockup's sum line). */
export function viableLine(s: PickSummary): string {
  const market = s.clearMarket ? `${s.clearMarket} clear${s.clearMarket === 1 ? "s" : ""} market costs` : "none clears market costs";
  const yours = s.yourKnown ? (s.viableYours ? `${s.viableYours} viable at your cost` : "none viable at your cost") : "your-cost view not stored";
  return `${market} · ${yours}`;
}

/** Picks grouped by company in payload order. */
export function groupBy<T, K extends string>(rows: readonly T[], key: (row: T) => K): [K, T[]][] {
  const out = new Map<K, T[]>();
  for (const r of rows) {
    const k = key(r);
    const list = out.get(k);
    if (list) list.push(r);
    else out.set(k, [r]);
  }
  return [...out.entries()];
}

export interface SettledTrade { view: string; family: Family; exit_date_actual: string | null; net_pnl: number | null }
export interface ProfitSeries { family: Family; points: number[] }
/**
 * The cumulative profit after costs per family by settlement day, from the settled trades of the accuracy view (the
 * Rule vs AI chart). Trades without an actual exit date never settled with money and are left out.
 */
export function cumulativeProfit(trades: readonly SettledTrade[], families: readonly Family[] = ["rule", "ai", "baseline"]): { days: string[]; series: ProfitSeries[]; trades: number } {
  const rows = trades.filter((r) => r.view === "accuracy" && r.exit_date_actual);
  const days = [...new Set(rows.map((r) => r.exit_date_actual as string))].sort();
  const series = families.map((family) => {
    let acc = 0;
    return {
      family,
      points: days.map((d) => {
        acc += rows.filter((r) => r.family === family && r.exit_date_actual === d).reduce((s, r) => s + (r.net_pnl ?? 0), 0);
        return acc;
      }),
    };
  });
  return { days, series, trades: rows.length };
}

/** A nice axis step for about four intervals over a span (1, 2, 5 or 10 times a power of ten). */
export function niceStep(span: number): number {
  if (!(span > 0)) return 1;
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const r = raw / mag;
  return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 5 ? 5 : 10) * mag;
}

export interface EodFamily { trades: number; wins: number; net_pnl: number | null }
/** The family that led the last close: the highest net profit among families with trades (ties all lead). */
export function eodLeaders(results: Partial<Record<Family, EodFamily>>): Set<Family> {
  const withTrades = FAMILIES.filter((f) => (results[f]?.trades ?? 0) > 0);
  if (!withTrades.length) return new Set();
  const best = Math.max(...withTrades.map((f) => results[f]?.net_pnl ?? Number.NEGATIVE_INFINITY));
  return new Set(withTrades.filter((f) => (results[f]?.net_pnl ?? Number.NEGATIVE_INFINITY) === best));
}

export interface RunState { at: string | null; ok: boolean | null; next_at?: string | null; new_items?: number | null }
export interface Runs { pre_open: RunState; intraday: RunState[]; post_close: RunState; news: RunState }
/** Runs ok of the day's expected runs: pre-open, the intraday checks, post-close and the latest news run. */
export function runsOk(runs: Runs): { ok: number; total: number } {
  const all = [runs.pre_open, ...runs.intraday.slice(0, INTRADAY_CHECKS_PER_SESSION), runs.post_close, runs.news];
  return { ok: all.filter((r) => r.ok === true).length, total: 1 + INTRADAY_CHECKS_PER_SESSION + 1 + 1 };
}
