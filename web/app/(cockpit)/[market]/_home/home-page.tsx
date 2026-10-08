"use client";
// Page 01, Home (design/mockups/01-home/): the session being predicted at a glance. Who agrees at the selected
// horizon (decision 30), today's head-to-head paper trades and whether each clears costs (decision 51), Rule vs AI
// (the cumulative profit chart, the last close, the head-to-head results to date), the latest intraday alerts, the top
// market movers, the runs of the day and the open paper trades. The page's own computations are in
// lib/market-pages/home.ts and news.ts. Every signal is Paper until a strategy meets the go-live bar; nothing trades.
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { CostLabels } from "../../../../components/blocks/costs.tsx";
import { PageFooter, PageHead, SignalsBand } from "../../../../components/blocks/page-head.tsx";
import { OpenTradesCard, strategyOf } from "../../../../components/blocks/records.tsx";
import { HorizonBars } from "../../../../components/charts/small.tsx";
import { AgreementBar } from "../../../../components/charts/small.tsx";
import { ChartLegend, LineChart } from "../../../../components/charts/line-chart.tsx";
import { HorizonTabs } from "../../../../components/ui/controls.tsx";
import { Icon } from "../../../../components/ui/icon.tsx";
import {
  Avatar, Card, CardHead, Delta, FamilyLabel, GoLink, Kpi, KpiRow, Label, MoneyDelta, Odds, PaperTag, Quiet,
  SentimentSquare, StatusBadge,
} from "../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../components/ui/states.tsx";
import type { Market } from "../../../../lib/data/constants.ts";
import {
  cumulativeProfit, eodLeaders, expectedGainMoney, groupBy, INTRADAY_CHECKS_PER_SESSION, isPicked, pickSummary, runsOk,
  viableLineOf, type EodFamily, type Family, type HeadToHeadPick, type PickRule, type RunState,
} from "../../../../lib/market-pages/home.ts";
import { CAN_CARRY, HOME_NEWS_MAX, kindWord, movers, type NewsItem } from "../../../../lib/market-pages/news.ts";
import { agreementAt, horizonWords, sumMoney } from "../../../../lib/market-pages/watchlist.ts";
import { BAND, FAMILY, FLAG, PICK_RULE } from "../../../../lib/ui/constants.ts";
import type { Pick as CostPick } from "../../../../lib/ui/costs.ts";
import { DOW_LONG, fmtDate, fmtLocal, money, moneyDecimals, pct, price, signed } from "../../../../lib/ui/format.ts";
import { companyPath, pagePath, stockStrategiesPath } from "../../../../lib/ui/routes.ts";
import type { AgreementMap, AgreementRow, CompanyRecord, GoLive, OpenTrade, PageBase, StrategyMap, TradeCheck } from "../../../../lib/ui/types.ts";
import { usePage } from "../../../../lib/ui/use-api.ts";
import "./home.css";

type H2HPick = HeadToHeadPick & {
  base_close: number | null; prob_up: number | null; move_pct: number | null; loss_pct: number | null; costs_pct: number | null;
  strongest_basis: string | null; prediction_id: string | null;
};
export interface EodAnalysis {
  session_date: string; settled_trades: number; results: Partial<Record<Family, EodFamily>>; summary: string;
  cited_ids: string[]; reason_ids: string[];
}
export interface ToDateRow { family: Family; pick_rule: string; trades: number; net_pnl: number | null; win_rate: number | null; sample_badge: string }
export type HomePayload = PageBase & {
  horizons: number[];
  default_horizon: number;
  go_live: GoLive;
  companies: CompanyRecord[];
  agreement: AgreementMap;
  head_to_head: H2HPick[];
  open_trades: OpenTrade[];
  trade_checks: (TradeCheck & { ticker: string; strategy_id: string; horizon_days: number; entry_price: number })[];
  eod: EodAnalysis | null;
  to_date: ToDateRow[];
  strategies: StrategyMap;
  news: NewsItem[];
  settled_trades: { view: string; family: Family; exit_date_actual: string | null; net_pnl: number | null }[];
};

