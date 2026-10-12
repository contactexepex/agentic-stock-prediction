"use client";
// Page 01, Home (design/mockups/01-home/): first the reader's questions (docs/ux/plain_language_review.md section 3):
// "Can I rely on this yet?" (the go-live checklist, the model's skill, the paper trades so far) and "Today in 3 lines";
// then the session being predicted at a glance: who agrees at the selected horizon (decision 30), today's head-to-head
// paper trades and whether each clears costs (decision 51), Rule vs AI (the cumulative profit chart, the last close,
// the head-to-head results to date), the latest intraday alerts, the top market movers, the runs of the day and the
// open paper trades. The page's own computations are in lib/market-pages/home.ts and news.ts. Every signal is Paper
// until a strategy meets the go-live bar; nothing trades and nothing says buy or sell.
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { CostLabels } from "../../../../components/blocks/costs.tsx";
import { PageFooter, PageHead } from "../../../../components/blocks/page-head.tsx";
import { OpenTradesCard, strategyOf } from "../../../../components/blocks/records.tsx";
import { HorizonBars } from "../../../../components/charts/small.tsx";
import { AgreementBar } from "../../../../components/charts/small.tsx";
import { ChartLegend, LineChart } from "../../../../components/charts/line-chart.tsx";
import { HorizonTabs } from "../../../../components/ui/controls.tsx";
import { Icon } from "../../../../components/ui/icon.tsx";
import {
  Avatar, Card, CardHead, Delta, ExpectedMoney, FamilyLabel, GoLink, Kpi, KpiRow, Label, MoneyDelta, Odds, PaperTag, Quiet,
  SentimentSquare, StatusBadge,
} from "../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../components/ui/states.tsx";
import type { Market } from "../../../../lib/data/constants.ts";
import {
  cumulativeProfit, eodLeaders, expectedGainMoney, groupBy, INTRADAY_CHECKS_PER_SESSION, isPicked, moodLine, nearestLine,
  pickSummary, relyChecks, runsOk, storyLine, tradesLine, tradesSoFar, viableLineOf, type EodFamily, type Family,
  type HeadToHeadPick, type PickRule, type RunState,
} from "../../../../lib/market-pages/home.ts";
import { CAN_CARRY, HOME_NEWS_MAX, kindWord, movers, type NewsItem } from "../../../../lib/market-pages/news.ts";
import { agreementAt, sumMoney } from "../../../../lib/market-pages/watchlist.ts";
import {
  BAND, FAMILY, FLAG, importanceWords, MIN_TRADES_TO_RANK, PICK_RULE, WHY_NO_BUY_SELL_ANCHOR,
} from "../../../../lib/ui/constants.ts";
import { noneFinishedYet, runningLine, tooEarly } from "../../../../lib/ui/empty.ts";
import type { Pick as CostPick } from "../../../../lib/ui/costs.ts";
import { DOW_LONG, fmtDate, fmtLocal, holdLabel, horizonLabel, money, moneyDecimals, pct, price, signed } from "../../../../lib/ui/format.ts";
import { companyPath, pagePath, stockStrategiesPath } from "../../../../lib/ui/routes.ts";
import type {
  AgreementMap, AgreementRow, CompanyRecord, GoLive, GoLiveChecks, GoLiveNearest, OpenTrade, PageBase, SkillVerdict,
  StrategyMap, TradeCheck,
} from "../../../../lib/ui/types.ts";
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
  /* the "Can I rely on this yet?" block's fields (review D1-D4); optional, an older payload lacks them */
  go_live_checks?: GoLiveChecks;
  go_live_nearest?: GoLiveNearest | null;
  skill?: SkillVerdict;
  intraday_next_at?: string | null;
};

interface Ctx { p: HomePayload; market: Market; cur: string; lt: string | null | undefined; horizon: number }
const companyOf = (p: HomePayload, t: string) => p.companies.find((c) => c.ticker === t) ?? { ticker: t, name: t } as Pick<CompanyRecord, "ticker" | "name"> & Partial<CompanyRecord>;
const REFERENCE_ID = "rule.model_news.v1";
const SHORT_FAMILY: Record<Family, string> = { rule: "Rule", baseline: "Baselines", ai: "AI" };

