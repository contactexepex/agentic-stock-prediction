// Geometry of the company page's price chart (design/mockups/03-company/template.html drawChart): candles and volume
// of the stored sessions, then FUT wider slots for the N+1..N+5 exit sessions where the reference strategy's fan
// (50% and 80% ranges from the last close), its targets and the spread of every strategy's target at the selected
// horizon are drawn. Pure: the component renders the returned numbers as SVG.
import type { Bar, Prediction } from "./types.ts";

export interface ChartInput {
  bars: Bar[]; width: number; horizons: number[]; horizon: number;
  reference: Prediction[];   // the reference strategy's predictions with ranges, one per horizon
  atHorizon: Prediction[];   // every strategy's prediction at the selected horizon with a target
  tagWidth: number;          // width of the last-close tag text, measured by the caller
}

export interface ChartGeometry {
  W: number; H: number; L: number; R: number; T: number; AX: number; PB: number; phone: boolean;
  bars: Bar[]; step: number; bw: number; labelAll: boolean; lo: number; hi: number;
  x: (i: number) => number; y: (v: number) => number; vy: (v: number) => number;
  ticks: number[]; lastY: number; targetTagY: number | null;
  fan80: string | null; fan50: string | null; targetLine: string | null;
  targets: Array<{ k: number; x: number; y: number; on: boolean }>;
  spread: { x: number; y1: number; y2: number; min: number; max: number; count: number } | null;
  monthTicks: Array<{ i: number; x: number; label: string; anchor: "start" | "middle" }>;
  indexOf: Map<string, number>;
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const PHONE_WIDTH = 560, PHONE_SESSIONS = 30, FUTURE_SLOTS = 5;

const hasRange = (r: Prediction): r is Prediction & { lo50: number; hi50: number; lo80: number; hi80: number; target_price: number } =>
  r.lo50 != null && r.hi50 != null && r.lo80 != null && r.hi80 != null && r.target_price != null;

/** Round tick values covering [lo, hi], about n of them (1, 2 or 5 times a power of ten apart). */
export function niceTicks(lo: number, hi: number, n: number): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag, out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

export function chartGeometry(input: ChartInput): ChartGeometry | null {
  const W = Math.max(280, input.width), phone = W < PHONE_WIDTH;
  const bars = (phone ? input.bars.slice(-PHONE_SESSIONS) : input.bars).filter(b => b.high != null && b.low != null);
  const n = bars.length;
  if (!n) return null;
  const H = phone ? 300 : 360, L = 6, T = 14, AX = 22, VH = phone ? 36 : 48, PB = H - AX - VH - 8;
  const R = Math.max(phone ? 50 : 62, input.tagWidth + 8);
  const FS = phone ? 2.4 : 2.2, step = (W - L - R) / (n + FUTURE_SLOTS * FS + 0.5);
  const x = (i: number) => L + (i < n ? (i + 0.5) * step : (n - 0.5) * step + (i - n + 1) * step * FS);
  const bw = Math.max(2, Math.min(12, step * 0.62)), labelAll = step * FS >= 22;
  const ref = input.horizons.map(k => input.reference.find(r => r.horizon_days === k)).filter((r): r is Prediction => !!r).filter(hasRange);
  const at = input.atHorizon.filter(r => r.target_price != null);
  let lo = Math.min(...bars.map(b => b.low)), hi = Math.max(...bars.map(b => b.high));
  for (const r of ref) { lo = Math.min(lo, r.lo80); hi = Math.max(hi, r.hi80); }
  for (const r of at) { lo = Math.min(lo, r.target_price as number); hi = Math.max(hi, r.target_price as number); }
  const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.01 || 1;
  lo -= pad; hi += pad;
  const y = (v: number) => T + (hi - v) / (hi - lo) * (PB - T);
  const vmax = Math.max(1, ...bars.map(b => b.volume ?? 0));
  const vy = (v: number) => H - AX - (v / vmax) * VH;
  const last = bars[n - 1], lastY = y(last.close);
  const sel = ref.find(r => r.horizon_days === input.horizon) ?? null;
  let targetTagY = sel ? y(sel.target_price) : null;
  if (sel && targetTagY != null && Math.abs(targetTagY - lastY) < 19) targetTagY = sel.target_price >= last.close ? lastY - 19 : lastY + 19;
  let fan80: string | null = null, fan50: string | null = null, targetLine: string | null = null;
  const targets: ChartGeometry["targets"] = [];
  if (ref.length) {
    const start = `${x(n - 1)},${y(last.close)}`;
    const pts = ref.map(r => ({ px: x(n + r.horizon_days), r }));
    const poly = (loK: "lo80" | "lo50", hiK: "hi80" | "hi50") =>
      [start, ...pts.map(p => `${p.px},${y(p.r[hiK])}`), ...pts.slice().reverse().map(p => `${p.px},${y(p.r[loK])}`)].join(" ");
    fan80 = poly("lo80", "hi80"); fan50 = poly("lo50", "hi50");
    targetLine = [start, ...pts.map(p => `${p.px},${y(p.r.target_price)}`)].join(" ");
    for (const p of pts) targets.push({ k: p.r.horizon_days, x: p.px, y: y(p.r.target_price), on: p.r.horizon_days === input.horizon });
  }
  let spread: ChartGeometry["spread"] = null;
  if (ref.length && at.length) {
    const vals = at.map(r => r.target_price as number), min = Math.min(...vals), max = Math.max(...vals);
    spread = { x: x(n + input.horizon), y1: y(max), y2: y(min), min, max, count: at.length };
  }
  const monthTicks: ChartGeometry["monthTicks"] = [];
  let lastMon = "";
  bars.forEach((b, i) => {
    const mo = b.date.slice(0, 7);
    if (mo === lastMon) return;
    lastMon = mo;
    if (i === 0 && phone) return;
    const label = MON[Number(b.date.slice(5, 7)) - 1] + (i === 0 || b.date.slice(5, 7) === "01" ? " " + b.date.slice(0, 4) : "");
    monthTicks.push({ i, x: i === 0 ? Math.max(L, x(i) - 4) : x(i), label, anchor: i === 0 ? "start" : "middle" });
  });
  const indexOf = new Map(bars.map((b, i) => [b.date, i] as [string, number]));
  return { W, H, L, R, T, AX, PB, phone, bars, step, bw, labelAll, lo, hi, x, y, vy, ticks: niceTicks(lo, hi, 5), lastY, targetTagY,
    fan80, fan50, targetLine, targets, spread, monthTicks, indexOf };
}

/** The bar index under a pointer x in chart units, clamped to the stored sessions. */
export const barAt = (g: ChartGeometry, px: number): number =>
  Math.max(0, Math.min(g.bars.length - 1, Math.round((px - g.L) / g.step - 0.5)));
