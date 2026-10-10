// Presentation-only sums and groupings of the company page (design/mockups/03-company/notes.md "Shown but computed by
// the page"): open-trade sums and flagged counts, the settled summary, the "why" bar parts, the chart's trade marks
// and the company's next event. Pure functions of the payload; no formatting.
import type { RangeBands } from "../ui/types.ts";
import type { AiReason, CalendarEvent, OpenTrade, Prediction, PublishedRange, SettledTrade, TradeCheck } from "./types.ts";

const num = (x: number | null | undefined): number => (x == null ? 0 : x);

export const isSettled = (t: SettledTrade): boolean => t.status === "settled";

/** The reference strategy's prediction at horizon k, or null. */
export const referencePrediction = (preds: Prediction[], reference: string, k: number): Prediction | null =>
  preds.find(r => r.strategy_id === reference && r.horizon_days === k) ?? null;

/** N+k of a trade or prediction id ("...-3d" or "...-3d@..."), or null. */
export const horizonOfId = (id: string): number | null => {
  const m = /-(\d)d(@|$)/.exec(id);
  return m ? Number(m[1]) : null;
};

export interface OpenSummary { count: number; unrealised: number; unrealisedKnown: number; flagged: number }
export function openSummary(open: OpenTrade[], checks: TradeCheck[]): OpenSummary {
  const known = open.filter(t => t.unrealised_pnl != null);
  return {
    count: open.length,
    unrealised: known.reduce((s, t) => s + num(t.unrealised_pnl), 0),
    unrealisedKnown: known.length,
    flagged: checks.filter(c => c.flagged).length,
  };
}

export interface SettledSummary { trades: number; won: number; net: number; reached: number; inRange: number; skipped: number; skippedStatuses: string[] }
export function settledSummary(rows: SettledTrade[]): SettledSummary {
  const done = rows.filter(isSettled), skipped = rows.filter(t => !isSettled(t));
  return {
    trades: done.length,
    won: done.filter(t => num(t.net_pnl) > 0).length,
    net: done.reduce((s, t) => s + num(t.net_pnl), 0),
    reached: done.filter(t => t.target_reached === true).length,
    inRange: done.filter(t => t.range_hit === true).length,
    skipped: skipped.length,
    skippedStatuses: [...new Set(skipped.map(t => t.status))],
  };
}

export type WhyPart = { key: "market" | "sector" | "news" | "company"; value: number };
export const whyParts = (t: SettledTrade): WhyPart[] => [
  { key: "market", value: num(t.market_pct) }, { key: "sector", value: num(t.sector_pct) },
  { key: "news", value: num(t.news_pct) }, { key: "company", value: num(t.company_pct) },
];

/** The largest summed absolute reason split of the rows, at least 1 (the "why" bars share one scale). */
export const whyScale = (rows: SettledTrade[]): number =>
  Math.max(1, ...rows.map(t => whyParts(t).reduce((s, p) => s + Math.abs(p.value), 0)));

/** The "why" bar segments in a 110 x 14 box: positive parts stack right of the centre (55), negative parts left. */
export function whySegments(t: SettledTrade, scale: number): Array<WhyPart & { x: number; width: number }> {
  const k = 50 / scale, out: Array<WhyPart & { x: number; width: number }> = [];
  let posX = 55, negX = 55;
  for (const part of whyParts(t)) {
    if (!part.value) continue;
    const width = Math.max(1, Math.abs(part.value) * k);
    if (part.value > 0) { out.push({ ...part, x: posX, width }); posX += width + 1; }
    else { negX -= width; out.push({ ...part, x: negX, width }); negX -= 1; }
  }
  return out;
}

export interface TradeMarks { entries: Map<string, SettledTrade[]>; exits: Map<string, SettledTrade[]>; open: Map<string, OpenTrade[]> }
/** Settled trades grouped by entry date and by actual exit date, open trades by entry date (the chart's triangles). */
export function tradeMarks(settled: SettledTrade[], open: OpenTrade[]): TradeMarks {
  const push = <T>(m: Map<string, T[]>, k: string, v: T) => { const l = m.get(k); if (l) l.push(v); else m.set(k, [v]); };
  const marks: TradeMarks = { entries: new Map(), exits: new Map(), open: new Map() };
  for (const t of settled) if (isSettled(t)) { push(marks.entries, t.entry_date, t); push(marks.exits, t.exit_date_actual ?? t.exit_date, t); }
  for (const t of open) push(marks.open, t.entry_date, t);
  return marks;
}

/** The distinct horizons of a group of trades, sorted ("N+1, N+3"). */
export const horizonsOf = (rows: Array<{ horizon_days: number }>): number[] =>
  [...new Set(rows.map(r => r.horizon_days))].sort((a, b) => a - b);

