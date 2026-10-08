// Presentation-only sums and groupings of the company page (design/mockups/03-company/notes.md "Shown but computed by
// the page"): open-trade sums and flagged counts, the settled summary, the "why" bar parts, the chart's trade marks
// and the company's next event. Pure functions of the payload; no formatting.
import type { CalendarEvent, OpenTrade, Prediction, SettledTrade, TradeCheck } from "./types.ts";

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
