"use client";
// Page 07, Paper portfolios (B16; design/mockups/07-paper-portfolios): the head-to-head family portfolios, every open
// paper trade grouped by strategy with its latest intraday check, and the owner's own paper portfolio with the
// add-trade form. Reads GET /api/v1/markets/{market}/portfolios (B13's rm.portfolio); the form posts to
// POST /api/v1/markets/{market}/paper-trades (B13's route into B5's tool layer: JSON only, same origin, one
// Idempotency-Key per opened form). A paper trade is a record, never an order: nothing is bought or sold.
import Link from "next/link";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { PageFooter, PageHead, SignalsBand } from "../../../../../components/blocks/page-head.tsx";
import { TradeCheckStatus } from "../../../../../components/blocks/records.tsx";
import { RangeBar } from "../../../../../components/charts/small.tsx";
import { HelpTip, Icon } from "../../../../../components/ui/icon.tsx";
import { Avatar, Card, CardHead, Delta, FamilyLabel, GoLink, Kpi, KpiRow, Label, MoneyDelta, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import { FAMILY, FAMILY_SHORT, MIN_TRADES_TO_RANK, PAPER_LABEL, PICK_RULE, type Family } from "../../../../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtLocal, money, moneyDecimals, pct, price, signed } from "../../../../../lib/ui/format.ts";
import { companyPath, pagePath } from "../../../../../lib/ui/routes.ts";
import type { GoLive, PageBase, TradeCheck as SharedCheck } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import { figure, tooFewToRank, type CostView } from "../../../../../lib/strategy-pages/scoreboard.ts";
import {
  familyH2hRow, groupOpenTrades, latestChecks, newIdempotencyKey, openSummary, pickRuleRow, positionsSummary,
  receiptState, SOURCE, tradeRequest, type OpenFilter, type PaperPortfoliosPayload, type Receipt, type TradeForm,
} from "../../../../../lib/strategy-pages/paper-portfolios.ts";
import { CostSwitch, LuckBar } from "../../_b16/parts.tsx";
import "./paper-portfolios.css";

type Payload = PageBase & PaperPortfoliosPayload & { go_live: GoLive | null };
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** A request the form sent and the tool layer accepted into the inbox (pending until the next run imports it). */
interface Sent {
  words: string;
  inboxId: string | null;
  duplicate: boolean;
}

export function PaperPortfoliosPage({ market }: { market: Market }) {
  const res = usePage<Payload>(market, "portfolios");
  return (
    <div className="p-portfolios">
      <PageState result={res}>{(p) => <Portfolios key={p.market} p={p} />}</PageState>
    </div>
  );
}

function Portfolios({ p }: { p: Payload }) {
  const [cost, setCost] = useState<CostView>("market");
  const [sent, setSent] = useState<Sent[]>([]);
  return (
    <>
      <PageHead page={p} title="Paper portfolios" subtitle={`head-to-head portfolios, open paper trades by strategy, and your own · ${p.name} · data as of the ${fmtDate(p.as_of, false)} close · research only, nothing is an order`} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      <div className="ctrls">
        <CostSwitch value={cost} onChange={setCost} help="Market cost: brokerage, taxes and fees (the ranking view). Your cost adds your own broker’s charges; the go-live bar uses it (decision 50). Open trades are before costs." />
      </div>
      <Kpis p={p} cost={cost} pending={sent.length} />
      <div style={{ marginTop: 16 }}><H2hCard p={p} cost={cost} /></div>
      <div style={{ marginTop: 16 }}><OpenTradesCard p={p} /></div>
      <div style={{ marginTop: 16 }}><OwnerCard p={p} sent={sent} onSent={(s) => setSent((list) => [...list, s])} /></div>
      <div className="legend2" aria-label="Legend">
        <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
        <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
        <span><span className="mb-label neutral" style={{ fontSize: 10.5, padding: "0 5px" }}>H2H</span> a head-to-head pick; <Label tone="success">edge</Label> / <Label tone="neutral">luck?</Label> / <Label tone="danger">loss</Label> the corrected luck interval above zero, including zero, or wholly below it</span>
        <span><PaperTag label={p.status.paper_label || PAPER_LABEL} /> every figure until proven; a paper trade is a record, never an order</span>
      </div>
      <PageFooter page={p} endpoint="portfolios" />
    </>
  );
}

function Kpis({ p, cost, pending }: { p: Payload; cost: CostView; pending: number }) {
  const cur = p.currency, d = moneyDecimals(cur), open = openSummary(p), own = positionsSummary(p.owner.positions);
  const R = familyH2hRow(p.h2h_rows, "rule"), A = familyH2hRow(p.h2h_rows, "ai");
  return (
    <KpiRow>
      <Kpi icon="account_balance_wallet" tone="paper" label="Open paper trades" value={String(open.open)}
        tip="Every paper trade that has entered and not yet exited, all strategies and horizons, both views; unrealised against the latest stored close."
        sub={<span>unrealised <MoneyDelta currency={cur} value={open.unrealised} decimals={d} /> before costs{p.trade_checks.length ? ` · ${open.flagged} flagged` : ""}</span>} />
      <Kpi icon="layers" tone="info" label="Head-to-head rule portfolio" value={R ? <MoneyDelta currency={cur} value={figure(R, "net_pnl", cost)} decimals={d} /> : "No trades yet"}
        tip="The two family portfolios of the head-to-head view: the strongest rule strategy vs the strongest AI trader on identical company-days (decisions 41-42)."
        sub={<span>AI portfolio {A ? <MoneyDelta currency={cur} value={figure(A, "net_pnl", cost)} decimals={d} /> : DASH}{` · after ${cost} cost · ${(R?.trades ?? 0) + (A?.trades ?? 0)} settled`}</span>} />
      <Kpi icon="apartment" label="Your own paper positions" value={own.count ? money(cur, own.value, d) : "None"}
        tip="Your manual paper trades (WS4), marked to the latest stored close. A paper trade is a record, never an order."
        sub={own.count ? <span><MoneyDelta currency={cur} value={own.pnl} decimals={d} />{` on ${plural(own.count, "position")}, before costs`}</span> : "no own paper trade recorded"} />
      <Kpi icon="pending" tone={pending ? "warn" : "neutral"} label="Pending requests" value={String(pending)}
        tip="An own paper trade sent from this page in this visit: appended to the inbox with your sign-in and an idempotency key; the next run imports it (F10) and it then shows in your portfolio."
        sub={pending ? "sent from this page, waiting for the next import" : "nothing sent from this page"} />
    </KpiRow>
  );
}

function H2hCard({ p, cost }: { p: Payload; cost: CostView }) {
  const cur = p.currency, d = moneyDecimals(cur);
  return (
    <Card label="Head-to-head portfolios">
      <CardHead title={<>Head-to-head portfolios <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>} end={<GoLink href={pagePath(p.market, "compare")}>Rule vs AI</GoLink>}
        help="The portfolios of the head-to-head view (F1, F7.1): per family (the strongest rule strategy and the strongest AI trader) and per pick rule (best expected gain, highest probability). Each pick is one paper trade of the company’s amount. Profit after the selected costs; the luck test says whether a lead could be chance." />
      <div className="h2h">
        {(["rule", "ai"] as const).map((f) => {
          const fr = familyH2hRow(p.h2h_rows, f);
          return (
            <div key={f} className="fbox">
              <div className="fh"><Avatar icon={FAMILY[f][1]} tone={f === "ai" ? "info" : ""} size="sm" /><b>{FAMILY[f][0]}</b><small>{fr ? `· ${p.strategies[fr.strategy_id]?.name ?? fr.strategy_id}` : "· nothing settled yet"}</small></div>
              {!fr ? <Quiet>No settled head-to-head trade for this family yet.</Quiet> : (
                <>
                  <div className="tot">
                    <span className="n"><MoneyDelta currency={cur} value={figure(fr, "net_pnl", cost)} decimals={d} /></span>
                    {tooFewToRank(fr) ? <Label tone="neutral" tip={`Fewer than ${MIN_TRADES_TO_RANK} settled trades: a handful of trades is mostly luck (SPEC section 6).`}>{`too few to rank (under ${MIN_TRADES_TO_RANK})`}</Label> : null}
                    <small>{`after ${cost} cost on ${plural(fr.trades, "trade")} · ${pct(figure(fr, "win_rate", cost))} won · drawdown ${money(cur, figure(fr, "max_drawdown", cost), d, true)}`}</small>
                    <LuckBar row={fr} cost={cost} span={72} />
                  </div>
                  {(["best_expected_gain", "highest_probability"] as const).map((k) => {
                    const r = pickRuleRow(p.h2h_rows, f, k);
                    return (
                      <div key={k} className="pr">
                        <span className="l">{PICK_RULE[k]}</span>
                        {r ? (
                          <span className="st">
                            <span>{plural(r.trades, "trade")}</span><span>{`${pct(figure(r, "win_rate", cost))} won`}</span>
                            {tooFewToRank(r) ? <span className="mb-label neutral" style={{ fontSize: 10.5, padding: "0 5px" }}>too few to rank</span> : null}
                            <LuckBar row={r} cost={cost} span={72} />
                          </span>
                        ) : <span className="st muted">no trade yet</span>}
                        {r ? <b><MoneyDelta currency={cur} value={figure(r, "net_pnl", cost)} decimals={d} /></b> : <b className="muted">{DASH}</b>}
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          );
        })}
      </div>
      <p className="note">{`Ranked on market cost (decision 50); your cost adds your broker’s charges. ${p.status.paper_label || PAPER_LABEL}: a paper trade is a record, never an order.`}</p>
    </Card>
  );
}

function OpenTradesCard({ p }: { p: Payload }) {
  const cur = p.currency, d = moneyDecimals(cur);
  const [filter, setFilter] = useState<OpenFilter>({ family: null, view: null });
  const groups = groupOpenTrades(p.open_trades, p.strategies, filter);
  const shown = groups.reduce((n, g) => n + g.trades.length, 0);
  const checks = useMemo(() => latestChecks(p.trade_checks), [p.trade_checks]);
  const newest = p.trade_checks.reduce<string | null>((at, c) => (at === null || c.check_at > at ? c.check_at : at), null);
  const chip = (label: string, on: boolean, set: () => void) => <button key={label} type="button" className="md-chip filter" aria-pressed={on} onClick={set}>{label}</button>;
  return (
    <Card label="Open paper trades by strategy">
      <CardHead title={<>Open paper trades by strategy <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>}
        end={`${shown} of ${p.open_trades.length} open${newest ? ` · checked ${fmtLocal(newest, p.market, p.status.session.local_time)}` : " · no intraday check yet"}`}
        help="Every paper trade that has entered (bought at the open of its entry session) and not yet exited, grouped by strategy: the accuracy view (one trade per qualifying prediction) and the head-to-head view (the daily picks, H2H). Unrealised = the latest stored close against the entry, before costs. Range = where the last close sits in the trade’s own predicted range. Check = the latest intraday check at its own price." />
      <div className="toolbar" role="group" aria-label="Filter the open trades" style={{ margin: "0 0 12px" }}>
        {chip("All families", filter.family === null, () => setFilter({ ...filter, family: null }))}
        {(["rule", "baseline", "ai"] as const).map((f) => chip(FAMILY[f][0], filter.family === f, () => setFilter({ ...filter, family: f })))}
        <span className="muted" style={{ margin: "0 4px" }} aria-hidden="true">·</span>
        {chip("Both views", filter.view === null, () => setFilter({ ...filter, view: null }))}
        {chip("Accuracy", filter.view === "accuracy", () => setFilter({ ...filter, view: "accuracy" }))}
        {chip("Head-to-head", filter.view === "head_to_head", () => setFilter({ ...filter, view: "head_to_head" }))}
      </div>
      {!p.open_trades.length ? <Quiet>No open paper trade: nothing has entered and not yet exited by the cut-off.</Quiet> : !shown ? <Quiet>No open paper trade matches the filter.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl ot">
            <thead><tr><th>Company</th><th>Horizon</th><th className="num cw">Entry</th><th className="num cw">Last</th><th className="num">Unrealised</th><th className="cm">Predicted range</th><th className="num c3">To target</th><th>Check</th></tr></thead>
            <tbody>
              {groups.map((g) => {
                const s = p.strategies[g.id], family: Family = s?.family ?? g.trades[0].family;
                return [
                  <tr key={g.id} className="grp">
                    <td colSpan={8}>
                      <Link className="tk" href={`${pagePath(p.market, "lab")}#${encodeURIComponent(g.id)}`} data-tip={`${s?.name ?? g.id}: open it in the Strategy lab.`}>{s?.name ?? g.id}</Link>{" "}
                      <FamilyLabel family={family}>{FAMILY_SHORT[family]}</FamilyLabel>
                      <small>{`${g.trades.length} open · unrealised `}</small><MoneyDelta currency={cur} value={g.unrealised} decimals={d} />
                    </td>
                  </tr>,
                  ...g.trades.map((t) => (
                    <tr key={t.trade_id}>
                      <td><span className="nm"><b><Link className="tk" href={companyPath(p.market, t.ticker)}>{t.ticker}</Link>{t.view === "head_to_head" ? <span className="mb-label neutral" style={{ marginLeft: 6, fontSize: 10.5, padding: "0 5px" }} data-tip="Head-to-head view: one of the daily picks for this company.">H2H</span> : null}</b><small>{p.companies.find((c) => c.ticker === t.ticker)?.name ?? t.ticker}</small></span></td>
                      <td><span className="h-lab">{`N+${t.horizon_days}`}</span><small className="muted cw" style={{ whiteSpace: "nowrap" }}>{` ${fmtDate(t.entry_date, false)} → ${fmtDate(t.exit_date, false)}`}</small></td>
                      <td className="num cw">{price(cur, t.entry_price)}</td>
                      <td className="num cw" data-tip={t.last_price_date ? `Latest stored close (${fmtDate(t.last_price_date)}).` : "No stored close yet."}>{price(cur, t.last_price)}</td>
                      <td className="num"><MoneyDelta currency={cur} value={t.unrealised_pnl} decimals={d} /><span className="cw"> <Delta value={t.unrealised_pct} /></span></td>
                      <td className="cm"><RangeBar currency={cur} bands={{ lo80: t.lo80, lo50: t.lo50, hi50: t.hi50, hi80: t.hi80, target_price: t.target_price }} last={t.last_price} entry={t.entry_price} /></td>
                      <td className="num c3"><span data-tip={t.to_target_pct === null ? "No target distance stored." : t.to_target_pct < 0 ? `Already past the target ${price(cur, t.target_price)}.` : `${signed(t.to_target_pct)} to the target ${price(cur, t.target_price)}.`}>{t.to_target_pct === null ? DASH : t.to_target_pct < 0 ? "past target" : signed(t.to_target_pct)}</span></td>
                      <td><TradeCheckStatus check={checks.get(t.trade_id) as unknown as SharedCheck | undefined} status={p.status} currency={cur} /></td>
                    </tr>
                  )),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const euro = (v: number) => (v < 0 ? "−" : "") + "€" + Math.abs(v).toLocaleString("en-IE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signedEuro = (v: number) => (v > 0 ? "+" : "") + euro(v);
const dir = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

function OwnerCard({ p, sent, onSent }: { p: Payload; sent: Sent[]; onSent: (s: Sent) => void }) {
  const cur = p.currency, d = moneyDecimals(cur), o = p.owner, lt = p.status.session.local_time;
  const [open, setOpen] = useState(false);
  return (
    <Card label="Your own paper portfolio">
      <CardHead title={<>Your own paper portfolio <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>}
        end={<button className="md-btn filled small" type="button" onClick={() => setOpen(true)}><Icon name="receipt_long" />Add own paper trade</button>}
        help="Your manual paper trades (WS4): each a record with its side, quantity, the price and its basis (the session’s open or close, or a manual price inside the day’s range), the date and the channel it came from. Positions are first-in-first-out, marked to the latest stored close, before costs. US positions carry a euro view (F1.11, decision 11): the EUR/USD rate on the buy date and now, and BUX’s FX markup each way." />
      {!o.positions.length && !o.trades.length ? (
        <Quiet>{`No own paper trade in ${p.name} yet. Add one above; the default amount per paper trade is ${money(cur, o.default_amount)}.`}</Quiet>
      ) : (
        <>
          {o.positions.length ? (
            <div className="md-table-wrap">
              <table className="md-table tbl own">
                <thead><tr><th>Position</th><th className="num">Shares</th><th className="num cw">Average price</th><th className="num cw">Last close</th><th className="num cm">Cost</th><th className="num">Value</th><th className="num">Profit</th></tr></thead>
                <tbody>
                  {o.positions.map((x) => (
                    <tr key={x.ticker}>
                      <td><Link className="tk" href={companyPath(p.market, x.ticker)}>{x.ticker}</Link><small className="muted" style={{ display: "block", fontSize: 11 }}>{p.companies.find((c) => c.ticker === x.ticker)?.name ?? x.ticker}</small></td>
                      <td className="num">{x.quantity}</td>
                      <td className="num cw">{price(cur, x.avg_price)}</td>
                      <td className="num cw" data-tip={x.last_close_date ? `Latest stored close, ${fmtDate(x.last_close_date)}.` : "No stored close."}>{price(cur, x.last_close)}</td>
                      <td className="num cm">{money(cur, x.cost, d)}</td>
                      <td className="num">{money(cur, x.value, d)}</td>
                      <td className="num pn"><b><MoneyDelta currency={cur} value={x.pnl} decimals={d} /></b><small>{signed(x.pnl_pct)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Quiet>No open position: the recorded trades below net to zero shares.</Quiet>}
          {o.positions.filter((x) => x.eur_view).map((x) => {
            const e = x.eur_view!;
            return (
              <div key={`eur-${x.ticker}`}>
                <div className="sub2" style={{ margin: "14px 0 0" }}>{`Euro view of ${x.ticker} (${plural(e.quantity, "share")}, marked ${fmtDate(e.mark_date, false)})`}<HelpTip tip={`What the position cost in euros and what it would give back if converted now: EUR/USD ${e.eurusd_at_buy} on the buy date, ${e.eurusd_now} now, FX markup ${(e.fx_fee_rate * 100).toFixed(2)}% each way. ${e.note}`} /></div>
                <div className="eur">
                  <div className="n" data-tip={`Dollars paid including the buy order’s cost: ${money(cur, e.cost_usd, 2)} ÷ ${e.eurusd_at_buy} × (1 + ${e.fx_fee_rate}).`}><div className="l">Euros paid</div><div className="v">{euro(e.cost_eur)}</div><div className="s">{`at EUR/USD ${e.eurusd_at_buy} + markup`}</div></div>
                  <div className="n" data-tip={`Dollars held now ${money(cur, e.value_usd, 2)} ÷ ${e.eurusd_now} × (1 − ${e.fx_fee_rate}).`}><div className="l">Euros back if sold now</div><div className="v">{euro(e.value_eur)}</div><div className="s">{`at EUR/USD ${e.eurusd_now} − markup`}</div></div>
                  <div className="n" data-tip="Euros back minus euros paid."><div className="l">Profit in euros</div><div className="v"><span className={`mb-delta ${dir(e.pnl_eur)}`}>{signedEuro(e.pnl_eur)}</span></div><div className="s">{`vs ${money(cur, x.pnl, 2, true)} in dollars before costs`}</div></div>
                  <div className="n" data-tip="The part of the euro result due to the exchange rate alone, before any fee."><div className="l">Of which the rate</div><div className="v"><span className={`mb-delta ${dir(e.fx_effect_eur)}`}>{signedEuro(e.fx_effect_eur)}</span></div><div className="s">rate change only</div></div>
                </div>
              </div>
            );
          })}
          <div className="sub2" style={{ margin: "14px 0 0" }}>{plural(o.trades.length, "recorded trade")}</div>
          <ul className="tl">
            {o.trades.map((t) => (
              <li key={t.id}>
                <Label tone={t.side === "buy" ? "success" : "warn"}>{t.side}</Label>
                <span>
                  {`${t.quantity} ${t.ticker} at ${price(cur, t.price)} (${t.price_basis === "manual" ? "manual price" : `the ${t.price_basis}`}) on ${fmtDate(t.trade_date)}`}
                  <small>{`from ${SOURCE[t.source] ?? t.source} · entered ${fmtLocal(t.entered_at, p.market, lt, true)}${t.note ? ` · “${t.note}”` : ""}${t.supersedes ? " · corrects an earlier record" : ""}`}</small>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="pend" aria-live="polite">
        {sent.map((s, i) => (
          <div key={i} className="mb-alert" style={{ padding: "10px 14px" }}>
            <Icon name="pending" />
            <div>
              <b className="t">{`Pending: ${s.words}`}</b>
              <div className="s">{`${s.duplicate ? "Already sent earlier with the same key; this is its receipt. " : ""}A paper trade is a record, never an order. Appended to the inbox${s.inboxId ? ` (${s.inboxId})` : ""} with your sign-in and an idempotency key; the next run imports it and checks the price against the stored bar (F10, WS4), then it shows above.`}</div>
            </div>
          </div>
        ))}
      </div>
      {open ? <TradeDialog p={p} onClose={() => setOpen(false)} onSent={(s) => { onSent(s); setOpen(false); }} /> : null}
    </Card>
  );
}

/** The add-trade form, in a modal dialog. One Idempotency-Key per opened form, reused whenever the same request is sent
 * again (after a 429/503, no answer, or a refusal); a changed request gets a new key, so a key never names two requests. */
function TradeDialog({ p, onClose, onSent }: { p: Payload; onClose: () => void; onSent: (s: Sent) => void }) {
  const cur = p.currency;
  const active = useMemo(() => p.companies.filter((c) => c.state === "active"), [p.companies]);
  const activeSet = useMemo(() => new Set(active.map((c) => c.ticker)), [active]);
  const [form, setForm] = useState<TradeForm>({ ticker: active[0]?.ticker ?? "", side: "buy", quantity: "1", trade_date: p.as_of ?? "", price_basis: "open", price: "", note: "" });
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  const usedFor = useRef<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const setRef = (node: HTMLDialogElement | null) => {
    dialog.current = node;
    if (node && !node.open) node.showModal();
  };
  const update = (patch: Partial<TradeForm>) => setForm((f) => ({ ...f, ...patch }));
  const words = (f: TradeForm) => `${f.side} ${f.quantity} ${f.ticker} at ${f.price_basis === "manual" ? (f.price ? price(cur, Number(f.price)) : "a typed price") : `the ${f.price_basis}`} on ${fmtDate(f.trade_date)}`;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const built = tradeRequest(form, cur, activeSet);
    if ("errors" in built) { setErrors(built.errors); return; }
    const signature = JSON.stringify(built.body);
    if (usedFor.current !== null && usedFor.current !== signature) key.current = newIdempotencyKey();
    usedFor.current = signature;
    setBusy(true);
    setErrors([]);
    try {
      const response = await fetch(`/api/v1/markets/${p.market}/paper-trades`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key.current },
        body: signature,
        credentials: "same-origin",
      });
      let receipt: Receipt | null = null;
      try { receipt = (await response.json()) as Receipt; } catch { receipt = null; }
      const state = receiptState(response.status);
      if (state === "pending" || state === "duplicate") {
        onSent({ words: words(form), inboxId: receipt?.inbox_id ?? null, duplicate: state === "duplicate" });
        return;
      }
      if (state === "retry") setErrors([`${receipt?.message ?? "The inbox cannot take the request right now."} Try again later; the same request keeps its key, so it is never recorded twice.`]);
      else {
        setErrors([receipt?.message ?? (receipt as unknown as { detail?: string })?.detail ?? `Refused (HTTP ${response.status}).`]);
      }
    } catch {
      setErrors(["No answer from the server. Try again; the same request keeps its key, so it is never recorded twice."]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <dialog className="md-dialog" ref={setRef} aria-labelledby="trade-title" onClose={onClose} onCancel={onClose}>
      <form onSubmit={submit} noValidate>
        <div className="dbody">
          <h3 id="trade-title">Add an own paper trade</h3>
          <div>A paper trade is a record of what you would have done, never an order. The price must be the stored bar’s open or close, or a typed price inside that day’s low-high; the import checks it (WS4). Whole shares in India, fractions in the US.</div>
          <label>Company
            <select value={form.ticker} onChange={(e) => update({ ticker: e.target.value })}>
              {active.map((c) => <option key={c.ticker} value={c.ticker}>{`${c.ticker} · ${c.name}`}</option>)}
            </select>
          </label>
          <div className="row2">
            <label>Side
              <select value={form.side} onChange={(e) => update({ side: e.target.value as TradeForm["side"] })}><option value="buy">Buy</option><option value="sell">Sell</option></select>
            </label>
            <label>Shares
              <input type="number" min="0" step={cur === "INR" ? "1" : "0.000001"} inputMode="decimal" value={form.quantity} onChange={(e) => update({ quantity: e.target.value })} />
            </label>
          </div>
          <div className="row2">
            <label>Price basis
              <select value={form.price_basis} onChange={(e) => update({ price_basis: e.target.value as TradeForm["price_basis"] })}>
                <option value="open">The session’s open</option><option value="close">The session’s close</option><option value="manual">A price I type (inside the day’s range)</option>
              </select>
            </label>
            <label>{`Price (${cur})`}
              <input type="number" step="0.01" inputMode="decimal" placeholder="only for a typed price" disabled={form.price_basis !== "manual"} value={form.price} onChange={(e) => update({ price: e.target.value })} />
            </label>
          </div>
          <label>Session date
            <input type="date" value={form.trade_date} max={p.as_of ?? undefined} onChange={(e) => update({ trade_date: e.target.value })} />
          </label>
          <label>Note (optional)
            <input type="text" maxLength={200} value={form.note} onChange={(e) => update({ note: e.target.value })} />
          </label>
          <div className="muted" style={{ fontSize: 12.5 }}>Recorded with your sign-in and an idempotency key; pending until the next run imports it. Nothing is bought or sold.</div>
          {errors.length ? (
            <div className="mb-alert danger" role="alert" style={{ padding: "10px 14px" }}>
              <Icon name="warning" />
              <div>{errors.map((m) => <div key={m}>{m}</div>)}</div>
            </div>
          ) : null}
        </div>
        <div className="dact">
          <button className="md-btn text" type="button" onClick={() => dialog.current?.close()}>Cancel</button>
          <button className="md-btn filled" type="submit" disabled={busy || !active.length}>{busy ? "Sending…" : "Record paper trade"}</button>
        </div>
      </form>
    </dialog>
  );
}
