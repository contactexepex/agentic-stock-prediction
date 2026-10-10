"use client";
// Page 02, Watchlist (design/mockups/02-watchlist/): one row per active company at the selected horizon (N+1 first,
// decision 39): the last close and day move, how many strategies would buy and their average chance, the buyers at
// each horizon, the reference rule strategy's published range, and its open paper trades with the flagged checks.
// Sorting, the sector chips and the text filter are the page's own (lib/market-pages/watchlist.ts). Inactive companies
// are named under the table only (decision 13). Every signal is Paper; nothing here trades.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageFooter, PageHead, SignalsBand } from "../../../../../components/blocks/page-head.tsx";
import { AgreementCell, AgreementOdds, CompanyCell } from "../../../../../components/blocks/records.tsx";
import { HorizonBars, RangeBar } from "../../../../../components/charts/small.tsx";
import { HorizonTabs } from "../../../../../components/ui/controls.tsx";
import { FilterChips, SearchInput } from "../../../../../components/ui/filters.tsx";
import { HelpTip, Icon } from "../../../../../components/ui/icon.tsx";
import { Delta, Kpi, KpiRow, Label, MoneyDelta } from "../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import {
  agreementAt, defaultDirection, distinctFlags, filterRows, horizonWords, mostAgreed, sectorsOf, sortRows, sumMoney,
  watchlistRows, type SortKey, type WatchlistRow,
} from "../../../../../lib/market-pages/watchlist.ts";
import { FLAG } from "../../../../../lib/ui/constants.ts";
import { fmtDate, fmtLocal, moneyDecimals, pct, price } from "../../../../../lib/ui/format.ts";
import { companyPath, pagePath, stockStrategiesPath } from "../../../../../lib/ui/routes.ts";
import type { AgreementMap, CompanyRecord, GoLive, OpenTrade, PageBase, StrategyMap, TradeCheck } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import "./watchlist.css";

export interface PredictionRange {
  id: string; ticker: string; horizon_days: number; target_price: number | null;
  lo50: number | null; hi50: number | null; lo80: number | null; hi80: number | null;
}
export type WatchlistPayload = PageBase & {
  horizons: number[];
  default_horizon: number;
  go_live: GoLive;
  companies: (CompanyRecord & { sector: string; last_close: number | null; change_pct: number | null })[];
  agreement: AgreementMap;
  open_trades: OpenTrade[];
  trade_checks: (TradeCheck & { ticker: string })[];
  ranges: PredictionRange[];
  /** ranges.py's published range per active company and horizon for the as-of date, shown whether or not a strategy
   *  is live (B11; the Range column). Absent in older payloads: read as none. */
  published_ranges?: PublishedRange[];
  strategies: StrategyMap;
};
export interface PublishedRange {
  ticker: string; horizon_days: number; base_close: number | null; target_price: number | null;
  lo50: number | null; hi50: number | null; lo80: number | null; hi80: number | null;
}
type Row = WatchlistRow<WatchlistPayload["companies"][number], PublishedRange>;

const bandsOf = (r: PublishedRange | null) =>
  r && r.lo80 != null && r.lo50 != null && r.hi50 != null && r.hi80 != null && r.target_price != null
    ? { lo80: r.lo80, lo50: r.lo50, hi50: r.hi50, hi80: r.hi80, target_price: r.target_price } : null;

function Kpis({ p, market, rows, horizon }: { p: WatchlistPayload; market: Market; rows: Row[]; horizon: number }) {
  const cur = p.currency, lt = p.status.session.local_time;
  const lead = mostAgreed(rows);
  const inactive = p.companies.filter((c) => c.state !== "active").length;
  const unreal = sumMoney(p.open_trades.map((t) => t.unrealised_pnl));
  const flagged = p.trade_checks.filter((c) => c.flagged).length;
  return (
    <KpiRow>
      <Kpi icon="apartment" label="Companies followed" value={String(rows.length)}
        sub={inactive ? <span>{`${inactive} inactive on the `}<Link href={pagePath(market, "companies")}>Companies page</Link></span> : "all active"}
        tip="Active companies are predicted and traded on paper. Inactive ones are still collected but never predicted (decision 13); they live on the Companies page." />
      <Kpi icon="trending_up" tone="success" label={`Most agreed at N+${horizon}`}
        value={lead?.agreement ? <Link className="tk" href={stockStrategiesPath(market, lead.company.ticker)}>{lead.company.ticker}</Link> : "None"}
        sub={lead?.agreement ? <span><Label tone="success">{`${lead.agreement.buy} of ${lead.agreement.of} buy`}</Label>{lead.agreement.avg_prob_up != null ? ` avg chance ${pct(lead.agreement.avg_prob_up)}` : " no probability"}</span> : "no strategy buys"}
        tip="The company most strategies would buy at the selected horizon (decision 30)." />
      <Kpi icon="account_balance_wallet" tone="paper" label="Open paper trades" value={String(p.open_trades.length)}
        sub={<span>unrealised <MoneyDelta currency={cur} value={unreal} decimals={moneyDecimals(cur)} /> before costs</span>}
        tip="Paper trades entered and not yet exited, every strategy and horizon; unrealised against the latest stored close, before costs." />
      <Kpi icon="warning" tone={flagged ? "warn" : "neutral"} label="Flagged today"
        value={p.trade_checks.length ? `${flagged} of ${p.trade_checks.length}` : "No check yet"}
        sub={p.trade_checks.length ? `open trades checked at ${fmtLocal(p.trade_checks[0].check_at, market, lt)}` : "first intraday check pending"}
        tip="Open trades flagged by the latest intraday check: outside their range, far from the target, or against the prediction." />
    </KpiRow>
  );
}

