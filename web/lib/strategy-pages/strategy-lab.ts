// The Strategy lab page's own presentation logic (B16; design/mockups/05-strategy-lab, notes.md "Shown but computed
// by the page"): the ranking order, the KPI picks, the compact heatmap profit, the heatmap colour share and the
// cumulative lines per series. Forward and back-test rows are never pooled: every function takes one basis. Pure.
import {
  FAMILY_ORDER, figure, rowsOf, type Basis, type CostView, type ScoreboardRow, type ScoreView, type Strategy,
} from "./scoreboard.ts";

export interface HeatmapCell {
  market: string;
  view: ScoreView;
  basis: Basis;
  strategy_id: string;
  dimension: "horizon" | "company" | "reason_code";
  column: string;
  week: string;
  trades: number;
  wins: number;
  win_rate: number | null;
  net_pnl: number;
}

export interface CumulativeLine {
  market: string;
  view: ScoreView;
  basis: Basis;
  series: string;
  date: string;
  net_pnl: number;
  cumulative_net_pnl: number;
}

export interface BacktestRun {
  history: boolean;
  first_date: string | null;
  last_date: string | null;
  eurusd: string | null;
  note: string | null;
}

export interface StrategyLabPayload {
  market: string;
  name: string;
  currency: string;
  as_of: string | null;
  horizons: number[];
  default_horizon: number | "all";
  reference_strategy: string;
  strategies: Record<string, Strategy>;
  companies: Array<{ ticker: string; name: string; sector?: string; state?: string }>;
  rows: ScoreboardRow[];
  cells: HeatmapCell[];
  lines: CumulativeLine[];
  bases: Basis[];
  backtest_run: BacktestRun | null;
}

export interface Slice {
  view: ScoreView;
  basis: Basis;
  horizon: number | "all";
}

export const REASON: Readonly<Record<string, string>> = {
  market_up: "market lift", market_down: "market drag", sector_lift: "sector lift", sector_drag: "sector drag",
  news_positive: "news +", news_negative: "news −", company_specific: "company", target_reached: "target reached",
  range_missed: "range missed",
};

export const KEYNAME: Readonly<Record<string, string>> = {
  signal: "signal", news_weight: "news weight", news_statuses: "news statuses", news_materiality: "news materiality",
  cross_market: "global cues", regime_filter: "regime filter", model: "model", inputs: "inputs",
  sees_model_score: "sees the model score",
};

export const keyName = (key: string): string => KEYNAME[key] ?? key.replace(/_/g, " ");

/** A strategy setting in words: lists joined, booleans yes/no, underscores as spaces. */
export function fmtParam(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item).replace(/_/g, " ")).join(", ");
  if (value === true) return "yes";
  if (value === false) return "no";
  return String(value).replace(/_/g, " ");
}

/** Every registry strategy in ranking order: by profit after market cost (decision 50: the ranking never changes
 * with the cost switch), then trades, then id; strategies without a row follow by family, then id. */
export function ranking(payload: StrategyLabPayload, slice: Slice): { ids: string[]; byId: Map<string, ScoreboardRow> } {
  const byId = new Map<string, ScoreboardRow>();
  for (const row of rowsOf(payload.rows, "strategy", slice.horizon, slice.view, slice.basis)) byId.set(row.strategy_id, row);
  const ids = Object.keys(payload.strategies).sort((x, y) => {
    const a = byId.get(x), b = byId.get(y);
    if (a && b) return b.net_pnl - a.net_pnl || b.trades - a.trades || x.localeCompare(y);
    if (a) return -1;
    if (b) return 1;
    return FAMILY_ORDER[payload.strategies[x].family] - FAMILY_ORDER[payload.strategies[y].family] || x.localeCompare(y);
  });
  return { ids, byId };
}

export interface KpiPicks {
  leader: ScoreboardRow | null;
  bestBaseline: ScoreboardRow | null;
  beat: number;
  contenders: number;
  nearest: ScoreboardRow | null;
}

/** The four KPI cards: the leader after market cost, the best baseline, how many contenders beat it, and the
 * contender nearest to the go-live bar (fewest trades still needed). */
export function kpiPicks(payload: StrategyLabPayload, slice: Slice): KpiPicks {
  const { ids, byId } = ranking(payload, slice);
  const ranked = ids.filter((id) => byId.has(id)).map((id) => byId.get(id) as ScoreboardRow);
  const bestBaseline = ranked.find((row) => row.family === "baseline") ?? null;
  const contenders = ranked.filter((row) => row.family !== "baseline");
  const beat = bestBaseline ? contenders.filter((row) => row.net_pnl > bestBaseline.net_pnl).length : 0;
  const nearest = contenders.filter((row) => row.go_live)
    .sort((a, b) => (a.go_live?.trades_needed ?? 0) - (b.go_live?.trades_needed ?? 0))[0] ?? null;
  return { leader: ranked[0] ?? null, bestBaseline, beat, contenders: contenders.length, nearest };
}

/** The forward accuracy row of a strategy over all horizons: the go-live bar's row whatever basis is shown. */
export function forwardAccuracyRow(payload: StrategyLabPayload, id: string): ScoreboardRow | null {
  return rowsOf(payload.rows, "strategy", "all", "accuracy", "forward").find((row) => row.strategy_id === id) ?? null;
}

