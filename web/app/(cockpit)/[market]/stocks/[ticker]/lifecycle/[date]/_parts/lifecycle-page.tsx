"use client";
// Page 03's call history for one session D (SPEC section 2 "Lifecycle of a prediction": made -> checks -> settled ->
// explained; no mockup of its own, built from the 03 mockup's parts): every prediction made for D on this company with
// its path, the head-to-head picks of D, every intraday check of those trades, their settlements with the "why" split
// and the analyst's notes. Reads GET .../stocks/{ticker}/lifecycle/{date} (B12, rm.lifecycle) and the company page
// (status, names, the dates around D). Research only: every signal is Paper, nothing trades.
import Link from "next/link";
import { CostLabels } from "../../../../../../../../components/blocks/costs.tsx";
import { PageFooter, PageHead, SignalsBand } from "../../../../../../../../components/blocks/page-head.tsx";
import { strategyOf } from "../../../../../../../../components/blocks/records.tsx";
import { RangeBar } from "../../../../../../../../components/charts/small.tsx";
import { Icon } from "../../../../../../../../components/ui/icon.tsx";
import { Card, CardHead, FamilyLabel, Label, MoneyDelta, Odds, PaperTag, Quiet } from "../../../../../../../../components/ui/primitives.tsx";
import { ErrorState, LoadingState, PageState } from "../../../../../../../../components/ui/states.tsx";
import { DataTable, type Column } from "../../../../../../../../components/ui/table.tsx";
import { BAND, BAND_SHORT, FAMILY_SHORT, FLAG, FLAG_SHORT, MARKET_LABEL, PICK_RULE } from "../../../../../../../../lib/ui/constants.ts";
import { fmtDate, fmtDateYear, pct, price, signed } from "../../../../../../../../lib/ui/format.ts";
import { companyPath, lifecyclePath } from "../../../../../../../../lib/ui/routes.ts";
import { usePage } from "../../../../../../../../lib/ui/use-api.ts";
import type { Market } from "../../../../../../../../lib/data/constants.ts";
import { bandsOf, isSettled, lifecycleDates, predictionPaths, type PredictionPath } from "../../../../../../../../lib/company-pages/company-logic.ts";
import { expectedGainMoney } from "../../../../../../../../lib/company-pages/strategies-logic.ts";
import type { CompanyPayload, HeadToHeadPick, LifecyclePayload, TradeCheck } from "../../../../../../../../lib/company-pages/types.ts";
import { ReasonsCard } from "../../../_parts/cards.tsx";
import { CheckState, StrategyCell } from "../../../_parts/cells.tsx";
import { pageCtx, type PageCtx } from "../../../_parts/context.ts";
import { plural } from "../../../_parts/labels.ts";
import { SettledCard } from "../../../_parts/trades.tsx";
import "../../../_parts/company.css";
import "./lifecycle.css";

/** The path of one call in words: made, checked, settled, explained (each step says when it has not happened yet). */
function PathCell({ path, ctx }: { path: PredictionPath; ctx: PageCtx }) {
  const done = path.settled.filter(isSettled), net = done.reduce((s, t) => s + (t.net_pnl ?? 0), 0), last = path.checks[0];
  const notTraded = !path.prediction.qualifies && !path.settled.length && !path.checks.length;
  return (
    <span className="path">
      <span className="step on" data-tip={`Made ${ctx.at(path.prediction.made_at, true)}.`} tabIndex={0}><Icon name="check" />made</span>
      {notTraded ? <span className="step muted">no trade ({path.prediction.direction === "down" ? "a down call" : "below its bar"})</span> : (
        <>
          <span className={"step" + (path.checks.length ? " on" : "")} tabIndex={0} data-tip={path.checks.length ? `${path.checks.length} intraday ${plural(path.checks.length, "check")}; the latest ${ctx.at(last.check_at, true)}.` : "No intraday check of its trades stored yet."}>
            {path.checks.length ? <>{path.checks.length} {plural(path.checks.length, "check")}{last.flagged ? <Icon name="warning" /> : null}</> : "no check yet"}
          </span>
          <span className={"step" + (done.length ? " on" : "")}>
            {done.length ? <span tabIndex={0} data-tip={done.length > 1 ? `Net after costs of its ${done.length} settled trades together (${done.map((t) => t.view === "head_to_head" ? "head-to-head" : "accuracy view").join(" and ")}).` : `Net after costs of its ${done[0].view === "head_to_head" ? "head-to-head" : "accuracy-view"} trade.`}>settled <MoneyDelta currency={ctx.currency} value={net} decimals={ctx.decimals} /></span> : path.settled.length ? path.settled.map((t) => t.status.replace(/_/g, " ")).join(", ") : "not settled yet"}
          </span>
          <span className={"step" + (path.reasons.length ? " on" : "")}>{path.reasons.length ? `${path.reasons.length} ${plural(path.reasons.length, "note")}` : "no note"}</span>
        </>
      )}
    </span>
  );
}

