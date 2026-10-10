// The company page's forecast history (B12's rm.stock `forecast_history`; owner, 2026-10-10: see how each forecast
// was calculated and what changed between runs, as a chart and as text). Per horizon: every stored ranges.py run and
// signal-model run of the last 10 as-of dates, the words of each run's change from the run before, how its numbers
// were made, and the geometry of the two-panel chart (price ranges over the runs' times above, P(up) below). Pure.
import { extent, linearScale, niceDomain, niceTicks } from "../ui/scales.ts";
import type { ForecastHistory, HistoryRange, HistoryScore } from "./types.ts";

const MINUS = "−";
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const sgn = (x: number, decimals: number, unit: string) => (x > 0 ? "+" : x < 0 ? MINUS : "") + Math.abs(x).toFixed(decimals) + unit;
const time = (iso: string) => new Date(iso).getTime();

/** The runs of one horizon in time order (ranges by made_at, scores by computed_at); empty without a history. */
export function historyAt(h: ForecastHistory | null | undefined, k: number): { ranges: HistoryRange[]; scores: HistoryScore[] } {
  const ranges = (h?.ranges ?? []).filter((r) => r.horizon_days === k).sort((a, b) => time(a.made_at) - time(b.made_at) || a.id.localeCompare(b.id));
  const scores = (h?.scores ?? []).filter((s) => s.horizon_days === k).sort((a, b) => time(a.computed_at) - time(b.computed_at) || a.id.localeCompare(b.id));
  return { ranges, scores };
}

export type HistoryEntry = { kind: "range"; at: string; row: HistoryRange; previous: HistoryRange | null }
  | { kind: "score"; at: string; row: HistoryScore; previous: HistoryScore | null };

/** Both kinds of run in one list, newest first, each with the run its change was taken against (when stored). */
export function historyEntries(ranges: HistoryRange[], scores: HistoryScore[]): HistoryEntry[] {
  const byRange = new Map(ranges.map((r) => [`${r.id}@${r.made_at}`, r]));
  const byScore = new Map(scores.map((s) => [`${s.id}@${s.computed_at}`, s]));
  const list: HistoryEntry[] = [
    ...ranges.map((row) => ({ kind: "range" as const, at: row.made_at, row, previous: row.change ? byRange.get(`${row.change.from_id}@${row.change.from_made_at}`) ?? null : null })),
    ...scores.map((row) => ({ kind: "score" as const, at: row.computed_at, row, previous: row.change ? byScore.get(`${row.change.from_id}@${row.change.from_computed_at}`) ?? null : null })),
  ];
  return list.sort((a, b) => time(b.at) - time(a.at) || (a.kind === b.kind ? 0 : a.kind === "range" ? -1 : 1));
}

/** "a revision of the same as-of date" when the previous run predicted from the same close, else the next date's. */
const revision = (row: { as_of_date: string }, previous: { as_of_date: string } | null) => previous != null && previous.as_of_date === row.as_of_date;

/** What changed in a range run since the run before (plain words; the first run says so). */
export function rangeChangeWords(e: { row: HistoryRange; previous: HistoryRange | null }): string[] {
  const { row, previous } = e, c = row.change;
  if (!c) return ["first range run in the window"];
  const words: string[] = [revision(row, previous) ? "revised for the same close" : "new close"];
  words.push(c.target_pct == null ? "target move not computable" : `target ${sgn(c.target_pct, 2, "%")}`);
  if (c.width80_pct == null) words.push("80% width move not computable");
  else words.push(c.width80_pct === 0 ? "80% range as wide as before" : `80% range ${c.width80_pct > 0 ? "wider" : "narrower"} by ${Math.abs(c.width80_pct).toFixed(2)}%`);
  for (const field of c.changed) {
    if (field === "regime") words.push(previous ? `regime ${previous.regime ?? "none"} → ${row.regime ?? "none"}` : `regime now ${row.regime ?? "none"}`);
    else if (field === "calibration_id") words.push("new calibration");
    else if (field === "inputs") {
      const before = new Set(previous?.inputs ?? []), now = new Set(row.inputs);
      const added = row.inputs.filter((x) => !before.has(x)), dropped = [...before].filter((x) => !now.has(x));
      words.push(previous ? `range inputs changed${added.length ? `: added ${added.join(", ")}` : ""}${dropped.length ? `${added.length ? ";" : ":"} dropped ${dropped.join(", ")}` : ""}` : "range inputs changed");
    } else words.push(`${field} changed`);
  }
  return words;
}

const groupWords = (groups: Record<string, number>) =>
  Object.entries(groups).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]) || a[0].localeCompare(b[0])).map(([g, v]) => `${g} ${sgn(v, 2, " pts")}`);

/** What changed in a model-score run since the run before. */
export function scoreChangeWords(e: { row: HistoryScore; previous: HistoryScore | null }): string[] {
  const { row, previous } = e, c = row.change;
  if (!c) return ["first score run in the window"];
  const words: string[] = [revision(row, previous) ? "re-scored for the same close" : "new close"];
  words.push(c.prob_up == null ? "P(up) move not computable" : `P(up) ${sgn(c.prob_up * 100, 1, " pts")}`);
  const moved = groupWords(c.groups);
  words.push(moved.length ? `points moved: ${moved.join(", ")}` : "no group’s points moved");
  if (c.news_added.length) words.push(`${c.news_added.length} news ${c.news_added.length === 1 ? "item" : "items"} added`);
  if (c.news_dropped.length) words.push(`${c.news_dropped.length} news ${c.news_dropped.length === 1 ? "item" : "items"} dropped`);
  for (const field of c.changed) {
    if (field === "model_version") words.push(`model ${previous?.model_version ?? "?"} → ${row.model_version ?? "none"}`);
    else if (field === "model_id") words.push("refitted model");
    else if (field === "trained_until") words.push(`trained until ${row.trained_until ?? "unknown"}`);
    else words.push(`${field} changed`);
  }
  return words;
}

