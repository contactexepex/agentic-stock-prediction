"use client";
// Your own paper portfolio on the Paper portfolios page (B16; moved unchanged into its own file by UX3): positions,
// the euro view of US positions, the recorded trades, the add-trade form (POST /api/v1/markets/{market}/paper-trades,
// one Idempotency-Key per opened form) and its pending receipts. A paper trade is a record, never an order.
import Link from "next/link";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { HelpTip, Icon } from "../../../../../components/ui/icon.tsx";
import { Card, CardHead, Label, MoneyDelta, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { PAPER_LABEL } from "../../../../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtLocal, money, moneyDecimals, price, signed } from "../../../../../lib/ui/format.ts";
import { companyPath } from "../../../../../lib/ui/routes.ts";
import { newIdempotencyKey, receiptState, SOURCE, tradeRequest, type PaperPortfoliosPayload, type Receipt, type TradeForm } from "../../../../../lib/strategy-pages/paper-portfolios.ts";
import type { PageBase } from "../../../../../lib/ui/types.ts";

type Payload = PageBase & PaperPortfoliosPayload;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** A request the form sent and the tool layer accepted into the inbox (pending until the next run imports it). */
export interface Sent {
  words: string;
  inboxId: string | null;
  duplicate: boolean;
}

const euro = (v: number) => (v < 0 ? "−" : "") + "€" + Math.abs(v).toLocaleString("en-IE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signedEuro = (v: number) => (v > 0 ? "+" : "") + euro(v);
const dir = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

export function OwnerCard({ p, sent, onSent }: { p: Payload; sent: Sent[]; onSent: (s: Sent) => void }) {
  const cur = p.currency, d = moneyDecimals(cur), o = p.owner, lt = p.status.session.local_time;
  const [open, setOpen] = useState(false);
  return (
    <Card label="Your own paper portfolio">
      <CardHead title={<>Your own paper portfolio <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>}
        end={<button className="md-btn filled small" type="button" onClick={() => setOpen(true)}><Icon name="receipt_long" />Add own paper trade</button>}
        help="Your manual paper trades: each a record with its side, quantity, the price and its basis (the session’s open or close, or a manual price inside the day’s range), the date and the channel it came from. Positions are first-in-first-out, marked to the latest stored close, before costs. US positions carry a euro view: the EUR/USD rate on the buy date and now, and BUX’s FX markup each way." />
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
                  {`${t.quantity ?? DASH} ${t.ticker} at ${price(cur, t.price)} (${t.price_basis === "manual" ? "manual price" : `the ${t.price_basis}`}) on ${fmtDate(t.trade_date)}`}
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
              <div className="s">{`${s.duplicate ? "Already sent earlier with the same key; this is its receipt. " : ""}A paper trade is a record, never an order. Saved${s.inboxId ? ` (${s.inboxId})` : ""} with your sign-in; sending it twice is safe. The next run checks the price against the stored day’s prices, then it shows above.`}</div>
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
  const key = useRef<string>("");
  if (!key.current) key.current = newIdempotencyKey();
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
          <div>A paper trade is a record of what you would have done, never an order. The price must be the stored bar’s open or close, or a typed price inside that day’s low-high; the next run checks it. Whole shares in India, fractions in the US.</div>
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
              <div>{errors.map((m, i) => <div key={i}>{m}</div>)}</div>
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
