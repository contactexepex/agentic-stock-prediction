// "All paper trades in one place" on the Paper portfolios page (owner request 2026-10-12; B13's `all_trades` block of
// GET /markets/{m}/portfolios, api/schemas/paper-portfolios.yaml AllTrades): the summary row a filter reads, the trade
// list's filters and each row's plain words. Scope `all` (accuracy view) and `head_to_head` are two views of the same
// predictions and are never added together. Not-entered trades are listed but never counted. Pure: no React.

export type TradeScope = "all" | "head_to_head" | "mine";
export type SummaryFamily = "all" | "rule" | "ai" | "baseline" | "mine";
export type SummaryPeriod = "to_date" | "window";

export interface AllTradesSummaryRow {
  scope: TradeScope;
  family: SummaryFamily;
  period: SummaryPeriod;
  open: number;
  closed: number;
  wins: number;
  losses: number;
  flat: number;
  win_rate: number | null;
  net_pnl_market: number | null;
  net_pnl_your: number | null;
  pnl_your_missing: number;
  currency: string | null;
}

export interface AllTradesRow {
  id: string;
  scope: TradeScope;
  view: "accuracy" | "head_to_head" | null;
  strategy_id: string | null;
  family: "rule" | "ai" | "baseline" | "mine";
  pick_rule: string | null;
  ticker: string;
  horizon_days: number | null;
  side?: "buy" | "sell" | null;
  entry_date: string | null;
  exit_date: string | null;
  state: "open" | "closed" | "not_entered";
  outcome: "win" | "loss" | "flat" | null;
  not_entered_reason?: "no_entry" | "skipped_price_above_amount" | null;
  entry_price: number | null;
  entry_price_source?: "daily_bar" | "intraday_check" | null;
  exit_or_last_price: number | null;
  last_price_date?: string | null;
  last_price_source?: "daily_close" | "intraday_check" | null;
  last_price_time?: string | null;
  price_pending: boolean;
  quantity: number | null;
  amount: number | null;
  currency: string | null;
  pnl_market: number | null;
  pnl_your: number | null;
  return_pct_market: number | null;
  return_pct_your: number | null;
  unrealised_pnl?: number | null;
  unrealised_pct?: number | null;
  settled_at: string | null;
  paper: boolean;
}

export interface AllTrades {
  window: { sessions: number; from: string | null; to: string | null };
  summary: AllTradesSummaryRow[];
  trades: AllTradesRow[];
}

/** The summary row of a scope, family and period, or null when the read model has none. */
export function summaryRow(all: AllTrades, scope: TradeScope, family: SummaryFamily, period: SummaryPeriod): AllTradesSummaryRow | null {
  return all.summary.find((row) => row.scope === scope && row.family === family && row.period === period) ?? null;
}

/** The families shown under a scope, in a fixed order (the scope's own total first). */
export function familiesOf(all: AllTrades, scope: TradeScope): SummaryFamily[] {
  const order: SummaryFamily[] = scope === "mine" ? ["mine"] : ["all", "rule", "baseline", "ai"];
  return order.filter((family) => all.summary.some((row) => row.scope === scope && row.family === family));
}

/** The scope's total row: family `all` for the strategy views, `mine` for the owner's trades. */
export const totalFamily = (scope: TradeScope): SummaryFamily => (scope === "mine" ? "mine" : "all");

export type StateFilter = "any" | "open" | "closed";
export type ResultFilter = "any" | "win" | "loss";

export interface TradeFilter {
  scope: TradeScope;
  state: StateFilter;
  result: ResultFilter;
}

/** The listed trades of a filter: one scope only (never two views pooled); a result filter keeps closed trades only. */
export function filterTrades(all: AllTrades, filter: TradeFilter): AllTradesRow[] {
  return all.trades.filter((row) => {
    if (row.scope !== filter.scope) return false;
    if (filter.state === "open" && row.state !== "open") return false;
    if (filter.state === "closed" && row.state !== "closed") return false;
    if (filter.result !== "any" && !(row.state === "closed" && row.outcome === filter.result)) return false;
    return true;
  });
}

export const NOT_ENTERED_WORDS: Readonly<Record<string, string>> = {
  no_entry: "did not enter: no stored open price that day",
  skipped_price_above_amount: "skipped: one share costs more than the amount",
};

/** A row's state in plain words. */
export function stateWords(row: AllTradesRow): string {
  if (row.state === "not_entered") return NOT_ENTERED_WORDS[row.not_entered_reason ?? ""] ?? "did not enter";
  if (row.state === "open") return row.price_pending ? "open, no price yet" : "open";
  if (row.outcome === "win") return "closed, made money";
  if (row.outcome === "loss") return "closed, lost money";
  if (row.outcome === "flat") return "closed, no gain or loss";
  return "closed";
}

/** The figure a row's result is judged on: after market cost for strategy trades, after your cost for your own. */
export function resultFigure(row: AllTradesRow): { value: number | null; cost: "market" | "your" | "before" } {
  if (row.state === "open") return { value: row.unrealised_pnl ?? null, cost: "before" };
  if (row.scope === "mine") return { value: row.pnl_your, cost: "your" };
  return { value: row.pnl_market, cost: "market" };
}

/** The headline counts of a summary row in plain words ("3 open · 5 closed · 3 won, 2 lost"). */
export function countsWords(row: AllTradesSummaryRow | null): string {
  if (!row) return "nothing recorded yet";
  const parts = [`${row.open} open`, `${row.closed} closed`];
  if (row.closed) parts.push(`${row.wins} won, ${row.losses} lost${row.flat ? `, ${row.flat} even` : ""}`);
  return parts.join(" · ");
}
