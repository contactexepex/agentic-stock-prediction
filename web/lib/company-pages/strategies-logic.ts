// Presentation-only ordering of the stock strategies page (design/mockups/04-stock-strategies/notes.md "Shown but
// computed by the page"): the ranking order (profit after costs, then trades, then id), the best row per scope and the
// expected gain in money. Pure functions of the payload.
import type { AgreementRow, ScoreRow } from "./types.ts";

/** A score row of a named strategy (the schema allows a null strategy_id; such rows are not ranked). */
export type StrategyRow = ScoreRow & { strategy_id: string };

/** The scope's rows pooled over every horizon, named strategies only. */
export const pooledRows = (rows: ScoreRow[]): StrategyRow[] =>
  rows.filter((r): r is StrategyRow => r.horizon_days === "all" && r.strategy_id != null);

const byProfit = (a: StrategyRow, b: StrategyRow) =>
  (b.net_pnl ?? 0) - (a.net_pnl ?? 0) || b.trades - a.trades || a.strategy_id.localeCompare(b.strategy_id);

/** The best row with at least one settled trade and a stored profit: highest profit after costs, then most trades,
 *  then id. */
export const bestOf = (rows: StrategyRow[]): StrategyRow | null =>
  rows.filter(r => r.trades > 0 && r.net_pnl != null).sort(byProfit)[0] ?? null;

/** Every strategy id, those with a row on this company first by profit after costs, then the rest by id. */
export function rankedIds(strategyIds: string[], rows: StrategyRow[]): string[] {
  const byId = new Map(rows.map(r => [r.strategy_id, r] as [string, StrategyRow]));
  return [...strategyIds].sort((x, y) => {
    const a = byId.get(x), b = byId.get(y);
    if (a && b) return byProfit(a, b);
    if (a) return -1;
    if (b) return 1;
    return x.localeCompare(y);
  });
}

/** Expected gain in money of a pick: its expected gain in percent of the amount. */
export const expectedGainMoney = (expectedGainPct: number | null, amount: number | null): number | null =>
  expectedGainPct == null || amount == null ? null : expectedGainPct * amount / 100;

/** The agreement row of a horizon (AgreementMap: "1".."5" -> one row for this company), or null. */
export const agreementAt = (agreement: Record<string, AgreementRow[] | undefined>, k: number): AgreementRow | null =>
  (agreement[String(k)] ?? [])[0] ?? null;

/** Bar widths in percent for the per-family buyer bars. */
export const buyShare = (x: { buy: number; of: number }): number => (x.of ? 100 * x.buy / x.of : 0);