interface Ctx { p: HomePayload; market: Market; cur: string; lt: string | null | undefined; horizon: number }
const companyOf = (p: HomePayload, t: string) => p.companies.find((c) => c.ticker === t) ?? { ticker: t, name: t } as Pick<CompanyRecord, "ticker" | "name"> & Partial<CompanyRecord>;
const ORDINAL = ["", "1st", "2nd", "3rd", "4th", "5th"];
const SHORT_FAMILY: Record<Family, string> = { rule: "Rule", baseline: "Baselines", ai: "AI" };

function Kpis({ c }: { c: Ctx }) {
  const { p, market, cur, lt, horizon } = c;
  const lead: AgreementRow | undefined = (p.agreement[String(horizon)] ?? [])[0];
  const s = pickSummary(p.head_to_head);
  const unreal = sumMoney(p.open_trades.map((t) => t.unrealised_pnl));
  const flagged = p.trade_checks.filter((x) => x.flagged).length;
  return (
    <KpiRow>
      <Kpi icon="trending_up" label={`Most agreed at N+${horizon}`}
        value={lead && lead.buy ? <Link className="tk" href={stockStrategiesPath(market, lead.ticker)}>{lead.ticker}</Link> : "None"}
        sub={lead && lead.buy ? <span><Label tone="success">{`${lead.buy} of ${lead.of} buy`}</Label>{lead.avg_prob_up != null ? ` avg chance ${pct(lead.avg_prob_up)}` : " no probability"}</span> : "no strategy buys"}
        tip="The company most strategies would buy at the selected horizon (decision 30)." />
      <Kpi icon="layers" tone="info" label="Head-to-head today" value={`${s.picked} trades`}
        sub={
          <span className="labs">
            <Label tone={s.clearMarket ? "success" : "neutral"} icon={s.clearMarket ? "check" : "close"}>{s.clearMarket ? `${s.clearMarket} clear market costs` : "none clears market costs"}</Label>
            <Label tone={s.viableYours ? "success" : "warn"} icon={s.viableYours ? "check" : "warning"}>{s.viableYours ? `${s.viableYours} viable at your cost` : "none viable at your cost"}</Label>
            <PaperTag label={p.status.paper_label} />
          </span>
        }
        tip="Up to four paper trades per company: strongest rule strategy and strongest AI trader × two pick rules. “Clears market costs” = expected gain after the market charges above zero (the ranking view); “viable at your cost” adds your own broker’s charges (decision 51)." />
      <Kpi icon="account_balance_wallet" tone="paper" label="Open paper trades" value={String(p.open_trades.length)}
        sub={<span>unrealised <MoneyDelta currency={cur} value={unreal} decimals={moneyDecimals(cur)} /> before costs</span>}
        tip="Paper trades entered and not yet exited, every strategy and horizon; unrealised against the latest stored close, before costs." />
      <Kpi icon="warning" tone={flagged ? "warn" : "neutral"} label="Alerts" value={p.trade_checks.length ? `${flagged} flagged` : "No check yet"}
        sub={p.trade_checks.length ? `of ${p.trade_checks.length} open trades checked at ${fmtLocal(p.trade_checks[0].check_at, market, lt)}` : "first intraday check pending"}
        tip="Open trades flagged by the latest intraday check: outside their range, far from the target, or against the prediction." />
    </KpiRow>
  );
}