/** The company's own next event in the payload's window (events are sorted by date). */
export const nextCompanyEvent = (events: CalendarEvent[], ticker: string, type?: string): CalendarEvent | null =>
  events.find(e => e.ticker === ticker && (type == null || e.type === type)) ?? null;

/** The 50% and 80% ranges and target of a prediction or trade, or null when any is missing (no range bar then). */
export function bandsOf(r: { lo80?: number | null; lo50?: number | null; hi50?: number | null; hi80?: number | null; target_price?: number | null }): RangeBands | null {
  const { lo80, lo50, hi50, hi80, target_price } = r;
  if (lo80 == null || lo50 == null || hi50 == null || hi80 == null || target_price == null) return null;
  return { lo80, lo50, hi50, hi80, target_price };
}

/** The sessions whose call history (rm.lifecycle) the page links, newest first: the session being predicted and the
 *  stored sessions before it, at most `count` (the read model keeps the last 30 market sessions). */
export function lifecycleDates(bars: Array<{ date: string }>, sessionBeingPredicted: string | null | undefined, count = 10): string[] {
  const dates = new Set(bars.map((b) => b.date).filter((d) => !sessionBeingPredicted || d < sessionBeingPredicted));
  const ordered = [...dates].sort().reverse();
  if (sessionBeingPredicted) ordered.unshift(sessionBeingPredicted);
  return ordered.slice(0, count);
}

export interface PredictionPath {
  prediction: Prediction;
  checks: TradeCheck[];
  settled: SettledTrade[];
  reasons: AiReason[];
}

/** One session's calls with what became of them (SPEC section 2 "Lifecycle of a prediction": made -> checks ->
 *  settled -> explained): the intraday checks and settlements of each prediction's trades (matched by prediction id;
 *  a prediction can have an accuracy-view and a head-to-head trade), and the AI reasons about those trades (by trade
 *  id). Ordered by horizon, then strategy. Checks newest first. */
export function predictionPaths(day: { predictions: Prediction[]; trade_checks: TradeCheck[]; settled: SettledTrade[]; reasons: AiReason[] }): PredictionPath[] {
  return [...day.predictions]
    .sort((a, b) => a.horizon_days - b.horizon_days || a.strategy_id.localeCompare(b.strategy_id))
    .map((prediction) => {
      const checks = day.trade_checks.filter((c) => c.prediction_id === prediction.id).sort((a, b) => b.check_at.localeCompare(a.check_at));
      const settled = day.settled.filter((t) => t.prediction_id === prediction.id);
      const trades = new Set([...settled.map((t) => t.trade_id), ...checks.map((c) => c.trade_id)]);
      const reasons = day.reasons.filter((r) => r.trade_id != null && trades.has(r.trade_id));
      return { prediction, checks, settled, reasons };
    });
}

export interface EventEffect { label: string; tone: "warn" | "neutral"; tip: string; plain: string }
/** What a company's own event does to its ranges and calls: results widen the ranges (earnings_vol_multiple) and
 *  block a new call within a day (prediction_rules: days_to_earnings <= 1); an ex-dividend date only centres the ranges
 *  whose window contains it lower by the dividend (config/ranges.yaml ex_dividend), calls go on. Other types: null. */
export function companyEventEffect(type: string): EventEffect | null {
  if (type === "earnings") return {
    label: "widens ranges", tone: "warn",
    tip: "Results widen this company’s ranges (earnings_vol_multiple) and no new call is made within a day of them.",
    plain: "ranges widen and no new call is made within a day of it",
  };
  if (type === "ex_dividend") return {
    label: "shifts ranges", tone: "neutral",
    tip: "On the ex-dividend date the price drops by the dividend: the ranges whose window contains it are centred lower by it (ex_dividend in config/ranges.yaml). Calls are made as usual.",
    plain: "the ranges whose window contains it are centred lower by the dividend; calls go on as usual",
  };
  return null;
}

/** A range row the card and the chart draw: the horizon, its exit session, target and 50% / 80% bands. */
export type RangeRow = Pick<PublishedRange, "horizon_days" | "exit_date" | "target_price" | "lo50" | "hi50" | "lo80" | "hi80">;

/** The published ranges per horizon, sorted by horizon: B12's `published_ranges` (ranges.py, shown whatever the
 *  strategies' live_from) when the payload carries the field, else the reference strategy's predictions (payloads
 *  built before it existed). */
export function publishedRanges(p: { published_ranges?: PublishedRange[] | null; predictions: Prediction[]; reference_strategy: string }): RangeRow[] {
  const rows: RangeRow[] = Array.isArray(p.published_ranges)
    ? p.published_ranges
    : p.predictions.filter((r) => r.strategy_id === p.reference_strategy);
  return [...rows].sort((a, b) => a.horizon_days - b.horizon_days);
}

/** The published range at horizon k, or null. */
export const publishedRangeAt = (rows: RangeRow[], k: number): RangeRow | null => rows.find((r) => r.horizon_days === k) ?? null;
