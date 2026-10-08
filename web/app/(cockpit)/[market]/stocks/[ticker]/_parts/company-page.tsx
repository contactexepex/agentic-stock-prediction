"use client";
// Page 03, Company (design/mockups/03-company/, SPEC section 6 page 3): one company's day in the order the investor
// asks it — where it stands, the chart with today's targets and ranges, the open paper trades, the settled ones and
// why they moved, the analyst's words, news with status, results, what is coming and the watchlist settings. Reads
// GET /api/v1/markets/{market}/stocks/{ticker} (B12, rm.stock). Research only: every signal is Paper, nothing trades.
import { useState } from "react";
import { PageFooter, PageHead, SignalsBand } from "../../../../../../components/blocks/page-head.tsx";
import { PageState } from "../../../../../../components/ui/states.tsx";
import { MARKET_LABEL } from "../../../../../../lib/ui/constants.ts";
import { fmtDate } from "../../../../../../lib/ui/format.ts";
import { usePage } from "../../../../../../lib/ui/use-api.ts";
import type { Market } from "../../../../../../lib/data/constants.ts";
import { lifecycleDates } from "../../../../../../lib/company-pages/company-logic.ts";
import type { CompanyPayload } from "../../../../../../lib/company-pages/types.ts";
import { Icon } from "../../../../../../components/ui/icon.tsx";
import { CommandDialog, type Intent, type Recorded } from "../../../companies/_parts/command-dialog.tsx";
import { EventsCard, NewsCard, ReasonsCard, ResultsCard, WatchlistCard } from "./cards.tsx";
import { pageCtx } from "./context.ts";
import { CompanyLine, DecisionCard } from "./decision.tsx";
import { CompanyLegend } from "./legend.tsx";
import { PriceChart } from "./price-chart.tsx";
import { OpenTradesTable, SettledCard } from "./trades.tsx";
import "./company.css";

function CompanyBody({ p }: { p: CompanyPayload }) {
  const ctx = pageCtx(p);
  const opening = typeof p.default_horizon === "number" ? p.default_horizon : p.horizons[0] ?? 1;
  const [horizon, setHorizon] = useState<number>(opening);
  const co = p.company;
  const dates = lifecycleDates(p.bars, p.status.session.session_date);
  // Change amount / Deactivate / Reactivate: B14's confirm dialog on B11's routes (the server's summary, then Confirm;
  // one Idempotency-Key per opening, so each opening is mounted with a new key). Pending until the next run imports it.
  const [intent, setIntent] = useState<Intent | null>(null);
  const [openings, setOpenings] = useState(0);
  const [recorded, setRecorded] = useState<Recorded[]>([]);
  const open = (kind: "amount" | "deactivate" | "reactivate") => { setOpenings((n) => n + 1); setIntent({ kind, company: co }); };
  const buttons = (
    <>
      <button className="md-btn outlined small" type="button" onClick={() => open("amount")}><Icon name="account_balance_wallet" />Change amount</button>
      {co.state === "active"
        ? <button className="md-btn outlined small" type="button" onClick={() => open("deactivate")}><Icon name="pending" />Deactivate</button>
        : <button className="md-btn outlined small" type="button" onClick={() => open("reactivate")}><Icon name="check" />Reactivate</button>}
    </>
  );
  const pending = recorded.length ? (
    <div className="pend">
      {recorded.map((r, i) => (
        <div className="mb-alert" key={i} style={{ padding: "10px 14px" }} role="status">
          <Icon name="pending" />
          <div><b className="t">{r.result === "duplicate" ? "Already requested" : "Pending"}: {r.summary}</b><div className="s">Recorded as a request; the next run imports it (F10). Nothing is bought or sold.</div></div>
        </div>
      ))}
    </div>
  ) : null;
  return (
    <>
      <PageHead
        page={p}
        title={`${co.ticker} · ${co.name}`}
        subtitle={`${co.sector ?? "sector not set"} · ${p.name} · data as of the ${fmtDate(p.as_of, false)} close · research only, nothing here trades`}
      />
      <CompanyLine p={p} ctx={ctx} actions={buttons} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      <DecisionCard p={p} ctx={ctx} horizon={horizon} onHorizon={setHorizon} />
      <PriceChart p={p} ctx={ctx} horizon={horizon} />
      <div style={{ marginTop: 16 }}><OpenTradesTable p={p} ctx={ctx} /></div>
      <div style={{ marginTop: 16 }}><SettledCard settled={p.settled} ctx={ctx} paperLabel={p.status.paper_label} ticker={co.ticker} /></div>
      <div className="grid even">
        <div className="col">
          <ReasonsCard reasons={p.reasons} news={p.news} ctx={ctx} />
          <ResultsCard p={p} ctx={ctx} />
          <WatchlistCard p={p} ctx={ctx} onChangeAmount={() => open("amount")} pending={pending} historyDates={dates} />
        </div>
        <div className="col">
          <NewsCard p={p} ctx={ctx} />
          <EventsCard p={p} />
        </div>
      </div>
      <CompanyLegend />
      <PageFooter page={p} endpoint={`stocks/${co.ticker}`} />
      {intent ? (
        <CommandDialog key={openings} intent={intent} market={ctx.market} currency={ctx.currency} defaultAmount={co.amount ?? 0} /* read only by the dialog's add intent, which this page never opens */
          onClose={() => setIntent(null)} onRecorded={(r) => setRecorded((list) => [...list, r])} onSwitch={(next) => { setOpenings((n) => n + 1); setIntent(next); }} />
      ) : null}
    </>
  );
}

export function CompanyPage({ market, ticker }: { market: Market; ticker: string }) {
  const res = usePage<CompanyPayload>(market, "stocks/{ticker}", { ticker });
  return (
    <PageState result={res} loadingLabel={`Loading ${ticker} (${MARKET_LABEL[market]})`}>
      {(p) => <CompanyBody key={`${p.market}/${p.ticker}`} p={p} />}
    </PageState>
  );
}
