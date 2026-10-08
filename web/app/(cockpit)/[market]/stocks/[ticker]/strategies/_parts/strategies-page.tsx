"use client";
// Page 04, Stock strategies (design/mockups/04-stock-strategies/, SPEC section 6 page 4): for one company, who agrees
// at each horizon, today's head-to-head picks and why, the best strategy on this company beside the best overall (the
// luck guard of SPEC section 6), and every strategy ranked by profit after costs with its prediction for today.
// Reads GET /api/v1/markets/{market}/stocks/{ticker}/strategies (B12, rm.stock_strategies). Research only, Paper.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CostLabels, viableLine, yourViable } from "../../../../../../../components/blocks/costs.tsx";
import { PageFooter, PageHead, SignalsBand } from "../../../../../../../components/blocks/page-head.tsx";
import { strategyOf } from "../../../../../../../components/blocks/records.tsx";
import { RangeBar } from "../../../../../../../components/charts/small.tsx";
import { HorizonTabs } from "../../../../../../../components/ui/controls.tsx";
import { Icon } from "../../../../../../../components/ui/icon.tsx";
import { Avatar, Card, CardHead, Delta, FamilyLabel, GoLink, Kpi, KpiRow, Label, MoneyDelta, Odds, PaperTag, Quiet } from "../../../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../../../components/ui/states.tsx";
import { FAMILY, FAMILY_SHORT, MARKET_LABEL, MIN_TRADES_TO_RANK, PICK_RULE, type Family } from "../../../../../../../lib/ui/constants.ts";
import { fmtDate, horizonWords, money, moneyDecimals, pct, price, signed } from "../../../../../../../lib/ui/format.ts";
import { companyPath, pagePath } from "../../../../../../../lib/ui/routes.ts";
import { usePage } from "../../../../../../../lib/ui/use-api.ts";
import type { Market } from "../../../../../../../lib/data/constants.ts";
import type { StrategyMap } from "../../../../../../../lib/ui/types.ts";
import { bandsOf } from "../../../../../../../lib/company-pages/company-logic.ts";
import { agreementAt, bestOf, buyShare, expectedGainMoney, isRanked, pooledRows, rankedIds } from "../../../../../../../lib/company-pages/strategies-logic.ts";
import type { HeadToHeadPick, ScoreRow, StockStrategiesPayload } from "../../../../../../../lib/company-pages/types.ts";
import { StrategiesLegend } from "../../_parts/legend.tsx";
import "./strategies.css";

const FAMILIES: Family[] = ["rule", "baseline", "ai"];

/** The luck test's words (F7.1): the uncorrected interval and, when stored, the Bonferroni-corrected one. */
function luck(r: ScoreRow): string {
  const t = r.luck_test;
  if (!t || t.low_pct == null) return "luck test: one trade, no interval yet.";
  const corr = t.corrected_low_pct != null
    ? ` Corrected for the ${t.m} rows compared at once: ${signed(t.corrected_low_pct)} to ${signed(t.corrected_high_pct)}, which ${t.corrected ? "excludes zero: an edge may be real" : "does not exclude zero: no edge claimed"}.`
    : "";
  return `luck test (${t.method.replace(/_/g, " ")}, ${t.n} trades): mean return per trade ${signed(t.low_pct)} to ${signed(t.high_pct)} (95% interval, uncorrected).${corr}`;
}