function SortButton({ label, k, sort, onSort }: { label: string; k: SortKey; sort: { key: SortKey; dir: 1 | -1 }; onSort: (k: SortKey) => void }) {
  const on = sort.key === k;
  return (
    <button type="button" className="sort" aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => onSort(k)}>
      {label}
      {on ? <Icon name={sort.dir < 0 ? "arrow_downward" : "arrow_upward"} /> : null}
    </button>
  );
}

function Table({ p, market, rows, horizon, sector, query, sort, onSort }: {
  p: WatchlistPayload; market: Market; rows: Row[]; horizon: number; sector: string | null; query: string;
  sort: { key: SortKey; dir: 1 | -1 }; onSort: (k: SortKey) => void;
}) {
  const router = useRouter();
  const cur = p.currency, lt = p.status.session.local_time;
  const list = sortRows(filterRows(rows, sector, query), sort.key, sort.dir);
  const ariaSort = (...keys: SortKey[]) => (keys.includes(sort.key) ? (sort.dir < 0 ? "descending" : "ascending") : undefined);
  const inactive = p.companies.filter((c) => c.state !== "active");
  return (
    <section className="card" aria-label="Companies">
      <div className="head">
        <h2>{`${list.length} of ${rows.length} companies`}</h2>
        <HelpTip tip="One row per active company. Agreement = how many of the strategies that predict it at this horizon would buy (rule, baselines and AI count alike), with the buyers’ average chance of a rise. Range = the published range for the horizon (ranges.py; target as the triangle, last close as the dark line), shown whether or not a strategy is live. Open = this company’s open paper trades and their unrealised profit. Click a row for the company page." />
        <div className="end">{`N+${horizon} = ${horizonWords(horizon)} · as of the ${fmtDate(p.as_of, false)} close · Paper`}</div>
      </div>
      <div className="md-table-wrap">
        <table className="md-table tbl wl">
          <thead>
            <tr>
              <th scope="col" aria-sort={ariaSort("name")}><SortButton label="Company" k="name" sort={sort} onSort={onSort} /></th>
              <th scope="col" className="num" aria-sort={ariaSort("last", "change")}>
                <SortButton label="Last" k="last" sort={sort} onSort={onSort} /><span className="sep" aria-hidden="true">·</span><SortButton label="Move" k="change" sort={sort} onSort={onSort} />
              </th>
              <th scope="col" aria-sort={ariaSort("agreement")}><SortButton label={`Agreement at N+${horizon}`} k="agreement" sort={sort} onSort={onSort} /></th>
              <th scope="col" className="cw" data-tip="Average probability of a rise given by the buyers that give one; 50% is a coin flip.">Chance</th>
              <th scope="col" className="c2" data-tip="Buyers at each horizon; the selected one is dark.">Buyers N+1…5</th>
              <th scope="col" className="cw" data-tip="The published 50% and 80% ranges for the horizon (ranges.py), drawn around the last close; the triangle is the target.">{`Range at N+${horizon}`}</th>
              <th scope="col" className="num cm" aria-sort={ariaSort("open")}><SortButton label="Open" k="open" sort={sort} onSort={onSort} /></th>
              <th scope="col" className="c3" aria-label="Open the company page" />
            </tr>
          </thead>
          <tbody>
            {list.length ? list.map((r) => {
              const c = r.company, bands = bandsOf(r.range);
              const flags = distinctFlags(r.flagged).map((f) => FLAG[f] ?? f).join(", ");
              return (
                <tr key={c.ticker} className="row" onClick={(e) => { if (!(e.target as HTMLElement).closest("a, button")) router.push(companyPath(market, c.ticker)); }}>
                  <td><CompanyCell company={c} /></td>
                  <td className="num last"><b>{price(cur, c.last_close)}</b><Delta value={c.change_pct} /></td>
                  <td className="ag"><AgreementCell row={r.agreement} subject={`${c.name} at N+${horizon}`} /></td>
                  <td className="cw"><AgreementOdds row={r.agreement} /></td>
                  <td className="c2"><HorizonBars horizons={p.horizons} splits={p.horizons.map((k) => agreementAt(p.agreement, k, c.ticker))} selected={horizon} /></td>
                  <td className="cw">{bands ? <RangeBar currency={cur} bands={bands} last={c.last_close ?? r.range?.base_close ?? null} /> : <span className="muted" data-tip="No published range stored for this company at this horizon.">—</span>}</td>
                  <td className="num cm ot">
                    {r.trades.length ? <span><b>{r.trades.length}</b><small><MoneyDelta currency={cur} value={r.unrealised} decimals={moneyDecimals(cur)} /></small></span> : <span className="muted">0</span>}
                    {r.flagged.length ? (
                      <span style={{ marginLeft: 6 }}>
                        <Label tone="warn" icon="warning" tip={`${r.flagged.length} open trade${r.flagged.length === 1 ? "" : "s"} flagged at the ${fmtLocal(r.flagged[0].check_at, market, lt)} check: ${flags}.`}>{String(r.flagged.length)}</Label>
                      </span>
                    ) : null}
                  </td>
                  <td className="c3 open"><Link href={companyPath(market, c.ticker)} aria-label={`Open ${c.name}`}>Open<Icon name="chevron_right" /></Link></td>
                </tr>
              );
            }) : (
              <tr><td colSpan={8}><div className="quiet">No company matches the filter.</div></td></tr>
            )}
          </tbody>
        </table>
      </div>
      {inactive.length ? (
        <div className="inactive">
          <Icon name="info" />
          <span>
            {`Not listed: ${inactive.map((c) => `${c.name} (${c.ticker}, inactive since ${fmtDate(c.state_since, false)})`).join(", ")} · still collected, never predicted · `}
            <Link href={pagePath(market, "companies")}>manage on the Companies page</Link>
          </span>
        </div>
      ) : null}
    </section>
  );
}

