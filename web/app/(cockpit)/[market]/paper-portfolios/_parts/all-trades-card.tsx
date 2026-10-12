"use client";
// "All paper trades in one place" (owner request 2026-10-12): a plain summary per family and of your own trades,
// then one trade list with filters (whose trades, open or closed, won or lost), from B13's `all_trades` block of
// GET /api/v1/markets/{market}/portfolios. Every strategy's trades (the accuracy view) and the head-to-head trades are
// two views of the same predictions: one is shown at a time, never added together. Paper only, never advice.
import Link from "next/link";
import { useState } from "react";
import { Segmented } from "../../../../../components/ui/controls.tsx";
import { Card, CardHead, FamilyLabel, MoneyDelta, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { FAMILY, FAMILY_SHORT, PAPER_LABEL, PICK_RULE } from "../../../../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtLocal, moneyDecimals, price, signed } from "../../../../../lib/ui/format.ts";
import { companyPath, pagePath } from "../../../../../lib/ui/routes.ts";
import type { PageBase } from "../../../../../lib/ui/types.ts";
import type { Strategy } from "../../../../../lib/strategy-pages/scoreboard.ts";
import {
  countsWords, familiesOf, filterTrades, resultFigure, stateWords, summaryRow, totalFamily, type AllTrades, type AllTradesRow,
  type AllTradesSummaryRow, type ResultFilter, type StateFilter, type SummaryFamily, type TradeScope,
} from "../../../../../lib/strategy-pages/all-trades.ts";
import { Control } from "../../_b16/parts.tsx";

const SCOPE_WORDS: Record<TradeScope, string> = { all: "All strategies", head_to_head: "Head-to-head", mine: "Mine" };
const FAMILY_WORDS: Record<SummaryFamily, string> = { all: "All strategies together", rule: FAMILY.rule[0], baseline: FAMILY.baseline[0], ai: FAMILY.ai[0], mine: "Your own trades" };
const COST_WORDS = { market: "after market cost", your: "after your cost", before: "so far, before costs" } as const;

interface Props {
  p: PageBase & { strategies: Record<string, Strategy>; companies: Array<{ ticker: string; name: string }> };
  all: AllTrades | null | undefined;
}

export function AllTradesCard({ p, all }: Props) {
  const [scope, setScope] = useState<TradeScope>("all");
  const [state, setState] = useState<StateFilter>("any");
  const [result, setResult] = useState<ResultFilter>("any");
  const label = p.status.paper_label || PAPER_LABEL;
  const head = (
    <CardHead title={<>All paper trades in one place <PaperTag label={label} /></>}
      end={all?.window.from && all.window.to ? `listed: every open trade, and the closed or never-entered ones from ${fmtDate(all.window.from, false)} to ${fmtDate(all.window.to, false)}` : undefined}
      help={`Every paper trade the strategies made, and your own, in one list. "All strategies" counts each strategy’s own trades; "Head-to-head" counts the daily picks of the strongest rule strategy and the strongest AI trader. The two are views of the same predictions, so they are shown one at a time and never added together. A trade wins when it made money after costs (strategies: after market cost; yours: after your own broker’s cost). This card always shows both costs; the cost switch above does not change it. A paper trade is a record, never an order; nothing here is advice.`} />
  );
  if (!all) return <Card label="All paper trades">{head}<Quiet>The list of all paper trades is not in this page’s data yet.</Quiet></Card>;
  const total = summaryRow(all, scope, totalFamily(scope), "to_date");
  const recent = summaryRow(all, scope, totalFamily(scope), "window");
  const rows = filterTrades(all, { scope, state, result });
  const cur = p.currency;
  return (
    <Card label="All paper trades" className="at">
      {head}
      <div className="ctrls">
        <Control label="Whose trades">
          <Segmented label="Whose trades" value={scope} onChange={setScope} options={(["all", "head_to_head", "mine"] as const).map((s) => ({ value: s, label: SCOPE_WORDS[s] }))} />
        </Control>
      </div>
      <div className="at-top" aria-live="polite">
        <Headline title="Since paper trading began" row={total} cur={cur} scope={scope} />
        <Headline title={`Last ${all.window.sessions} sessions`} row={recent} cur={cur} scope={scope} />
      </div>
      <FamilyTable all={all} scope={scope} cur={cur} />
      <div className="ctrls" role="group" aria-label="Filter the trades">
        <Control label="Show">
          <Segmented label="Open or closed" value={state} onChange={setState} options={[{ value: "any", label: "All" }, { value: "open", label: "Open" }, { value: "closed", label: "Closed" }]} />
        </Control>
        <Control label="Result">
          <Segmented label="Won or lost" value={result} onChange={setResult} options={[{ value: "any", label: "Any" }, { value: "win", label: "Won" }, { value: "loss", label: "Lost" }]} />
        </Control>
      </div>
      <TradeList p={p} rows={rows} />
      <p className="note">
        {`Closed trades older than the last ${all.window.sessions} sessions are counted above but not listed. A trade that never entered (no stored open price, or one share costs more than its amount) is listed but never counted. Open trades show their result so far, before costs. ${label}: a paper trade is a record, never an order.`}
      </p>
    </Card>
  );
}

function Headline({ title, row, cur, scope }: { title: string; row: AllTradesSummaryRow | null; cur: string; scope: TradeScope }) {
  const d = moneyDecimals(cur);
  return (
    <div className="at-h">
      <div className="l">{title}</div>
      <div className="v">{countsWords(row)}</div>
      <div className="s">
        {!row || !row.closed ? "no closed trade yet" : (
          <>
            {scope !== "mine" ? <span>after market cost <MoneyDelta currency={cur} value={row.net_pnl_market} decimals={d} /> · </span> : null}
            <span>after your cost <MoneyDelta currency={cur} value={row.net_pnl_your} decimals={d} /></span>
            {row.pnl_your_missing ? <span className="muted">{` (${row.pnl_your_missing} without your-cost figure yet)`}</span> : null}
          </>
        )}
      </div>
    </div>
  );
}

function FamilyTable({ all, scope, cur }: { all: AllTrades; scope: TradeScope; cur: string }) {
  const families = familiesOf(all, scope);
  if (!families.length) return <Quiet>No summary for these trades yet.</Quiet>;
  const d = moneyDecimals(cur);
  return (
    <div className="md-table-wrap">
      <table className="md-table tbl at-fam">
        <thead>
          <tr><th>Who</th><th className="num">Open</th><th className="num">Closed</th><th className="num">Won</th><th className="num">Lost</th><th className="num">Won share</th>
            {scope !== "mine" ? <th className="num">Net after market cost</th> : null}<th className="num">Net after your cost</th></tr>
        </thead>
        <tbody>
          {families.map((family) => {
            const r = summaryRow(all, scope, family, "to_date");
            if (!r) return null;
            return (
              <tr key={family} className={family === "all" || family === "mine" ? "tot" : ""}>
                <td>{family === "all" || family === "mine" ? <b>{FAMILY_WORDS[family]}</b> : <FamilyLabel family={family}>{FAMILY_WORDS[family]}</FamilyLabel>}</td>
                <td className="num">{r.open}</td><td className="num">{r.closed}</td><td className="num">{r.wins}</td><td className="num">{r.losses}</td>
                <td className="num">{r.win_rate === null ? DASH : `${Math.round(r.win_rate)}%`}</td>
                {scope !== "mine" ? <td className="num"><MoneyDelta currency={cur} value={r.net_pnl_market} decimals={d} /></td> : null}
                <td className="num"><MoneyDelta currency={cur} value={r.net_pnl_your} decimals={d} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function who(p: Props["p"], row: AllTradesRow) {
  if (row.scope === "mine") return <span>You<small>{row.side === "sell" ? "sold" : "bought"}</small></span>;
  const s = row.strategy_id ? p.strategies[row.strategy_id] : null;
  const name = s?.name ?? row.strategy_id ?? DASH;
  return (
    <span>
      {row.strategy_id ? <Link className="tk" href={`${pagePath(p.market, "lab")}#${encodeURIComponent(row.strategy_id)}`}>{name}</Link> : name}{" "}
      {row.family !== "mine" ? <FamilyLabel family={row.family}>{FAMILY_SHORT[row.family]}</FamilyLabel> : null}
      <small>{[row.horizon_days ? `N+${row.horizon_days}` : null, row.pick_rule ? PICK_RULE[row.pick_rule] ?? row.pick_rule : null].filter(Boolean).join(" · ")}</small>
    </span>
  );
}

function TradeList({ p, rows }: { p: Props["p"]; rows: AllTradesRow[] }) {
  if (!rows.length) return <Quiet>No paper trade matches these filters.</Quiet>;
  const nameOf = (t: string) => p.companies.find((c) => c.ticker === t)?.name ?? t;
  const lt = p.status.session.local_time;
  return (
    <div className="md-table-wrap">
      <table className="md-table tbl at-list">
        <thead><tr><th>Company</th><th>Whose</th><th className="dt">Dates</th><th className="num cw">Bought at</th><th className="num cw">Sold at / last</th><th className="stc">State</th><th className="num">Result</th></tr></thead>
        <tbody>
          {rows.map((row) => {
            const cur = row.currency ?? p.currency, d = moneyDecimals(cur), res = resultFigure(row);
            const lastWords = row.state === "open" && row.last_price_source === "intraday_check" && row.last_price_time
              ? `checked ${fmtLocal(row.last_price_time, p.market, lt)}` : row.state === "open" && row.last_price_date ? `close of ${fmtDate(row.last_price_date, false)}` : null;
            return (
              <tr key={`${row.scope}-${row.id}`} className={row.state === "not_entered" ? "few" : ""}>
                <td><Link className="tk" href={companyPath(p.market, row.ticker)}>{row.ticker}</Link><small className="muted" style={{ display: "block", fontSize: 11 }}>{nameOf(row.ticker)}</small></td>
                <td className="whom">{who(p, row)}</td>
                <td className="nowrap dt">{row.scope === "mine" ? (row.side === "sell" ? `sold ${fmtDate(row.exit_date, false)}` : `bought ${fmtDate(row.entry_date, false)}`) : <>{row.entry_date ? fmtDate(row.entry_date, false) : DASH}{" → "}{row.exit_date ? fmtDate(row.exit_date, false) : DASH}</>}{row.state === "open" && row.exit_date ? <small className="muted" style={{ display: "block", fontSize: 11 }}>planned exit</small> : null}</td>
                <td className="num cw">{row.price_pending ? DASH : price(cur, row.entry_price)}</td>
                <td className="num cw">{row.price_pending ? DASH : price(cur, row.exit_or_last_price)}{lastWords ? <small className="muted" style={{ display: "block", fontSize: 11 }}>{lastWords}</small> : null}</td>
                <td className="stc">{stateWords(row)}</td>
                <td className="num res">
                  <span className="st-ph">{stateWords(row)}</span>
                  {res.value === null ? <span className="muted">{row.state === "closed" ? "not stored yet" : DASH}</span> : <MoneyDelta currency={cur} value={res.value} decimals={d} />}
                  {res.value !== null ? <small className="muted" style={{ display: "block", fontSize: 11 }}>{COST_WORDS[res.cost]}{row.state === "open" && row.unrealised_pct !== null && row.unrealised_pct !== undefined ? ` · ${signed(row.unrealised_pct)}` : ""}</small> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