function Kpis({ p, horizon, strategies }: { p: StockStrategiesPayload; horizon: number; strategies: StrategyMap }) {
  const cur = p.currency, dec = moneyDecimals(cur), a = agreementAt(p.agreement, horizon);
  const picks = p.head_to_head.filter((k) => k.status === "picked");
  const viable = picks.filter((k) => k.expected_gain_pct > 0).length, yours = picks.filter((k) => yourViable(k) === true).length;
  const bestHere = bestOf(pooledRows(p.on_company)), bestAll = bestOf(pooledRows(p.overall));
  const few = (r: ScoreRow) => (r.sample_badge === "too_few_to_rank" ? <Label tone="neutral">too few to rank</Label> : null);
  return (
    <KpiRow>
      <Kpi icon="trending_up" tone="success" label={`Agreement at N+${horizon}`} value={a ? `${a.buy} of ${a.of}` : "—"}
        sub={a ? <span>strategies buy · {a.avg_prob_up != null ? `avg chance ${pct(a.avg_prob_up)}` : "no probability"}</span> : "no agreement row"}
        tip="How many of the strategies that predict this company at the selected horizon would buy it (decision 30)." />
      <Kpi icon="settings" label="Best on this company" value={bestHere ? strategyOf(strategies, bestHere.strategy_id).name : "None yet"}
        sub={bestHere ? <span><MoneyDelta currency={cur} value={bestHere.net_pnl} decimals={dec} /> on {bestHere.trades} trade{bestHere.trades === 1 ? "" : "s"} {few(bestHere)}</span> : "no settled trade on it"}
        tip={bestHere ? `Profit after costs on this company, all horizons pooled. ${luck(bestHere)} Under ${MIN_TRADES_TO_RANK} trades it is mostly noise (SPEC section 6).` : "No strategy has a settled trade on this company yet."} />
      <Kpi icon="query_stats" tone="info" label="Best overall" value={bestAll ? strategyOf(strategies, bestAll.strategy_id).name : "None yet"}
        sub={bestAll ? <span><MoneyDelta currency={cur} value={bestAll.net_pnl} decimals={dec} /> on {bestAll.trades} trade{bestAll.trades === 1 ? "" : "s"}, all companies {few(bestAll)}</span> : "no settled trade"}
        tip={bestAll ? `The market's best strategy by profit after costs across all companies, shown beside the per-company best as the luck guard of SPEC section 6. ${luck(bestAll)}` : undefined} />
      <Kpi icon="layers" tone="paper" label="Head-to-head today" value={`${picks.length} trade${picks.length === 1 ? "" : "s"}`}
        sub={picks.length ? (
          <span className="labs">
            <Label tone={viable ? "success" : "neutral"} icon={viable ? "check" : "close"}>{viable ? `${viable} clear market costs` : "none clears market costs"}</Label>
            <Label tone={yours ? "success" : "warn"} icon={yours ? "check" : "warning"}>{yours ? `${yours} viable at your cost` : "none viable at your cost"}</Label>
            <PaperTag label={p.status.paper_label} />
          </span>
        ) : "no candidate today"}
        tip="Up to four paper trades on this company today: the strongest rule strategy and the strongest AI trader × two pick rules (decisions 41-42). “Clears market costs” is the ranking view; “viable at your cost” adds your own broker’s charges (decision 51)." />
    </KpiRow>
  );
}

/** Grouped stacked bars: buyers per horizon by family; the selected horizon full, the others dimmed. */
function AgreementChart({ p, horizon, onPick }: { p: StockStrategiesPayload; horizon: number; onPick: (k: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
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
  const W = Math.max(240, width), H = W < 480 ? 170 : 200, L = 30, R = 10, T = 22, B = 28;
  const rows = p.horizons.map((k) => agreementAt(p.agreement, k));
  const max = Math.max(1, ...rows.map((a) => (a ? a.of : 0)));
  const Y = (v: number) => T + ((max - v) / max) * (H - T - B);
  const slot = (W - L - R) / p.horizons.length, bw = Math.min(56, slot * 0.5);
  return (
    <div className="agc" ref={ref}>
      {width ? (
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="Buyers per horizon by family">
          {rows.map((a, i) => {
            const k = p.horizons[i], x = L + slot * i + (slot - bw) / 2, on = k === horizon;
            if (!a) return null;
            let y = Y(0);
            const rects = FAMILIES.map((f) => {
              const nf = a.by_family[f].buy;
              if (!nf) return null;
              const h = Y(0) - Y(nf);
              y -= h;
              return <rect key={f} className={FAMILY[f][2] + (on ? "" : " dim")} x={x} y={y} width={bw} height={h} rx={2} />;
            });
            const tip = `N+${k}: ${a.buy} of ${a.of} buy · rule ${a.by_family.rule.buy}/${a.by_family.rule.of}, baselines ${a.by_family.baseline.buy}/${a.by_family.baseline.of}, AI ${a.by_family.ai.buy}/${a.by_family.ai.of}${a.avg_prob_up != null ? ` · avg chance ${pct(a.avg_prob_up)}` : ""}. Click to select.`;
            return (
              <g key={k}>
                {rects}
                <text className="tot" x={x + bw / 2} y={Y(a.buy) - 6} textAnchor="middle">{a.buy}/{a.of}</text>
                <rect className="hit" x={L + slot * i} y={T} width={slot} height={H - T - B} tabIndex={0} role="button" aria-label={tip} data-tip={tip}
                  onClick={() => onPick(k)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(k); } }} />
              </g>
            );
          })}
          <g className="grid">{[0, Math.round(max / 2), max].map((v) => <line key={v} x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} />)}</g>
          <g className="axis">
            {[0, Math.round(max / 2), max].map((v) => <text key={v} x={L - 6} y={Y(v) + 4} textAnchor="end">{v}</text>)}
            {p.horizons.map((k, i) => <text key={k} className={"tick" + (k === horizon ? " on" : "")} x={L + slot * i + slot / 2} y={H - 8} textAnchor="middle">N+{k}</text>)}
          </g>
        </svg>
      ) : null}
    </div>
  );
}

