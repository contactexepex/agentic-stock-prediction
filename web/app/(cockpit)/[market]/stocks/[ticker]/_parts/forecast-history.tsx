"use client";
// The company page's forecast history (owner, 2026-10-10; B12's rm.stock `forecast_history`): for the selected
// horizon, every stored ranges.py run and signal-model run of the last 10 as-of dates. Above, a chart over the runs'
// times: the 80% and 50% ranges as bands, the target and the base close (the price the run started from), then P(up)
// against the 50% line. Below, one line per run, newest first: what changed since the run before and, opened, how its
// numbers were made. Every point is focusable and reads its run. Logic: lib/company-pages/history-logic.ts.
import { useMemo } from "react";
import { HorizonTabs } from "../../../../../../components/ui/controls.tsx";
import { Card, CardHead } from "../../../../../../components/ui/primitives.tsx";
import { fmtDate, offsetMinutes, pct, price, signed } from "../../../../../../lib/ui/format.ts";
import {
  centreMovePct, historyAt, historyEntries, historyGeometry, rangeChangeWords, scoreChangeWords, scoreParts, type HistoryEntry,
} from "../../../../../../lib/company-pages/history-logic.ts";
import type { CompanyPayload, HistoryRange, HistoryScore } from "../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "./context.ts";
import { useWidth } from "./price-chart.tsx";

const SHOWN = 6;

function RangeHow({ r, ctx }: { r: HistoryRange; ctx: PageCtx }) {
  const cur = ctx.currency, move = centreMovePct(r);
  return (
    <ul className="fh-how">
      <li>Target {price(cur, r.target_price)} = base close {price(cur, r.base_close)} (the {fmtDate(r.as_of_date)} close){move == null ? "" : ` moved by its centre ${signed(move)}`}; exit at the close of {fmtDate(r.exit_date)}, entry at the open of {fmtDate(r.session_date)}.</li>
      <li>50% range {price(cur, r.lo50)}–{price(cur, r.hi50)}, 80% range {price(cur, r.lo80)}–{price(cur, r.hi80)}{r.sigma_h == null ? "" : `; spread over the horizon (σ) ${(r.sigma_h * 100).toFixed(2)}%`}.</li>
      <li>Regime {r.regime ?? "not stored"} · calibration {r.calibration_id ?? "not stored"}{r.inputs.length ? ` · inputs ${r.inputs.join(", ")}` : ""}{r.notes.length ? ` · notes: ${r.notes.join("; ")}` : ""}.</li>
    </ul>
  );
}

function ScoreHow({ s }: { s: HistoryScore }) {
  const { base, parts, sum } = scoreParts(s);
  const drivers = [...s.drivers_up, ...s.drivers_down].map((d) => d.text || `${d.feature} ${signed(d.points, 2, " pts")}`);
  return (
    <ul className="fh-how">
      <li>
        P(up) {pct(s.prob_up, 1)}{base == null ? "" : ` = base rate ${pct(base, 1)}${parts.map(([g, v]) => ` ${v < 0 ? "−" : "+"} ${Math.abs(v).toFixed(2)} pts ${g}`).join("")}${sum == null ? "" : ` (${sum.toFixed(1)}% from the stored, rounded points)`}`}.
        {s.prob_model != null ? ` Without news ${pct(s.prob_model, 1)}.` : ""}
      </li>
      <li>
        News: {s.news_items ?? 0} {s.news_items === 1 ? "item" : "items"} counted{s.news_score != null ? `, score ${signed(s.news_score, 2, "")}` : ""}.
        {drivers.length ? ` Strongest drivers: ${drivers.join("; ")}.` : " No driver of 0.05 pts or more."}
      </li>
      <li>Model {s.model_version ?? "not stored"}{s.model_id ? ` (${s.model_id})` : ""}{s.trained_until ? `, trained until ${fmtDate(s.trained_until, false)} ${s.trained_until.slice(0, 4)}` : ""}; window {fmtDate(s.entry_date)} open to {fmtDate(s.exit_date)} close.</li>
    </ul>
  );
}

