// The Track record page's own presentation logic (B16; design/mockups/08-track-record, notes.md "Shown but computed
// by the page"): the words for a back-test key and a baseline, the verdict badge, the "not enough history yet" gate,
// interval-bar and calibration geometry, and the weekly series of the selected scoring basis. Pure: no React, no DOM.
import type { CallBasisBlock, CallBlock, ReliabilityBand, TrackRecordPayload, WeeklyCallSeries } from "./types.ts";

export const BASELINE: Readonly<Record<string, string>> = {
  always_up: "Always up",
  momentum_5d: "Momentum (5 days)",
  rsi_mean_reversion: "RSI mean reversion",
  benchmark_long_per_date: "Benchmark long, per date",
  "–": "(no baseline)",
};

export const BASIS_WORDS: Readonly<Record<string, string>> = {
  close_to_close: "from the as-of close to the close h sessions later (calls made before the switch date in the settings)",
  open_to_close:
    "N+k: bought at the open of the first session after the call, sold at the close of the k-th session after it (calls from the switch date on)",
};

export function basisLabel(basis: string): string {
  return basis === "close_to_close" ? "close→close" : basis === "open_to_close" ? "open→close" : basis;
}

/** "1d close_to_close" -> "1 session · close→close"; any other key unchanged. */
export function keyWords(key: string): string {
  const match = /^(\d+)d (\w+)$/.exec(key);
  if (!match) return key;
  return `${match[1]} session${match[1] === "1" ? "" : "s"} · ${basisLabel(match[2])}`;
}

/** A verdict that beats is green, one that loses red, anything else neutral (never colour alone: the text is shown). */
export function verdictKind(verdict: string): "success" | "danger" | "neutral" {
  if (/beat|better|above/.test(verdict)) return "success";
  if (/lose|worse|below/.test(verdict)) return "danger";
  return "neutral";
}

export function tooFew(n: number, minSample: number): boolean {
  return n < minSample;
}

/** Position (0..width) of a value on an interval bar's axis, clamped to the ends. */
export function axisX(value: number, min: number, max: number, width: number): number {
  return Math.max(0, Math.min(width, ((value - min) / (max - min)) * width));
}

/** The paper long's symmetric axis around zero: wide enough for the interval and the mean, at least ±1 point. */
export function symmetricSpan(lo: number | null, hi: number | null, mean: number | null): number {
  return Math.max(1, Math.abs(lo ?? 0), Math.abs(hi ?? 0), Math.abs(mean ?? 0)) * 1.1;
}

/** The interval bar's colour class: up when the whole interval lies above the reference, down when below. */
export function intervalClass(lo: number | null, hi: number | null, reference: number): "up" | "down" | "" {
  if (lo !== null && lo > reference) return "up";
  if (hi !== null && hi < reference) return "down";
  return "";
}

/** The basis shown: the chosen key when it exists, else the first block (the mockup's default). */
export function selectedBasis(calls: readonly CallBasisBlock[], key: string | null): CallBasisBlock | null {
  return calls.find((block) => block.key === key) ?? calls[0] ?? null;
}

/** "All horizons" first, then each horizon in order of h. */
export function horizonRows(block: CallBasisBlock): Array<{ name: string; legacy: boolean; stats: CallBlock }> {
  const perHorizon = Object.values(block.by_horizon).sort((a, b) => (a.h ?? 0) - (b.h ?? 0));
  return [
    { name: "All horizons", legacy: false, stats: block.all },
    ...perHorizon.map((stats) => ({ name: stats.name ?? "", legacy: stats.horizon_label === "legacy_cc", stats })),
  ];
}

/** The weekly series of one scoring basis key (never pooled with another), or null. */
export function weeklyOf(weekly: readonly WeeklyCallSeries[] | undefined, key: string | null): WeeklyCallSeries | null {
  if (!weekly || key === null) return null;
  return weekly.find((series) => series.key === key) ?? null;
}

/** The back-test's paper-long rows grouped by key, in first-seen order. */
export function groupByKey<T extends { key: string }>(rows: readonly T[]): Array<[string, T[]]> {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const list = groups.get(row.key);
    if (list) list.push(row);
    else groups.set(row.key, [row]);
  }
  return [...groups.entries()];
}

export interface CalibrationLayout {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
  x: (value: number) => number;
  y: (value: number) => number;
}

/** The calibration chart's frame for a host width: the x axis spans the bands' confidence range, y 0-100%. */
export function calibrationLayout(bands: readonly ReliabilityBand[], hostWidth: number): CalibrationLayout {
  const width = Math.max(240, hostWidth);
  const height = width < 480 ? 200 : 240;
  const left = 40, right = 14, top = 14, bottom = 34;
  const x0 = Math.min(...bands.map((band) => band.lo));
  const x1 = Math.max(...bands.map((band) => band.hi));
  return {
    width, height, left, right, top, bottom,
    x: (value) => left + ((value - x0) / (x1 - x0)) * (width - left - right),
    y: (value) => top + (1 - value) * (height - top - bottom),
  };
}

/** The headline block: the first basis's all-horizon figures (the KPI cards), or null before any scored call. */
export function headline(track: TrackRecordPayload["track"]): { basis: CallBasisBlock; all: CallBlock } | null {
  const basis = track.calls[0];
  return basis ? { basis, all: basis.all } : null;
}