function AgreementCard({ c, onHorizon }: { c: Ctx; onHorizon: (k: number) => void }) {
  const { p, market, cur, horizon } = c;
  const rows = p.agreement[String(horizon)] ?? [];
  const active = p.companies.filter((x) => x.state === "active").length;
  return (
    <Card label="Top companies by agreement">
      <CardHead
        title={`Who agrees at N+${horizon}`}
        help="Decision 30: companies ranked by how many strategies would buy them at this horizon (a call counts when it is “up” and at or above the strategy’s own bar), then by the average probability of those buyers. Rule, baseline and AI strategies count alike; a click opens the company’s strategy page."
        end={<HorizonTabs horizons={p.horizons} value={horizon} onChange={onHorizon} />}
      />
      <div className="sub2">{`${rows.length} of ${active} active companies · N+${horizon} = ${horizon === 1 ? horizonWords(1) : `the close of the ${ORDINAL[horizon] ?? `${horizon}th`} session after the open`} · Paper ranking from today’s predictions`}</div>
      {!rows.some((r) => r.buy > 0) ? <Quiet>{`No strategy buys any company at N+${horizon} today.`}</Quiet> : (
        <ul className="agl">
          {rows.map((r, i) => {
            const co = companyOf(p, r.ticker);
            const fams: Family[] = ["rule", "baseline", "ai"];
            return (
              <li key={r.ticker} className={i === 0 ? "top" : undefined}>
                <div className="rk" role="img" aria-label={`rank ${r.rank}`}>{r.rank}</div>
                <Avatar icon="apartment" tone={i === 0 ? "" : "neutral"} />
                <div className="who">
                  <div className="nm">
                    <Link className="tk" href={stockStrategiesPath(market, r.ticker)} data-tip={`${co.name}: open its stock strategies page (every strategy ranked on this company).`}>{r.ticker}</Link>
                    {co.name}
                    <small>{`${price(cur, co.last_close)} `}<Delta value={co.change_pct} /></small>
                  </div>
                  <div className="sent"><b>{`${r.buy} of ${r.of}`}</b>{` strategies buy at N+${r.horizon_days}`}</div>
                  <AgreementBar byFamily={r.by_family} of={r.of} subject={`${co.name} at N+${r.horizon_days}`} />
                  <div className="fam">
                    {fams.map((f) => {
                      const x = r.by_family[f];
                      return (
                        <span key={f} data-tip={`${FAMILY[f][0]}: ${x.buy} of the ${x.of} that predict ${co.name} at N+${r.horizon_days} would buy.`}>
                          <FamilyLabel family={f}>{`${FAMILY[f][0].split(" ")[0]} ${x.of ? `${x.buy}/${x.of}` : "—"}`}</FamilyLabel>
                        </span>
                      );
                    })}
                  </div>
                </div>
                <div className="hz">
                  <HorizonBars horizons={p.horizons} splits={p.horizons.map((k) => agreementAt(p.agreement, k, r.ticker))} selected={horizon} />
                  <small>buyers N+1 … N+5</small>
                </div>
                <div className="right">
                  <Odds p={r.avg_prob_up} tip={r.avg_prob_up == null ? "Only always-buy and follow-yesterday buy it; neither gives a probability." : `Average probability of a rise given by the buyers that give one: ${pct(r.avg_prob_up, 1)}. 50% is a coin flip.`} />
                  <div className="l">{r.avg_prob_up == null ? "no probability" : "avg. chance of a rise"}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function HeadToHeadCard({ c }: { c: Ctx }) {
  const { p, market, cur } = c;
  const picks = p.head_to_head;
  const byTicker = groupBy(picks, (k) => k.ticker);
  const picked = picks.filter(isPicked);
  const viable = picked.filter((k) => (k.expected_gain_pct ?? 0) > 0).length;
  return (
    <Card label="Today’s head-to-head paper trades">
      <CardHead
        title={<>Today’s head-to-head trades <PaperTag label={p.status.paper_label} /></>}
        help="Decisions 41-42: for each company, the strongest rule strategy and the strongest AI trader each choose one horizon under two pick rules: best expected gain (the horizon with the highest p × move − (1 − p) × loss − costs) and highest probability. Up to four paper trades of the company’s amount per company per day. A pick clears market costs when its expected gain after the market charges is above zero; “viable at your cost” (decision 51) adds your own broker’s charges and is the flag the owner acts on."
        end={<GoLink href={pagePath(market, "compare")}>Rule vs AI</GoLink>}
      />
      {!picks.length ? <Quiet>No head-to-head picks stored for today’s session yet.</Quiet> : (
        <>
          <div className="sumline">
            <Avatar icon={viable ? "check" : "info"} tone={viable ? "success" : "neutral"} size="sm" />
            <span>
              {`${picked.length} paper trades today across ${byTicker.length} compan${byTicker.length === 1 ? "y" : "ies"} · `}
              <b>{viableLineOf(picks)}</b>
              {" (expected gain after costs above zero; your cost = decision 51)"}
            </span>
          </div>
          <div className="h2h">
            {byTicker.map(([t, ks]) => {
              const co = companyOf(p, t);
              return (
                <div className="cmp" key={t}>
                  <div className="ch">
                    <Avatar icon="apartment" tone="neutral" size="sm" />
                    <Link className="tk" href={stockStrategiesPath(market, t)}>{t}</Link>
                    <span className="nm">{co.name}</span>
                    <span className="muted" style={{ fontSize: 12.5 }}>{`close ${price(cur, ks[0].base_close)}`}</span>
                    <span className="amt" data-tip={co.amount_overridden ? "This company’s amount is overridden (decision 44)." : "The market’s default amount per paper trade (decision 26)."}>{`${money(cur, ks[0].amount)} per trade${co.amount_overridden ? " (override)" : ""}`}</span>
                  </div>
                  {ks.every((k) => !isPicked(k)) ? (
                    <div className="quiet" style={{ marginTop: 10, background: "var(--md-sys-color-surface-container-lowest)" }}>{`No candidate: no rule strategy and no AI trader buys ${co.name} at any horizon today, so no head-to-head trade.`}</div>
                  ) : (
                    <div className="fams">
                      {(["rule", "ai"] as const).map((f) => <FamilyBox key={f} c={c} family={f} picks={ks.filter((k) => k.family === f)} />)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <p className="note">Expected gain is in percent of the trade amount, from the latest close (the entry open is not known before the open). Every trade is Paper: a record, never an order.</p>
        </>
      )}
    </Card>
  );
}

function FamilyBox({ c, family, picks }: { c: Ctx; family: "rule" | "ai"; picks: H2HPick[] }) {
  const { p, cur } = c;
  const any = picks.find(isPicked);
  const st = any?.strategy_id ? strategyOf(p.strategies, any.strategy_id) : null;
  return (
    <div className="fam-box">
      <div className="fh">
        <Avatar icon={family === "ai" ? "bolt" : "settings"} tone={family === "ai" ? "info" : ""} size="sm" />
        <b>{family === "ai" ? "AI" : "Rule"}</b>
        {st && any ? (
          <small data-tip={`${st.name} (${any.strategy_id}): the family’s strongest strategy with a buyable horizon today, ranked on ${any.strongest_basis === "per_company" ? "this company (20+ settled trades on it)" : "all companies (fewer than 20 settled trades on this one)"}.`}>{`· ${st.name}`}</small>
        ) : <small>· no candidate</small>}
      </div>
      {picks.map((k) => (
        <div className="pk" key={k.id}>
          <span className="rule">{PICK_RULE[k.pick_rule] ?? k.pick_rule}</span>
          {!isPicked(k) ? <span className="line muted">no candidate</span> : (
            <>
              <span className="line">
                <span className="h-lab">{`N+${k.horizon_days}`}</span>
                <Odds p={k.prob_up} tip={`${pct(k.prob_up, 1)} chance of a rise from the open to the N+${k.horizon_days} close (the prediction ${k.prediction_id ?? "—"}).`} />
                <span className="gain">
                  <MoneyDelta currency={cur} value={expectedGainMoney(k)} decimals={moneyDecimals(cur)} />
                  <CostLabels currency={cur} pick={k as unknown as CostPick} />
                </span>
              </span>
              <span className="det">{`to target ${signed(k.move_pct)} · downside ${signed(k.loss_pct == null ? null : -k.loss_pct)} · costs ${k.costs_pct ?? "—"}%`}</span>
            </>
          )}
        </div>
      ))}
      {any && any.candidates ? (
        <details className="cand">
          <summary>{`Why these horizons: ${any.candidates.length} buyable horizons`}</summary>
          <div className="md-table-wrap">
            <table className="md-table">
              <thead><tr><th scope="col">Horizon</th><th scope="col" className="num">Chance</th><th scope="col" className="num">To target</th><th scope="col" className="num">Downside</th><th scope="col" className="num">Costs</th><th scope="col" className="num">Expected</th></tr></thead>
              <tbody>
                {any.candidates.map((cd) => (
                  <tr key={cd.horizon_days}>
                    <td>{`N+${cd.horizon_days}`}</td><td className="num">{pct(cd.prob_up, 1)}</td><td className="num">{signed(cd.move_pct)}</td>
                    <td className="num">{signed(cd.loss_pct == null ? null : -cd.loss_pct)}</td><td className="num">{`${cd.costs_pct ?? "—"}%`}</td><td className="num"><Delta value={cd.expected_gain_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}

function RuleVsAiCard({ c }: { c: Ctx }) {
  const { p, market, cur, lt } = c;
  const e = p.eod, pc = p.status.runs.post_close;
  const profit = cumulativeProfit(p.settled_trades);
  const dec = moneyDecimals(cur);
  const leaders = e ? eodLeaders(e.results) : new Set<Family>();
  const key = { rule: "r", baseline: "b", ai: "a" } as const;
  return (
    <Card label="Rule vs AI">
      <CardHead
        title="Rule vs AI"
        help="Who is better: profit after costs on the same companies and amounts (decision 8). The chart adds up every settled paper trade of the accuracy view by settlement day. Last close: the post-close run’s end-of-day analysis. To date: the head-to-head scoreboard, family × pick rule, every horizon pooled."
        end={<GoLink href={pagePath(market, "compare")}>Compare</GoLink>}
      />
      <div className="sub2">
        {profit.days.length ? `Cumulative profit after costs · ${profit.trades} settled paper trades, ${fmtDate(profit.days[0], false)}–${fmtDate(profit.days[profit.days.length - 1], false)} · Paper` : "No settled paper trade yet"}
      </div>
      {profit.days.length ? (
        <>
          <LineChart
            label="Cumulative profit after costs per family"
            labels={profit.days.map((d) => fmtDate(d, false))}
            series={profit.series.map((s) => ({ key: key[s.family], name: FAMILY[s.family][0], values: s.points, area: true }))}
            formatY={(v) => money(cur, Math.round(v), 0, true).replace("+", "")}
            formatValue={(v) => (v === null ? "—" : money(cur, v, dec, true))}
            legend={false}
          />
          <ChartLegend items={profit.series.map((s) => ({ key: key[s.family], name: FAMILY[s.family][0], value: money(cur, s.points[s.points.length - 1], dec, true) }))} />
        </>
      ) : null}
      <div className="head" style={{ margin: "16px 0 8px" }}>
        <h2 style={{ fontSize: 13.5 }}>{e ? `Last close · ${fmtDate(e.session_date)}` : "Last close"}</h2>
        {e ? <Label tone="neutral">{`${e.settled_trades} settled`}</Label> : null}
        {pc && pc.at == null ? <span className="end">{`next post-close ${fmtLocal(pc.next_at, market, lt)}`}</span> : null}
      </div>
      {!e ? <Quiet>No end-of-day analysis stored yet.</Quiet> : (
        <>
          <div className="lastclose" style={{ marginTop: 0 }}>
            {(["rule", "ai", "baseline"] as const).map((f) => {
              const x = e.results[f] ?? { trades: 0, wins: 0, net_pnl: null };
              const lead = leaders.has(f);
              return (
                <div key={f} className={`t${lead ? " lead" : ""}`} data-tip={`${FAMILY[f][0]}, accuracy view: ${x.trades} trades settled on ${fmtDate(e.session_date)}, ${x.wins} with a profit after costs.${lead ? " Led the day." : ""}`}>
                  <div className="l">{FAMILY[f][0].split(" ")[0]}</div>
                  <div className="v">{x.trades ? <MoneyDelta currency={cur} value={x.net_pnl} /> : <span className="muted">none</span>}</div>
                  <div className="s">{x.trades ? `${x.wins} of ${x.trades} won${lead ? " · led" : ""}` : "no trades"}</div>
                </div>
              );
            })}
          </div>
          <p className="note" style={{ marginTop: 10 }}>
            {e.summary}{" "}
            <Link href={pagePath(market, "compare")} data-tip={`The EOD analyst cites ${e.cited_ids.length} trade ids and ${e.reason_ids.length} AI reasons; gated.`}>reasons</Link>
          </p>
        </>
      )}
      <div className="head" style={{ margin: "16px 0 4px" }}>
        <h2 style={{ fontSize: 13.5 }}>Head-to-head to date</h2>
        <button className="md-help" type="button" aria-label="Explain" data-tip="Head-to-head view: one trade per company, family and pick rule each day. Profit after costs, settled trades and win rate. Fewer than 20 trades: too few to rank (SPEC section 6).">?</button>
      </div>
      <div className="grid22">
        <div />
        {(["best_expected_gain", "highest_probability"] as PickRule[]).map((r) => <div className="hd" key={r}>{r === "best_expected_gain" ? "Gain pick" : "Probability pick"}</div>)}
        {(["rule", "ai"] as const).map((f) => [
          <div className="rh" key={`h-${f}`}><Icon name={FAMILY[f][1]} />{SHORT_FAMILY[f]}</div>,
          ...(["best_expected_gain", "highest_probability"] as PickRule[]).map((r) => {
            const row = p.to_date.find((x) => x.family === f && x.pick_rule === r);
            if (!row) return <div className="cell none" key={`${f}-${r}`}>no settled trade yet</div>;
            return (
              <div className="cell" key={`${f}-${r}`}>
                <div className="v"><MoneyDelta currency={cur} value={row.net_pnl} /></div>
                <div className="s">
                  {`${row.trades} trade${row.trades === 1 ? "" : "s"} · ${pct(row.win_rate)} won `}
                  {row.sample_badge === "too_few_to_rank" ? <span className="mb-label neutral" style={{ fontSize: 10.5, padding: "0 5px" }} data-tip="Fewer than 20 settled trades: too few to rank; the number is shown but proves nothing yet.">too few to rank</span> : null}
                </div>
              </div>
            );
          }),
        ])}
      </div>
    </Card>
  );
}

function AlertsCard({ c }: { c: Ctx }) {
  const { p, market, cur, lt } = c;
  const flagged = p.trade_checks.filter((x) => x.flagged);
  const first = p.trade_checks[0];
  return (
    <Card label="Alerts">
      <CardHead
        title="Alerts"
        help="Flagged intraday trade checks of the latest check today: an open paper trade outside its range, far from its target, or moving against the prediction. Monitoring only; nothing is traded on an alert."
        end={first ? `check at ${fmtLocal(first.check_at, market, lt)}` : "no check yet"}
      />
      {!first ? <Quiet>{`No intraday check stored yet today. Checks run ${INTRADAY_CHECKS_PER_SESSION === 2 ? "twice" : `${INTRADAY_CHECKS_PER_SESSION} times`} per session; the first one fills this card.`}</Quiet>
        : !flagged.length ? <Quiet>{`No open trade is flagged at the ${fmtLocal(first.check_at, market, lt)} check.`}</Quiet> : (
          <ul className="al">
            {groupBy(flagged, (x) => x.ticker).map(([t, cks]) => {
              const co = companyOf(p, t);
              const flags = [...new Set(cks.flatMap((x) => x.flags))].map((f) => FLAG[f] ?? f);
              return (
                <li key={t}>
                  <Avatar icon="warning" tone="warn" size="sm" />
                  <div>
                    <b><Link className="tk" href={companyPath(market, t)}>{t}</Link>{` ${co.name}: ${cks.length} open trade${cks.length === 1 ? "" : "s"} ${flags.join(" and ")}`}</b>
                    <div className="d">{`${price(cur, cks[0].last_price)} at ${fmtLocal(cks[0].check_at, market, lt)} · ${signed(cks[0].ret_since_entry_pct)} since entry ${price(cur, cks[0].entry_price)}`}</div>
                    <small>{cks.map((x) => `${strategyOf(p.strategies, x.strategy_id).name} N+${x.horizon_days} (${(BAND[x.band] ?? [x.band])[0]}, session ${x.session_number ?? "—"})`).join(" · ")}</small>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
    </Card>
  );
}

function NewsCard({ c }: { c: Ctx }) {
  const { p, market } = c;
  const items = p.news;
  const top = movers(items, HOME_NEWS_MAX);
  const carry = items.filter((n) => (CAN_CARRY as readonly string[]).includes(n.status ?? "")).length;
  return (
    <Card label="News">
      <CardHead
        title="Market movers · last 3 days"
        help="The stories most likely to move prices in the last three days, as the News page ranks them: the engine’s market-moving flag first (high materiality and market-wide or a results item), then market-wide stories, the watchlist’s results and high materiality, newest first. Each links to its article. Only a confirmed or corroborated story can be the main evidence of a call; market-wide stories carry no status because verification is per company. The News page has every story of the window with filters and the calendar."
        end={<GoLink href={pagePath(market, "news")}>All news</GoLink>}
      />
      {top.length ? (
        <ul className="nl">
          {top.map((n) => (
            <li key={n.id}>
              <SentimentSquare value={n.enrichment.sentiment} />
              <div className="hd">
                {n.url ? <a className="t" href={n.url} rel="noopener noreferrer" target="_blank">{n.title}</a> : <span className="t">{n.title}</span>}
                {n.summary ? <div className="sum">{n.summary}</div> : null}
                <small>
                  {n.status ? <StatusBadge status={n.status} /> : <Label tone="neutral" tip="A market-wide story carries no verification status: verification is per company.">not verified per company</Label>}
                  {n.market_moving ? <Label tone="warn" icon="warning">market moving</Label> : null}
                  {n.primary_tickers.map((t) => <Link key={t} className="tk" href={companyPath(market, t)}>{t}</Link>)}
                  <span>{`${n.source ?? "Unknown outlet"} · ${n.enrichment.materiality ?? "unscored"} materiality · ${n.scope === "market" ? (n.category && n.category !== "company" && n.category !== "general" ? n.category : "market-wide") : kindWord(n)}`}</span>
                </small>
              </div>
            </li>
          ))}
        </ul>
      ) : <Quiet>{`No market-moving story in the last 3 days (${items.length} stored in the window).`}</Quiet>}
      <p className="note" style={{ margin: "8px 0 0" }}>
        {`${items.length} stor${items.length === 1 ? "y" : "ies"} in the last 3 days, ${carry} that can carry a call (confirmed or corroborated). `}
        <Link href={pagePath(market, "news")}>Open the News page</Link>
        {" for all of them, the filters and the week’s calendar."}
      </p>
    </Card>
  );
}

function RunsCard({ c }: { c: Ctx }) {
  const { p, market, lt } = c;
  const r = p.status.runs as unknown as { pre_open: RunState; intraday: RunState[]; post_close: RunState; news: RunState };
  const { ok, total } = runsOk(r);
  const mark = (state: boolean | null) => (
    <span className={`mb-mark ${state == null ? "na" : state ? "ok" : "no"}`} role="img" aria-label={state == null ? "not run yet" : state ? "ok" : "failed"}>
      <Icon name={state == null ? "schedule" : state ? "check" : "close"} />
    </span>
  );
  const item = (key: string, state: boolean | null, what: string, sub: string, when: ReactNode) => (
    <li key={key}>{mark(state)}<span>{what}<small>{sub}</small></span><span className="t">{when}</span></li>
  );
  return (
    <Card label="Last runs">
      <CardHead
        title="Runs today"
        help="The routines of this market: pre-open (collect, model, strategies, AI traders, picks), two intraday checks, post-close (settlement, end-of-day analysis) and the news run every four hours (the latest one counts here). A tick means the run finished and its gates passed."
        end={<Label tone={ok === total ? "success" : "neutral"}>{`${ok} of ${total} ok`}</Label>}
      />
      <ul className="runs">
        {item("pre", r.pre_open.ok, "Pre-open", "collect · model · strategies · AI traders · picks", fmtLocal(r.pre_open.at, market, lt))}
        {Array.from({ length: INTRADAY_CHECKS_PER_SESSION }, (_, i) => {
          const x = r.intraday[i];
          return x
            ? item(`i${i}`, x.ok, `Intraday check ${i + 1}`, "open trades vs range and target", fmtLocal(x.at, market, lt))
            : item(`i${i}`, null, `Intraday check ${i + 1}`, "open trades vs range and target · not yet", "—");
        })}
        {item("post", r.post_close.ok, "Post-close", r.post_close.at ? "settlement · end-of-day analysis" : "settlement · end-of-day analysis · not yet",
          r.post_close.at ? fmtLocal(r.post_close.at, market, lt) : <span><small>next </small>{fmtLocal(r.post_close.next_at, market, lt)}</span>)}
        {item("news", r.news.ok, "News (latest run)", `every 4 hours · ${r.news.new_items ?? 0} new items`, fmtLocal(r.news.at, market, lt))}
      </ul>
      <p className="note">{`Cut-off ${fmtLocal(p.cutoff, market, lt, true)}: every number on this page was stored by then.`}</p>
    </Card>
  );
}

function Legend() {
  return (
    <div className="legend2" aria-label="Legend">
      <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
      <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
      <span><span className="mb-tag paper">paper</span> every signal and trade until proven</span>
      <span><StatusBadge status="confirmed_primary" /> <StatusBadge status="corroborated" /> can carry a call</span>
      <span><StatusBadge status="rumour" /> <StatusBadge status="promotional" /> never</span>
      <span>Click a company for its page, a ticker in a ranking for its strategies.</span>
    </div>
  );
}

export function HomeView({ p, market }: { p: HomePayload; market: Market }) {
  const [horizon, setHorizon] = useState<number>(p.default_horizon);
  const c: Ctx = { p, market, cur: p.currency, lt: p.status.session.local_time, horizon };
  const sd = p.status.session.session_date;
  const title = sd ? `${DOW_LONG[new Date(sd.slice(0, 10) + "T00:00:00Z").getUTCDay()]} ${fmtDate(sd, false)} ${sd.slice(0, 4)}` : "Home";
  return (
    <div className="mb-home">
      <PageHead page={p} title={title} subtitle={`${p.name} · the session being predicted · data as of the ${fmtDate(p.as_of, false)} close · research only, nothing here trades`} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} context="The ranking below says who agrees; it is not advice." />
      <Kpis c={c} />
      <div className="grid">
        <div className="col">
          <AgreementCard c={c} onHorizon={setHorizon} />
          <HeadToHeadCard c={c} />
        </div>
        <div className="col">
          <RuleVsAiCard c={c} />
          <AlertsCard c={c} />
          <NewsCard c={c} />
          <RunsCard c={c} />
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <OpenTradesCard trades={p.open_trades} checks={p.trade_checks} strategies={p.strategies} companies={p.companies} status={p.status} currency={p.currency} allTradesHref={pagePath(market, "portfolios")} />
      </div>
      <Legend />
      <PageFooter page={p} endpoint="home" />
    </div>
  );
}

export function HomePage({ market }: { market: Market }) {
  const res = usePage<HomePayload>(market, "home");
  return <PageState result={res}>{(p) => <HomeView key={market} p={p} market={market} />}</PageState>;
}
