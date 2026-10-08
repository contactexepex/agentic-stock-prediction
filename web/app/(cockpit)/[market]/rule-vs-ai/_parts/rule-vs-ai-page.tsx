"use client";
// Page 06, Rule vs AI (B16; design/mockups/06-rule-vs-ai): the head-to-head view on identical company-days: the
// scorecard (strongest rule strategy vs strongest AI trader), today's picks with their cost viability, the matches,
// the pick-rule and regime slices, per company, the cumulative lines, the end-of-day analyst and the week's research
// review with its news-impact study. Reads GET /api/v1/markets/{market}/compare (B13's rm.compare) and
// GET /api/v1/markets/{market}/review (rm.review). Paper trades only; nothing here is advice.
import Link from "next/link";
import { useState } from "react";
import { PageFooter, PageHead, SignalsBand } from "../../../../../components/blocks/page-head.tsx";
import { LineChart } from "../../../../../components/charts/line-chart.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Avatar, Card, CardHead, FamilyLabel, GoLink, Label, MoneyDelta, Odds, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { ErrorState, LoadingState, PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import { FAMILY, FAMILY_SHORT, MIN_TRADES_TO_RANK, PAPER_LABEL, PICK_RULE, type Family } from "../../../../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtDateYear, money, moneyDecimals, pct, signed } from "../../../../../lib/ui/format.ts";
import { companyPath, pagePath } from "../../../../../lib/ui/routes.ts";
import type { GoLive, PageBase } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import { figure, REGIME_WORDS, tooFewToRank, type CostView, type ScoreboardRow } from "../../../../../lib/strategy-pages/scoreboard.ts";
import {
  familyLines, familyRow, matches, matchTally, matchWinner, perCompany, pickCandidate, pickFor, tradeNet, tradeReturn,
  viableLine, whoLeads, type Match, type Pick, type ReviewPayload, type RuleVsAiPayload, type SettledTrade,
} from "../../../../../lib/strategy-pages/rule-vs-ai.ts";
import { CostSwitch, LuckBar } from "../../_b16/parts.tsx";
import "./rule-vs-ai.css";

type Payload = PageBase & RuleVsAiPayload & { go_live: GoLive | null };
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const familyIcon = (f: Family) => FAMILY[f][1];

export function RuleVsAiPage({ market }: { market: Market }) {
  const res = usePage<Payload>(market, "compare");
  return (
    <div className="p-compare">
      <PageState result={res}>{(p) => <RuleVsAi key={p.market} p={p} market={market} />}</PageState>
    </div>
  );
}

function RuleVsAi({ p, market }: { p: Payload; market: Market }) {
  const [cost, setCost] = useState<CostView>("market");
  return (
    <>
      <PageHead page={p} title="Rule vs AI" subtitle={`head-to-head paper trades on identical company-days · ${p.name} · data as of the ${fmtDate(p.as_of, false)} close · research only`} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      <div className="ctrls">
        <CostSwitch value={cost} onChange={setCost} help="Market cost: brokerage, taxes and fees (the ranking view). Your cost adds your own broker’s charges; the go-live bar uses it (decision 50). The switch changes the scorecard, the slice tables, the matches and the per-company sums (per-trade your-cost figures from the cost views; a figure not stored says so); the cumulative lines and the EOD analyst stay on market cost." />
      </div>
      <div style={{ marginTop: 16 }}><Scorecard p={p} cost={cost} /></div>
      <div style={{ marginTop: 16 }}><Picks p={p} /></div>
      <div style={{ marginTop: 16 }}><Matches p={p} cost={cost} /></div>
      <div style={{ marginTop: 16 }}><Slices p={p} cost={cost} /></div>
      <div className="grid even">
        <PerCompany p={p} cost={cost} />
        <Cumulative p={p} />
      </div>
      <div style={{ marginTop: 16 }}><Why p={p} /></div>
      <div style={{ marginTop: 16 }}><ReviewCard p={p} market={market} /></div>
      <Legend p={p} />
      <PageFooter page={p} endpoint="compare" />
    </>
  );
}

const strategyName = (p: Payload, id: string | null) => (id ? p.strategies[id]?.name ?? id : DASH);
const companyName = (p: Payload, t: string) => p.companies.find((c) => c.ticker === t)?.name ?? t;

