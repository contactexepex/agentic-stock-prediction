// The Rule vs AI page's own presentation logic (B16; design/mockups/06-rule-vs-ai, notes.md "Shown but computed by
// the page"): who leads, the matches on identical company-days, the per-company sums, the cumulative lines per
// family and the picks' cost counts. Pure: no React, no DOM.
import { figure, type CostView, type Family, type ScoreboardRow, type Strategy } from "../_b16/scoreboard.ts";

export interface SettledTrade {
  trade_id: string;
  prediction_id: string;
  strategy_id: string;
  family: Family;
  view: string;
  pick_rule: string;
  ticker: string;
  horizon_days: number;
  entry_date: string;
  exit_date: string;
  exit_date_actual: string | null;
  net_pnl: number;
  return_pct: number;
  target_error_pct: number | null;
  target_reached: boolean | null;
  regime?: string | null;
}

export interface PickCandidate {
  horizon_days: number;
  your_cost_pct?: number | null;
  expected_gain_your_pct?: number | null;
  cost_viable?: boolean | null;
}

export interface Pick {
  id: string;
  ticker: string;
  session_date: string;
  family: Family;
  pick_rule: string;
  status: string;
  strategy_id: string | null;
  horizon_days: number | null;
  prob_up: number | null;
  move_pct: number | null;
  loss_pct: number | null;
  costs_pct: number | null;
  expected_gain_pct: number | null;
  candidates: PickCandidate[];
  amount: number;
}

export interface YourCostRecord {
  trade_id: string;
  net_pnl_your: number;
  return_pct_your: number;
}

export interface Reason {
  id: string;
  ticker: string;
  strategy_id: string;
  session_date: string;
  text: string;
  cited_ids: string[];
}

export interface FamilyResult {
  trades: number;
  wins?: number;
  net_pnl: number;
}

export interface EodAnalysis {
  id: string;
  session_date: string;
  settled_trades: number;
  results: Record<string, FamilyResult>;
  summary: string;
}

export interface Review {
  id: string;
  iso_week: string;
  period_start: string;
  period_end: string;
  leaders: Array<{ scope: string; strategy_id: string; net_pnl: number; trades: number }>;
  findings: Array<{ text: string; cited_ids: string[] }>;
  proposals: Array<{ proposal_id: string; kind: string; file: string; diff: string; rationale: string;
    cited_ids: string[]; status: string }>;
  report_path: string;
}

export interface NewsImpactRow {
  id: string;
  iso_week: string;
  event_type: string;
  status: string;
  materiality: string;
  horizon_days: number;
  n_events: number;
  mean_abnormal_pct: number | null;
  ci_low_pct: number | null;
  ci_high_pct: number | null;
  enough: boolean;
}

export interface RuleVsAiPayload {
  market: string;
  name: string;
  currency: string;
  as_of: string | null;
  session_date: string | null;
  strategies: Record<string, Strategy>;
  companies: Array<{ ticker: string; name: string }>;
  rows: ScoreboardRow[];
  trades: SettledTrade[];
  picks: Pick[];
  your_costs: YourCostRecord[];
  reasons: Reason[];
  eod: EodAnalysis[];
  reviews: Review[];
  review_due: { date: string; iso_week: string } | null;
}

export interface ReviewPayload {
  reviews: Review[];
  review_due: { date: string; iso_week: string } | null;
  news_impact: NewsImpactRow[];
}

/** The family's head-to-head row over all horizons (forward), or null. */
export function familyRow(rows: readonly ScoreboardRow[], family: Family): ScoreboardRow | null {
  return rows.find((row) => row.scope === "strategy" && row.family === family && row.horizon_days === "all"
    && row.basis === "forward") ?? null;
}

/** A trade's profit on the cost view: the your-cost figure from its cost-view record, else the market figure is
 * NOT substituted; null when the your-cost record is missing. */
export function tradeNet(trade: SettledTrade, costs: readonly YourCostRecord[], cost: CostView): number | null {
  if (cost === "market") return trade.net_pnl;
  return costs.find((record) => record.trade_id === trade.trade_id)?.net_pnl_your ?? null;
}

export function tradeReturn(trade: SettledTrade, costs: readonly YourCostRecord[], cost: CostView): number | null {
  if (cost === "market") return trade.return_pct;
  return costs.find((record) => record.trade_id === trade.trade_id)?.return_pct_your ?? null;
}

export type Leader = "rule" | "ai" | "level";

/** Who leads on the cost view, and by how much; null when either family has no row or a figure is not stored. */
export function whoLeads(rule: ScoreboardRow | null, ai: ScoreboardRow | null, cost: CostView):
  { leader: Leader; by: number } | null {
  if (!rule || !ai) return null;
  const r = figure(rule, "net_pnl", cost), a = figure(ai, "net_pnl", cost);
  if (r === null || a === null) return null;
  const gap = r - a;
  return { leader: Math.abs(gap) < 1e-9 ? "level" : gap > 0 ? "rule" : "ai", by: Math.abs(gap) };
}

export interface Match {
  entry_date: string;
  ticker: string;
  pick_rule: string;
  rule: SettledTrade | null;
  ai: SettledTrade | null;
}

