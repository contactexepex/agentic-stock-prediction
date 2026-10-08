"use client";
// The company page's price chart (design/mockups/03-company drawChart): daily candles (hollow = closed above the open,
// filled = below) with volume, the session being predicted (D) and the N+1..N+5 exit slots where the reference
// strategy's 50% and 80% ranges draw a fan from the last close, its targets as dots on a dashed line, the selected
// horizon's target as a tag on the price axis, the spread of every strategy's target at that horizon, and the paper
// trades as triangles (entries below, exits above, hollow = still open). Hover or the arrow keys read each day;
// Escape clears. Drawn at the container's width, redrawn on resize. Geometry: lib/company-pages/chart-geometry.ts.
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardHead, PaperTag } from "../../../../../../components/ui/primitives.tsx";
import { DASH, fmtDate, fmtDateYear, money, price, signed } from "../../../../../../lib/ui/format.ts";
import { LOCALE } from "../../../../../../lib/ui/constants.ts";
import { barAt, chartGeometry } from "../../../../../../lib/company-pages/chart-geometry.ts";
import { horizonsOf, tradeMarks } from "../../../../../../lib/company-pages/company-logic.ts";
import type { CompanyPayload } from "../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "./context.ts";
import { plural } from "./labels.ts";

const horizonList = (rows: Array<{ horizon_days: number }>) => horizonsOf(rows).map((k) => `N+${k}`).join(", ");

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => setWidth((w) => (Math.abs(w - node.clientWidth) > 2 ? node.clientWidth : w));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function Mark({ x, y, up, cls, tip, count }: { x: number; y: number; up: boolean; cls: string; tip: string; count: number }) {
  return (
    <g tabIndex={0} data-tip={tip} aria-label={tip} role="img">
      <path className={cls} d={up ? `M${x},${y} l-5,8 h10 z` : `M${x},${y} l-5,-8 h10 z`} />
      {count > 1 ? <text x={x + 7} y={up ? y + 9 : y - 1}>{count}</text> : null}
    </g>
  );
}

