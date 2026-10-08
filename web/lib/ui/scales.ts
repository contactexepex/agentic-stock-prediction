// Chart arithmetic for the hand-drawn SVG charts (components/charts/), the same approach as the approved mockups:
// linear scales, round tick values and SVG path strings. Pure, no DOM.

export type Scale = ((value: number) => number) & { domain: [number, number]; range: [number, number] };

/** A linear map from [d0, d1] to [r0, r1]; a zero-width domain maps to the middle of the range. */
export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const f = ((v: number) => (d1 === d0 ? (r0 + r1) / 2 : r0 + ((v - d0) / (d1 - d0)) * (r1 - r0))) as Scale;
  f.domain = domain;
  f.range = range;
  return f;
}

/** The [min, max] of finite values, widened by `pad` (a fraction of the span, or of |value| when the span is 0). */
export function extent(values: readonly (number | null | undefined)[], pad = 0): [number, number] | null {
  const finite = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!finite.length) return null;
  let lo = Math.min(...finite), hi = Math.max(...finite);
  const span = hi - lo || Math.abs(hi) || 1;
  lo -= span * pad;
  hi += span * pad;
  return [lo, hi];
}

/** The round step for about `count` intervals over a span (1, 2, 2.5 or 5 times a power of ten). */
export function niceStep(span: number, count = 5): number {
  const raw = Math.abs(span) / Math.max(1, count) || 1;
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw * (1 - 1e-12)) ?? 10 * power;
}

/** [lo, hi] widened to whole steps, so the axis starts and ends on a tick (the mockups' charts). */
export function niceDomain(lo: number, hi: number, count = 5): [number, number] {
  if (hi === lo) return [lo - 1, hi + 1];
  const step = niceStep(hi - lo, count);
  return [Math.floor(lo / step + 1e-9) * step, Math.ceil(hi / step - 1e-9) * step];
}

/** About `count` round tick values inside [lo, hi] (steps of 1, 2, 2.5 or 5 times a power of ten). */
export function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (!(Number.isFinite(lo) && Number.isFinite(hi)) || count < 1) return [];
  if (hi < lo) [lo, hi] = [hi, lo];
  if (hi === lo) return [lo];
  const step = niceStep(hi - lo, count);
  const first = Math.ceil(lo / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = first; v <= hi + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

export interface Point {
  x: number;
  y: number;
}

const r = (v: number) => Math.round(v * 100) / 100;

/** "M x,y L x,y ..." through the points; a null point breaks the line. */
export function linePath(points: readonly (Point | null)[]): string {
  let d = "", pen = false;
  for (const p of points) {
    if (!p) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${r(p.x)},${r(p.y)} `;
    pen = true;
  }
  return d.trim();
}

/** A closed area under the points down to `baseY` (the gradient fill of area charts). */
export function areaPath(points: readonly Point[], baseY: number): string {
  if (!points.length) return "";
  const line = points.map((p, i) => `${i ? "L" : "M"}${r(p.x)},${r(p.y)}`).join(" ");
  return `${line} L${r(points[points.length - 1].x)},${r(baseY)} L${r(points[0].x)},${r(baseY)} Z`;
}

/** A band between a lower and an upper series (a range fan): upper left to right, lower right to left. */
export function bandPath(upper: readonly Point[], lower: readonly Point[]): string {
  if (!upper.length || upper.length !== lower.length) return "";
  const top = upper.map((p, i) => `${i ? "L" : "M"}${r(p.x)},${r(p.y)}`).join(" ");
  const bottom = [...lower].reverse().map((p) => `L${r(p.x)},${r(p.y)}`).join(" ");
  return `${top} ${bottom} Z`;
}

/** The range bar's domain (design/mockups/_shared/shell.js rangeBar): the 80% band, entry, last and target, padded 0.3%. */
export function rangeBarDomain(bands: { lo80: number; hi80: number; target_price: number }, last: number | null, entry: number | null): [number, number] {
  const lo = Math.min(bands.lo80, entry ?? bands.lo80, last ?? bands.lo80) * 0.997;
  const hi = Math.max(bands.hi80, entry ?? bands.hi80, last ?? bands.hi80, bands.target_price) * 1.003;
  return [lo, hi];
}