function RelyBlock({ c }: { c: Ctx }) {
  const { p, market, cur } = c;
  const proven = p.go_live.proven;
  const checks = relyChecks(p.go_live, p.go_live_checks, p.skill);
  const near = nearestLine(p.go_live_nearest, REFERENCE_ID);
  const sofar = tradesSoFar(p.settled_trades);
  const pc = p.status.runs.post_close;
  const mark = (met: boolean | null) => (
    <span className={`mb-mark ${met == null ? "na" : met ? "ok" : "no"}`} role="img" aria-label={met == null ? "not measurable yet" : met ? "met" : "not met"}>
      <Icon name={met == null ? "help" : met ? "check" : "close"} />
    </span>
  );
  return (
    <section className={`md-card rely${proven ? " proven" : ""}`} aria-label="Can I rely on this yet?">
      <div className="rely-head">
        <h2>Can I rely on this yet?</h2>
        <b className="verdict">{proven ? "One strategy has passed the test" : "NOT YET"}</b>
        <Link className="why" href={`${pagePath(market, "help")}#${WHY_NO_BUY_SELL_ANCHOR}`}>Why? <Icon name="chevron_right" /></Link>
      </div>
      <p className="rely-lead">
        {proven
          ? "Even now, this shows what a tested strategy would do on paper. It is not advice, and nothing here tells you to buy or sell."
          : "Everything here is a test on paper. No real money moves, and nothing here tells you to buy or sell."}
        {" "}<PaperTag label={p.status.paper_label} />
      </p>
      <div className="rely-sub">What has to happen before any strategy counts as “proven”:</div>
      <ul className="rely-checks">
        {checks.map((x) => (
          <li key={x.key}>
            {mark(x.met)}
            <span className="w">{x.what}</span>
            <span className="d">
              {x.detail}
              {x.key === "skill" ? <>{" "}<Link href={pagePath(market, "track")}>Track record</Link></> : null}
            </span>
          </li>
        ))}
      </ul>
      {near ? <p className="rely-near">{near}</p> : null}
      <div className="rely-sofar">
        <b>Paper trades so far:</b>{" "}
        {sofar.finished
          ? <>{`${sofar.finished} finished · ${sofar.won} won · ${sofar.lost} lost · net `}<MoneyDelta currency={cur} value={sofar.net} decimals={moneyDecimals(cur)} />{` after market fees · ${runningLine(p.open_trades)}`}</>
          : `${noneFinishedYet(p.open_trades, pc?.next_at, market, c.lt)} ${p.open_trades.length} running now.`}
      </div>
    </section>
  );
}

function TodayBlock({ c }: { c: Ctx }) {
  const { p, market } = c;
  const top = movers(p.news, 1)[0];
  const lines = [
    moodLine(p.status.regime, p.status.benchmark, p.companies),
    tradesLine(p.open_trades, p.status.session.session_date),
    storyLine(top),
  ];
  return (
    <section className="md-card today" aria-label="Today in 3 lines">
      <h2>Today in 3 lines</h2>
      <ol>{lines.map((line, i) => <li key={i}>{line}</li>)}</ol>
      <GoLink href={pagePath(market, "portfolios")}>See all paper trades</GoLink>
    </section>
  );
}