export function PriceChart({ p, ctx, horizon }: { p: CompanyPayload; ctx: PageCtx; horizon: number }) {
  const cur = ctx.currency;
  const [hostRef, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const reference = useMemo(() => p.predictions.filter((r) => r.strategy_id === p.reference_strategy), [p.predictions, p.reference_strategy]);
  const atHorizon = useMemo(() => p.predictions.filter((r) => r.horizon_days === horizon && r.target_price != null), [p.predictions, horizon]);
  const lastClose = p.bars.length ? p.bars[p.bars.length - 1].close : null;
  const tagText = price(cur, lastClose);
  const tagW = Math.round(tagText.length * 6.6 + 12);
  const g = useMemo(
    () => (width ? chartGeometry({ bars: p.bars, width, horizons: p.horizons, horizon, reference, atHorizon, tagWidth: tagW }) : null),
    [p.bars, p.horizons, width, horizon, reference, atHorizon, tagW],
  );
  const marks = useMemo(() => tradeMarks(p.settled, p.open_trades), [p.settled, p.open_trades]);
  const n = p.bars.length;
  const svgRef = useRef<SVGSVGElement>(null);

  const head = (
    <CardHead
      title="Price with today’s targets and ranges"
      help="Daily candles of the stored sessions (hollow = closed above the open, filled = below). To the right of the last close: the reference strategy’s published targets for N+1..N+5 (dots on a dashed line), its 50% and 80% ranges as the shaded fan, and at the selected horizon the spread of every strategy’s target (the thin bar). Triangles mark the paper trades: entries below, exits above, hollow = still open. Hover or use the arrow keys for each day’s prices."
      end={n ? (<span className="ctl">{n} sessions to {fmtDate(p.bars[n - 1].date)}<span className="muted">·</span><PaperTag label={p.status.paper_label} /></span>) : undefined}
    />
  );
  if (!n) {
    return (
      <Card label="Price chart">
        {head}
        <div className="quiet">No stored price for this company yet.</div>
      </Card>
    );
  }

  let body = null, legend = null;
  if (g) {
    const { W, H, L, R, T, AX, PB, x, y, vy, bw } = g;
    const bars = g.bars, nb = bars.length, last = bars[nb - 1];
    const selected = g.targets.find((t) => t.on) ?? null;
    const selPred = reference.find((r) => r.horizon_days === horizon) ?? null;
    const markEls: React.ReactNode[] = [];
    for (const [d, ts] of marks.entries) {
      const i = g.indexOf.get(d);
      if (i === undefined) continue;
      markEls.push(<Mark key={`en${d}`} x={x(i)} y={y(bars[i].low) + 4} up cls="en" count={ts.length}
        tip={`${ts.length} paper ${plural(ts.length, "trade")} entered ${fmtDate(d)} at ${price(cur, ts[0].entry_price)} (the open): ${horizonList(ts)}.`} />);
    }
    for (const [d, ts] of marks.exits) {
      const i = g.indexOf.get(d);
      if (i === undefined) continue;
      const net = ts.reduce((s, t) => s + (t.net_pnl ?? 0), 0);
      markEls.push(<Mark key={`ex${d}`} x={x(i)} y={y(bars[i].high) - 4} up={false} cls="ex" count={ts.length}
        tip={`${ts.length} paper ${plural(ts.length, "trade")} exited ${fmtDate(d)} at ${price(cur, ts[0].exit_price)} (the close): net ${money(cur, net, ctx.decimals, true)} after costs.`} />);
    }
    for (const [d, ts] of marks.open) {
      const i = g.indexOf.get(d);
      if (i === undefined) continue;
      markEls.push(<Mark key={`op${d}`} x={x(i)} y={y(bars[i].low) + 16} up cls="op" count={ts.length}
        tip={`${ts.length} open paper ${plural(ts.length, "trade")} entered ${fmtDate(d)} at ${price(cur, ts[0].entry_price)}: ${horizonList(ts)}; still running.`} />);
    }
    const onKey = (e: React.KeyboardEvent) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        setHover((h) => (h === null ? nb - 1 : Math.max(0, Math.min(nb - 1, h + (e.key === "ArrowRight" ? 1 : -1)))));
      } else if (e.key === "Escape" || e.key === "Home") setHover(null);
    };
    const onMove = (e: React.PointerEvent) => {
      const r = svgRef.current?.getBoundingClientRect();
      if (r) setHover(barAt(g, (e.clientX - r.left) * (W / r.width)));
    };
    const hb = hover !== null && hover < nb ? bars[hover] : null;
    const prev = hover !== null && hover > 0 ? bars[hover - 1] : null;
    const entriesThere = hb ? (marks.entries.get(hb.date)?.length ?? 0) + (marks.open.get(hb.date)?.length ?? 0) : 0;
    const exitsThere = hb ? marks.exits.get(hb.date)?.length ?? 0 : 0;
    const tickTexts = g.ticks.filter((v) => !(Math.abs(y(v) - g.lastY) < 13 || (g.targetTagY != null && Math.abs(y(v) - g.targetTagY) < 13)));
    body = (
      <>
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" tabIndex={0} onKeyDown={onKey} onBlur={() => setHover(null)}
          aria-label={`${p.company.name} daily prices, ${nb} sessions, with today’s targets and ranges. Use the left and right arrow keys to read each day.`}>
          <g className="grid">{g.ticks.map((v) => <line key={v} x1={L} x2={W - R} y1={y(v)} y2={y(v)} />)}</g>
          <g className="vol">{bars.map((b, i) => <rect key={b.date} x={x(i) - bw / 2} y={vy(b.volume ?? 0)} width={bw} height={H - AX - vy(b.volume ?? 0)} />)}</g>
          <line className="vl" x1={x(nb)} x2={x(nb)} y1={T} y2={PB} />
          {g.fan80 ? (
            <g className="fan">
              <polygon className="b80" points={g.fan80} />
              <polygon className="b50" points={g.fan50 ?? ""} />
              <polyline className="tl" points={g.targetLine ?? ""} />
              {g.spread ? <line className="spread" x1={g.spread.x} x2={g.spread.x} y1={g.spread.y1} y2={g.spread.y2} tabIndex={0}
                data-tip={`${g.spread.count} strategies’ targets at N+${horizon}: ${price(cur, g.spread.min)} to ${price(cur, g.spread.max)}.`} /> : null}
              {g.targets.map((t) => <circle key={t.k} className={"tg" + (t.on ? " on" : "")} cx={t.x} cy={t.y} r={t.on ? 5 : 3.5} />)}
            </g>
          ) : null}
          {selected ? <line className="vl on" x1={selected.x} x2={selected.x} y1={T} y2={PB} /> : null}
          <g>
            {bars.map((b, i) => {
              const up = b.close >= b.open, y1 = y(Math.max(b.open, b.close)), y2 = y(Math.min(b.open, b.close));
              return (
                <g key={b.date} className={"c " + (up ? "up" : "dn")}>
                  <line className="w" x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} />
                  <rect className="b" x={x(i) - bw / 2} y={y1} width={bw} height={Math.max(1, y2 - y1)} rx={1} />
                </g>
              );
            })}
          </g>
          <g className="mk">{markEls}</g>
          {selPred && selected && g.targetTagY != null && selPred.target_price != null ? (
            <g className="ttag">
              <title>{`N+${horizon} target ${price(cur, selPred.target_price)}`}</title>
              <line x1={selected.x} x2={W - R + 2} y1={selected.y} y2={g.targetTagY} />
              <rect x={W - R + 2} y={g.targetTagY - 9} width={tagW} height={18} rx={4} />
              <text x={W - R + 2 + tagW / 2} y={g.targetTagY + 4} textAnchor="middle">{price(cur, selPred.target_price)}</text>
            </g>
          ) : null}
          <g className="ax">
            {tickTexts.map((v) => <text key={v} x={W - R + 6} y={y(v) + 4}>{price(cur, v)}</text>)}
            {g.monthTicks.map((t) => <text key={t.i} x={t.x} y={H - 6} textAnchor={t.anchor}>{t.label}</text>)}
            <text x={x(nb)} y={H - 6} textAnchor="middle">D</text>
            {g.targets.filter((t) => g.labelAll || t.on).map((t) => <text key={t.k} className={t.on ? "on" : undefined} x={t.x} y={H - 6} textAnchor="middle">+{t.k}</text>)}
          </g>
          <g className="last">
            <line x1={L} x2={W - R} y1={g.lastY} y2={g.lastY} />
            <rect x={W - R + 2} y={g.lastY - 9} width={tagW} height={18} rx={4} />
            <text x={W - R + 2 + tagW / 2} y={g.lastY + 4} textAnchor="middle">{price(cur, last.close)}</text>
          </g>
          {hb ? (
            <g className="hover">
              <line x1={x(hover!)} x2={x(hover!)} y1={T} y2={H - AX} />
              <circle r={4} cx={x(hover!)} cy={y(hb.close)} />
            </g>
          ) : null}
          <rect className="hit" x={L} y={T} width={W - L - R} height={H - T - AX} onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
        <div className={"ctip" + (hb ? " on" : "")} role="status" aria-live="polite"
          style={hb ? { left: Math.max(0, x(hover!) > W * 0.6 ? x(hover!) - 244 : x(hover!) + 14), top: Math.max(0, y(hb.close) - 40) } : undefined}>
          {hb ? (
            <>
              <b>{fmtDateYear(hb.date)}</b><br />
              <span className="mono">O {price(cur, hb.open)} · H {price(cur, hb.high)} · L {price(cur, hb.low)} · C {price(cur, hb.close)}</span><br />
              <span>{prev ? `${signed((hb.close / prev.close - 1) * 100)} on the day · ` : ""}volume {hb.volume == null ? DASH : hb.volume.toLocaleString(LOCALE[cur])}</span>
              {entriesThere || exitsThere ? <span><br />{entriesThere} {entriesThere === 1 ? "entry" : "entries"}, {exitsThere} {plural(exitsThere, "exit")}</span> : null}
            </>
          ) : null}
        </div>
      </>
    );
    legend = (
      <div className="chleg" aria-label="Chart legend">
        <span><i className="cu" />closed up</span>
        <span><i className="cd" />closed down</span>
        {g.fan80 ? (
          <>
            <span><i className="b8" />80% range</span>
            <span><i className="b5" />50% range</span>
            <span><i className="tg" />reference target per horizon (the tag on the axis = the selected one)</span>
            {g.spread ? <span><i className="sp" />all strategies’ targets at the selected horizon</span> : null}
          </>
        ) : null}
        {marks.entries.size || marks.exits.size ? (<><span><i className="tri en" />trade entry</span><span><i className="tri ex" />trade exit</span></>) : null}
        {marks.open.size ? <span><i className="tri en" style={{ borderBottomColor: "var(--md-sys-color-outline)" }} />open trade entry</span> : null}
        <span className="muted">D = the session being predicted{g.fan80 ? ", +k = the N+k exit session" : ""}. Volume below the candles. Research only.</span>
      </div>
    );
  }
  return (
    <Card label="Price chart">
      {head}
      <div className="chart" ref={hostRef}>{body}</div>
      {legend}
    </Card>
  );
}