function RunLine({ e, ctx }: { e: HistoryEntry; ctx: PageCtx }) {
  const cur = ctx.currency;
  const head = e.kind === "range"
    ? `Range · target ${price(cur, e.row.target_price)}, 80% ${price(cur, e.row.lo80)}–${price(cur, e.row.hi80)}`
    : `Score · P(up) ${pct(e.row.prob_up, 1)}`;
  const words = e.kind === "range" ? rangeChangeWords(e) : scoreChangeWords(e);
  return (
    <li className={"fh-run " + e.kind}>
      <span className="fh-when">{ctx.at(e.at, true)}<small>as of the {fmtDate(e.row.as_of_date, false)} close</small></span>
      <div className="fh-what">
        <b>{head}</b>
        <span className="fh-chg">{words.join(" · ")}</span>
        <details>
          <summary>How it was calculated</summary>
          {e.kind === "range" ? <RangeHow r={e.row} ctx={ctx} /> : <ScoreHow s={e.row} />}
        </details>
      </div>
    </li>
  );
}

export function ForecastHistoryCard({ p, ctx, horizon, onHorizon }: { p: CompanyPayload; ctx: PageCtx; horizon: number; onHorizon: (k: number) => void }) {
  const cur = ctx.currency;
  const [hostRef, width] = useWidth<HTMLDivElement>();
  const { ranges, scores } = useMemo(() => historyAt(p.forecast_history, horizon), [p.forecast_history, horizon]);
  const entries = useMemo(() => historyEntries(ranges, scores), [ranges, scores]);
  const g = useMemo(() => historyGeometry(ranges, scores, width, offsetMinutes(p.status.session.local_time)), [ranges, scores, width, p.status.session.local_time]);
  const head = (
    <CardHead
      title="Forecast history: how each run changed"
      help="Every stored run of the last 10 as-of dates at the selected horizon: the published range (ranges.py: the target, the 50% and 80% ranges and the close it started from) and the signal model’s chance of a rise, P(up). Each line says what changed since the run before; open it to see how the numbers were made. A range or score run again for the same close is a revision. History only: it says how the forecast moved, not whether it was right."
      end={<HorizonTabs horizons={p.horizons} value={horizon} onChange={onHorizon} />}
    />
  );
  if (!p.forecast_history) {
    return <Card label="Forecast history">{head}<div className="quiet">No forecast history in this page yet; it arrives with the next page build.</div></Card>;
  }
  if (!entries.length) {
    return <Card label="Forecast history">{head}<div className="quiet">No range or score run stored for this company at N+{horizon} in the last 10 as-of dates.</div></Card>;
  }
  const recent = entries.slice(0, SHOWN), earlier = entries.slice(SHOWN);
  let chart = null;
  if (g) {
    const { W, H, L, R, T, PH, QT, QH } = g;
    const right = W - R;
    chart = (
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
        aria-label={`${p.company.name} at N+${horizon}: ${ranges.length} range ${ranges.length === 1 ? "run" : "runs"} and ${scores.length} score ${scores.length === 1 ? "run" : "runs"} over the last 10 as-of dates. Tab to each point to read its run; the list below says the same.`}>
        {PH ? (
          <g className="fh-price">
            <g className="grid">{g.priceTicks.map((v) => <line key={v} x1={L} x2={right} y1={g.py(v)} y2={g.py(v)} />)}</g>
            {g.band80 ? <polygon className="b80" points={g.band80} /> : null}
            {g.band50 ? <polygon className="b50" points={g.band50} /> : null}
            <polyline className="base" points={g.base.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ")} />
            <polyline className="tl" points={g.target.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ")} />
            {ranges.map((r, i) => (
              <g key={`${r.id}@${r.made_at}`}>
                <rect className="bs" x={g.base[i].x - 3} y={g.base[i].y - 3} width={6} height={6} />
                <circle className="tg" cx={g.target[i].x} cy={g.target[i].y} r={4} tabIndex={0} role="img"
                  aria-label={`Range run ${ctx.at(r.made_at, true)}: target ${price(cur, r.target_price)}, 50% ${price(cur, r.lo50)}–${price(cur, r.hi50)}, 80% ${price(cur, r.lo80)}–${price(cur, r.hi80)}, from the close ${price(cur, r.base_close)}.`}
                  data-tip={`${ctx.at(r.made_at, true)} · target ${price(cur, r.target_price)} · 80% ${price(cur, r.lo80)}–${price(cur, r.hi80)} · close ${price(cur, r.base_close)}${r.change?.target_pct != null ? ` · target ${signed(r.change.target_pct)}` : ""}`} />
              </g>
            ))}
            <g className="ax">
              {g.priceTicks.map((v) => <text key={v} x={right + 6} y={g.py(v) + 4}>{price(cur, v)}</text>)}
              <text className="ttl" x={L} y={T + 10}>Price</text>
            </g>
          </g>
        ) : null}
        {QH ? (
          <g className="fh-prob">
            <g className="grid">{g.probTicks.map((v) => <line key={v} x1={L} x2={right} y1={g.qy(v)} y2={g.qy(v)} />)}</g>
            <line className="half" x1={L} x2={right} y1={g.half} y2={g.half} />
            <polyline className="pl" points={g.prob.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ")} />
            {scores.filter((s) => s.prob_up != null).map((s, i) => (
              <circle key={`${s.id}@${s.computed_at}`} className="pp" cx={g.prob[i].x} cy={g.prob[i].y} r={3.5} tabIndex={0} role="img"
                aria-label={`Score run ${ctx.at(s.computed_at, true)}: P(up) ${pct(s.prob_up, 1)}${s.change?.prob_up != null ? `, ${signed(s.change.prob_up * 100, 1, " points")}` : ""}.`}
                data-tip={`${ctx.at(s.computed_at, true)} · P(up) ${pct(s.prob_up, 1)}${s.change?.prob_up != null ? ` (${signed(s.change.prob_up * 100, 1, " pts")})` : ""} · ${s.news_items ?? 0} news`} />
            ))}
            <g className="ax">
              {g.probTicks.map((v) => <text key={v} x={right + 6} y={g.qy(v) + 4}>{pct(v)}</text>)}
              <text className="ttl" x={L} y={QT + 10}>P(up)</text>
            </g>
          </g>
        ) : null}
        <g className="ax">{g.days.map((d) => <text key={d.label} x={d.x} y={H - 6} textAnchor="middle">{d.label}</text>)}</g>
      </svg>
    );
  }
  return (
    <Card label="Forecast history">
      {head}
      <div className="chart fh-chart" ref={hostRef}>{chart}</div>
      <div className="chleg" aria-label="Forecast history legend">
        {ranges.length ? (
          <>
            <span><i className="b8" />80% range</span>
            <span><i className="b5" />50% range</span>
            <span><i className="tg" />target</span>
            <span><i className="fh-bs" />close the run started from</span>
          </>
        ) : <span className="muted">No range run at N+{horizon} in the window.</span>}
        {scores.length ? <span><i className="fh-pp" />P(up), dashed line = 50%</span> : <span className="muted">No score run at N+{horizon} in the window.</span>}
      </div>
      <ol className="fh-runs" aria-label={`Runs at N+${horizon}, newest first`}>
        {recent.map((e) => <RunLine key={`${e.kind}:${e.row.id}@${e.at}`} e={e} ctx={ctx} />)}
      </ol>
      {earlier.length ? (
        <details className="fh-more">
          <summary>Earlier runs ({earlier.length})</summary>
          <ol className="fh-runs">{earlier.map((e) => <RunLine key={`${e.kind}:${e.row.id}@${e.at}`} e={e} ctx={ctx} />)}</ol>
        </details>
      ) : null}
    </Card>
  );
}