function CallsCard({ day, ctx, paperLabel }: { day: LifecyclePayload; ctx: PageCtx; paperLabel: string }) {
  const paths = predictionPaths(day);
  const columns: Column<PredictionPath>[] = [
    { key: "strategy", header: "Strategy", render: (r) => <StrategyCell id={r.prediction.strategy_id} ctx={ctx} sub={`exit ${fmtDate(r.prediction.exit_date, false)}`} /> },
    { key: "call", header: "Call", render: (r) => (
      <span className="call">
        <span className="h-lab">N+{r.prediction.horizon_days}</span>
        {r.prediction.prob_up != null ? <Odds p={r.prediction.prob_up} /> : <span className="muted">{r.prediction.direction}</span>}
        {r.prediction.qualifies ? <Label tone="success" icon="check">would buy</Label> : <Label tone="neutral">{r.prediction.direction === "down" ? "down, no trade" : "no trade"}</Label>}
      </span>) },
    { key: "range", header: "Target and range", className: "cm", render: (r) => {
      const b = bandsOf(r.prediction);
      return b ? <span className="tgt">{price(ctx.currency, r.prediction.target_price)} <RangeBar currency={ctx.currency} bands={b} /></span> : <span className="muted">—</span>;
    } },
    { key: "path", header: "What became of it", render: (r) => <PathCell path={r} ctx={ctx} /> },
  ];
  return (
    <Card label="The calls made for this session">
      <CardHead title={<>The calls made for {fmtDate(day.session_date)} <PaperTag label={paperLabel} /></>}
        help="Every prediction made for this session on this company, by horizon then strategy: its chance of a rise and whether it would trade, its target and ranges, and its path: made before the open, checked during the holding window, settled after the exit close, explained by the end-of-day analyst. A down call or an up call below the strategy’s bar is scored but never traded."
        end={`${paths.length} ${plural(paths.length, "call")}`} />
      {paths.length ? <DataTable columns={columns} rows={paths} rowKey={(r) => r.prediction.id} label="Calls" className="lcy" /> : <Quiet>No prediction was made for this session on this company.</Quiet>}
    </Card>
  );
}

function PicksCard({ picks, ctx }: { picks: HeadToHeadPick[]; ctx: PageCtx }) {
  const columns: Column<HeadToHeadPick>[] = [
    { key: "family", header: "Family", render: (k) => <FamilyLabel family={k.family}>{FAMILY_SHORT[k.family]}</FamilyLabel> },
    { key: "rule", header: "Pick rule", render: (k) => PICK_RULE[k.pick_rule] ?? k.pick_rule },
    { key: "strategy", header: "Strategy", render: (k) => (k.status === "picked" ? <StrategyCell id={k.strategy_id} ctx={ctx} /> : <span className="muted">no candidate</span>) },
    { key: "pick", header: "Pick", render: (k) => k.status !== "picked" ? <span className="muted">—</span> : (
      <span className="call">
        <span className="h-lab">N+{k.horizon_days}</span>
        <Odds p={k.prob_up} />
        <MoneyDelta currency={ctx.currency} value={expectedGainMoney(k.expected_gain_pct, k.amount)} decimals={ctx.decimals} />
        <CostLabels currency={ctx.currency} pick={k} />
      </span>) },
  ];
  return (
    <Card label="Head-to-head picks">
      <CardHead title="Head-to-head picks of the session"
        help="The strongest rule strategy and the strongest AI trader each picked one horizon under two pick rules (decisions 41-42). Expected gain in money of the trade amount, after market costs; “viable at your cost” adds your own broker’s charges (decision 51)." />
      {picks.length ? <DataTable columns={columns} rows={picks} rowKey={(k) => k.id} label="Head-to-head picks" className="lcy" /> : <Quiet>No head-to-head pick stored for this session.</Quiet>}
    </Card>
  );
}