function Kpis({ c }: { c: Ctx }) {
  const { p, market, cur, lt, horizon } = c;
  const lead: AgreementRow | undefined = (p.agreement[String(horizon)] ?? [])[0];
  const s = pickSummary(p.head_to_head);
  const unreal = sumMoney(p.open_trades.map((t) => t.unrealised_pnl));
  const flagged = p.trade_checks.filter((x) => x.flagged).length;
  return (
    <KpiRow>
      <Kpi icon="trending_up" label={`Most strategies like (${holdLabel(horizon)})`}
        value={lead && lead.buy ? <Link className="tk" href={stockStrategiesPath(market, lead.ticker)}>{lead.ticker}</Link> : "None"}
        sub={lead && lead.buy ? <span><Label tone="success">{`${lead.buy} of ${lead.of} would buy`}</Label>{lead.avg_prob_up != null ? ` avg chance ${pct(lead.avg_prob_up)}` : " no probability"}</span> : "no strategy would buy"}
        tip={`The company the largest number of test strategies would buy for this holding period (${horizonLabel(horizon)}). Agreement is not proof: they can all be wrong together.`} />
      <Kpi icon="layers" tone="info" label="Today’s test trades: rule vs AI" value={`${s.picked} trades`}
        sub={
          <span className="labs">
            <Label tone={s.clearMarket ? "success" : "neutral"} icon={s.clearMarket ? "check" : "close"}>{s.clearMarket ? `${s.clearMarket} expected to beat market fees` : "none expected to beat market fees"}</Label>
            <Label tone={s.viableYours ? "success" : "warn"} icon={s.viableYours ? "check" : "warning"}>{s.viableYours ? `${s.viableYours} worth it after your fees` : "none worth it after your fees"}</Label>
            <PaperTag label={p.status.paper_label} />
          </span>
        }
        tip="For each company, the best rule-based strategy and the best AI each make up to two paper trades, so we can compare them fairly on the same days. “Expected to beat market fees” = the expected gain is bigger than brokerage, taxes and exchange fees; “worth it after your fees” also counts your own broker’s extra charges." />
      <Kpi icon="account_balance_wallet" tone="paper" label="Paper trades running now" value={String(p.open_trades.length)}
        sub={<span><MoneyDelta currency={cur} value={unreal} decimals={moneyDecimals(cur)} /> so far, before fees</span>}
        tip="Paper trades entered and not yet sold, every strategy and holding period; the amount so far is against the latest stored close, before fees." />
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
        title={`Which companies most strategies would buy · ${holdLabel(horizon)}`}
        help="Companies ranked by how many strategies would buy them for this holding period (a call counts when it is “up” and at or above the strategy’s own bar), then by the average chance of a rise of those buyers. Rule, benchmark and AI strategies count alike; a click opens the company’s strategy page. Agreement is not proof: they can all be wrong together."
        end={<HorizonTabs horizons={p.horizons} value={horizon} onChange={onHorizon} />}
      />
      <div className="sub2">{`${rows.length} of ${active} active companies · ${holdLabel(horizon)}: buy at today’s open, sell at the close ${horizon} trading day${horizon === 1 ? "" : "s"} later · Paper ranking from today’s predictions`}</div>
      {!rows.some((r) => r.buy > 0) ? <Quiet>{`No strategy would buy any company for a ${holdLabel(horizon)} today.`}</Quiet> : (
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
                  <div className="sent"><b>{`${r.buy} of ${r.of}`}</b>{` strategies would buy for a ${holdLabel(r.horizon_days)}`}</div>
                  <AgreementBar byFamily={r.by_family} of={r.of} subject={`${co.name}, ${holdLabel(r.horizon_days)}`} />
                  <div className="fam">
                    {fams.map((f) => {
                      const x = r.by_family[f];
                      return (
                        <span key={f} data-tip={`${FAMILY[f][0]}: ${x.buy} of the ${x.of} that predict ${co.name} for a ${holdLabel(r.horizon_days)} would buy.`}>
                          <FamilyLabel family={f}>{`${FAMILY[f][0].split(" ")[0]} ${x.of ? `${x.buy}/${x.of}` : "—"}`}</FamilyLabel>
                        </span>
                      );
                    })}
                  </div>
                </div>
                <div className="hz">
                  <HorizonBars horizons={p.horizons} splits={p.horizons.map((k) => agreementAt(p.agreement, k, r.ticker))} selected={horizon} />
                  <small>buyers, 1 to 5-day holds</small>
                </div>
                <div className="right">
                  <Odds p={r.avg_prob_up} tip={r.avg_prob_up == null ? "Only always-buy and follow-yesterday buy it; neither gives a probability." : `Average probability of a rise given by the buyers that give one: ${pct(r.avg_prob_up, 1)}. 50% is a coin flip.`} />
                  <div className="l">{r.avg_prob_up == null ? "no probability" : <>avg. chance of a rise<small className="cf">50% = coin flip</small></>}</div>
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
    <Card label="Today’s test trades: rule vs AI">
      <CardHead
        title={<>Today’s test trades: rule vs AI <PaperTag label={p.status.paper_label} /></>}
        help="Each side picks the holding period it thinks is best, in two ways: the biggest expected gain and the highest chance of rising. Each pick is a paper trade of the company’s amount. “Expected” is the average result if the stated chances hold, not a result; the formula is on the Help page. “Worth it after your fees” also counts your own broker’s extra charges."
        end={<GoLink href={pagePath(market, "compare")}>Rule vs AI</GoLink>}
      />
      {!picks.length ? <Quiet>{`No rule-vs-AI picks for today’s session yet. The morning run makes them before the open${p.status.runs.pre_open.at ? "" : " (it has not run yet)"}.`}</Quiet> : (
        <>
          <div className="sumline">
            <Avatar icon={viable ? "check" : "info"} tone={viable ? "success" : "neutral"} size="sm" />
            <span>
              {`${picked.length} paper trades today across ${byTicker.length} compan${byTicker.length === 1 ? "y" : "ies"} · `}
              <b>{viableLineOf(picks)}</b>
              {" (worth it = the expected gain is bigger than all fees)"}
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
                    <span className="amt" data-tip={co.amount_overridden ? "This company has its own amount per paper trade." : "The market’s default amount per paper trade."}>{`${money(cur, ks[0].amount)} per trade${co.amount_overridden ? " (override)" : ""}`}</span>
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
          <p className="note">Expected = what the odds suggest, not what happened. It is in percent of the trade amount, from the latest close (the entry price is not known before the open). Every trade is Paper: a record, never an order.</p>
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
                <span className="h-lab" data-tip={horizonLabel(k.horizon_days ?? 0)}>{holdLabel(k.horizon_days ?? 0)}</span>
                <Odds p={k.prob_up} tip={`${pct(k.prob_up, 1)} chance of a rise from the open to the close ${k.horizon_days} trading day${k.horizon_days === 1 ? "" : "s"} later.`} />
                <span className="gain">
                  <ExpectedMoney currency={cur} value={expectedGainMoney(k)} decimals={moneyDecimals(cur)} />
                  <CostLabels currency={cur} pick={k as unknown as CostPick} />
                </span>
              </span>
              <span className="det">{`If right: ${signed(k.move_pct)} · if wrong: ${signed(k.loss_pct == null ? null : -k.loss_pct)} · fees ${k.costs_pct ?? "—"}%`}</span>
            </>
          )}
        </div>
      ))}
      {any && any.candidates ? (
        <details className="cand">
          <summary>{`Why this holding period: ${any.candidates.length} possible`}</summary>
          <div className="md-table-wrap">
            <table className="md-table">
              <thead><tr><th scope="col">Hold</th><th scope="col" className="num">Chance</th><th scope="col" className="num">If right</th><th scope="col" className="num">If wrong</th><th scope="col" className="num">Fees</th><th scope="col" className="num">Expected</th></tr></thead>
              <tbody>
                {any.candidates.map((cd) => (
                  <tr key={cd.horizon_days}>
                    <td>{holdLabel(cd.horizon_days)}</td><td className="num">{pct(cd.prob_up, 1)}</td><td className="num">{signed(cd.move_pct)}</td>
                    <td className="num">{signed(cd.loss_pct == null ? null : -cd.loss_pct)}</td><td className="num">{`${cd.costs_pct ?? "—"}%`}</td><td className="num">{signed(cd.expected_gain_pct)}</td>
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
        help="Who is better: profit after fees on the same companies and amounts. The chart adds up every finished paper trade (all trades view) by the day it finished. Last close: the after-close write-up. So far: the daily rule-vs-AI picks, per side and pick rule, every holding period together."
        end={<GoLink href={pagePath(market, "compare")}>Compare</GoLink>}
      />
      <div className="sub2">
        {profit.days.length ? `Cumulative profit after fees · ${profit.trades} finished paper trades, ${fmtDate(profit.days[0], false)}–${fmtDate(profit.days[profit.days.length - 1], false)} · Paper` : noneFinishedYet(p.open_trades, pc?.next_at, market, lt)}
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
        {pc && pc.at == null ? <span className="end">{`next after-close run ${fmtLocal(pc.next_at, market, lt)}`}</span> : null}
      </div>
      {!e ? <Quiet>{`The after-close write-up appears after the first trades finish${pc?.next_at ? ` (next after-close run ${fmtLocal(pc.next_at, market, lt, true)})` : ""}.`}</Quiet> : (
        <>
          <div className="lastclose" style={{ marginTop: 0 }}>
            {(["rule", "ai", "baseline"] as const).map((f) => {
              const x = e.results[f] ?? { trades: 0, wins: 0, net_pnl: null };
              const lead = leaders.has(f);
              return (
                <div key={f} className={`t${lead ? " lead" : ""}`} data-tip={`${FAMILY[f][0]}, all trades: ${x.trades} finished on ${fmtDate(e.session_date)}, ${x.wins} with a profit after fees.${lead ? " Led the day." : ""}`}>
                  <div className="l">{FAMILY[f][0].split(" ")[0]}</div>
                  <div className="v">{x.trades ? <MoneyDelta currency={cur} value={x.net_pnl} /> : <span className="muted">none</span>}</div>
                  <div className="s">{x.trades ? `${x.wins} of ${x.trades} won${lead ? " · led" : ""}` : "no trades"}</div>
                </div>
              );
            })}
          </div>
          <p className="note" style={{ marginTop: 10 }}>
            {e.summary}{" "}
            <Link href={pagePath(market, "compare")} data-tip={`The after-close write-up cites ${e.cited_ids.length} trades and ${e.reason_ids.length} AI reasons, each checked before it is stored.`}>reasons</Link>
          </p>
        </>
      )}
      <div className="head" style={{ margin: "16px 0 4px" }}>
        <h2 style={{ fontSize: 13.5 }}>Rule vs AI so far</h2>
        <button className="md-help" type="button" aria-label="Explain" data-tip={`One trade per company, side and pick rule each day. Profit after fees, finished trades and win rate. Under ${MIN_TRADES_TO_RANK} finished trades the numbers are mostly luck, so no winner is named yet.`}>?</button>
      </div>
      <div className="grid22">
        <div />
        {(["best_expected_gain", "highest_probability"] as PickRule[]).map((r) => <div className="hd" key={r}>{r === "best_expected_gain" ? "Picked for biggest expected gain" : "Picked for highest chance"}</div>)}
        {(["rule", "ai"] as const).map((f) => [
          <div className="rh" key={`h-${f}`}><Icon name={FAMILY[f][1]} />{SHORT_FAMILY[f]}</div>,
          ...(["best_expected_gain", "highest_probability"] as PickRule[]).map((r) => {
            const row = p.to_date.find((x) => x.family === f && x.pick_rule === r);
            if (!row) return <div className="cell none" key={`${f}-${r}`}>{runningLine(p.open_trades.filter((t) => t.view === "head_to_head" && t.family === f))}</div>;
            return (
              <div className="cell" key={`${f}-${r}`}>
                <div className="v"><MoneyDelta currency={cur} value={row.net_pnl} /></div>
                <div className="s">
                  {`${row.trades} trade${row.trades === 1 ? "" : "s"} · ${pct(row.win_rate)} won `}
                  {row.sample_badge === "too_few_to_rank" ? <span className="mb-label neutral" style={{ fontSize: 10.5, padding: "0 5px" }} data-tip={`Under ${MIN_TRADES_TO_RANK} finished trades: the number is shown but proves nothing yet.`}>{tooEarly(row.trades)}</span> : null}
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
      {!first ? <Quiet>{`No intraday check stored yet today. Checks run ${INTRADAY_CHECKS_PER_SESSION === 2 ? "twice" : `${INTRADAY_CHECKS_PER_SESSION} times`} per session; the first one fills this card${p.intraday_next_at ? ` (next check around ${fmtLocal(p.intraday_next_at, market, lt, true)})` : ""}.`}</Quiet>
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
                    <small>{cks.map((x) => `${strategyOf(p.strategies, x.strategy_id).name} ${holdLabel(x.horizon_days)} (${(BAND[x.band] ?? [x.band])[0]}, day ${x.session_number ?? "—"})`).join(" · ")}</small>
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
        help="The stories most likely to move prices in the last three days: big company news, results, and market-wide news (rates, inflation, oil), newest first. Each links to its article. Only a story confirmed by an official filing or reported independently by two or more outlets can be the main reason for a prediction. The News page has every story of the window with filters and the calendar."
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
                  {n.status ? <StatusBadge status={n.status} /> : <Label tone="neutral" tip="Checking is done per company, so a market-wide story has no check status.">market-wide news</Label>}
                  {n.market_moving ? <Label tone="warn" icon="warning">likely to move prices</Label> : null}
                  {n.primary_tickers.map((t) => <Link key={t} className="tk" href={companyPath(market, t)}>{t}</Link>)}
                  <span>{`${n.source ?? "Unknown outlet"} · ${importanceWords(n.enrichment.materiality)} · ${n.scope === "market" ? (n.category && n.category !== "company" && n.category !== "general" ? n.category : "market-wide") : kindWord(n)}`}</span>
                </small>
              </div>
            </li>
          ))}
        </ul>
      ) : <Quiet>{`No market-moving story in the last 3 days (${items.length} stored in the window).`}</Quiet>}
      <p className="note" style={{ margin: "8px 0 0" }}>
        {`${items.length} stor${items.length === 1 ? "y" : "ies"} in the last 3 days, ${carry} checked (confirmed or reported by two or more outlets). `}
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
        help="Did today’s automatic steps run? A tick = finished and checked. The full schedule is on the Help page."
        end={<Label tone={ok === total ? "success" : "neutral"}>{`${ok} of ${total} ok`}</Label>}
      />
      <ul className="runs">
        {item("pre", r.pre_open.ok, "Morning run", "prices and news · model · strategies · AI traders · picks", fmtLocal(r.pre_open.at, market, lt))}
        {Array.from({ length: INTRADAY_CHECKS_PER_SESSION }, (_, i) => {
          const x = r.intraday[i];
          return x
            ? item(`i${i}`, x.ok, `Intraday check ${i + 1}`, "open trades vs range and target", fmtLocal(x.at, market, lt))
            : item(`i${i}`, null, `Intraday check ${i + 1}`, "open trades vs range and target · not yet", i === r.intraday.length && p.intraday_next_at ? <span><small>next </small>{fmtLocal(p.intraday_next_at, market, lt)}</span> : "—");
        })}
        {item("post", r.post_close.ok, "After-close run", r.post_close.at ? "finished trades settled · end-of-day write-up" : "finished trades settled · end-of-day write-up · not yet",
          r.post_close.at ? fmtLocal(r.post_close.at, market, lt) : <span><small>next </small>{fmtLocal(r.post_close.next_at, market, lt)}</span>)}
        {item("news", r.news.ok, "News (latest run)", `several times a day · ${r.news.new_items ?? 0} new items`, fmtLocal(r.news.at, market, lt))}
      </ul>
      <p className="note">{`Every number on this page was stored by ${fmtLocal(p.cutoff, market, lt, true)}.`}</p>
    </Card>
  );
}

function Legend() {
  return (
    <div className="legend2" aria-label="Legend">
      <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
      <span><span className="mb-expected">Expected <b>+1.2%</b></span> = what the odds suggest, not what happened</span>
      <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
      <span><span className="mb-tag paper">paper</span> every signal and trade until proven</span>
      <span><StatusBadge status="confirmed_primary" /> <StatusBadge status="corroborated" /> checked: can be the main reason for a prediction</span>
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
      <PageHead page={p} title={title} subtitle={`${p.name} · what the strategies expect for ${sd ? `${fmtDate(sd)}’s` : "the next"} trading · data up to the ${fmtDate(p.as_of, false)} close · research only, nothing here trades`} />
      <div className="top2">
        <RelyBlock c={c} />
        <TodayBlock c={c} />
      </div>
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
