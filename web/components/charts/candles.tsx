"use client";
// Candlesticks with optional price lines (e.g. a published range or a trade's entry), on the vendored TradingView
// Lightweight Charts 5.2.1 (web/public/vendor/, SRI-pinned in lib/ui/vendor.ts; the same file the static dashboard
// uses). The script loads once per tab from the app's own origin. Colours come from the design tokens. The chart has an
// accessible name and a text summary; the page keeps its numbers in tables, so the chart is never the only source.
import { useEffect, useRef, useState } from "react";
import { LIGHTWEIGHT_CHARTS } from "../../lib/ui/vendor.ts";

export interface Candle {
  time: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface PriceLine {
  price: number;
  title: string;
  tone?: "accent" | "muted" | "up" | "down";
  dashed?: boolean;
}

/* The library's global (a minimal typing of what this wrapper uses). */
interface LwcSeries {
  setData(data: Candle[]): void;
  createPriceLine(options: Record<string, unknown>): unknown;
}
interface LwcChart {
  addSeries(kind: unknown, options: Record<string, unknown>): LwcSeries;
  timeScale(): { fitContent(): void };
  applyOptions(options: Record<string, unknown>): void;
  remove(): void;
}
interface Lwc {
  createChart(container: HTMLElement, options: Record<string, unknown>): LwcChart;
  CandlestickSeries: unknown;
  LineStyle: { Solid: number; Dashed: number };
}

let loading: Promise<Lwc> | null = null;
const NO_LINES: readonly PriceLine[] = [];

/** Load the vendored library once (script tag with Subresource Integrity). */
export function loadLightweightCharts(): Promise<Lwc> {
  const existing = (window as unknown as { LightweightCharts?: Lwc }).LightweightCharts;
  if (existing) return Promise.resolve(existing);
  if (loading) return loading;
  loading = new Promise<Lwc>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = LIGHTWEIGHT_CHARTS.src;
    script.integrity = LIGHTWEIGHT_CHARTS.integrity;
    script.crossOrigin = "anonymous";
    script.async = true;
    script.onload = () => {
      const lib = (window as unknown as { LightweightCharts?: Lwc }).LightweightCharts;
      if (lib) resolve(lib);
      else reject(new Error("chart library missing"));
    };
    script.onerror = () => {
      loading = null;
      reject(new Error("chart library failed to load"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function Candles({ candles, lines = NO_LINES, label, summary, height = 300 }: { candles: readonly Candle[]; lines?: readonly PriceLine[]; label: string; summary?: string; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let chart: LwcChart | null = null;
    let observer: ResizeObserver | null = null;
    let cancelled = false;
    loadLightweightCharts()
      .then((lib) => {
        if (cancelled || !box.current) return;
        const ink = token("--md-sys-color-on-surface-variant"), grid = token("--mb-chart-grid");
        chart = lib.createChart(box.current, {
          height,
          width: box.current.clientWidth,
          layout: { background: { color: "transparent" }, textColor: ink, fontFamily: token("--md-ref-typeface-plain") || undefined },
          grid: { vertLines: { color: grid }, horzLines: { color: grid } },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false },
        });
        const up = token("--mb-color-up"), down = token("--mb-color-down");
        const series = chart.addSeries(lib.CandlestickSeries, { upColor: up, downColor: down, wickUpColor: up, wickDownColor: down, borderVisible: false });
        series.setData([...candles]);
        const colour = { accent: token("--mb-chart-1"), muted: token("--md-sys-color-outline"), up, down };
        for (const line of lines) {
          series.createPriceLine({ price: line.price, title: line.title, color: colour[line.tone ?? "accent"], lineWidth: 1, lineStyle: line.dashed ? lib.LineStyle.Dashed : lib.LineStyle.Solid, axisLabelVisible: true });
        }
        chart.timeScale().fitContent();
        observer = new ResizeObserver(() => box.current && chart?.applyOptions({ width: box.current.clientWidth }));
        observer.observe(box.current);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      observer?.disconnect();
      chart?.remove();
    };
  }, [candles, lines, height]);
  return (
    <figure className="mb-candles">
      <div ref={box} role="img" aria-label={label} style={{ height }} />
      {failed ? <div className="quiet">The chart could not be drawn; the numbers are in the tables on this page.</div> : null}
      {summary ? <figcaption className="note">{summary}</figcaption> : null}
    </figure>
  );
}
