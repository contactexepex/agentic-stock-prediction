"use client";
// The company page's two trade tables (design/mockups/03-company openTrades, settled): today's path of every open
// paper trade with its latest intraday check (F5), and the settled trades newest first with the automatic reason
// split as a diverging "why" bar (F1.9-F1.10, decision 43). Monitoring and records only; nothing is traded.
import { strategyOf } from "../../../../../../components/blocks/records.tsx";
import { RangeBar } from "../../../../../../components/charts/small.tsx";
import { Icon } from "../../../../../../components/ui/icon.tsx";
import { Card, CardHead, Delta, FamilyLabel, GoLink, Label, MoneyDelta, PaperTag, Quiet } from "../../../../../../components/ui/primitives.tsx";
import { DataTable, type Column } from "../../../../../../components/ui/table.tsx";
import { BAND, BAND_SHORT, FAMILY_SHORT, FLAG, FLAG_SHORT, PICK_RULE } from "../../../../../../lib/ui/constants.ts";
import { fmtDate, money, pct, price, signed } from "../../../../../../lib/ui/format.ts";
import { stockStrategiesPath } from "../../../../../../lib/ui/routes.ts";
import { bandsOf, isSettled, settledSummary, whyScale, whySegments } from "../../../../../../lib/company-pages/company-logic.ts";
import type { CompanyPayload, OpenTrade, SettledTrade, TradeCheck } from "../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "./context.ts";
import { plural, reasonWords } from "./labels.ts";

function StrategyCell({ id, sub, ctx }: { id: string; sub: string; ctx: PageCtx }) {
  const st = strategyOf(ctx.strategies, id);
  return (
    <span className="nm">
      <b>{st.name} <FamilyLabel family={st.family}>{FAMILY_SHORT[st.family] ?? st.family}</FamilyLabel></b>
      <small>{sub}</small>
    </span>
  );
}

function CheckCell({ check, ctx }: { check: TradeCheck | undefined; ctx: PageCtx }) {
  if (!check) return <span className="st muted" data-tip="No intraday check stored for this trade by the cut-off.">—</span>;
  const [bandWords, bandClass] = BAND[check.band] ?? [check.band, ""];
  const flags = check.flags.map((f) => FLAG[f] ?? f);
  const tip =
    `${ctx.at(check.check_at)}: ${price(ctx.currency, check.last_price)}, ${signed(check.ret_since_entry_pct)} since entry, ${bandWords}` +
    (flags.length ? `; ${flags.join(", ")}` : "") +
    `. Best so far ${signed(check.high_since_entry_pct)}, worst ${signed(check.low_since_entry_pct)}` +
    (check.target_reached ? `; target reached in session ${check.target_reached_session}` : "") + ".";
  return (
    <>
      <span className={`st ${check.flagged ? "flag" : bandClass}`} data-tip={tip}>
        <Icon name={check.flagged ? "warning" : "check"} />
        {check.flagged ? check.flags.map((f) => FLAG_SHORT[f] ?? f).join(", ") : BAND_SHORT[check.band] ?? check.band}
      </span>
      <small className="muted" style={{ display: "block", fontSize: 11 }}>at {price(ctx.currency, check.last_price)} · {signed(check.ret_since_entry_pct)} since entry</small>
    </>
  );
}