function NotStored() {
  return <span className="muted" data-tip="Not stored for the your-cost view.">not stored</span>;
}

function Scorecard({ p, cost }: { p: Payload; cost: CostView }) {
  const cur = p.currency, d = moneyDecimals(cur), R = familyRow(p.rows, "rule"), A = familyRow(p.rows, "ai"), lead = whoLeads(R, A, cost);
  const side = (f: Family, r: ScoreboardRow | null) => {
    const net = r ? figure(r, "net_pnl", cost) : null;
    const leads = lead !== null && lead.leader === f;
    return (
      <div className={`side${leads ? " lead" : ""}`}>
        <div className="fh"><Avatar icon={familyIcon(f)} tone={f === "ai" ? "info" : ""} size="sm" /><b>{FAMILY[f][0]}</b><small>{r ? `· ${strategyName(p, r.strategy_id)}` : "· no settled head-to-head trade yet"}</small></div>
        {!r ? <Quiet>Nothing settled yet in the head-to-head view.</Quiet> : (
          <>
            <div className="net">{net === null ? <NotStored /> : <MoneyDelta currency={cur} value={net} decimals={d} />}<small>{`profit after ${cost} cost on ${plural(r.trades, "trade")} · ${tooFewToRank(r) ? `too few to rank (under ${MIN_TRADES_TO_RANK})` : "enough to rank"}`}</small></div>
            <div className="st">
              <div data-tip={`${pct(figure(r, "win_rate", cost))} of trades made money after ${cost} cost.`}>Win rate<b>{pct(figure(r, "win_rate", cost))}</b></div>
              <div data-tip="Average distance of the exit close from the predicted target, in percent (F1.9).">Target error<b>{signed(r.avg_target_error_pct)}</b></div>
              <div data-tip={`Mean return per trade after ${cost} cost; drawdown ${money(cur, figure(r, "max_drawdown", cost), d, true)}, worst streak ${figure(r, "worst_losing_streak", cost) ?? DASH}.`}>Per trade<b>{signed(figure(r, "mean_return_pct", cost))}</b></div>
            </div>
            <LuckBar row={r} cost={cost} />
          </>
        )}
      </div>
    );
  };
  return (
    <Card label="Head-to-head scorecard">
      <CardHead title="Head-to-head: the strongest rule strategy vs the strongest AI trader" end={<><PaperTag label={p.status.paper_label || PAPER_LABEL} />{`forward · as of the ${fmtDate(p.as_of, false)} close`}</>}
        help="The head-to-head view (F1, decisions 41-42): every session, for each company, the family’s strongest strategy picks one horizon under each of two pick rules (best expected gain, highest probability); each pick is one paper trade of the company’s amount. Rule and AI trade on identical company-days, so their results compare fairly. Figures after the selected costs; the luck test says whether the gap could be chance." />
      <div className="vs">
        {side("rule", R)}
        <div className="mid">
          <Icon name="layers" />
          {lead && R && A ? (
            <>
              <div className="who">{lead.leader === "level" ? "Level" : lead.leader === "rule" ? "Rule ahead" : "AI ahead"}</div>
              <div>{lead.leader === "level" ? "identical results so far" : `by ${money(cur, lead.by, d)} after ${cost} cost`}</div>
              <div className="muted">{`${R.trades + A.trades} trades in all · ${p.status.paper_label || PAPER_LABEL}`}</div>
            </>
          ) : <div className="who">No verdict yet</div>}
        </div>
        {side("ai", A)}
      </div>
      <p className="note">A lead on a handful of trades is mostly luck (SPEC section 6): the luck bar must clear zero after correction before anyone is called better. Nothing here is advice.</p>
    </Card>
  );
}

