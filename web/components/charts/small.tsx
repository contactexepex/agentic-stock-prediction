// Small inline charts of the tables and cards, drawn as the mockups draw them (design/mockups/_shared/shell.js):
// the range bar, the buyers-by-horizon bars and the agreement bar (rule / baselines / AI). Each carries a text
// alternative (aria-label) and a tooltip with every number, so nothing is told by colour alone.
import { FAMILY } from "../../lib/ui/constants.ts";
import { price } from "../../lib/ui/format.ts";
import { linearScale, rangeBarDomain } from "../../lib/ui/scales.ts";
import type { BuySplit, RangeBands } from "../../lib/ui/types.ts";
import type { Family } from "../../lib/ui/constants.ts";

/** The 50% and 80% bands, the entry dotted, the target as a triangle, the last price as the dark line. */
export function RangeBar({ currency, bands, last = null, entry = null }: { currency: string; bands: RangeBands; last?: number | null; entry?: number | null }) {
  const x = linearScale(rangeBarDomain(bands, last, entry), [2, 98]);
  const t = x(bands.target_price);
  const tip =
    `Predicted 50% range ${price(currency, bands.lo50)}–${price(currency, bands.hi50)}, 80% range ${price(currency, bands.lo80)}–${price(currency, bands.hi80)}; ` +
    `target ${price(currency, bands.target_price)} (the triangle)` +
    (entry !== null ? `; entry ${price(currency, entry)} (dotted)` : "") +
    (last !== null ? `; last ${price(currency, last)} (the dark line)` : "") + ".";
  return (
    <span className="rng" data-tip={tip}>
      <svg viewBox="0 0 100 18" role="img" aria-label={`80% range ${price(currency, bands.lo80)} to ${price(currency, bands.hi80)}${last !== null ? ", last " + price(currency, last) : ""}`}>
        <rect x={x(bands.lo80)} y={5} width={x(bands.hi80) - x(bands.lo80)} height={8} rx={4} fill="var(--mb-chart-band-80)" />
        <rect x={x(bands.lo50)} y={5} width={x(bands.hi50) - x(bands.lo50)} height={8} rx={4} fill="var(--mb-chart-band-50)" />
        {entry !== null ? <line x1={x(entry)} x2={x(entry)} y1={3} y2={15} stroke="var(--md-sys-color-outline)" strokeWidth={1.5} strokeDasharray="2 1.5" /> : null}
        <path d={`M${t - 3},1 L${t + 3},1 L${t},5 Z`} fill="var(--mb-chart-1)" />
        {last !== null ? <line x1={x(last)} x2={x(last)} y1={2} y2={16} stroke="var(--md-sys-color-on-surface)" strokeWidth={2} /> : null}
      </svg>
    </span>
  );
}

/** Buyers at each horizon: five small bars, the selected horizon dark; `null` = no prediction at that horizon. */
export function HorizonBars({ horizons, splits, selected }: { horizons: readonly number[]; splits: readonly (BuySplit | null)[]; selected: number }) {
  const max = Math.max(1, ...splits.map((a) => (a ? a.of : 0)));
  const tip =
    "Buyers at each horizon: " +
    horizons.map((k, i) => `N+${k} ${splits[i] ? `${splits[i]!.buy} of ${splits[i]!.of}` : "no prediction"}`).join(" · ") +
    ". The strongest other horizon is the one with the most buyers (ties: the shorter).";
  return (
    <span className="hzb" data-tip={tip}>
      <svg viewBox="0 0 96 40" role="img" aria-label={tip}>
        {horizons.map((k, i) => {
          const a = splits[i], x0 = i * 19 + 1, h = a ? Math.max(2, (a.buy / max) * 26) : 2, on = k === selected;
          return (
            <g key={k}>
              <rect className={on ? "on" : "off"} x={x0} y={28 - h} width={15} height={h} rx={3} />
              <text className={on ? "on" : undefined} x={x0 + 7.5} y={38} textAnchor="middle">
                {a ? a.buy : "–"}
              </text>
            </g>
          );
        })}
      </svg>
    </span>
  );
}

const FAMILIES: readonly Family[] = ["rule", "baseline", "ai"];

/** The stacked agreement bar: of all strategies predicting, the share each family would buy. */
export function AgreementBar({ byFamily, of, subject }: { byFamily: Record<Family, BuySplit>; of: number; subject?: string }) {
  const words = `rule ${byFamily.rule.buy}, baselines ${byFamily.baseline.buy}, AI ${byFamily.ai.buy}`;
  const tip = `Rule ${byFamily.rule.buy}/${byFamily.rule.of} · baselines ${byFamily.baseline.buy}/${byFamily.baseline.of} · AI ${byFamily.ai.buy}/${byFamily.ai.of} would buy${subject ? " " + subject : ""}.`;
  const total = byFamily.rule.buy + byFamily.baseline.buy + byFamily.ai.buy;
  return (
    <div className="mb-agbar" role="img" aria-label={`${total} of ${of}: ${words}`} data-tip={tip}>
      {FAMILIES.map((f) => (
        <i key={f} className={`ser-${FAMILY[f][2]}`} style={{ width: `${of ? ((100 * byFamily[f].buy) / of).toFixed(1) : 0}%` }} />
      ))}
    </div>
  );
}