export function OpenTradesTable({ p, ctx }: { p: CompanyPayload; ctx: PageCtx }) {
  const rows = p.open_trades, check0 = p.trade_checks[0];
  const checks = new Map(p.trade_checks.map((c) => [c.trade_id, c]));
  const cur = ctx.currency;
  const columns: Column<OpenTrade>[] = [
    { key: "strategy", header: "Strategy", render: (r) => <StrategyCell id={r.strategy_id} ctx={ctx} sub={r.view === "head_to_head" ? "head-to-head pick" : "accuracy view"} /> },
    { key: "horizon", header: "Horizon", render: (r) => (<><span className="h-lab">N+{r.horizon_days}</span><small className="muted cw" style={{ whiteSpace: "nowrap" }}> {fmtDate(r.entry_date, false)} → {fmtDate(r.exit_date, false)}</small></>) },
    { key: "entry", header: "Entry", numeric: true, className: "cw", render: (r) => price(cur, r.entry_price) },
    { key: "last", header: "Last", numeric: true, className: "cw", render: (r) => <span data-tip={`Latest stored close (${fmtDate(r.last_price_date)}); unrealised and the distance to the target are measured at it.`}>{price(cur, r.last_price)}</span> },
    { key: "unrealised", header: "Unrealised", numeric: true, render: (r) => (<><MoneyDelta currency={cur} value={r.unrealised_pnl} decimals={ctx.decimals} /><span className="cw"> <Delta value={r.unrealised_pct} /></span></>) },
    { key: "range", header: "Predicted range", className: "cm", render: (r) => { const b = bandsOf(r); return b ? <RangeBar currency={cur} bands={b} last={r.last_price} entry={r.entry_price} /> : <span className="muted">—</span>; } },
    { key: "target", header: "To target", numeric: true, className: "cw", render: (r) => r.to_target_pct == null ? <span className="muted">—</span> : (
      <span data-tip={r.to_target_pct < 0 ? `Already past the target ${price(cur, r.target_price)}.` : `${signed(r.to_target_pct)} to the target ${price(cur, r.target_price)}.`}>{r.to_target_pct < 0 ? "past target" : signed(r.to_target_pct)}</span>) },
    { key: "check", header: "Check", render: (r) => <CheckCell check={checks.get(r.trade_id)} ctx={ctx} /> },
  ];
  return (
    <Card label="Today’s path">
      <CardHead
        title={<>Today’s path: open paper trades <PaperTag label={p.status.paper_label} /></>}
        help="Every paper trade on this company that has entered and not yet exited (bought at the open of its entry session). Last, unrealised and the distance to the target are at the latest stored close; the check column has the latest intraday check at its own price: where that price sits in the trade’s own predicted range and whether it is flagged (outside the range, far from the target, against the prediction). Monitoring only; nothing is traded."
        end={check0 ? `checked ${ctx.at(check0.check_at)}${check0.session_number != null ? ` · session ${check0.session_number} of the window` : ""}` : rows.length ? "no intraday check yet today" : undefined}
      />
      {rows.length ? (
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.trade_id} label="Open paper trades" className="ot" />
      ) : (
        <Quiet>{p.company.state === "active" ? "No open paper trade on this company." : "No open paper trade; inactive companies get no new ones."}</Quiet>
      )}
    </Card>
  );
}

const WHY_CLASS = { market: "m", sector: "s", news: "n", company: "co" } as const;

function WhyBar({ t, scale }: { t: SettledTrade; scale: number }) {
  const parts = [["market", t.market_pct], ["sector", t.sector_pct], ["news", t.news_pct], ["company", t.company_pct]] as const;
  return (
    <svg viewBox="0 0 110 14" role="img" aria-label={`move ${signed(t.move_pct)}: ` + parts.map(([k, v]) => `${k} ${signed(v)}`).join(", ")}>
      <line className="z" x1={55} x2={55} y1={1} y2={13} />
      {whySegments(t, scale).map((s) => <rect key={s.key} className={WHY_CLASS[s.key]} x={s.x} y={3} width={s.width} height={8} rx={1} />)}
    </svg>
  );
}

function skippedWords(skipped: SettledTrade[], cur: string): string {
  return [...new Set(skipped.map((t) => t.status))]
    .map((s) => s === "skipped_price_above_amount"
      ? `one share (${price(cur, skipped.find((t) => t.status === s)?.entry_price)}) costs more than the ${money(cur, skipped.find((t) => t.status === s)?.amount)} amount; raise the amount with "Change amount"`
      : s.replace(/_/g, " "))
    .join("; ");
}

/** Settled trades with the summary strip and the "why" bars; `settled` is the company's (page 03) or one session's
 *  (the call history). */