function CostLabels({ p, k }: { p: Payload; k: Pick }) {
  const cur = p.currency, clears = (k.expected_gain_pct ?? 0) > 0, cd = pickCandidate(k);
  return (
    <>
      <Label tone={clears ? "success" : "neutral"} icon={clears ? "check" : "close"}
        tip={`Expected gain after market costs ${signed(k.expected_gain_pct)} of ${money(cur, k.amount)}: ${pct(k.prob_up, 1)} × ${signed(k.move_pct)} − ${pct(k.prob_up === null ? null : 1 - k.prob_up, 1)} × ${k.loss_pct ?? DASH}% − ${k.costs_pct ?? DASH}% (brokerage, taxes and fees of config/costs.yaml; strategies are ranked on this view).`}>
        {`${signed(k.expected_gain_pct)} · ${clears ? "clears market costs" : "below market costs"}`}
      </Label>
      {cd && cd.cost_viable !== null && cd.cost_viable !== undefined ? (
        <Label tone={cd.cost_viable ? "success" : "warn"} icon={cd.cost_viable ? "check" : "warning"}
          tip={`Decision 51, your own costs: with your broker’s extra charges the round trip is ${cd.your_cost_pct ?? DASH}% and the expected gain ${signed(cd.expected_gain_your_pct)}, so this pick is ${cd.cost_viable ? "viable" : "not viable"} at your cost. The flag never blocks a paper trade.`}>
          {cd.cost_viable ? "viable at your cost" : "not viable at your cost"}
        </Label>
      ) : null}
    </>
  );
}

