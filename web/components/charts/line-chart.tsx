"use client";
// The shared line / area chart (the Home page's cumulative profit chart generalised): category x axis, round y ticks,
// up to four series in the chart tokens (series r/b/a/k = --mb-chart-1..4, the families' colours), gradient area fills,
// a zero line, a dashed cursor and one focusable hit column per x with a tooltip of every series' value (keyboard and
// screen-reader path). The legend below names each series with its last value: never colour alone.
import { useId, useState, type ReactNode } from "react";
import { areaPath, extent, linearScale, linePath, niceDomain, niceTicks, type Point } from "../../lib/ui/scales.ts";

export type SeriesKey = "r" | "b" | "a" | "k";

export interface LineSeries {
  key: SeriesKey;
  name: string;
  values: readonly (number | null)[];
  area?: boolean;
}

export function LineChart({
  labels,
  series,
  label,
  formatY = (v) => String(v),
  formatValue,
  height = 220,
  width = 420,
  zeroLine = true,
  legend = true,
}: {
  /** One label per x position (e.g. dates already formatted). */
  labels: readonly string[];
  series: readonly LineSeries[];
  /** The chart's accessible name. */
  label: string;
  formatY?: (v: number) => string;
  /** How a value reads in the tooltip and legend (defaults to formatY). */
  formatValue?: (v: number | null) => string;
  height?: number;
  width?: number;
  zeroLine?: boolean;
  legend?: boolean;
}) {
  const gradientId = useId().replace(/:/g, "");
  const [cursor, setCursor] = useState<number | null>(null);
  const show = formatValue ?? ((v: number | null) => (v === null ? "—" : formatY(v)));
  const W = width, H = height, L = 54, R = 12, T = 14, B = 30;
  const span = extent(series.flatMap((s) => s.values).concat(zeroLine ? [0] : []));
  if (!span || !labels.length) return null;
  const [lo, hi] = niceDomain(span[0], span[1], 4);
  const ticks = niceTicks(lo, hi, 4);
  const n = labels.length;
  const X = (i: number) => (n === 1 ? L + (W - L - R) / 2 : L + (i * (W - L - R)) / (n - 1));
  const Y = linearScale([lo, hi], [H - B, T]);
  const every = Math.max(1, Math.ceil(n / 6));
  const half = (W - L - R) / Math.max(1, n - 1) / 2;
  return (
    <div className="chart mb-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label={label} style={{ height }}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`${gradientId}-${s.key}`} x1={0} y1={0} x2={0} y2={1}>
              <stop offset="0" stopColor={`var(--mb-chart-${"rbak".indexOf(s.key) + 1}-fill)`} />
              <stop offset="1" stopColor={`var(--mb-chart-${"rbak".indexOf(s.key) + 1}-fill)`} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <g className="grid">
          {ticks.map((v) => (
            <line key={v} x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} />
          ))}
          {zeroLine && lo < 0 && hi > 0 ? <line x1={L} x2={W - R} y1={Y(0)} y2={Y(0)} style={{ stroke: "var(--md-sys-color-outline)" }} /> : null}
        </g>
        <g className="axis">
          {ticks.map((v) => (
            <text key={v} x={L - 6} y={Y(v) + 4} textAnchor="end">
              {formatY(v)}
            </text>
          ))}
          {labels.map((text, i) =>
            i % every === 0 || i === n - 1 ? (
              <text key={i} x={X(i)} y={H - 8} textAnchor="middle">
                {text}
              </text>
            ) : null,
          )}
        </g>
        {series.map((s) => {
          const points = s.values.map((v, i) => (v === null ? null : ({ x: X(i), y: Y(v) } as Point)));
          const solid = points.filter((p): p is Point => p !== null);
          return (
            <g key={s.key}>
              {s.area && solid.length > 1 ? <path d={areaPath(solid, Y(lo))} fill={`url(#${gradientId}-${s.key})`} /> : null}
              <path className={`ln ${s.key}`} d={solid.length > 1 ? linePath(points) : solid.length ? `M${solid[0].x - 6},${solid[0].y} L${solid[0].x + 6},${solid[0].y}` : ""} />
              {solid.map((p, i) => (
                <circle key={i} className={`pt ${s.key}`} cx={p.x} cy={p.y} r={4} />
              ))}
            </g>
          );
        })}
        <line className="cursor" x1={cursor === null ? 0 : X(cursor)} x2={cursor === null ? 0 : X(cursor)} y1={T} y2={H - B} style={{ opacity: cursor === null ? 0 : 1 }} />
        {labels.map((text, i) => {
          const x0 = Math.max(L, X(i) - half), x1 = Math.min(W - R, X(i) + half);
          const tip = `${text}: ` + series.map((s) => `${s.name} ${show(s.values[i] ?? null)}`).join(" · ");
          return (
            <rect
              key={i}
              className="hit"
              x={x0}
              y={T}
              width={Math.max(1, x1 - x0)}
              height={H - T - B}
              tabIndex={0}
              role="img"
              data-tip={tip}
              aria-label={tip}
              onPointerEnter={() => setCursor(i)}
              onPointerLeave={() => setCursor(null)}
              onFocus={() => setCursor(i)}
              onBlur={() => setCursor(null)}
            />
          );
        })}
      </svg>
      {legend ? <ChartLegend items={series.map((s) => ({ key: s.key, name: s.name, value: show(lastValue(s.values)) }))} /> : null}
    </div>
  );
}

function lastValue(values: readonly (number | null)[]): number | null {
  for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null) return values[i];
  return null;
}

/** A legend row: swatch, name and (optionally) a value per series. */
export function ChartLegend({ items }: { items: readonly { key: SeriesKey; name: string; value?: ReactNode }[] }) {
  return (
    <div className="legend">
      {items.map((item) => (
        <span key={item.key + item.name}>
          <i className={`sw ${item.key}`} aria-hidden="true" />
          {item.name} {item.value !== undefined ? <b>{item.value}</b> : null}
        </span>
      ))}
    </div>
  );
}