export function SettledCard({ settled, ctx, paperLabel, ticker }: { settled: SettledTrade[]; ctx: PageCtx; paperLabel: string; ticker: string }) {
  const cur = ctx.currency, rows = settled.filter(isSettled), skipped = settled.filter((t) => !isSettled(t));
  const sum = settledSummary(settled), scale = whyScale(rows);
  const columns: Column<SettledTrade>[] = [
    { key: "exit", header: "Exit", render: (t) => (<>{fmtDate(t.exit_date_actual ?? t.exit_date, false)}{t.flags.length ? <small className="muted" data-tip={t.flags.join(", ")}> *</small> : null}</>) },
    { key: "strategy", header: "Strategy", render: (t) => <StrategyCell id={t.strategy_id} ctx={ctx} sub={t.view === "head_to_head" ? `head-to-head · ${PICK_RULE[t.pick_rule ?? ""] ?? t.pick_rule ?? "pick"}` : "accuracy view"} /> },
    { key: "horizon", header: "Horizon", render: (t) => <span className="h-lab">N+{t.horizon_days}</span> },
    { key: "prices", header: "Entry → exit", numeric: true, className: "cw", render: (t) => (
      <span data-tip={`Bought ${t.quantity ?? "—"} ${plural(t.quantity ?? 0, "share")} at the open of ${fmtDate(t.entry_date)}, sold at the close of ${fmtDate(t.exit_date_actual ?? t.exit_date)}; chance given ${pct(t.prob_up, 1)}, target ${price(cur, t.target_price)} (${t.target_reached ? `reached in session ${t.target_reached_session}` : "not reached"}), best ${signed(t.max_favourable_pct)}, worst ${signed(t.max_adverse_pct)}.`}>
        {price(cur, t.entry_price)} → {price(cur, t.exit_price)}
      </span>) },
    { key: "net", header: "Net after costs", numeric: true, className: "pn", render: (t) => (
      <span data-tip={`Gross ${money(cur, t.gross_pnl, ctx.decimals, true)}, costs ${money(cur, t.costs, ctx.decimals)} → net ${money(cur, t.net_pnl, ctx.decimals, true)} on ${money(cur, t.amount)} (${signed(t.return_pct)}). Move ${signed(t.move_pct)}.`}>
        <b><MoneyDelta currency={cur} value={t.net_pnl} decimals={ctx.decimals} /></b>
        <small>{signed(t.return_pct)}</small>
      </span>) },
    { key: "why", header: "Why it moved", className: "cm", render: (t) => {
      const main = reasonWords(t.reason_code);
      const also = t.reason_codes.filter((c) => c !== t.reason_code).map((c) => reasonWords(c)[0]).join(", ");
      const d = t.reason_detail ?? {};
      const tip = `Move ${signed(t.move_pct)} = market ${signed(t.market_pct)} (${d.benchmark ?? "benchmark"} × beta ${d.beta ?? "—"}) + sector ${signed(t.sector_pct)} (${d.sector_source ?? "sector"}) + news ${signed(t.news_pct)} + company ${signed(t.company_pct)}. Main cause: ${main[0]}${also ? `; also ${also}` : ""}. ${main[1]}`;
      return <span className="why" data-tip={tip}><WhyBar t={t} scale={scale} /><Label tone="neutral">{main[0]}</Label></span>;
    } },
  ];
  return (
    <Card label="Settled paper trades">
      <CardHead
        title={<>Settled results and why each moved <PaperTag label={paperLabel} /></>}
        help="Every paper trade on this company that has exited, newest first, both views (accuracy: one trade per qualifying prediction; head-to-head: the daily picks). Net = profit after the market-cost charges of config/costs.yaml. “Why” splits the move into what the market explains (beta × benchmark), the sector beyond the market, verified news inside the window, and what is left for the company (F1.10, decision 43): bars to the right of the centre line pushed the price up, to the left down."
        end={<GoLink href={stockStrategiesPath(ctx.market, ticker)}>By strategy</GoLink>}
      />
      {rows.length ? (
        <>
          <div className="sumrow">
            <div><b>{sum.trades}</b><span>settled trades</span></div>
            <div><b>{sum.won} of {sum.trades}</b><span>made money after costs</span></div>
            <div><b><MoneyDelta currency={cur} value={sum.net} decimals={ctx.decimals} /></b><span>net after costs, all strategies</span></div>
            <div><b>{sum.reached} of {sum.trades}</b><span>reached the target</span></div>
            <div><b>{sum.inRange} of {sum.trades}</b><span>exited inside the 80% range</span></div>
          </div>
          <DataTable columns={columns} rows={rows} rowKey={(t) => t.id} label="Settled paper trades" className="sd" />
          <div className="chleg">
            <span>Why bars: </span>
            <span><i className="sw r" />market</span>
            <span><i className="sw b" />sector</span>
            <span><i className="sw a" />news</span>
            <span><i className="sw k" />company</span>
            <span className="muted">right of the centre = pushed up, left = pushed down; the parts add up to the move</span>
            {skipped.length ? <span className="muted">· {skipped.length} {plural(skipped.length, "prediction")} skipped ({[...new Set(skipped.map((t) => t.status.replace(/_/g, " ")))].join(", ")})</span> : null}
          </div>
        </>
      ) : (
        <Quiet>{skipped.length ? `No settled trade yet. ${skipped.length} predictions could not become trades: ${skippedWords(skipped, cur)}.` : "No settled paper trade yet."}</Quiet>
      )}
    </Card>
  );
}
