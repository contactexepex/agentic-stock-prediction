"use client";
// Shared cards and cells of B4's entity blocks: strategies (StrategyEntry), the Company record, agreement (AgreementRow)
// and open paper trades (OpenTrade with its latest TradeCheck), drawn as the mockups draw them. Pages pass the blocks of
// their own payload; each part carries its words and numbers in text or tooltip, and every signal its Paper tag.
import Link from "next/link";
import { BAND, BAND_SHORT, FAMILY, FAMILY_SHORT, FLAG, FLAG_SHORT, type Family } from "../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtLocal, moneyDecimals, pct, price, signed } from "../../lib/ui/format.ts";
import { companyPath, pagePath } from "../../lib/ui/routes.ts";
import type { AgreementRow, CompanyRecord, OpenTrade, StatusBlock, StrategyEntry, StrategyMap, TradeCheck } from "../../lib/ui/types.ts";
import { AgreementBar, RangeBar } from "../charts/small.tsx";
import { Icon } from "../ui/icon.tsx";
import { Avatar, Card, CardHead, Delta, FamilyLabel, FamilySwatch, Label, MoneyDelta, Odds, PaperTag, Quiet } from "../ui/primitives.tsx";
import { DataTable, type Column, type RowGroup } from "../ui/table.tsx";

/** A strategy id's entry, or a stand-in that shows the id (never invents a name). */
export function strategyOf(strategies: StrategyMap | undefined, id: string): StrategyEntry {
  return strategies?.[id] ?? { id, name: id, family: "rule" };
}

/** A strategy's name with its family swatch; the tooltip names the family, the id and its live state. */
export function StrategyName({ strategy }: { strategy: StrategyEntry }) {
  const live = strategy.live === undefined ? "" : strategy.live ? " · live" : " · not live yet";
  const settled = strategy.settled_trades === undefined ? "" : ` · ${strategy.settled_trades} settled trades`;
  return (
    <span className="mb-strat" data-tip={`${FAMILY_SHORT[strategy.family] ?? strategy.family} · ${strategy.id}${live}${settled}`}>
      <FamilySwatch family={strategy.family} />
      {strategy.name}
    </span>
  );
}