function ChecksCard({ checks, ctx }: { checks: TradeCheck[]; ctx: PageCtx }) {
  const rows = [...checks].sort((a, b) => b.check_at.localeCompare(a.check_at) || a.trade_id.localeCompare(b.trade_id));
  const columns: Column<TradeCheck>[] = [
    { key: "at", header: "Checked", render: (c) => ctx.at(c.check_at, true) },
    { key: "strategy", header: "Trade", render: (c) => <StrategyCell id={c.strategy_id ?? null} ctx={ctx} sub={`${c.view === "head_to_head" ? "head-to-head" : "accuracy view"}${c.horizon_days ? ` · N+${c.horizon_days}` : ""}${c.session_number != null ? ` · session ${c.session_number}` : ""}`} /> },
    { key: "price", header: "Price", numeric: true, className: "cm", render: (c) => price(ctx.currency, c.last_price) },
    { key: "since", header: "Since entry", numeric: true, render: (c) => signed(c.ret_since_entry_pct) },
    { key: "state", header: "Check", render: (c) => <CheckState check={c} ctx={ctx} withDate /> },
  ];
  return (
    <Card label="Intraday checks">
      <CardHead title="Checked during the holding window"
        help="Every intraday check of these calls’ paper trades, newest first: the price at the check, the move since entry, where it sat in the trade’s own predicted range and whether it was flagged (outside the range, far from the target, against the prediction). Monitoring only; nothing is traded." />
      {rows.length ? <DataTable columns={columns} rows={rows} rowKey={(c) => c.id ?? `${c.trade_id}@${c.check_at}`} label="Intraday checks" className="lcy" /> : <Quiet>No intraday check of these trades stored yet.</Quiet>}
    </Card>
  );
}

function DayNav({ ctx, ticker, date, dates }: { ctx: PageCtx; ticker: string; date: string; dates: string[] }) {
  const i = dates.indexOf(date), later = i > 0 ? dates[i - 1] : null, earlier = i >= 0 && i < dates.length - 1 ? dates[i + 1] : null;
  return (
    <nav className="daynav" aria-label="Other sessions">
      <Link className="md-btn text small" href={companyPath(ctx.market, ticker)}><Icon name="chevron_right" style={{ transform: "rotate(180deg)" }} />Company page</Link>
      {earlier ? <Link className="md-btn outlined small" href={lifecyclePath(ctx.market, ticker, earlier)}>Earlier: {fmtDate(earlier, false)}</Link> : null}
      {later ? <Link className="md-btn outlined small" href={lifecyclePath(ctx.market, ticker, later)}>Later: {fmtDate(later, false)}</Link> : null}
    </nav>
  );
}

function LifecycleBody({ p, day }: { p: CompanyPayload; day: LifecyclePayload }) {
  const ctx = pageCtx(p), co = p.company;
  const dates = lifecycleDates(p.bars, p.status.session.session_date, 30);
  return (
    <>
      <PageHead page={p} title={`${co.ticker} · calls for ${fmtDate(day.session_date)}`}
        subtitle={`${co.name} · ${p.name} · the predictions made for the session of ${fmtDateYear(day.session_date)} and what became of them · research only, nothing here trades`} />
      <DayNav ctx={ctx} ticker={co.ticker} date={day.session_date} dates={dates} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      <CallsCard day={day} ctx={ctx} paperLabel={p.status.paper_label} />
      <div style={{ marginTop: 16 }}><PicksCard picks={day.head_to_head} ctx={ctx} /></div>
      <div style={{ marginTop: 16 }}><ChecksCard checks={day.trade_checks} ctx={ctx} /></div>
      <div style={{ marginTop: 16 }}><SettledCard settled={day.settled} ctx={ctx} paperLabel={p.status.paper_label} ticker={co.ticker} /></div>
      <div style={{ marginTop: 16 }}><ReasonsCard reasons={day.reasons} news={p.news} ctx={ctx} /></div>
      <PageFooter page={p} endpoint={`stocks/${co.ticker}/lifecycle/${day.session_date}`} />
    </>
  );
}

export function LifecyclePage({ market, ticker, date }: { market: Market; ticker: string; date: string }) {
  const company = usePage<CompanyPayload>(market, "stocks/{ticker}", { ticker });
  const day = usePage<LifecyclePayload>(market, "stocks/{ticker}/lifecycle/{date}", { ticker, date });
  const label = `Loading ${ticker}’s calls for ${date} (${MARKET_LABEL[market]})`;
  if (day.state === "error") {
    const problem = day.problem.status === 404
      ? { ...day.problem, detail: "No call history is stored for this session: the history keeps the last 30 sessions of a collected company." }
      : day.problem;
    return <ErrorState problem={problem} onRetry={day.reload} />;
  }
  if (day.state === "loading") return <LoadingState label={label} />;
  return (
    <PageState result={company} loadingLabel={label}>
      {(p) => <LifecycleBody key={`${p.market}/${p.ticker}/${day.envelope.payload.session_date}`} p={p} day={day.envelope.payload} />}
    </PageState>
  );
}