/** How a score was made: the base rate plus the points of every group that has some (they add up to P(up) - base
 *  rate in percentage points, explain.py; stored rounded, so the sum can differ by a few hundredths). */
export function scoreParts(s: HistoryScore): { base: number | null; parts: Array<[string, number]>; sum: number | null } {
  const parts = Object.entries(s.groups).filter(([, v]) => v !== 0).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]) || a[0].localeCompare(b[0]));
  const base = s.base_rate ?? null;
  return { base, parts, sum: base == null ? null : base * 100 + parts.reduce((t, [, v]) => t + v, 0) };
}

/** The range's centre as a percent move from the base close: exp(center) - 1 (target = base close x exp(center)). */
export const centreMovePct = (r: HistoryRange) => (r.center == null ? null : (Math.exp(r.center) - 1) * 100);

export interface HistoryPoint { x: number; y: number; at: string; id: string }

export interface HistoryGeometry {
  W: number; H: number; L: number; R: number; T: number; PH: number; GAP: number; QT: number; QH: number; AX: number;
  x: (t: number) => number; py: (v: number) => number; qy: (v: number) => number;
  priceTicks: number[]; probTicks: number[];
  band80: string | null; band50: string | null;
  target: HistoryPoint[]; base: HistoryPoint[]; prob: HistoryPoint[]; half: number;
  days: Array<{ x: number; label: string }>;
}

const MIN_SPAN = 12 * 3600 * 1000;
const poly = (pts: Array<[number, number]>) => pts.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(" ");

/** The chart's numbers: one time axis shared by the price panel (the 80% and 50% bands, the target and the base
 *  close of every range run) and the P(up) panel (every score run, with the 50% line); day labels at each date's
 *  first run on the market's clock (offsetMin east of UTC), dropped when closer than 44 px to the one before. */
export function historyGeometry(ranges: HistoryRange[], scores: HistoryScore[], width: number, offsetMin = 0): HistoryGeometry | null {
  if (!width || !(ranges.length || scores.length)) return null;
  const W = Math.max(280, Math.round(width)), L = 10, R = 68, T = 10, PH = ranges.length ? 160 : 0, GAP = ranges.length && scores.length ? 32 : 0;
  const QH = scores.length ? 86 : 0, QT = T + PH + GAP, AX = 22, H = QT + QH + AX;
  const times = [...ranges.map((r) => time(r.made_at)), ...scores.map((s) => time(s.computed_at))];
  let t0 = Math.min(...times), t1 = Math.max(...times);
  if (t1 - t0 < MIN_SPAN) { const mid = (t0 + t1) / 2; t0 = mid - MIN_SPAN / 2; t1 = mid + MIN_SPAN / 2; }
  const pad = 14;
  const x = linearScale([t0, t1], [L + pad, W - R - pad]);
  const pe = extent(ranges.flatMap((r) => [r.lo80, r.hi80, r.target_price, r.base_close]), 0.04) ?? [0, 1];
  const [p0, p1] = niceDomain(pe[0], pe[1], 4);
  const py = linearScale([p0, p1], [T + PH, T]);
  const probs = scores.map((s) => s.prob_up).filter((v): v is number => v != null);
  const qe = extent([...probs, 0.5], 0.15) ?? [0.4, 0.6];
  const [q0, q1] = niceDomain(Math.max(0, qe[0]), Math.min(1, qe[1]), 3);
  const qy = linearScale([q0, q1], [QT + QH, QT]);
  const pt = (t: string, v: number, id: string): HistoryPoint => ({ x: x(time(t)), y: py(v), at: t, id });
  const band = (lo: (r: HistoryRange) => number, hi: (r: HistoryRange) => number) =>
    ranges.length ? poly([...ranges.map((r) => [x(time(r.made_at)), py(hi(r))] as [number, number]), ...[...ranges].reverse().map((r) => [x(time(r.made_at)), py(lo(r))] as [number, number])]) : null;
  const days: HistoryGeometry["days"] = [];
  const firstOfDay = new Map<string, number>();
  for (const t of [...times].sort((a, b) => a - b)) {
    const d = new Date(t + offsetMin * 60000).toISOString().slice(0, 10);
    if (!firstOfDay.has(d)) firstOfDay.set(d, t);
  }
  for (const [d, t] of firstOfDay) {
    const px = x(t);
    if (days.length && px - days[days.length - 1].x < 44) continue;
    days.push({ x: px, label: `${Number(d.slice(8, 10))} ${MON[Number(d.slice(5, 7)) - 1]}` });
  }
  return {
    W, H, L, R, T, PH, GAP, QT, QH, AX, x, py, qy,
    priceTicks: ranges.length ? niceTicks(p0, p1, 4) : [], probTicks: scores.length ? niceTicks(q0, q1, 3) : [],
    band80: band((r) => r.lo80, (r) => r.hi80), band50: band((r) => r.lo50, (r) => r.hi50),
    target: ranges.map((r) => pt(r.made_at, r.target_price, r.id)), base: ranges.map((r) => pt(r.made_at, r.base_close, r.id)),
    prob: scores.filter((s) => s.prob_up != null).map((s) => ({ x: x(time(s.computed_at)), y: qy(s.prob_up as number), at: s.computed_at, id: s.id })),
    half: qy(0.5), days,
  };
}
