// Shared by B16's strategy and performance pages (05 Strategy lab, 06 Rule vs AI, 07 Paper portfolios): the
// scoreboard row as B13's endpoints serve it (api/schemas/strategy-lab.yaml ScoreboardRow, Strategy) and the pure
// logic the mockups compute on it: the cost view of a figure, the luck test's verdict and bar geometry, nice axis
// ticks. Pure: no React, no DOM. The `_b16` folder is private (no route).

export type Family = "rule" | "baseline" | "ai";
export type CostView = "market" | "your";
export type ScoreView = "accuracy" | "head_to_head";
export type Basis = "forward" | "backtest";

export interface LuckTest {
  method?: string;
  n: number;
  m: number;
  low_pct: number | null;
  high_pct: number | null;
  excludes_zero?: boolean | null;
  corrected_low_pct: number | null;
  corrected_high_pct: number | null;
  corrected: boolean | null;
}

export interface YourCostFigures {
  net_pnl?: number | null;
  mean_return_pct?: number | null;
  win_rate?: number | null;
  worst_losing_streak?: number | null;
  max_drawdown?: number | null;
  luck_test?: LuckTest | null;
}

export interface RowGoLive {
  proven: boolean;
  months_forward: number;
  trades_needed: number;
  beats_best_baseline: boolean | null;
  best_baseline_net_pnl?: number | null;
  drawdown_limit?: number | null;
  drawdown_within_limit?: boolean | null;
  holds_in_calm_and_volatile?: boolean | null;
  cost_view?: string;
}

export interface ScoreboardRow {
  scope: string;
  market: string;
  view: ScoreView;
  basis: Basis;
  strategy_id: string;
  family: Family;
  pick_rule: string | null;
  ticker?: string | null;
  regime?: string | null;
  horizon_days: number | "all";
  trades: number;
  net_pnl: number;
  mean_return_pct: number | null;
  win_rate: number | null;
  target_reached_rate: number | null;
  median_reached_session?: number | null;
  avg_target_error_pct: number | null;
  range_hit_rate: number | null;
  worst_losing_streak: number | null;
  max_drawdown: number | null;
  sample_badge: string;
  first_entry: string | null;
  last_exit: string | null;
  as_of?: string | null;
  luck_test: LuckTest | null;
  your_cost: YourCostFigures | null;
  go_live?: RowGoLive | null;
}

export interface Strategy {
  id: string;
  family: Family;
  name: string;
  description?: string;
  compared_to?: string | null;
  differs_in?: string | null;
  parameters?: Record<string, unknown>;
  threshold: number | null;
  horizons: number[];
  live_from?: string | null;
  live: boolean;
  settled_trades: number;
}

export const FAMILY_ORDER: Readonly<Record<Family, number>> = { rule: 0, baseline: 1, ai: 2 };

type Figure = Exclude<keyof YourCostFigures, "luck_test">;

/** A row's figure on the cost view; null when the your-cost view does not store it (a back-test row stores profit
 * and mean return only), never the market figure in its place. */
export function figure(row: ScoreboardRow, key: Figure, cost: CostView): number | null {
  if (cost === "market") return (row[key] as number | null | undefined) ?? null;
  const your = row.your_cost;
  return your && key in your ? ((your[key] as number | null | undefined) ?? null) : null;
}

/** The luck test of the cost view (the your-cost one may be absent: null). */
export function luckOf(row: ScoreboardRow, cost: CostView): LuckTest | null {
  if (cost === "your") return row.your_cost?.luck_test ?? null;
  return row.luck_test ?? null;
}

export type LuckVerdict = "edge" | "loss" | "luck?";

/** 'edge' only when the corrected interval lies above zero, 'loss' when wholly below zero, else 'luck?'. */
export function luckVerdict(test: LuckTest): LuckVerdict {
  if (test.corrected_low_pct !== null && test.corrected_low_pct > 0) return "edge";
  if (test.corrected_high_pct !== null && test.corrected_high_pct < 0) return "loss";
  return "luck?";
}

/** x of a value on the luck bar (width `span` from x = 4), the axis covering both intervals and zero. */
export function luckScale(test: LuckTest, span: number): (value: number) => number {
  const low = test.low_pct ?? 0, high = test.high_pct ?? 0;
  const lo = Math.min(test.corrected_low_pct ?? low, low, 0);
  const hi = Math.max(test.corrected_high_pct ?? high, high, 0);
  return (value) => 4 + ((value - lo) / (hi - lo || 1)) * span;
}

/** About n round axis ticks between lo and hi (steps of 1, 2, 5 x 10^k). */
export function niceTicks(lo: number, hi: number, n: number): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / n, magnitude = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / magnitude;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * magnitude;
  const out: number[] = [];
  for (let value = Math.ceil(lo / step) * step; value <= hi; value += step) out.push(+value.toFixed(6));
  return out;
}

/** Rows of one scope, view, basis and horizon (the horizon compared as text: "all" or "3"). */
export function rowsOf(rows: readonly ScoreboardRow[], scope: string, horizon: number | "all", view: ScoreView,
  basis: Basis): ScoreboardRow[] {
  return rows.filter((row) => row.scope === scope && row.view === view && row.basis === basis
    && String(row.horizon_days) === String(horizon));
}

export const REGIME_WORDS: Readonly<Record<string, string>> = {
  CALM: "calm", TRENDING: "trending", EVENT_HEAVY: "event-heavy", UNSTABLE: "unstable",
};

export const tooFewToRank = (row: ScoreboardRow): boolean => row.sample_badge === "too_few_to_rank";