function AgreementCard({ p, horizon, onPick }: { p: StockStrategiesPayload; horizon: number; onPick: (k: number) => void }) {
  const a = agreementAt(p.agreement, horizon);
  return (
    <Card label="Who agrees, by horizon">
      <CardHead title="Who agrees, by horizon"
        help="For each horizon N+1..N+5: how many strategies would buy this company (a call counts when it is “up” and at or above the strategy’s own bar), stacked by family. Rule strategies and baselines predict every horizon; AI traders predict N+1, N+3 and N+5 (decision 38). Click a horizon or use the tabs."
        end={<HorizonTabs horizons={p.horizons} value={horizon} onChange={onPick} />} />
      <div className="sub2">N+{horizon} = {horizonWords(horizon)} · as of the {fmtDate(p.as_of, false)} close · Paper</div>
      <AgreementChart p={p} horizon={horizon} onPick={onPick} />
      <div className="agl">
        {a ? FAMILIES.map((f) => {
          const x = a.by_family[f];
          return (
            <div className="row" key={f}>
              <span className="l"><i className={`sw ${FAMILY[f][2]}`} />{FAMILY_SHORT[f]}</span>
              <div className="bar" role="img" aria-label={`${FAMILY[f][0]} ${x.buy} of ${x.of}`}><i className={`ser-${FAMILY[f][2]}`} style={{ width: `${buyShare(x).toFixed(1)}%` }} /></div>
              <b>{x.of ? `${x.buy} of ${x.of}` : "no prediction"}</b>
            </div>
          );
        }) : null}
      </div>
      <p className="note">
        {a ? `${a.label}${a.avg_prob_up != null ? `; the buyers’ average chance of a rise is ${pct(a.avg_prob_up)}` : ""}. A majority says the strategies lean the same way; it does not say they are right (see the track record).` : "No agreement row for this horizon."}
      </p>
    </Card>
  );
}

