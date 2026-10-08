"use client";
// Small parts B16's pages share (05 Strategy lab, 06 Rule vs AI, 07 Paper portfolios, 08 Track record), drawn as the
// mockups draw them: the luck-test bar, an interval bar, a host-width hook for the charts that redraw at the card's
// width, and the cost switch. Their CSS sits in each page's stylesheet (scoped per page). Private folder: no route.
import { useEffect, useState, type ReactNode } from "react";
import { Segmented } from "../../../../components/ui/controls.tsx";
import { HelpTip } from "../../../../components/ui/icon.tsx";
import { Label } from "../../../../components/ui/primitives.tsx";
import { LUCK_INTERVAL_PCT, MIN_TRADES_TO_RANK } from "../../../../lib/ui/constants.ts";
import { DASH, signed } from "../../../../lib/ui/format.ts";
import {
  figure, luckOf, luckScale, luckVerdict, tooFewToRank, type CostView, type ScoreboardRow,
} from "../../../../lib/strategy-pages/scoreboard.ts";

/** A callback ref and the width of the element it is attached to, updated on resize (null before the first layout).
 * A callback ref, so an element that appears later (e.g. a chart once its data exists) is measured too. */
export function useWidth<T extends HTMLElement>(): [(node: T | null) => void, number | null] {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    if (!node) return;
    setWidth(node.clientWidth);
    const observer = new ResizeObserver(() => setWidth((old) => (old === null || Math.abs(old - node.clientWidth) > 2 ? node.clientWidth : old)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return [setNode, width];
}

const VERDICT_TONE = { edge: "success", loss: "danger", "luck?": "neutral" } as const;

/** The luck test of a row on the cost view: the thin 95% interval, the thick corrected one, the mean and zero tick,
 * and the verdict in words ('edge' / 'luck?' / 'loss'; with fewer than 20 trades an edge reads 'edge? too few'). */
export function LuckBar({ row, cost, span = 88, none = "none yet" }: { row: ScoreboardRow; cost: CostView; span?: number; none?: string }) {
  const test = luckOf(row, cost);
  if (!test || test.low_pct === null || test.high_pct === null) {
    const stored = row.trades >= 2;
    return (
      <span className="muted" data-tip={stored ? "No luck test stored for this cost view." : "Fewer than 2 trades: no luck interval yet."}>
        {stored ? "not stored" : none}
      </span>
    );
  }
  const x = luckScale(test, span), mean = figure(row, "mean_return_pct", cost);
  const verdict = luckVerdict(test), few = tooFewToRank(row);
  const word = verdict === "edge" && few ? "edge? too few" : verdict;
  const said = verdict === "edge"
    ? few ? `The corrected interval lies above zero, but on fewer than ${MIN_TRADES_TO_RANK} trades: not counted as an edge yet.` : "The corrected interval lies above zero: an edge may be real."
    : verdict === "loss" ? "The corrected interval lies wholly below zero: the strategy loses money after costs, and that is not luck."
      : "The corrected interval includes zero: the result could be luck; no edge claimed.";
  const corrected = test.corrected_low_pct !== null && test.corrected_high_pct !== null;
  const tip = `Luck test (${test.n} trades): the mean return per trade is ${signed(mean)}; a bootstrap puts it between ${signed(test.low_pct)} and ${signed(test.high_pct)} (thin bar, ${LUCK_INTERVAL_PCT}%).`
    + (corrected ? ` Corrected for the ${test.m} rows compared at once: ${signed(test.corrected_low_pct)} to ${signed(test.corrected_high_pct)} (thick bar).` : "")
    + ` ${said} The tick is zero.`;
  return (
    <span className="luck" data-tip={tip}>
      <svg viewBox={`0 0 ${span + 8} 16`} role="img" aria-label={`luck interval ${signed(test.low_pct)} to ${signed(test.high_pct)}${corrected ? `, corrected ${signed(test.corrected_low_pct)} to ${signed(test.corrected_high_pct)}` : ""}`}>
        <line className="z" x1={x(0)} x2={x(0)} y1={1} y2={15} />
        <line className="raw" x1={x(test.low_pct)} x2={x(test.high_pct)} y1={8} y2={8} />
        {corrected ? <line className={`cor${verdict === "edge" ? " edge" : ""}`} x1={x(test.corrected_low_pct as number)} x2={x(test.corrected_high_pct as number)} y1={8} y2={8} /> : null}
        {mean !== null ? <circle className="mean" cx={x(mean)} cy={8} r={2.5} /> : null}
      </svg>
      <Label tone={few && verdict === "edge" ? "neutral" : VERDICT_TONE[verdict]}>{word}</Label>
    </span>
  );
}

/** An interval bar: the interval as a thick line, the point as a dot, an optional dashed middle and reference tick. */
export function CiBar({ lo, hi, point, min = 0, max = 1, mid = null, base = null, cls = "", text, tip }: {
  lo: number | null; hi: number | null; point: number | null; min?: number; max?: number; mid?: number | null;
  base?: number | null; cls?: string; text: string | null; tip?: string;
}) {
  const W = 120, H = 14, X = (v: number) => Math.max(0, Math.min(W, ((v - min) / (max - min)) * W));
  return (
    <span className="ci" data-tip={tip}>
      <svg viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
        <rect className="track" x={0} y={5} width={W} height={4} rx={2} />
        {mid !== null ? <line className="mid" x1={X(mid)} x2={X(mid)} y1={1} y2={13} /> : null}
        {base !== null ? <line className="base" x1={X(base)} x2={X(base)} y1={1} y2={13} /> : null}
        {lo !== null && hi !== null ? <line className={`band${cls ? " " + cls : ""}`} x1={X(lo)} x2={X(hi)} y1={7} y2={7} /> : null}
        {point !== null ? <circle className="pt" cx={X(point)} cy={7} r={3} /> : null}
      </svg>
      <b>{text ?? DASH}</b>
    </span>
  );
}

/** The cost switch of the strategy pages (market cost ranks; your cost is the go-live bar's view, decision 50). */
export function CostSwitch({ value, onChange, help }: { value: CostView; onChange: (v: CostView) => void; help: string }) {
  return (
    <span className="c">
      Costs
      <HelpTip tip={help} />
      <Segmented label="Costs" value={value} onChange={onChange} options={[{ value: "market", label: "Market cost" }, { value: "your", label: "Your cost" }]} />
    </span>
  );
}

/** A labelled control of the controls bar. */
export function Control({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <span className="c">
      {label}
      {help ? <HelpTip tip={help} /> : null}
      {children}
    </span>
  );
}