/** The settled head-to-head trades grouped by entry date, company and pick rule; newest entry first. */
export function matches(trades: readonly SettledTrade[]): Match[] {
  const groups = new Map<string, Match>();
  for (const trade of trades) {
    if (trade.family !== "rule" && trade.family !== "ai") continue;
    const key = `${trade.entry_date}|${trade.ticker}|${trade.pick_rule}`;
    const match = groups.get(key) ?? { entry_date: trade.entry_date, ticker: trade.ticker, pick_rule: trade.pick_rule, rule: null, ai: null };
    match[trade.family] = trade;
    groups.set(key, match);
  }
  return [...groups.values()].sort((a, b) => b.entry_date.localeCompare(a.entry_date) || a.ticker.localeCompare(b.ticker)
    || a.pick_rule.localeCompare(b.pick_rule));
}

export type MatchWinner = "rule" | "ai" | "draw" | "unknown";

/** The winner of a match with both sides settled, by net profit on the cost view ("unknown": a figure not stored). */
export function matchWinner(match: Match, costs: readonly YourCostRecord[], cost: CostView): MatchWinner | null {
  if (!match.rule || !match.ai) return null;
  const r = tradeNet(match.rule, costs, cost), a = tradeNet(match.ai, costs, cost);
  if (r === null || a === null) return "unknown";
  return r === a ? "draw" : r > a ? "rule" : "ai";
}

/** The match summary: completed matches and the wins per side. */
export function matchTally(list: readonly Match[], costs: readonly YourCostRecord[], cost: CostView):
  { both: number; rule: number; ai: number; draw: number } {
  const tally = { both: 0, rule: 0, ai: 0, draw: 0 };
  for (const match of list) {
    const winner = matchWinner(match, costs, cost);
    if (winner === null) continue;
    tally.both++;
    if (winner === "rule" || winner === "ai" || winner === "draw") tally[winner]++;
  }
  return tally;
}

/** The pick of one family for a match's day, company and rule (an open pick or a missing candidate), or null. */
export function pickFor(picks: readonly Pick[], match: Match, family: Family): Pick | null {
  return picks.find((pick) => pick.session_date === match.entry_date && pick.ticker === match.ticker
    && pick.pick_rule === match.pick_rule && pick.family === family) ?? null;
}

export interface CompanySum {
  n: number;
  net: number | null;
  won: number | null;
}

/** Per company and family: trades, summed profit and trades that made money on the cost view (null when any your-cost
 * figure is missing). */
export function perCompany(trades: readonly SettledTrade[], costs: readonly YourCostRecord[], cost: CostView):
  Array<{ ticker: string; rule: CompanySum | null; ai: CompanySum | null }> {
  const tickers = [...new Set(trades.map((trade) => trade.ticker))].sort();
  const sum = (list: SettledTrade[]): CompanySum | null => {
    if (!list.length) return null;
    const nets = list.map((trade) => tradeNet(trade, costs, cost));
    if (nets.some((net) => net === null)) return { n: list.length, net: null, won: null };
    const values = nets as number[];
    return { n: list.length, net: values.reduce((total, net) => total + net, 0), won: values.filter((net) => net > 0).length };
  };
  return tickers.map((ticker) => ({
    ticker,
    rule: sum(trades.filter((trade) => trade.ticker === ticker && trade.family === "rule")),
    ai: sum(trades.filter((trade) => trade.ticker === ticker && trade.family === "ai")),
  }));
}

/** The cumulative head-to-head lines (market cost): the first entry date at zero, then each exit date. */
export function familyLines(trades: readonly SettledTrade[]): { dates: string[]; rule: number[]; ai: number[] } {
  const exitOf = (trade: SettledTrade) => trade.exit_date_actual ?? trade.exit_date;
  const exits = [...new Set(trades.map(exitOf))].sort();
  if (!exits.length) return { dates: [], rule: [], ai: [] };
  const start = trades.map((trade) => trade.entry_date).sort()[0];
  const dates = [start, ...exits.filter((date) => date !== start)];
  const line = (family: Family) => {
    let running = 0;
    return dates.map((date) => {
      for (const trade of trades) if (trade.family === family && exitOf(trade) === date) running += trade.net_pnl;
      return running;
    });
  };
  return { dates, rule: line("rule"), ai: line("ai") };
}

/** The candidate of a pick's chosen horizon (it carries the your-cost viability, decision 51). */
export function pickCandidate(pick: Pick): PickCandidate | null {
  return pick.candidates.find((candidate) => candidate.horizon_days === pick.horizon_days) ?? null;
}

/** "n clear(s) market costs · m viable at your cost" for the picked picks of a session. */
export function viableLine(picked: readonly Pick[]): string {
  const clears = picked.filter((pick) => (pick.expected_gain_pct ?? 0) > 0).length;
  const viable = picked.filter((pick) => pickCandidate(pick)?.cost_viable === true).length;
  const known = picked.filter((pick) => (pickCandidate(pick)?.cost_viable ?? null) !== null).length;
  const market = clears ? `${clears} clear${clears === 1 ? "s" : ""} market costs` : "none clears market costs";
  const your = known ? (viable ? `${viable} viable at your cost` : "none viable at your cost") : "your-cost view not stored";
  return `${market} · ${your}`;
}