function FamilyBox({ family, picks, p, strategies }: { family: "rule" | "ai"; picks: HeadToHeadPick[]; p: StockStrategiesPayload; strategies: StrategyMap }) {
  const cur = p.currency, dec = moneyDecimals(cur);
  const any = picks.find((k) => k.status === "picked"), st = any?.strategy_id ? strategyOf(strategies, any.strategy_id) : null;
  const basis = any?.strongest_basis === "per_company" ? "this company" : "all companies";
  return (
    <div className="fam-box">
      <div className="fh">
        <Avatar icon={FAMILY[family][1]} tone={family === "ai" ? "info" : ""} size="sm" />
        <b>{FAMILY_SHORT[family]}</b>
        {st && any ? (
          <small tabIndex={0} data-tip={`${st.name} (${any.strategy_id}) is the family’s strongest strategy with a buyable horizon today, ranked on ${any.strongest_basis === "per_company" ? `this company (${MIN_TRADES_TO_RANK}+ settled trades on it)` : `all companies (fewer than ${MIN_TRADES_TO_RANK} settled trades on this one)`}. Ranking: ${(any.ranking ?? []).map((x) => `${x.rank}. ${strategyOf(strategies, x.strategy_id).name} ${money(cur, x.net_pnl, dec, true)} on ${x.settled_trades}`).join(" · ")}.`}>
            · {st.name} · ranked on {basis}
          </small>
        ) : <small>· no candidate</small>}
      </div>
      {picks.map((k) => (
        <div className="pk" key={k.id}>
          <span className="rule">{PICK_RULE[k.pick_rule] ?? k.pick_rule}</span>
          {k.status !== "picked" ? <span className="line muted">no candidate</span> : (
            <>
              <span className="line">
                <span className="h-lab">N+{k.horizon_days}</span>
                <Odds p={k.prob_up} tip={`${pct(k.prob_up, 1)} chance of a rise from the open to the N+${k.horizon_days} close (prediction ${k.prediction_id}).`} />
                <span className="gain"><MoneyDelta currency={cur} value={expectedGainMoney(k.expected_gain_pct, k.amount)} decimals={dec} /><CostLabels currency={cur} pick={k} /></span>
              </span>
              <span className="det">to target {signed(k.move_pct)} · downside {signed(-k.loss_pct)} · costs {k.costs_pct}%</span>
            </>
          )}
        </div>
      ))}
      {any?.candidates?.length ? (
        <details className="cand">
          <summary>Why these horizons: {any.candidates.length} buyable horizons</summary>
          <div className="md-table-wrap">
            <table className="md-table">
              <thead><tr><th>Horizon</th><th className="num">Chance</th><th className="num">To target</th><th className="num">Downside</th><th className="num">Market costs</th><th className="num">Expected</th><th className="num">Your costs</th><th>Viable</th></tr></thead>
              <tbody>
                {any.candidates.map((cd) => (
                  <tr key={cd.horizon_days}>
                    <td>N+{cd.horizon_days}</td>
                    <td className="num">{pct(cd.prob_up, 1)}</td>
                    <td className="num">{signed(cd.move_pct)}</td>
                    <td className="num">{cd.loss_pct == null ? "—" : signed(-cd.loss_pct)}</td>
                    <td className="num">{cd.costs_pct == null ? "—" : `${cd.costs_pct}%`}</td>
                    <td className="num"><Delta value={cd.expected_gain_pct} /></td>
                    <td className="num">{cd.your_cost_pct != null ? `${cd.your_cost_pct}%` : "—"}</td>
                    <td>{cd.cost_viable == null ? "—" : cd.cost_viable ? <Label tone="success">yes</Label> : <Label tone="warn">no</Label>}</td>
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

function HeadToHeadCard({ p, strategies }: { p: StockStrategiesPayload; strategies: StrategyMap }) {
  const ks = p.head_to_head, picked = ks.filter((k) => k.status === "picked"), viable = picked.filter((k) => k.expected_gain_pct > 0);
  return (
    <Card label="Today’s head-to-head picks">
      <CardHead
        title={<>Today’s head-to-head picks <PaperTag label={p.status.paper_label} /></>}
        help={`Decisions 41-42: the strongest rule strategy and the strongest AI trader each choose one horizon under two pick rules: best expected gain (the horizon with the highest p × move − (1 − p) × loss − costs) and highest probability. “Strongest” = the family’s best profit after costs on this company once it has ${MIN_TRADES_TO_RANK} settled trades on it, else across all companies. A pick clears market costs when its expected gain after the market charges is above zero; “viable at your cost” (decision 51) adds your own broker’s charges.`}
        end={<GoLink href={pagePath(p.market, "compare")}>Rule vs AI</GoLink>}
      />
      {!ks.length ? <Quiet>No head-to-head picks stored for today’s session.</Quiet> : (
        <>
          <div className="sumline">
            <Avatar icon={viable.length ? "check" : "info"} tone={viable.length ? "success" : "neutral"} size="sm" />
            <span>{picked.length ? <span>{picked.length} paper trade{picked.length === 1 ? "" : "s"} of {money(p.currency, ks[0].amount)} each · <b>{viableLine(picked)}</b></span> : <b>No candidate today</b>}</span>
          </div>
          {picked.length ? (
            <div className="fams">
              {(["rule", "ai"] as const).map((f) => <FamilyBox key={f} family={f} picks={ks.filter((k) => k.family === f)} p={p} strategies={strategies} />)}
            </div>
          ) : <Quiet>No rule strategy and no AI trader buys {p.company.name} at any horizon today, so no head-to-head trade.</Quiet>}
          {picked.length ? <p className="note">Expected gain is in percent of the trade amount, from the latest close. Every trade is Paper: a record, never an order.</p> : null}
        </>
      )}
    </Card>
  );
}

function RankedCard({ p, horizon, onPick, strategies }: { p: StockStrategiesPayload; horizon: number; onPick: (k: number) => void; strategies: StrategyMap }) {
  const cur = p.currency, dec = moneyDecimals(cur), c = p.company;
  const rows = pooledRows(p.on_company), byId = new Map(rows.map((r) => [r.strategy_id, r]));
  const overall = new Map(pooledRows(p.overall).map((r) => [r.strategy_id, r]));
  const preds = new Map(p.predictions.filter((r) => r.horizon_days === horizon).map((r) => [r.strategy_id, r]));
  const ids = rankedIds(Object.keys(strategies), rows), best = bestOf(rows);
  let rank = 0;
  return (
    <Card label="Every strategy on this company">
      <CardHead
        title={`Every strategy on ${c.name}`}
        help={`All ${ids.length} strategies, baselines included, ranked by profit after costs on this company (accuracy view, all horizons pooled). Fewer than ${MIN_TRADES_TO_RANK} settled trades on it is “too few to rank” and greyed: a handful of trades is mostly luck (SPEC section 6). Beside each profit: the trades it rests on and the luck test’s interval in the tooltip. “Today” is the strategy’s prediction for the selected horizon: its chance of a rise, target and range, and whether it would trade.`}
        end={<>today at N+{horizon}<HorizonTabs horizons={p.horizons} value={horizon} onChange={onPick} /></>}
      />
      <div className="md-table-wrap">
        <table className="md-table tbl rk" aria-label={`Every strategy on ${c.name}`}>
          <thead>
            <tr>
              <th className="cm" scope="col">#</th><th scope="col">Strategy</th><th className="num" scope="col">Profit after costs</th><th className="num cm" scope="col">Trades</th>
              <th className="num cw" scope="col">Win rate</th><th className="num cw" scope="col">Target error</th><th className="c4" scope="col">Overall</th>
              <th scope="col">Today at N+{horizon}</th><th className="c2" scope="col">Range</th>
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => {
              const st = strategies[id], r = byId.get(id), o = overall.get(id), pr = preds.get(id);
              if (isRanked(r)) rank += 1;
              const bands = pr ? bandsOf(pr) : null;
              const cls = [r ? (r.sample_badge === "too_few_to_rank" ? "few" : "") : "none", best && r === best ? "best" : ""].filter(Boolean).join(" ");
              const sub = st.differs_in ? `differs from the reference in ${st.differs_in.replace(/_/g, " ")}` : st.family === "baseline" ? "yardstick, not a contender" : st.family === "ai" ? (st.parameters?.sees_model_score ? "sees the model score" : "blind to the model score") : "the reference rule strategy";
              const predicts = (st.horizons ?? p.horizons).includes(horizon);
              return (
                <tr key={id} className={cls || undefined}>
                  <td className="rank cm">{isRanked(r) ? String(rank) : "—"}</td>
                  <td>
                    <span className="nm">
                      <b><Link className="tk" href={`${pagePath(p.market, "lab")}#${id}`} data-tip={`${st.description ?? st.name} Open it in the Strategy lab.`}>{st.name}</Link> <FamilyLabel family={st.family}>{FAMILY_SHORT[st.family]}</FamilyLabel></b>
                      <small>{sub}</small>
                    </span>
                  </td>
                  <td className="num pn">
                    {r ? (
                      <span data-tip={luck(r)} tabIndex={0}>
                        <b><MoneyDelta currency={cur} value={r.net_pnl} decimals={dec} /></b>
                        <small>on {r.trades} trade{r.trades === 1 ? "" : "s"}<span className="sep"> · </span>{r.sample_badge === "too_few_to_rank" ? <span>too few to rank<span className="sep"> · </span></span> : null}{signed(r.mean_return_pct)}/trade</small>
                      </span>
                    ) : <span className="muted" tabIndex={0} data-tip="No settled paper trade on this company yet.">no trades yet</span>}
                  </td>
                  <td className="num cm">{r ? String(r.trades) : "0"}</td>
                  <td className="num cw">{r ? pct(r.win_rate) : "—"}</td>
                  <td className="num cw">{r ? <span tabIndex={0} data-tip="Average distance of the exit close from the predicted target, in percent.">{signed(r.avg_target_error_pct)}</span> : "—"}</td>
                  <td className="c4 ov">
                    {o ? <span tabIndex={0} data-tip={`All companies, all horizons: ${o.trades} trades, ${pct(o.win_rate)} won. ${luck(o)}`}><b><MoneyDelta currency={cur} value={o.net_pnl} decimals={dec} /></b><small>{o.trades} trades, all companies</small></span> : <span className="muted">—</span>}
                  </td>
                  <td>
                    {pr ? (
                      <span className="call">
                        {pr.prob_up != null ? (
                          <Odds p={pr.prob_up} tip={`${pct(pr.prob_up, 1)} chance of a rise from the open to the N+${horizon} close${pr.model_prob != null ? ` (model ${pct(pr.model_prob, 1)}, adjustment ${signed((pr.agent_adjustment ?? 0) * 100, 1)}: ${pr.adjustment_reason || "none"})` : ""}.${pr.reason ? " " + pr.reason : ""}`} />
                        ) : <span className="muted" tabIndex={0} data-tip="Always-buy and follow-yesterday give a direction, not a probability.">{pr.direction === "up" ? "up, no probability" : "down"}</span>}
                        {pr.qualifies ? (
                          <Label tone="success" icon="check" tip={`Up call at or above the strategy’s bar${pr.threshold != null ? ` (${pct(pr.threshold)})` : ""}: it would buy ${c.name} at the open for N+${horizon}. Paper.`}>would buy</Label>
                        ) : (
                          <Label tone="neutral" tip={pr.direction === "down" ? "A down call: scored as a prediction, never traded (decision 3)." : `Up call below the strategy’s bar${pr.threshold != null ? ` (${pct(pr.threshold)})` : ""}, or filtered out by its regime rule: no trade.`}>{pr.direction === "down" ? "down, no trade" : "no trade"}</Label>
                        )}
                        <span className="muted" style={{ fontSize: 12 }} tabIndex={0} data-tip={`Target ${price(cur, pr.target_price)} = the expected exit close; 80% range ${price(cur, pr.lo80)}–${price(cur, pr.hi80)}${pr.range_widen ? ` (widened ${Math.round(pr.range_widen * 100)}% by the trader)` : ""}.`}>target {price(cur, pr.target_price)}</span>
                      </span>
                    ) : (
                      <span className="muted" tabIndex={0} data-tip={predicts ? "No prediction stored for this horizon." : `This strategy predicts N+${(st.horizons ?? []).join(", N+")} only (decision 38).`}>{predicts ? "—" : `not at N+${horizon}`}</span>
                    )}
                  </td>
                  <td className="c2">{bands ? <RangeBar currency={cur} bands={bands} last={c.last_close ?? null} /> : <span className="muted">—</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="note">Profit after costs on {c.name}, every horizon pooled, accuracy view (one paper trade per qualifying prediction, {money(cur, c.amount)} each). The best strategy here is outlined; the best overall is in the card above, so a lucky handful of trades does not pass for skill.</p>
    </Card>
  );
}

function StrategiesBody({ p }: { p: StockStrategiesPayload }) {
  const opening = typeof p.default_horizon === "number" ? p.default_horizon : p.horizons[0] ?? 1;
  const [horizon, setHorizon] = useState<number>(opening);
  const c = p.company, cur = p.currency;
  return (
    <>
      <PageHead page={p} title={`${c.ticker} · ${c.name}`}
        subtitle={`${c.sector ?? "sector not set"} · ${p.name} · ${money(cur, c.amount)} per paper trade${c.amount_overridden ? " (override)" : ""} · data as of the ${fmtDate(p.as_of, false)} close · research only`}>
        <div className="cohead" style={{ marginTop: 6 }}>
          <span className="px">{price(cur, c.last_close)}</span>
          <Delta value={c.change_pct} />
          <span className="muted" style={{ fontSize: 12.5 }}>last close, {fmtDate(c.last_close_date)}</span>
          <Link className="md-btn text small" href={companyPath(p.market, c.ticker)}>Company page<Icon name="chevron_right" /></Link>
        </div>
      </PageHead>
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      <Kpis p={p} horizon={horizon} strategies={p.strategies} />
      <div className="grid even">
        <AgreementCard p={p} horizon={horizon} onPick={setHorizon} />
        <HeadToHeadCard p={p} strategies={p.strategies} />
      </div>
      <div style={{ marginTop: 16 }}><RankedCard p={p} horizon={horizon} onPick={setHorizon} strategies={p.strategies} /></div>
      <StrategiesLegend />
      <PageFooter page={p} endpoint={`stocks/${c.ticker}/strategies`} />
    </>
  );
}

export function StockStrategiesPage({ market, ticker }: { market: Market; ticker: string }) {
  const res = usePage<StockStrategiesPayload>(market, "stocks/{ticker}/strategies", { ticker });
  return (
    <PageState result={res} loadingLabel={`Loading the strategies on ${ticker} (${MARKET_LABEL[market]})`}>
      {(p) => <StrategiesBody key={`${p.market}/${p.ticker}`} p={p} />}
    </PageState>
  );
}