function Legend() {
  return (
    <div className="legend2" aria-label="Legend">
      <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
      <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
      <span><span className="mb-tag paper">paper</span> every signal and trade until proven</span>
      <span><Label tone="warn" icon="warning">1</Label> flagged open trades at the latest intraday check</span>
      <span>Click a row for the company page; the ticker in the &quot;most agreed&quot; card opens its strategies.</span>
    </div>
  );
}

export function WatchlistView({ p, market }: { p: WatchlistPayload; market: Market }) {
  const [horizon, setHorizon] = useState<number>(p.default_horizon);
  const [sector, setSector] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "agreement", dir: -1 });
  const rows: Row[] = watchlistRows({ ...p, ranges: p.published_ranges ?? [] }, horizon);
  const sectors = sectorsOf(rows);
  const onSort = (k: SortKey) => setSort((s) => (s.key === k ? { key: k, dir: s.dir === 1 ? -1 : 1 } : { key: k, dir: defaultDirection(k) }));
  return (
    <div className="mb-watchlist">
      <PageHead page={p} title="Watchlist" subtitle={`${p.name} · ${rows.length} active companies · data as of the ${fmtDate(p.as_of, false)} close · research only, nothing here trades`} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      <Kpis p={p} market={market} rows={rows} horizon={horizon} />
      <div className="toolbar" role="search">
        <SearchInput label="Filter by symbol or name" value={query} onChange={setQuery} />
        <FilterChips<string>
          label="Sector"
          value={sector ?? "__all"}
          onChange={(v) => setSector(v === "__all" ? null : v)}
          options={[{ value: "__all", label: "All sectors" }, ...sectors.map((s) => ({ value: s.sector, label: <>{s.sector}<span className="muted">{` ${s.count}`}</span></> }))]}
        />
        <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 12.5 }}>Horizon</span>
          <HelpTip tip="N+k: buy at the open of the session being predicted, sell at the close of the k-th market session after it. The selector sets the agreement, chance and range columns; it opens on N+1 (decision 39)." />
          <HorizonTabs horizons={p.horizons} value={horizon} onChange={setHorizon} />
        </span>
      </div>
      <div style={{ marginTop: 16 }}>
        <Table p={p} market={market} rows={rows} horizon={horizon} sector={sector} query={query} sort={sort} onSort={onSort} />
      </div>
      <Legend />
      <PageFooter page={p} endpoint="watchlist" />
    </div>
  );
}

export function WatchlistPage({ market }: { market: Market }) {
  const res = usePage<WatchlistPayload>(market, "watchlist");
  return <PageState result={res}>{(p) => <WatchlistView key={market} p={p} market={market} />}</PageState>;
}