/** A heatmap cell's compact profit: three significant digits, then a unit (k; lakh L and crore Cr for rupees, M for
 * dollars), the sign always, no currency symbol. */
export function compactProfit(currency: string, value: number): string {
  const units: Array<[number, string]> = currency === "INR" ? [[1e7, "Cr"], [1e5, "L"], [1e3, "k"]] : [[1e6, "M"], [1e3, "k"]];
  const abs0 = Math.abs(value), abs = abs0 >= 1 ? Number(abs0.toPrecision(3)) : Math.round(abs0);
  if (abs === 0) return "0";
  const sign = value > 0 ? "+" : "−";
  const unit = units.find(([size]) => abs >= size);
  if (!unit) return sign + abs.toFixed(0);
  const scaled = abs / unit[0];
  return sign + (scaled >= 100 ? scaled.toFixed(0) : scaled >= 10 ? scaled.toFixed(1) : scaled.toFixed(2)) + unit[1];
}

export interface HeatValue {
  n: number;
  net: number;
  win: number | null;
}

/** Colour strength (0-60, percent of the up or down colour) of every cell, the largest absolute value darkest. */
export function heatShares(values: ReadonlyArray<HeatValue | null>, metric: "net" | "win"): number[] {
  const magnitude = (cell: HeatValue) => metric === "net" ? Math.abs(cell.net) : Math.abs((cell.win ?? 0.5) - 0.5);
  const max = Math.max(1e-9, ...values.map((cell) => cell ? magnitude(cell) : 0));
  return values.map((cell) => cell ? Math.min(60, (magnitude(cell) / max) * 60) : 0);
}

/** The forward cells of the view; the weeks they hold, oldest first; a week not held falls back to "all". */
export function heatWeeks(cells: readonly HeatmapCell[], view: ScoreView, basis: Basis, week: string):
  { cells: HeatmapCell[]; weeks: string[]; week: string } {
  const ofView = basis === "forward" ? cells.filter((cell) => cell.view === view && cell.basis === "forward") : [];
  const weeks = [...new Set(ofView.filter((cell) => cell.week !== "all").map((cell) => cell.week))].sort();
  const chosen = weeks.includes(week) ? week : "all";
  return { cells: ofView.filter((cell) => cell.week === chosen), weeks, week: chosen };
}

export function cellValue(cells: readonly HeatmapCell[], id: string, dimension: string, column: string): HeatValue | null {
  const cell = cells.find((x) => x.strategy_id === id && x.dimension === dimension && x.column === column);
  return cell ? { n: cell.trades, net: cell.net_pnl, win: cell.win_rate } : null;
}

export interface Series {
  id: string;
  points: number[];
  count: number;
  last: number;
}

/** The cumulative lines of a view (forward only): every exit date of any series, each series' running total
 * carried flat between its own dates. */
export function cumulativeSeries(lines: readonly CumulativeLine[], view: ScoreView, basis: Basis):
  { dates: string[]; series: Series[] } {
  const points = basis === "forward" ? lines.filter((line) => line.view === view && line.basis === "forward") : [];
  const dates = [...new Set(points.map((line) => line.date))].sort();
  const grouped = new Map<string, CumulativeLine[]>();
  for (const line of points) {
    const list = grouped.get(line.series);
    if (list) list.push(line);
    else grouped.set(line.series, [line]);
  }
  const series = [...grouped.entries()].map(([id, list]) => {
    list.sort((a, b) => a.date.localeCompare(b.date));
    let running = 0, j = 0;
    const values = dates.map((date) => {
      while (j < list.length && list[j].date <= date) running = list[j++].cumulative_net_pnl;
      return running;
    });
    return { id, points: values, count: list.length, last: values[values.length - 1] ?? 0 };
  });
  return { dates, series };
}

/** The coloured series (at most four): the selected one and the highest cumulative profits, in registry order. */
export function colouredSeries(series: readonly Series[], selected: string | null, registry: readonly string[]): string[] {
  const byLast = series.slice().sort((a, b) => b.last - a.last || b.count - a.count || a.id.localeCompare(b.id));
  const order = (id: string) => { const at = registry.indexOf(id); return at < 0 ? registry.length : at; };
  return [...new Set([selected, ...byLast.map((line) => line.id)])]
    .filter((id): id is string => id !== null && series.some((line) => line.id === id))
    .slice(0, 4)
    .sort((a, b) => order(a) - order(b) || a.localeCompare(b));
}

/** The figure of a row on the cost view, or null when not stored (never the other view's figure). */
export const shown = (row: ScoreboardRow, key: "net_pnl" | "mean_return_pct" | "win_rate" | "max_drawdown"
  | "worst_losing_streak", cost: CostView): number | null => figure(row, key, cost);

/** The detail card's default: the first ranked strategy with a row, else the reference strategy. */
export function defaultSelection(payload: StrategyLabPayload, slice: Slice): string {
  const { ids, byId } = ranking(payload, slice);
  return ids.find((id) => byId.has(id)) ?? payload.reference_strategy;
}