/** The strategy registry as a compact list grouped by family (rule strategies, baselines, AI traders). */
export function StrategyList({ strategies }: { strategies: StrategyMap }) {
  const families: Family[] = ["rule", "baseline", "ai"];
  return (
    <div className="mb-stratlist">
      {families.map((f) => {
        const list = Object.values(strategies).filter((s) => s.family === f);
        if (!list.length) return null;
        return (
          <div key={f}>
            <FamilyLabel family={f}>
              {FAMILY[f][0]} · {list.length}
            </FamilyLabel>
            <ul>
              {list.map((s) => (
                <li key={s.id}>
                  <StrategyName strategy={s} />
                  {s.settled_trades !== undefined ? <small className="muted"> {s.settled_trades} settled</small> : null}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

/** A company cell: icon tile, the ticker linking to its company page, name and sector below. */
export function CompanyCell({ company }: { company: Pick<CompanyRecord, "market" | "ticker" | "name" | "sector"> }) {
  return (
    <span className="mb-co">
      <Avatar icon="apartment" tone="neutral" size="sm" />
      <span className="nm">
        <Link className="tk" href={companyPath(company.market, company.ticker)} data-tip={`${company.name}: open its company page.`}>
          {company.ticker}
        </Link>
        <small>
          {company.name}
          {company.sector ? ` · ${company.sector}` : ""}
        </small>
      </span>
    </span>
  );
}

/** A Company record's state as a label (inactive companies are collected, never predicted). */
export function CompanyState({ company }: { company: CompanyRecord }) {
  return company.state === "active" ? (
    <Label tone="success" icon="check">active</Label>
  ) : (
    <Label tone="neutral" icon="block" tip={`Inactive${company.state_since ? " since " + fmtDate(company.state_since, false) : ""}: still collected, never predicted or traded.`}>
      inactive
    </Label>
  );
}

/** The agreement cell: "12 of 15 buy" and the stacked family bar. */
export function AgreementCell({ row, subject }: { row: Pick<AgreementRow, "buy" | "of" | "by_family"> | null | undefined; subject?: string }) {
  if (!row) return <span className="muted" data-tip="No agreement row for this company at this horizon.">{DASH}</span>;
  return (
    <span className="mb-ag">
      <b>
        {row.buy} of {row.of}
      </b>
      <small> buy</small>
      <AgreementBar byFamily={row.by_family} of={row.of} subject={subject} />
    </span>
  );
}

/** The agreement chance: the buyers' average probability of a rise on the odds meter. */
export function AgreementOdds({ row }: { row: Pick<AgreementRow, "avg_prob_up"> | null | undefined }) {
  if (!row) return <span className="muted">{DASH}</span>;
  return (
    <Odds
      p={row.avg_prob_up}
      tip={row.avg_prob_up === null ? "None of the buyers gives a probability (the always-buy and follow-yesterday baselines)." : `Average chance of a rise given by the buyers that give one: ${pct(row.avg_prob_up, 1)}. 50% is a coin flip.`}
    />
  );
}

/** An open trade's latest intraday check: the band word, or its flags with a warning icon. */
export function TradeCheckStatus({ check, status, currency }: { check: TradeCheck | undefined; status: StatusBlock; currency: string }) {
  if (!check) return <span className="st muted" data-tip="No intraday check stored for this trade by the cut-off.">{DASH}</span>;
  const [bandWords, bandClass] = BAND[check.band] ?? [check.band, ""];
  const flags = check.flags.map((f) => FLAG[f] ?? f);
  const tip =
    `${fmtLocal(check.check_at, status.market, status.session.local_time)}: ${price(currency, check.last_price)}, ${signed(check.ret_since_entry_pct)} since entry, ${bandWords}` +
    (flags.length ? `; ${flags.join(", ")}` : "") +
    (check.session_number !== undefined ? `. Session ${check.session_number} of the holding window.` : ".");
  return (
    <span className={`st ${check.flagged ? "flag" : bandClass}`} data-tip={tip}>
      <Icon name={check.flagged ? "warning" : "check"} />
      {check.flagged ? check.flags.map((f) => FLAG_SHORT[f] ?? f).join(", ") : BAND_SHORT[check.band] ?? check.band}
    </span>
  );
}

function bandsOf(trade: OpenTrade) {
  const { lo80, lo50, hi50, hi80, target_price } = trade;
  if (lo80 == null || lo50 == null || hi50 == null || hi80 == null || target_price == null) return null;
  return { lo80, lo50, hi50, hi80, target_price };
}

/** The open paper trades card (Home's design): grouped by company, one row per trade with its strategy, horizon window,
 *  entry, last, unrealised before costs, its own predicted range, the distance to target and the latest check. */
export function OpenTradesCard({
  trades,
  checks = [],
  strategies,
  companies = [],
  status,
  currency,
  title = "Open paper trades",
  allTradesHref,
}: {
  trades: readonly OpenTrade[];
  checks?: readonly TradeCheck[];
  strategies?: StrategyMap;
  companies?: readonly Pick<CompanyRecord, "ticker" | "name">[];
  status: StatusBlock;
  currency: string;
  title?: string;
  allTradesHref?: string;
}) {
  const byTrade = new Map(checks.map((c) => [c.trade_id, c]));
  const h2h = trades.filter((t) => t.view === "head_to_head").length;
  const nameOf = (t: string) => companies.find((c) => c.ticker === t)?.name ?? t;
  const decimals = moneyDecimals(currency);
  const tickers = [...new Set(trades.map((t) => t.ticker))];
  const groups: RowGroup<OpenTrade>[] = tickers.map((ticker) => {
    const rows = trades.filter((t) => t.ticker === ticker).sort((a, b) => a.horizon_days - b.horizon_days || a.strategy_id.localeCompare(b.strategy_id));
    const sum = rows.reduce((a, r) => a + r.unrealised_pnl, 0);
    return {
      key: ticker,
      title: (
        <>
          <Link className="tk" href={companyPath(status.market, ticker)} data-tip={`${nameOf(ticker)}: open its company page.`}>
            {ticker}
          </Link>{" "}
          {nameOf(ticker)}
        </>
      ),
      note: (
        <>
          {rows.length} open · last {price(currency, rows[0].last_price)} ({fmtDate(rows[0].last_price_date, false)}) · unrealised <MoneyDelta currency={currency} value={sum} decimals={decimals} />
        </>
      ),
      rows,
    };
  });
  const columns: Column<OpenTrade>[] = [
    {
      key: "strategy",
      header: "Strategy",
      render: (r) => (
        <>
          <StrategyName strategy={strategyOf(strategies, r.strategy_id)} />
          {r.view === "head_to_head" ? (
            <span className="mb-label neutral mb-h2h" data-tip="Head-to-head view: one of the up to four daily picks for this company.">
              H2H
            </span>
          ) : null}
        </>
      ),
    },
    {
      key: "horizon",
      header: "Horizon",
      render: (r) => (
        <>
          <span className="h-lab">N+{r.horizon_days}</span>
          <small className="muted cw nowrap"> {fmtDate(r.entry_date, false)} → {fmtDate(r.exit_date, false)}</small>
        </>
      ),
    },
    { key: "entry", header: "Entry", numeric: true, className: "cw", render: (r) => price(currency, r.entry_price) },
    { key: "last", header: "Last", numeric: true, className: "cw", render: (r) => price(currency, r.last_price) },
    {
      key: "unrealised",
      header: "Unrealised",
      numeric: true,
      render: (r) => (
        <>
          <MoneyDelta currency={currency} value={r.unrealised_pnl} decimals={decimals} />
          <span className="cw"> <Delta value={r.unrealised_pct} /></span>
        </>
      ),
    },
    {
      key: "range",
      header: "Predicted range",
      className: "cm",
      render: (r) => {
        const bands = bandsOf(r);
        return bands ? <RangeBar currency={currency} bands={bands} last={byTrade.get(r.trade_id)?.last_price ?? r.last_price} entry={r.entry_price} /> : <span className="muted">{DASH}</span>;
      },
    },
    {
      key: "target",
      header: "To target",
      numeric: true,
      className: "cw",
      render: (r) =>
        r.to_target_pct == null ? (
          <span className="muted">{DASH}</span>
        ) : (
          <span data-tip={r.to_target_pct < 0 ? `Already past the target ${price(currency, r.target_price)}.` : `${signed(r.to_target_pct)} to the target ${price(currency, r.target_price)}.`}>
            {r.to_target_pct < 0 ? "past target" : signed(r.to_target_pct)}
          </span>
        ),
    },
    { key: "check", header: "Check", render: (r) => <TradeCheckStatus check={byTrade.get(r.trade_id)} status={status} currency={currency} /> },
  ];
  return (
    <Card label={title}>
      <CardHead
        title={
          <>
            {title} <PaperTag label={status.paper_label} />
          </>
        }
        help="Every paper trade that has entered (bought at the open of its entry session) and not yet exited, all strategies and horizons: the accuracy view (one trade per qualifying prediction) and the head-to-head view (H2H). Unrealised = the latest stored close against the entry, before costs. Range = where the price sits in the trade’s own predicted range. Check = the latest intraday check, where one exists."
        end={
          <>
            {trades.length} open · {trades.length - h2h} accuracy, {h2h} head-to-head
            <Link className="go" href={allTradesHref ?? pagePath(status.market, "portfolios")}>
              All trades <Icon name="chevron_right" />
            </Link>
          </>
        }
      />
      {trades.length ? <DataTable columns={columns} groups={groups} rowKey={(r) => r.trade_id} label={title} className="mb-ot" /> : <Quiet>No open paper trade.</Quiet>}
    </Card>
  );
}