function Picks({ p }: { p: Payload }) {
  const cur = p.currency, today = p.picks.filter((k) => k.session_date === p.session_date), picked = today.filter((k) => k.status === "picked");
  return (
    <Card label="Today’s head-to-head picks">
      <CardHead title={<>{`Today’s picks for ${fmtDate(p.session_date)}`} <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>} end={picked.length ? viableLine(picked) : "no pick today"}
        help="The paper trades both families will make at the open of the session being predicted: for each company, the strongest rule strategy and the strongest AI trader each pick one horizon per pick rule. “Clears market costs” is the ranking view; “viable at your cost” adds your broker’s charges (decision 51)." />
      {!today.length ? <Quiet>No head-to-head picks stored for the session.</Quiet> : (
        <div className="pks">
          {(["rule", "ai"] as const).map((f) => {
            const fk = picked.filter((k) => k.family === f), first = fk[0];
            return (
              <div key={f} className="pkbox">
                <div className="h"><Avatar icon={familyIcon(f)} tone={f === "ai" ? "info" : ""} size="sm" /><b>{FAMILY[f][0]}</b><span className="muted">{first ? `· ${strategyName(p, first.strategy_id)} · ${plural(fk.length, "pick")}` : "· no candidate today"}</span></div>
                {fk.map((k) => (
                  <div key={k.id} className="pk">
                    <span className="l1"><Link className="tk" href={companyPath(p.market, k.ticker)}>{k.ticker}</Link><small>{`${companyName(p, k.ticker)} · ${PICK_RULE[k.pick_rule] ?? k.pick_rule}`}</small><span className="h-lab">{`N+${k.horizon_days}`}</span></span>
                    <span className="l2">
                      <Odds p={k.prob_up} tip={`${pct(k.prob_up, 1)} chance of a rise from the open to the N+${k.horizon_days} close.`} />
                      <span className="g"><MoneyDelta currency={cur} value={k.expected_gain_pct === null ? null : (k.expected_gain_pct * k.amount) / 100} decimals={moneyDecimals(cur)} /></span>
                      <CostLabels p={p} k={k} />
                    </span>
                  </div>
                ))}
                {!fk.length ? <Quiet>{`No ${f === "rule" ? "rule strategy" : "AI trader"} buys any company at any horizon today.`}</Quiet> : null}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function Matches({ p, cost }: { p: Payload; cost: CostView }) {
  const cur = p.currency, d = moneyDecimals(cur), list = matches(p.trades), tally = matchTally(list, p.your_costs, cost);
  const result = (m: Match, f: Family) => {
    const t: SettledTrade | null = f === "rule" ? m.rule : m.ai;
    if (t) {
      const net = tradeNet(t, p.your_costs, cost), ret = tradeReturn(t, p.your_costs, cost);
      return (
        <span className="res">
          <b>{net === null ? <NotStored /> : <MoneyDelta currency={cur} value={net} decimals={d} />}</b>
          <small>{`${strategyName(p, t.strategy_id)} · N+${t.horizon_days} · ${signed(ret)}`}<span className="cw">{` · target ${t.target_reached ? "reached" : "missed"}, error ${t.target_error_pct === null ? DASH : Math.abs(t.target_error_pct).toFixed(2) + "%"}`}</span></small>
        </span>
      );
    }
    const k = pickFor(p.picks, m, f);
    if (k && k.status === "picked") return <span className="res"><b className="muted">open</b><small>{`${strategyName(p, k.strategy_id)} · N+${k.horizon_days} · not settled by the cut-off`}</small></span>;
    return <span className="muted" data-tip={k ? "This family had no strategy buying this company at any horizon that day." : "No head-to-head pick stored for this family and day."}>{k ? "no candidate" : "no pick stored"}</span>;
  };
  const winner = (m: Match) => {
    const w = matchWinner(m, p.your_costs, cost);
    if (w === "draw") return <Label tone="neutral" tip="Both families made the same profit: picks of the same horizon are the same trade.">draw</Label>;
    if (w === "rule") return <Label icon="settings">rule</Label>;
    if (w === "ai") return <Label tone="info" icon="bolt">AI</Label>;
    if (w === "unknown") return <span className="muted" data-tip="A your-cost figure of this match is not stored.">not stored</span>;
    const k = pickFor(p.picks, m, m.rule ? "ai" : "rule");
    return <span className="muted">{k && k.status === "picked" ? "waiting" : "no match"}</span>;
  };
  return (
    <Card label="Matches">
      <CardHead title={<>Match by match: identical company-days <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>}
        end={`after ${cost} cost · ${tally.both ? `${tally.both} match${tally.both === 1 ? "" : "es"}: rule ${tally.rule}, AI ${tally.ai}, draw ${tally.draw}` : "no completed match yet"}`}
        help={`One row per company, entry session and pick rule in the head-to-head view (the entry session under the company name). Where both families’ trades have settled, the row says who made more after ${cost} cost (a draw when they made the same, e.g. the same horizon picked, so the same trade). A side whose pick is still running shows “open”; “no candidate” means that family had no strategy buying the company that day; “no pick stored” means no pick of that family is stored for that day.`} />
      {!list.length ? <Quiet>No settled head-to-head trade yet.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl mt">
            <thead><tr><th>Company · entry</th><th className="cm">Pick rule</th><th>Rule</th><th>AI</th><th>Who won</th></tr></thead>
            <tbody>
              {list.map((m) => (
                <tr key={`${m.entry_date}-${m.ticker}-${m.pick_rule}`}>
                  <td><Link className="tk" href={companyPath(p.market, m.ticker)}>{m.ticker}</Link><small className="muted" style={{ display: "block", fontSize: 11 }}>{`${companyName(p, m.ticker)} · entered ${fmtDate(m.entry_date, false)}`}</small></td>
                  <td className="cm">{PICK_RULE[m.pick_rule] ?? m.pick_rule}</td>
                  <td>{result(m, "rule")}</td>
                  <td>{result(m, "ai")}</td>
                  <td className="win">{winner(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function SliceTable({ p, rows, cost, first, firstOf }: { p: Payload; rows: ScoreboardRow[]; cost: CostView; first: string; firstOf: (r: ScoreboardRow) => React.ReactNode }) {
  const cur = p.currency;
  return (
    <div className="md-table-wrap">
      <table className="md-table tbl mt">
        <thead><tr><th>{first}</th><th className="num">Trades</th><th className="num">{`Profit after ${cost} cost`}</th><th className="num">Win rate</th><th className="num cm">Target error</th><th>Luck test</th></tr></thead>
        <tbody>
          {rows.map((r, i) => {
            const net = figure(r, "net_pnl", cost), win = figure(r, "win_rate", cost);
            return (
              <tr key={`${r.family}-${r.pick_rule}-${r.regime}-${r.strategy_id}-${i}`}>
                <td><FamilyLabel family={r.family}>{FAMILY_SHORT[r.family]}</FamilyLabel> {firstOf(r)}</td>
                <td className="num">{r.trades}</td>
                <td className="num">{net === null ? <NotStored /> : <MoneyDelta currency={cur} value={net} decimals={moneyDecimals(cur)} />}</td>
                <td className="num">{win === null ? <NotStored /> : pct(win)}</td>
                <td className="num cm">{signed(r.avg_target_error_pct)}</td>
                <td><LuckBar row={r} cost={cost} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Slices({ p, cost }: { p: Payload; cost: CostView }) {
  const pr = p.rows.filter((r) => r.scope === "pick_rule" && r.horizon_days === "all" && r.basis === "forward").sort((a, b) => a.family.localeCompare(b.family) || String(a.pick_rule).localeCompare(String(b.pick_rule)));
  const rg = p.rows.filter((r) => r.scope === "strategy_regime" && r.basis === "forward").sort((a, b) => a.family.localeCompare(b.family) || String(a.regime).localeCompare(String(b.regime)));
  return (
    <Card label="By pick rule and regime">
      <CardHead title={<>Gain-pick vs probability-pick, and by regime <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>}
        help="The same head-to-head trades cut two ways (F7.1): by the pick rule that chose the horizon (best expected gain vs highest probability) and by the market regime at prediction time (F2.6)." />
      <div className="sub2" style={{ margin: "0 0 8px" }}>By pick rule</div>
      {pr.length ? <SliceTable p={p} rows={pr} cost={cost} first="Family × pick rule" firstOf={(r) => PICK_RULE[r.pick_rule ?? ""] ?? r.pick_rule} /> : <Quiet>No pick-rule row yet.</Quiet>}
      <div className="sub2" style={{ margin: "14px 0 8px" }}>By market regime at prediction time</div>
      {rg.length ? <SliceTable p={p} rows={rg} cost={cost} first="Family × regime" firstOf={(r) => <span>{REGIME_WORDS[r.regime ?? ""] ?? r.regime}<small className="muted" style={{ display: "block", fontSize: 11 }}>{strategyName(p, r.strategy_id)}</small></span>} /> : <Quiet>No regime row yet.</Quiet>}
    </Card>
  );
}

function PerCompany({ p, cost }: { p: Payload; cost: CostView }) {
  const cur = p.currency, d = moneyDecimals(cur), sums = perCompany(p.trades, p.your_costs, cost);
  const cell = (a: { n: number; net: number | null; won: number | null } | null) => (a
    ? <span className="res"><b>{a.net === null ? <NotStored /> : <MoneyDelta currency={cur} value={a.net} decimals={d} />}</b><small>{`${plural(a.n, "trade")} · ${a.won === null ? "not stored" : `${a.won} won`}`}</small></span>
    : <span className="muted">no trade</span>);
  return (
    <Card label="Per company">
      <CardHead title={<>Per company <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>} end={<>{`after ${cost} cost`}<GoLink href={pagePath(p.market, "watchlist")}>Watchlist</GoLink></>}
        help={`Rule vs AI on each company, head-to-head view: settled trades, profit after ${cost} cost and how many made money, summed from the settled head-to-head trades (the page sums the trades itself to give both cost views). A per-company lead on a few trades is mostly luck.`} />
      {!sums.length ? <Quiet>No settled head-to-head trade on any company yet.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl mt">
            <thead><tr><th>Company</th><th>Rule</th><th>AI</th><th>Ahead</th></tr></thead>
            <tbody>
              {sums.map(({ ticker, rule, ai }) => {
                let who = <span className="muted">{DASH}</span>;
                if (rule && ai) who = rule.net === null || ai.net === null ? <span className="muted">not stored</span> : rule.net === ai.net ? <Label tone="neutral">level</Label> : rule.net > ai.net ? <Label>rule</Label> : <Label tone="info">AI</Label>;
                else if (rule || ai) who = <span className="muted">one side only</span>;
                return (
                  <tr key={ticker}>
                    <td><Link className="tk" href={companyPath(p.market, ticker)} data-tip={`${companyName(p, ticker)}: open the company page.`}>{ticker}</Link><small className="muted" style={{ display: "block", fontSize: 11 }}>{companyName(p, ticker)}</small></td>
                    <td>{cell(rule)}</td><td>{cell(ai)}</td><td>{who}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Cumulative({ p }: { p: Payload }) {
  const cur = p.currency, lines = familyLines(p.trades);
  return (
    <Card label="Cumulative profit">
      <CardHead title="Cumulative profit after market cost, head-to-head" end={<PaperTag label={p.status.paper_label || PAPER_LABEL} />}
        help="Each family’s settled head-to-head trades added up by exit date (F2.8), starting at zero on the first entry date. Identical picks add the same trade to both lines." />
      {!lines.dates.length ? <Quiet>No settled head-to-head trade yet.</Quiet> : (
        <LineChart label={`Cumulative head-to-head profit by exit date: rule ${money(cur, lines.rule.at(-1), moneyDecimals(cur), true)}, AI ${money(cur, lines.ai.at(-1), moneyDecimals(cur), true)}.`}
          labels={lines.dates.map((x) => fmtDate(x, false))} height={200}
          series={[{ key: "r", name: "Rule", values: lines.rule }, { key: "a", name: "AI", values: lines.ai }]}
          formatY={(v) => money(cur, v, 0, true)} formatValue={(v) => money(cur, v, moneyDecimals(cur), true)} />
      )}
    </Card>
  );
}

function Why({ p }: { p: Payload }) {
  const cur = p.currency, e = p.eod[0] ?? null;
  return (
    <Card label="Why: the end-of-day analyst">
      <CardHead title={<>Why: the end-of-day analyst <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>} end={e ? `session ${fmtDate(e.session_date)} · ${e.settled_trades} trades settled` : undefined}
        help="After each close the EOD analyst (Sonnet, F6.1) sums the day per family and per pick rule, writes a summary of at most 150 words citing ids, and a reason of at most 60 words for every head-to-head trade settled that day, grounded in the trade’s automatic reason split (market, sector, news, company). A deterministic gate checks every id and number. It explains; it never predicts." />
      {!e ? <Quiet>No end-of-day analysis stored by the cut-off.</Quiet> : (
        <>
          <div className="fam3">
            {(["rule", "baseline", "ai"] as const).map((f) => {
              const x = e.results[f];
              return (
                <div key={f} className="f">
                  <div className="l"><i className={`sw ${FAMILY[f][2]}`} />{FAMILY[f][0]}</div>
                  <div className="v">{x ? <MoneyDelta currency={cur} value={x.net_pnl} decimals={moneyDecimals(cur)} /> : DASH}</div>
                  <div className="s">{x && x.trades ? `${x.wins ?? 0} of ${plural(x.trades, "trade")} made money (accuracy view, market cost)` : "no trade settled"}</div>
                </div>
              );
            })}
          </div>
          <div className="lead-row">
            {(["best_expected_gain", "highest_probability"] as const).map((k) => {
              const x = e.results[k];
              return <span key={k} data-tip={`Head-to-head trades chosen by the ${PICK_RULE[k].toLowerCase()} rule that settled this session.`}>{`${PICK_RULE[k]}: `}<b>{x && x.trades ? `${money(cur, x.net_pnl, moneyDecimals(cur), true)} on ${x.trades}` : "no trade"}</b></span>;
            })}
          </div>
          <div className="summ" style={{ marginTop: 12 }}><Icon name="description" /><div>{e.summary}</div></div>
        </>
      )}
      {p.reasons.length ? (
        <ul className="rl">
          {p.reasons.map((r) => {
            const s = p.strategies[r.strategy_id];
            return (
              <li key={r.id}>
                <div className="rh">{s ? <FamilyLabel family={s.family}>{FAMILY_SHORT[s.family]}</FamilyLabel> : null}<b>{strategyName(p, r.strategy_id)}</b><Link className="tk" href={companyPath(p.market, r.ticker)}>{r.ticker}</Link><span>{`· settled ${fmtDate(r.session_date)}`}</span></div>
                <div>{r.text}</div>
                <div className="ids">{r.cited_ids.map((id) => <code key={id}>{id}</code>)}</div>
              </li>
            );
          })}
        </ul>
      ) : e ? <div style={{ marginTop: 10 }}><Quiet>No head-to-head reason stored yet.</Quiet></div> : null}
    </Card>
  );
}

/** The week's research review and its news-impact study, from GET /review (rm.review). */
function ReviewCard({ p, market }: { p: Payload; market: Market }) {
  const res = usePage<ReviewPayload>(market, "review");
  const r = res.state === "ready" ? res.envelope.payload.reviews[0] ?? null : null;
  const head = (
    <CardHead title="The week’s research review" end={r ? `${r.iso_week} · ${fmtDate(r.period_start, false)}–${fmtDate(r.period_end, false)}` : undefined}
      help="Every Saturday the research director (Opus, F6.2) reads the scoreboard, the news-impact study, the week’s EOD analyses and lessons, and writes who is ahead and why, which information helped, and proposals as config diffs. It changes nothing itself: every proposal stays “proposed” until the owner approves it." />
  );
  if (res.state === "loading") return <Card label="Weekly research review" className="rev">{head}<LoadingState label="Loading the research review" cards={1} /></Card>;
  if (res.state === "error") return <Card label="Weekly research review" className="rev">{head}<ErrorState problem={res.problem} onRetry={res.reload} /></Card>;
  const rp = res.envelope.payload, cur = p.currency;
  return (
    <Card label="Weekly research review" className="rev">
      {head}
      {!r ? (
        <Quiet>{rp.review_due ? `No weekly review written by the cut-off. The next one (${rp.review_due.iso_week}) is due on Saturday ${fmtDateYear(rp.review_due.date)}, after the cut-off.` : "No weekly review written by the cut-off."}</Quiet>
      ) : (
        <>
          <h3>Who leads</h3>
          <div className="lead-row">
            {r.leaders.map((l) => (
              <span key={`${l.scope}-${l.strategy_id}`}>
                {l.scope in FAMILY ? <FamilyLabel family={l.scope as Family}>{FAMILY_SHORT[l.scope as Family]}</FamilyLabel> : <Label tone="neutral">{l.scope}</Label>}{" "}
                <b>{strategyName(p, l.strategy_id)}</b>{` ${money(cur, l.net_pnl, moneyDecimals(cur), true)} on ${plural(l.trades, "trade")}`}
              </span>
            ))}
          </div>
          <h3>Findings</h3>
          <ul className="rl">
            {r.findings.map((f, i) => <li key={i}><div>{f.text}</div><div className="ids">{f.cited_ids.map((id) => <code key={id}>{id}</code>)}</div></li>)}
          </ul>
          <h3>Proposals (nothing applied until the owner approves)</h3>
          {!r.proposals.length ? <Quiet>No proposals this week.</Quiet> : r.proposals.map((q) => (
            <div key={q.proposal_id} className="prop">
              <div className="ph"><b>{`${q.kind} · ${q.file}`}</b><Label tone={q.status === "proposed" ? "warn" : "neutral"}>{q.status}</Label><code>{q.proposal_id}</code></div>
              <div style={{ marginTop: 4 }}>{q.rationale}</div>
              <pre>{q.diff}</pre>
              <div className="ids" style={{ marginTop: 6 }}>{q.cited_ids.map((id) => <code key={id}>{id}</code>)}</div>
            </div>
          ))}
          <p className="note">{`Full report: ${r.report_path}`}</p>
        </>
      )}
      <NewsImpact rp={rp} />
    </Card>
  );
}

function NewsImpact({ rp }: { rp: ReviewPayload }) {
  const rows = rp.news_impact;
  return (
    <>
      <h3>Which news moved prices (the week’s news-impact study)</h3>
      {!rows.length ? <Quiet>No news-impact study computed by the cut-off.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl mt">
            <thead><tr><th>Event · status · materiality</th><th className="num">Horizon</th><th className="num">Events</th><th className="num">Abnormal move</th><th>Enough events</th></tr></thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.id}>
                  <td><b>{x.event_type.replace(/_/g, " ")}</b><small className="muted" style={{ display: "block", fontSize: 11 }}>{`${x.status.replace(/_/g, " ")} · ${x.materiality} · ${x.iso_week}`}</small></td>
                  <td className="num">{`N+${x.horizon_days}`}</td>
                  <td className="num">{x.n_events}</td>
                  <td className="num" data-tip={x.ci_low_pct !== null ? `Mean move beyond the market and sector ${signed(x.mean_abnormal_pct)}, 95% interval ${signed(x.ci_low_pct)} to ${signed(x.ci_high_pct)}.` : "No interval yet."}>{signed(x.mean_abnormal_pct)}</td>
                  <td>{x.enough ? <Label tone="success" icon="check">enough</Label> : <Label tone="neutral">too few</Label>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Legend({ p }: { p: Payload }) {
  return (
    <div className="legend2" aria-label="Legend">
      <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
      <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
      <span><Label tone="success">edge</Label> the corrected luck interval lies above zero; <Label tone="neutral">luck?</Label> it includes zero; <Label tone="danger">loss</Label> it lies wholly below zero</span>
      <span><PaperTag label={p.status.paper_label || PAPER_LABEL} /> every signal and trade until proven; nothing here is advice</span>
    </div>
  );
}
