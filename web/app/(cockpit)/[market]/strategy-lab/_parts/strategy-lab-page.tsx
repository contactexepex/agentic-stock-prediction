"use client";
// Page 05, Strategy lab (B16; design/mockups/05-strategy-lab): every registry strategy on one scoreboard, ranked by
// profit after market cost (decision 50), with the view (accuracy / head-to-head), basis (forward / back-test, never
// pooled), cost view and horizon switches, the KPI picks, the selected strategy in plain words against the go-live
// bar, the cumulative profit lines and the heatmaps. Reads GET /api/v1/markets/{market}/strategies (B13's
// rm.strategies). The selected strategy follows the URL hash (#<strategy_id>), as the Help page and the portfolios link it.
import Link from "next/link";
import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { PageFooter, PageHead, SignalsBand } from "../../../../../components/blocks/page-head.tsx";
import { Segmented } from "../../../../../components/ui/controls.tsx";
import { HelpTip, Icon } from "../../../../../components/ui/icon.tsx";
import { Card, CardHead, FamilyLabel, Kpi, KpiRow, Label, MoneyDelta, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import {
  BACKTEST_YEARS, CURRENCY_SYMBOL, FAMILY, FAMILY_SHORT, GO_LIVE_MONTHS, GO_LIVE_TRADES_ABOUT, LUCK_INTERVAL_PCT,
  MIN_TRADES_TO_RANK, PAPER_LABEL, PICK_RULE,
} from "../../../../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtDateYear, money, moneyDecimals, pct, signed } from "../../../../../lib/ui/format.ts";
import { stockStrategiesPath } from "../../../../../lib/ui/routes.ts";
import type { GoLive, PageBase } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import {
  byNetDesc, figure, niceTicks, REGIME_WORDS, rowsOf, tooFewToRank, type Basis, type CostView, type ScoreboardRow, type ScoreView, type Strategy,
} from "../../../../../lib/strategy-pages/scoreboard.ts";
import {
  cellValue, colouredSeries, compactProfit, cumulativeSeries, defaultSelection, fmtParam, forwardAccuracyRow, heatShares,
  heatWeeks, keyName, kpiPicks, ranking, REASON, type HeatValue, type Slice, type StrategyLabPayload,
} from "../../../../../lib/strategy-pages/strategy-lab.ts";
import { Control, LuckBar, useWidth } from "../../_b16/parts.tsx";
import "./strategy-lab.css";

type Payload = PageBase & StrategyLabPayload & { go_live: GoLive | null };
type Horizon = number | "all";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const hashId = () => (typeof window === "undefined" ? "" : decodeURIComponent(window.location.hash.slice(1)));

export function StrategyLabPage({ market }: { market: Market }) {
  const res = usePage<Payload>(market, "strategies");
  return (
    <div className="p-lab">
      <PageState result={res}>{(p) => <StrategyLab key={p.market} p={p} />}</PageState>
    </div>
  );
}

interface View {
  view: ScoreView;
  basis: Basis;
  cost: CostView;
  horizon: Horizon;
}

function StrategyLab({ p }: { p: Payload }) {
  const [v, setV] = useState<View>({ view: "accuracy", basis: "forward", cost: "market", horizon: p.default_horizon ?? "all" });
  // The selection is fixed once: the URL hash, else the first ranked strategy of the opening slice (the mockup keeps it
  // while the switches change); a click or a new hash changes it.
  const [chosen, setChosen] = useState<string>(() => defaultSelection(p, { view: "accuracy", basis: "forward", horizon: p.default_horizon ?? "all" }));
  useEffect(() => {
    const read = () => { const id = hashId(); if (id && p.strategies[id]) setChosen(id); };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, [p.strategies]);
  const slice: Slice = { view: v.view, basis: v.basis, horizon: v.horizon };
  const selected = p.strategies[chosen] ? chosen : p.reference_strategy;
  const select = (id: string) => {
    setChosen(id);
    window.history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  };
  const all = Object.values(p.strategies);
  const count = (f: string) => all.filter((s) => s.family === f).length;
  return (
    <>
      <PageHead page={p} title="Strategy lab"
        subtitle={`${all.length} strategies on one scoreboard: ${count("rule")} rule strategies, ${count("baseline")} baselines, ${count("ai")} AI traders · ${p.name} · data as of the ${fmtDate(p.as_of, false)} close · research only`} />
      <SignalsBand page={p} goLive={p.go_live} strategies={all.length} />
      <Controls p={p} v={v} set={setV} />
      <Kpis p={p} slice={slice} />
      <div style={{ marginTop: 16 }}><Leaderboard p={p} v={v} selected={selected} onSelect={select} /></div>
      <div className="grid even">
        <Detail p={p} v={v} selected={selected} />
        <CumulativeCard p={p} v={v} selected={selected} />
      </div>
      <div style={{ marginTop: 16 }}><Heatmaps p={p} v={v} /></div>
      <Legend p={p} />
      <PageFooter page={p} endpoint="strategies" />
    </>
  );
}

function Controls({ p, v, set }: { p: Payload; v: View; set: (v: View) => void }) {
  return (
    <div className="ctrls" role="group" aria-label="Scoreboard settings">
      <Control label="View" help="Accuracy: every qualifying prediction is its own paper trade, so each strategy is judged on everything it said. Head-to-head: only the up to four daily picks per company (the strongest rule strategy vs the strongest AI trader under two pick rules), on identical company-days (F1, decisions 41-42).">
        <Segmented label="View" value={v.view} onChange={(view) => set({ ...v, view })} options={[{ value: "accuracy", label: "Accuracy" }, { value: "head_to_head", label: "Head-to-head" }]} />
      </Control>
      <Control label="Basis" help={`Forward: real paper trades made before each session’s open. Back-test: the strategies that need no news replayed on the stored history (F2.3; the ${BACKTEST_YEARS}-year cache when the run used it). Never pooled: a back-test says what would have happened, forward says what did.`}>
        <Segmented label="Basis" value={v.basis} onChange={(basis) => set({ ...v, basis })} options={[{ value: "forward", label: "Forward" }, { value: "backtest", label: "Back-test" }]} />
      </Control>
      <Control label="Costs" help="Market cost: brokerage, taxes and fees of config/costs.yaml; strategies are ranked on it. Your cost adds your own broker’s charges (India: NRI reporting and DP charges; US: FX markup and the portfolio fee); the go-live bar is measured on it (decision 50). The ranking does not change with this switch; the numbers do.">
        <Segmented label="Costs" value={v.cost} onChange={(cost) => set({ ...v, cost })} options={[{ value: "market", label: "Market cost" }, { value: "your", label: "Your cost" }]} />
      </Control>
      <Control label="Horizon" help={`All horizons pooled, or one horizon N+k (sell at the close of the k-th session after the entry session). A strategy with no settled trade at a horizon shows "no trades yet".`}>
        <Segmented<string> label="Horizon" value={String(v.horizon)} onChange={(h) => set({ ...v, horizon: h === "all" ? "all" : Number(h) })}
          options={["all", ...(p.horizons ?? []).map(String)].map((k) => ({ value: k, label: k === "all" ? "All" : `N+${k}` }))} />
      </Control>
    </div>
  );
}

function Kpis({ p, slice }: { p: Payload; slice: Slice }) {
  const cur = p.currency, k = kpiPicks(p, slice), name = (row: ScoreboardRow | null) => (row ? p.strategies[row.strategy_id]?.name ?? row.strategy_id : DASH);
  return (
    <KpiRow>
      <Kpi icon="query_stats" tone="success" label="Leading after market cost" value={k.leader ? name(k.leader) : "No trades yet"}
        tip="The strategy with the highest profit after market cost in the selected view, basis and horizon. With few trades the lead is mostly luck (SPEC section 6)."
        sub={k.leader ? <span><MoneyDelta currency={cur} value={k.leader.net_pnl} decimals={moneyDecimals(cur)} />{` on ${plural(k.leader.trades, "trade")} `}{tooFewToRank(k.leader) ? <Label tone="neutral">too few to rank</Label> : null}</span> : "nothing settled in this slice"} />
      <Kpi icon="trending_flat" tone="warn" label="Best yardstick (baseline)" value={name(k.bestBaseline)}
        tip="The best of the three baselines (always buy, follow yesterday, model without news). A strategy must beat it after your cost to go live (F7.2)."
        sub={k.bestBaseline ? <span><MoneyDelta currency={cur} value={k.bestBaseline.net_pnl} decimals={moneyDecimals(cur)} />{` on ${plural(k.bestBaseline.trades, "trade")}`}</span> : "no baseline trade yet"} />
      <Kpi icon="layers" tone="info" label="Beat the yardstick" value={k.bestBaseline ? `${k.beat} of ${k.contenders}` : DASH}
        tip="How many rule strategies and AI traders with settled trades are ahead of the best baseline in this slice, before the luck test."
        sub={k.bestBaseline ? "strategies ahead of the best baseline after market cost" : "needs a baseline row"} />
      <Kpi icon="schedule" tone="paper" label="Nearest to go-live (baselines aside)" value={name(k.nearest)}
        tip={`The go-live bar (F7.2, your cost): about ${GO_LIVE_TRADES_ABOUT} settled trades, ${GO_LIVE_MONTHS} months forward, beating the best baseline with the corrected luck test, drawdown within the limit, holding in calm and volatile regimes. ${p.status.paper_label || PAPER_LABEL}.`}
        sub={k.nearest?.go_live ? `${k.nearest.go_live.trades_needed} trades and ${Math.max(0, GO_LIVE_MONTHS - k.nearest.go_live.months_forward).toFixed(1)} months to go` : "no rule strategy or AI trader with settled trades in this slice"} />
    </KpiRow>
  );
}

function NotStored() {
  return <span className="muted" data-tip="Not stored for the your-cost view (a back-test row stores profit and mean return only).">not stored</span>;
}

function GoLiveChips({ row, currency }: { row: ScoreboardRow; currency: string }) {
  const g = row.go_live;
  if (!g) return <span className="muted">{DASH}</span>;
  const chip = (ok: boolean | null | undefined, text: string, tip: string) => (
    <Label tone={ok === true ? "success" : "neutral"} icon={ok === true ? "check" : ok === false ? "close" : "remove"} tip={tip}>{text}</Label>
  );
  return (
    <span className="gl">
      {chip(g.trades_needed === 0, g.trades_needed ? `${g.trades_needed} trades to go` : "trades ok", `About ${GO_LIVE_TRADES_ABOUT} settled trades are needed (F7.2); ${g.trades_needed} still to go.`)}
      {chip(g.months_forward >= GO_LIVE_MONTHS, `${g.months_forward} of ${GO_LIVE_MONTHS} months`, `At least ${GO_LIVE_MONTHS} months of forward paper trading.`)}
      {chip(g.beats_best_baseline, g.beats_best_baseline ? "beats yardstick" : "behind yardstick", `Must beat the best baseline after your cost (${money(currency, g.best_baseline_net_pnl, moneyDecimals(currency), true)}) with the corrected luck test excluding zero.`)}
    </span>
  );
}

function strategyNote(s: Strategy): string {
  if (s.differs_in) return `differs in ${keyName(s.differs_in)}`;
  if (s.family === "ai") return s.parameters?.sees_model_score ? "sees the model score" : "blind to the model score";
  if (s.family === "baseline") return (s.description ?? "").split(".")[0];
  return "the reference rule strategy";
}

function Leaderboard({ p, v, selected, onSelect }: { p: Payload; v: View; selected: string; onSelect: (id: string) => void }) {
  const cur = p.currency, d = moneyDecimals(cur), { ids, byId } = ranking(p, v);
  const hzWords = v.horizon === "all" ? "all horizons pooled" : `N+${v.horizon} only`;
  const viewWords = v.view === "accuracy" ? "accuracy" : "head-to-head";
  const other: CostView = v.cost === "your" ? "market" : "your";
  const head = (
    <CardHead title="Every strategy, ranked by profit after costs"
      help={`All ${ids.length} strategies of the registry (rule strategies, the three baselines as yardsticks, the AI traders) on the ${viewWords} view, ${v.basis} basis, ${hzWords}. Ranked on market cost (decision 50); the ${other}-cost figure sits under each profit. Fewer than ${MIN_TRADES_TO_RANK} settled trades is "too few to rank" and greyed: a handful of trades is mostly luck. The luck bar shows the ${LUCK_INTERVAL_PCT}% interval of the mean return per trade, thin uncorrected and thick corrected for the rows compared at once; only a thick bar clear of the zero tick counts as an edge. Click a name to read the strategy in plain words.`}
      end={`${viewWords} view · ${v.basis} · ${hzWords} · as of the ${fmtDate(p.as_of, false)} close · Paper`} />
  );
  const hasBack = p.rows.some((r) => r.basis === "backtest");
  if (v.basis === "backtest" && !hasBack) {
    return <Card label="Scoreboard">{head}<Quiet>{`No back-test rows stored yet. Back-tests cover only the strategies that need no news (always buy, follow yesterday, model without news and the rule strategies with the news weight at zero), and are never pooled with forward results (F2.3).`}</Quiet></Card>;
  }
  const run = p.backtest_run;
  let rank = 0;
  return (
    <Card label="Scoreboard">
      {head}
      {v.basis === "backtest" && run ? (
        <div className="quiet" style={{ marginBottom: 10 }}>
          <b>Back-test run. </b>
          {`Bars stored from ${fmtDateYear(run.first_date)} to ${fmtDateYear(run.last_date)}, ${run.history ? `with the ${BACKTEST_YEARS}-year history cache` : `without the ${BACKTEST_YEARS}-year history cache (not in the repository)`}${run.note ? `; ${run.note}` : ""}${run.eurusd ? `; EUR/USD: ${run.eurusd}` : ""}. Never pooled with forward results (F2.3); no targets or ranges, so those figures are empty.`}
        </div>
      ) : null}
      <div className="md-table-wrap">
        <table className="md-table tbl lb">
          <thead>
            <tr>
              <th className="cm">#</th><th>Strategy</th><th className="num">{`Profit after ${v.cost} cost`}</th><th className="num cm">Trades</th>
              <th className="num">Win rate</th><th className="num c2">Per trade</th><th className="num c2">Drawdown</th><th>Luck test</th><th className="c3">Go-live bar</th>
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => {
              const s = p.strategies[id], r = byId.get(id) ?? null;
              if (r) rank++;
              const net = r ? figure(r, "net_pnl", v.cost) : null, alt = r ? figure(r, "net_pnl", other) : null;
              const win = r ? figure(r, "win_rate", v.cost) : null, mean = r ? figure(r, "mean_return_pct", v.cost) : null;
              const dd = r ? figure(r, "max_drawdown", v.cost) : null, streak = r ? figure(r, "worst_losing_streak", v.cost) : null;
              const cls = [r ? (tooFewToRank(r) ? "few" : "") : "none", id === selected ? "on" : ""].filter(Boolean).join(" ");
              const notThere = v.horizon !== "all" && !s.horizons.includes(Number(v.horizon));
              return (
                <tr key={id} className={cls}>
                  <td className="rank cm">{r ? rank : DASH}</td>
                  <td>
                    <span className="nm">
                      <span className="t">
                        <button type="button" className="sel" aria-pressed={id === selected} onClick={() => onSelect(id)}>{s.name}</button>
                        <FamilyLabel family={s.family}>{FAMILY_SHORT[s.family]}</FamilyLabel>
                        {s.family === "baseline" ? <Label tone="neutral" tip="A baseline is the yardstick: a strategy must beat the best baseline after your cost to go live.">yardstick</Label> : null}
                        {id === p.reference_strategy ? <Label tone="neutral">reference</Label> : null}
                      </span>
                      <small>{strategyNote(s)}</small>
                    </span>
                  </td>
                  <td className="num pn">
                    {r ? (
                      <span data-tip={`Profit after ${v.cost} cost ${net === null ? "not stored" : money(cur, net, d, true)} on ${plural(r.trades, "trade")}${alt !== null ? `; after ${other} cost ${money(cur, alt, d, true)}` : ""}. Ranked on market cost (decision 50).`}>
                        <b>{net === null ? <NotStored /> : <MoneyDelta currency={cur} value={net} decimals={d} />}</b>
                        <small>{tooFewToRank(r) ? <Label tone="neutral">too few to rank</Label> : null}{alt !== null ? <span className="alt">{` ${other} cost ${money(cur, alt, d, true)}`}</span> : null}</small>
                      </span>
                    ) : (
                      <span className="muted" data-tip={`No settled trade in this slice yet${notThere ? ` (this strategy predicts N+${s.horizons.join(", N+")} only)` : ""}${v.basis === "backtest" ? ". Not run in the back-test: it needs news or walk-forward probabilities." : "."}`}>
                        {v.basis === "backtest" ? "not run" : "no trades yet"}
                      </span>
                    )}
                  </td>
                  <td className="num cm">{r ? r.trades : 0}</td>
                  <td className="num">{!r ? DASH : win === null ? <NotStored /> : <span data-tip={`${pct(win)} of ${plural(r.trades, "trade")} made money after ${v.cost} cost.`}>{pct(win)}</span>}</td>
                  <td className="num c2">{!r ? DASH : mean === null ? <NotStored /> : (
                    <span data-tip={`Mean return per trade after ${v.cost} cost, in percent of the amount. ${r.target_reached_rate === null ? "No targets or ranges in this basis." : `${pct(r.target_reached_rate)} of trades touched the target (typically in session ${r.median_reached_session ?? DASH}); ${pct(r.range_hit_rate)} of exit closes landed inside the 80% range; average miss of the target ${r.avg_target_error_pct === null ? DASH : signed(r.avg_target_error_pct)}.`}`}>{signed(mean)}</span>
                  )}</td>
                  <td className="num c2">{!r ? DASH : dd === null ? <NotStored /> : <span data-tip={`Deepest fall of cumulative profit from its peak: ${money(cur, dd, d, true)}; worst losing streak ${streak ?? DASH} trade${streak === 1 ? "" : "s"}.`}>{money(cur, dd, d, true)}</span>}</td>
                  <td>{r ? <LuckBar row={r} cost={v.cost} none="no interval" /> : <span className="muted">{DASH}</span>}</td>
                  <td className="c3">{r && r.go_live ? <GoLiveChips row={r} currency={cur} /> : <span className="muted">{DASH}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {v.basis === "backtest" ? <p className="note" style={{ marginTop: 8 }}>A strategy marked "not run" was not run in this back-test: it needs news, verified statuses or the model’s walk-forward probabilities, which the back-test engine does not have.</p> : null}
      {v.view === "head_to_head" ? <PickRuleTable p={p} v={v} /> : null}
    </Card>
  );
}

function PickRuleTable({ p, v }: { p: Payload; v: View }) {
  const cur = p.currency, rows = rowsOf(p.rows, "pick_rule", v.horizon, v.view, v.basis).sort(byNetDesc);
  if (!rows.length) return null;
  return (
    <>
      <div className="sub2" style={{ margin: "14px 0 0" }}>By family and pick rule (the head-to-head portfolios): gain-pick vs probability-pick.</div>
      <div className="md-table-wrap">
        <table className="md-table tbl co-tbl" style={{ marginTop: 14 }}>
          <thead><tr><th>Family × pick rule</th><th className="num">Trades</th><th className="num">{`Profit after ${v.cost} cost`}</th><th className="num">Win rate</th><th className="pr-luck">Luck test</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const net = figure(r, "net_pnl", v.cost), win = figure(r, "win_rate", v.cost);
              return (
                <tr key={`${r.family}-${r.pick_rule}`}>
                  <td><FamilyLabel family={r.family}>{FAMILY_SHORT[r.family]}</FamilyLabel> {PICK_RULE[r.pick_rule ?? ""] ?? r.pick_rule}</td>
                  <td className="num">{r.trades}</td>
                  <td className="num">{net === null ? <NotStored /> : <MoneyDelta currency={cur} value={net} decimals={moneyDecimals(cur)} />}</td>
                  <td className="num">{win === null ? <NotStored /> : pct(win)}</td>
                  <td className="pr-luck"><LuckBar row={r} cost={v.cost} none="no interval" /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** A signed bar around a middle line (the detail card's per-horizon and per-regime bars). */
function MiniRow({ label, value, max, text, tip }: { label: string; value: number | null; max: number; text: string; tip: string }) {
  const w = value === null ? 0 : (Math.abs(value) / max) * 50;
  return (
    <>
      <span className="l">{label}</span>
      <div className="bar">
        <s style={{ left: "50%" }} />
        {value !== null ? <i className={value >= 0 ? "up" : "dn"} style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} /> : null}
      </div>
      <b data-tip={tip}>{text}</b>
    </>
  );
}

function Detail({ p, v, selected }: { p: Payload; v: View; selected: string }) {
  const cur = p.currency, d = moneyDecimals(cur), s = p.strategies[selected];
  if (!s) return <Card label="Strategy in plain words"><CardHead title="In plain words" /><Quiet>No strategy selected.</Quiet></Card>;
  const ref = s.compared_to ? p.strategies[s.compared_to] : null, k = s.differs_in ?? "";
  const params = s.parameters ?? {};
  const fwd = forwardAccuracyRow(p, selected);
  const perHorizon = (p.horizons ?? []).map((h) => rowsOf(p.rows, "strategy", h, v.view, v.basis).find((r) => r.strategy_id === selected) ?? null);
  const nets = (rows: (ScoreboardRow | null)[]) => rows.map((r) => (r ? figure(r, "net_pnl", v.cost) : null));
  const maxOf = (values: (number | null)[]) => Math.max(1, ...values.map((x) => Math.abs(x ?? 0)));
  const hzNets = nets(perHorizon), hzMax = maxOf(hzNets);
  const regimes = p.rows.filter((r) => r.scope === "strategy_regime" && r.view === v.view && r.basis === v.basis && r.strategy_id === selected);
  const rgNets = nets(regimes), rgMax = maxOf(rgNets);
  const companies = p.rows.filter((r) => r.scope === "strategy_company" && r.view === v.view && r.basis === v.basis && r.strategy_id === selected && String(r.horizon_days) === String(v.horizon))
    .sort(byNetDesc);
  const nameOf = (t: string) => p.companies.find((c) => c.ticker === t)?.name ?? t;
  const g = fwd?.go_live ?? null;
  let diff: ReactNode = null;
  if (s.compared_to) {
    const change = k === "threshold"
      ? ` (${ref && ref.threshold !== null ? pct(ref.threshold) + " → " : ""}${pct(s.threshold)})`
      : ref?.parameters && k in ref.parameters ? ` (${fmtParam(ref.parameters[k])} → ${fmtParam(params[k])})` : k in params ? ` (${fmtParam(params[k])})` : "";
    diff = <div className="diff"><Icon name="science" /><div><b>{`Compared to ${ref ? ref.name : s.compared_to}`}</b>{", it changes one setting: "}<b>{keyName(k)}</b>{`${change}. If its results differ from ${ref ? ref.name : "the reference"}, that setting is why.`}</div></div>;
  } else if (selected === p.reference_strategy) {
    diff = <div className="diff"><Icon name="science" /><div><b>The reference.</b> Every other rule strategy changes exactly one of its settings.</div></div>;
  } else if (s.family === "baseline") {
    diff = <div className="diff"><Icon name="trending_flat" /><div><b>A yardstick, not a contender.</b> Strategies must beat the best baseline after your cost to go live.</div></div>;
  }
  const li = (ok: boolean | null | undefined, text: string, sub: string) => (
    <li className={ok === true ? "ok" : ok === false ? "no" : "na"}><Icon name={ok === true ? "check" : ok === false ? "close" : "remove"} /><span>{text}<small>{sub}</small></span></li>
  );
  return (
    <Card label="Strategy in plain words" className="det">
      <CardHead title="In plain words" end={<PaperTag label={p.status.paper_label || PAPER_LABEL} />}
        help="What the selected strategy does, which single setting it changes against the strategy it is compared to (F2.5: a difference in results points to that setting), its numbers per horizon, regime and company in the selected view, and where it stands against the go-live bar (your cost). Click another name in the scoreboard to switch." />
      <div className="big">
        {s.name}
        <FamilyLabel family={s.family}>{FAMILY[s.family][0]}</FamilyLabel>
        {s.live ? <span className="mb-tag live">live</span> : <span className="mb-tag" data-tip="Not live yet: paper trading of this strategy is switched on in Wave 5; nothing trades for real anyway.">not live yet</span>}
      </div>
      <div className="desc">{s.description}</div>
      {diff}
      <div className="params">
        {Object.entries(params).map(([key, value]) => <span key={key} className="md-chip small" data-tip={`Setting ${key}: ${fmtParam(value)}`}>{`${keyName(key)}: ${fmtParam(value)}`}</span>)}
        <span className="md-chip small" data-tip="The lowest probability of a rise that still makes a trade.">{s.threshold !== null ? `bar ${pct(s.threshold)}` : "no probability bar"}</span>
        <span className="md-chip small">{`horizons N+${s.horizons.join(", N+")}`}</span>
        <span className="md-chip small" data-tip={`Settled trades of this strategy in ${p.name}, accuracy view, forward (the registry’s ${s.settled_trades} counts both markets).`}>{`${fwd ? fwd.trades : 0} forward settled trades in ${p.name}`}</span>
      </div>
      <h3>{`Per horizon · ${v.view === "accuracy" ? "accuracy" : "head-to-head"} · ${v.cost} cost`}</h3>
      <div className="mini">
        {(p.horizons ?? []).map((h, i) => {
          const r = perHorizon[i], net = hzNets[i], win = r ? figure(r, "win_rate", v.cost) : null;
          const tip = r ? `N+${h}: ${plural(r.trades, "trade")}, ${win === null ? "win rate not stored for this cost view" : `${pct(win)} won`}, ${net === null ? "profit not stored" : money(cur, net, d, true)} after ${v.cost} cost.` : s.horizons.includes(h) ? "No settled trade at this horizon yet." : "This strategy does not predict this horizon.";
          return <MiniRow key={h} label={`N+${h}`} value={net} max={hzMax} tip={tip} text={r ? `${net === null ? "not stored" : money(cur, net, d, true)} · ${r.trades}` : s.horizons.includes(h) ? DASH : "n/a"} />;
        })}
      </div>
      <h3>Per market regime at prediction time</h3>
      {regimes.length ? (
        <div className="mini">
          {regimes.map((r, i) => (
            <MiniRow key={r.regime ?? i} label={REGIME_WORDS[r.regime ?? ""] ?? r.regime ?? DASH} value={rgNets[i]} max={rgMax}
              text={`${rgNets[i] === null ? "not stored" : money(cur, rgNets[i], d, true)} · ${r.trades}`}
              tip={`${r.regime}: ${r.trades} trades, ${pct(figure(r, "win_rate", v.cost))} won. ${params.regime_filter ? "This strategy skips EVENT_HEAVY and UNSTABLE days." : "Rule strategies never lower their probability by regime; the effect is measured here (F2.6)."}`} />
          ))}
        </div>
      ) : <Quiet>{v.basis === "backtest" ? "The back-test stores no split by regime." : "No settled trade in this view yet, so no regime split."}</Quiet>}
      <h3>{`Per company · ${v.horizon === "all" ? "all horizons" : `N+${v.horizon}`}`}</h3>
      {companies.length ? (
        <div className="md-table-wrap">
          <table className="md-table tbl co-tbl">
            <thead><tr><th>Company</th><th className="num">Trades</th><th className="num">Profit</th><th className="num">Win rate</th><th><span className="mb-sr">Sample</span></th></tr></thead>
            <tbody>
              {companies.map((r) => {
                const net = figure(r, "net_pnl", v.cost), win = figure(r, "win_rate", v.cost), t = r.ticker ?? "";
                return (
                  <tr key={t}>
                    <td><Link className="tk" href={stockStrategiesPath(p.market, t)} data-tip={`${nameOf(t)}: every strategy on it (page 4).`}>{t}</Link></td>
                    <td className="num">{r.trades}</td>
                    <td className="num">{net === null ? <NotStored /> : <MoneyDelta currency={cur} value={net} decimals={d} />}</td>
                    <td className="num">{win === null ? <NotStored /> : pct(win)}</td>
                    <td>{tooFewToRank(r) ? <Label tone="neutral">too few</Label> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <Quiet>{v.basis === "backtest" ? "The back-test stores no split by company." : "No settled trade on any company in this slice yet."}</Quiet>}
      <h3>Against the go-live bar (your cost)</h3>
      {g ? (
        <>
          <ul className="chk">
            {li(g.trades_needed === 0, g.trades_needed ? `${g.trades_needed} more settled trades needed` : "Enough settled trades", `about ${GO_LIVE_TRADES_ABOUT} per strategy (F7.2), accuracy view`)}
            {li(g.months_forward >= GO_LIVE_MONTHS, `${g.months_forward} of ${GO_LIVE_MONTHS} months of forward paper trading`, "counted from the first forward trade")}
            {li(g.beats_best_baseline, g.beats_best_baseline ? "Beats the best baseline after your cost" : "Does not beat the best baseline after your cost yet", `best baseline ${money(cur, g.best_baseline_net_pnl, d, true)}; needs the corrected luck interval to lie above zero`)}
            {li(g.drawdown_within_limit, g.drawdown_within_limit ? "Drawdown within the limit" : g.drawdown_within_limit === false ? "Drawdown beyond the limit" : "Drawdown: not measured yet", `limit ${money(cur, g.drawdown_limit)} of cumulative loss on the accuracy-view trades`)}
            {li(g.holds_in_calm_and_volatile, g.holds_in_calm_and_volatile === null || g.holds_in_calm_and_volatile === undefined ? "Calm and volatile regimes: not enough data yet" : g.holds_in_calm_and_volatile ? "Holds in calm and volatile regimes" : "Fails in one regime", "measured per regime (F2.6)")}
          </ul>
          <p className="note">{g.proven ? "Proven: this strategy has met the bar; Strong signals may appear." : `Not proven. ${p.status.paper_label || PAPER_LABEL}: nothing here is advice.`}</p>
        </>
      ) : <Quiet>No forward accuracy row yet, so no position against the bar.</Quiet>}
    </Card>
  );
}

function CumulativeCard({ p, v, selected }: { p: Payload; v: View; selected: string }) {
  return (
    <Card label="Cumulative profit">
      <CardHead title="Cumulative profit after market cost" end={<PaperTag label={p.status.paper_label || PAPER_LABEL} />}
        help="Each line adds up a strategy’s settled paper trades after costs by exit date (F2.8), in the selected view; market cost here, since the trades carry that view. The selected strategy and the three with the highest cumulative profit are coloured and named (colours follow the registry order, not the rank); the rest are grey; the selected one is thick. Strategies with identical trades draw on top of each other; the tooltip lists each. Hover or use the arrow keys to read a date." />
      <CumulativeChart p={p} v={v} selected={selected} />
    </Card>
  );
}

function CumulativeChart({ p, v, selected }: { p: Payload; v: View; selected: string }) {
  const [ref, hostWidth] = useWidth<HTMLDivElement>();
  const [at, setAt] = useState<number | null>(null);
  const cur = p.currency, d = moneyDecimals(cur);
  const { dates, series } = cumulativeSeries(p.lines, v.view, v.basis);
  const registry = Object.keys(p.strategies);
  const nameOf = (id: string) => p.strategies[id]?.name ?? id.split(":").map((w, i) => (i === 0 ? FAMILY_SHORT[w as keyof typeof FAMILY_SHORT] ?? w : PICK_RULE[w] ?? w)).join(" · ");
  if (!dates.length) {
    return <div className="cum" ref={ref}><Quiet>{v.basis === "forward" ? "No settled trade in this view yet." : "The back-test stores no trades and no lines, only its scoreboard rows, and a back-test is never pooled with forward trades (F2.3)."}</Quiet></div>;
  }
  const coloured = colouredSeries(series, selected, registry);
  const klass = (id: string) => (coloured.includes(id) ? `k${coloured.indexOf(id) + 1}` : "grey");
  const W = Math.max(280, hostWidth ?? 560), phone = W < 560, H = phone ? 240 : 280, L = phone ? 52 : 64, T = 14, B = 26;
  const labelOf = (id: string) => { const n = nameOf(id); return n.length > 22 ? n.slice(0, 21) + "…" : n; };
  const R = phone ? 12 : Math.min(Math.round(W * 0.34), Math.max(90, ...coloured.map((id) => Math.round(labelOf(id).length * 6.4 + 16))));
  const values = series.flatMap((s) => s.points);
  let lo = Math.min(0, ...values), hi = Math.max(0, ...values);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const X = (i: number) => L + (dates.length === 1 ? (W - L - R) / 2 : (i / (dates.length - 1)) * (W - L - R));
  const Y = (value: number) => T + ((hi - value) / (hi - lo)) * (H - T - B);
  const ordered = series.slice().sort((a, b) => Number(a.id === selected) - Number(b.id === selected) || Number(coloured.includes(a.id)) - Number(coloured.includes(b.id)));
  const labels = phone ? [] : (() => {
    const items = coloured.map((id) => ({ id, y: Y(series.find((s) => s.id === id)!.last) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < 13) items[i].y = items[i - 1].y + 13;
    const over = items.length ? items[items.length - 1].y - (H - B - 4) : 0;
    if (over > 0) for (const it of items) it.y -= over;
    return items;
  })();
  const onKey = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setAt((old) => (old === null ? dates.length - 1 : Math.max(0, Math.min(dates.length - 1, old + (event.key === "ArrowRight" ? 1 : -1)))));
    } else if (event.key === "Escape") setAt(null);
  };
  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const box = (event.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const x = (event.clientX - box.left) * (W / box.width);
    let best = 0;
    dates.forEach((_, i) => { if (Math.abs(X(i) - x) < Math.abs(X(best) - x)) best = i; });
    setAt(best);
  };
  const others = series.length - coloured.length;
  return (
    <div className="cum" ref={ref}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" tabIndex={0} onKeyDown={onKey} onBlur={() => setAt(null)}
        aria-label={`Cumulative profit after market cost by exit date, ${series.length} ${v.view === "accuracy" ? "strategies" : "family and pick-rule lines"}, ${plural(dates.length, "date")}. Use the arrow keys to read each date.`}>
        <g className="grid">{niceTicks(lo, hi, 4).map((t) => <line key={t} x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} />)}</g>
        <line className="zero" x1={L} x2={W - R} y1={Y(0)} y2={Y(0)} />
        {ordered.map((s) => {
          const k = klass(s.id);
          return (
            <g key={s.id}>
              <polyline className={`ln ${k}${s.id === selected ? " on" : ""}`} points={[`${X(0)},${Y(0)}`, ...s.points.map((value, i) => `${X(i)},${Y(value)}`)].join(" ")} />
              {s.points.map((value, i) => <circle key={i} className={`pt ${k}`} cx={X(i)} cy={Y(value)} r={k === "grey" ? 2 : 3.5} />)}
            </g>
          );
        })}
        {labels.map((it) => <text key={it.id} className="lab" x={W - R + 8} y={it.y + 4}>{labelOf(it.id)}</text>)}
        <g className="ax">
          {niceTicks(lo, hi, 4).map((t) => <text key={t} x={L - 6} y={Y(t) + 4} textAnchor="end">{money(cur, t, 0, true)}</text>)}
          {dates.map((date, i) => <text key={date} x={X(i)} y={H - 8} textAnchor="middle">{fmtDate(date, false)}</text>)}
        </g>
        {at !== null ? <g className="hover"><line x1={X(at)} x2={X(at)} y1={T} y2={H - B} /></g> : null}
        <rect className="hit" x={L} y={T} width={W - L - R} height={H - T - B} onPointerMove={onMove} onPointerLeave={() => setAt(null)} />
      </svg>
      <div className={`ctip${at !== null ? " on" : ""}`} role="status" aria-live="polite"
        style={at !== null ? { left: Math.max(0, Math.min(W - 270, X(at) > W * 0.55 ? X(at) - 270 : X(at) + 12)), top: 8 } : undefined}>
        {at !== null ? (
          <>
            <b>{`Through ${fmtDateYear(dates[at])}`}</b>
            {series.slice().sort((a, b) => b.points[at] - a.points[at]).slice(0, 8).map((s) => (
              <span key={s.id}><br /><i className={klass(s.id)} />{`${nameOf(s.id)}: ${money(cur, s.points[at], d, true)}`}</span>
            ))}
            {series.length > 8 ? <><br />{`… ${series.length - 8} more`}</> : null}
          </>
        ) : null}
      </div>
      <div className="cleg">
        {coloured.map((id) => <span key={id}><i className={klass(id)} />{nameOf(id)}</span>)}
        {others > 0 ? <span><i className="grey" />{`${others} other ${v.view === "accuracy" ? (others === 1 ? "strategy" : "strategies") : (others === 1 ? "line" : "lines")} (hover to read)`}</span> : null}
        <span className="muted">dotted line = zero</span>
      </div>
    </div>
  );
}

interface HeatColumn { label: string; full: string; key: string }

function Heat({ title, help, ids, cols, cellOf, p, metric }: {
  title: string; help: string; ids: string[]; cols: HeatColumn[]; cellOf: (id: string, col: HeatColumn) => HeatValue | null; p: Payload; metric: "net" | "win";
}) {
  const cur = p.currency, cells = ids.map((id) => cols.map((c) => cellOf(id, c))), shares = heatShares(cells.flat(), metric);
  return (
    <div className="hm">
      <h3>{title}<HelpTip tip={help} /></h3>
      <table role="grid" aria-label={title}>
        <thead><tr><th className="r" />{cols.map((c) => <th key={c.key} scope="col" title={c.full}>{c.label}</th>)}</tr></thead>
        <tbody>
          {ids.map((id, i) => (
            <tr key={id}>
              <th className="r" scope="row" title={p.strategies[id]?.name}>{p.strategies[id]?.name ?? id}</th>
              {cols.map((c, j) => {
                const x = cells[i][j];
                if (!x) return <td key={c.key} className="e"><span>·</span></td>;
                const share = shares[i * cols.length + j], up = metric === "net" ? x.net >= 0 : (x.win ?? 0) >= 0.5;
                return (
                  <td key={c.key} tabIndex={0} style={{ background: `color-mix(in srgb, var(${up ? "--mb-color-up" : "--mb-color-down"}) ${share.toFixed(0)}%, var(--md-sys-color-surface-container-lowest))` }}
                    data-tip={`${p.strategies[id]?.name ?? id} × ${c.full}: ${plural(x.n, "trade")}, ${pct(x.win)} won, ${money(cur, x.net, moneyDecimals(cur), true)} after market cost.`}>
                    <span>{metric === "net" ? compactProfit(cur, x.net) : pct(x.win)}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Heatmaps({ p, v }: { p: Payload; v: View }) {
  const [metric, setMetric] = useState<"net" | "win">("net");
  const [week, setWeek] = useState("all");
  const picked = heatWeeks(p.cells, v.view, v.basis, week);
  const cells = picked.cells;
  const strategyRows = p.rows.filter((r) => r.scope === "strategy" && r.view === v.view && r.basis === v.basis);
  const ids = Object.keys(p.strategies).filter((id) => (v.basis === "backtest" && strategyRows.some((r) => r.strategy_id === id)) || cells.some((c) => c.strategy_id === id));
  const nameOf = (t: string) => p.companies.find((c) => c.ticker === t)?.name ?? t;
  const end = (
    <>
      <Control label="Show"><Segmented label="Show" value={metric} onChange={setMetric} options={[{ value: "net", label: `Profit (${CURRENCY_SYMBOL[p.currency] ?? p.currency})` }, { value: "win", label: "Win rate" }]} /></Control>
      {v.basis === "backtest"
        ? <span className="muted">{p.backtest_run ? `back-test ${fmtDateYear(p.backtest_run.first_date)} – ${fmtDateYear(p.backtest_run.last_date)}` : "back-test"}</span>
        : <Control label="Week" help="The ISO week of the trades’ exit, or all weeks pooled (F2.8: the cells are stored per week)."><Segmented label="Week" value={picked.week} onChange={setWeek} options={[{ value: "all", label: "All weeks" }, ...picked.weeks.map((w) => ({ value: w, label: w }))]} /></Control>}
    </>
  );
  const head = (
    <CardHead title="Where each strategy wins and loses" end={end}
      help="Heatmaps of profit after market cost or win rate (F2.8, decision 42) by strategy × horizon, × company, × market regime and × reason code, for the selected view and basis. Green = profit (or win rate above half), red = loss, darker = larger; the number is in every cell, so colour never stands alone; a dot means no trade. The reason-code map is derived from the settled trades’ automatic reason (market, sector, news, company; F1.10). The maps by horizon, company and reason read the cells per ISO week of exit, all weeks pooled by default (the Week control); the regime map is the scoreboard’s, all weeks." />
  );
  if (!ids.length) return <Card label="Heatmaps">{head}<Quiet>No settled trade in this view and basis yet.</Quiet></Card>;
  const horizonCols = (p.horizons ?? []).map((k) => ({ label: `N+${k}`, full: `N+${k}`, key: String(k) }));
  const tickers = [...new Set(cells.filter((c) => c.dimension === "company").map((c) => c.column))].sort();
  const rgRows = p.rows.filter((r) => r.scope === "strategy_regime" && r.view === v.view && r.basis === v.basis);
  const regimes = [...new Set(rgRows.map((r) => r.regime ?? ""))].sort();
  const rgIds = Object.keys(p.strategies).filter((id) => rgRows.some((r) => r.strategy_id === id));
  const codes = [...new Set(cells.filter((c) => c.dimension === "reason_code").map((c) => c.column))].sort();
  const fromRow = (r: ScoreboardRow | undefined): HeatValue | null => (r && r.net_pnl !== null ? { n: r.trades, net: r.net_pnl, win: r.win_rate } : null);
  return (
    <Card label="Heatmaps">
      {head}
      <div className="hms">
        <Heat title="By horizon" help="Which holding period works for each strategy." ids={ids} cols={horizonCols} p={p} metric={metric}
          cellOf={(id, c) => (v.basis === "forward" ? cellValue(cells, id, "horizon", c.key) : fromRow(strategyRows.find((x) => x.strategy_id === id && String(x.horizon_days) === c.key)))} />
        {tickers.length
          ? <Heat title="By company" help="Which companies each strategy reads well (all horizons pooled). A per-company lead on a handful of trades is mostly luck; the Stock strategies page shows the luck test." ids={ids} p={p} metric={metric}
            cols={tickers.map((t) => ({ label: t, full: nameOf(t), key: t }))} cellOf={(id, c) => cellValue(cells, id, "company", c.key)} />
          : <Quiet>{v.basis === "backtest" ? "By company: the back-test stores no split by company." : "By company: no per-company row in this view yet."}</Quiet>}
        {regimes.length
          ? <Heat title={picked.week === "all" ? "By market regime" : "By market regime (all weeks)"} p={p} metric={metric} ids={rgIds}
            help="The regime at prediction time (F2.6); the scoreboard stores the regime split for all weeks only, so this map does not follow the week picker. Rule strategies either filter EVENT_HEAVY and UNSTABLE days or not; the effect is measured here, not assumed."
            cols={regimes.map((r) => ({ label: REGIME_WORDS[r] ?? r, full: r, key: r }))} cellOf={(id, c) => fromRow(rgRows.find((x) => x.strategy_id === id && x.regime === c.key))} />
          : <Quiet>{v.basis === "backtest" ? "By market regime: the back-test stores no split by regime." : "By market regime: no per-regime row in this view yet."}</Quiet>}
        {codes.length
          ? <Heat title="By reason the price moved" p={p} metric={metric} ids={ids}
            help="The main cause of each settled trade’s move, from the automatic reason split (F1.10, decision 43): did the strategy make its money when the market lifted, when the sector did, on verified news, or on something company-specific?"
            cols={codes.map((c) => ({ label: REASON[c] ?? c, full: `${REASON[c] ?? c} (${c})`, key: c }))} cellOf={(id, c) => cellValue(cells, id, "reason_code", c.key)} />
          : null}
      </div>
      <div className="hmleg">
        <span>{metric === "net" ? "Profit after market cost:" : "Win rate:"}</span>
        <span className="sc" aria-hidden="true">
          <i style={{ background: "color-mix(in srgb, var(--mb-color-down) 60%, var(--md-sys-color-surface-container-lowest))" }} />
          <i style={{ background: "color-mix(in srgb, var(--mb-color-down) 25%, var(--md-sys-color-surface-container-lowest))" }} />
          <i style={{ background: "var(--md-sys-color-surface-container-low)" }} />
          <i style={{ background: "color-mix(in srgb, var(--mb-color-up) 25%, var(--md-sys-color-surface-container-lowest))" }} />
          <i style={{ background: "color-mix(in srgb, var(--mb-color-up) 60%, var(--md-sys-color-surface-container-lowest))" }} />
        </span>
        <span>{metric === "net" ? "loss … profit, darker = larger; the number is in every cell (k = thousand; the exact figure in the tooltip)" : "below half … above half; the number is in every cell"}</span>
        <span>· = no trade · every cell’s tooltip has the trade count</span>
      </div>
    </Card>
  );
}

function Legend({ p }: { p: Payload }) {
  return (
    <div className="legend2" aria-label="Legend">
      <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
      <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
      <span><Label tone="success">edge</Label> the corrected luck interval lies above zero; <Label tone="neutral">luck?</Label> it includes zero; <Label tone="danger">loss</Label> it lies wholly below zero</span>
      <span><Label tone="neutral">too few to rank</Label>{` under ${MIN_TRADES_TO_RANK} settled trades`}</span>
      <span><PaperTag label={p.status.paper_label || PAPER_LABEL} /> every signal and trade until proven; nothing here is advice</span>
    </div>
  );
}
