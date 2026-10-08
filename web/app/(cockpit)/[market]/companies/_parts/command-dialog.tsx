"use client";
// The Companies page's request dialogs (design/mockups/10-companies/ addDialog, amountDialog, stateDialog, deleteDialog,
// manageDialog) on B11's routes: the form, then the server's preview (its summary and, for an add, the resolved
// identifiers), then Confirm, which sends that summary back unchanged. One Idempotency-Key per dialog, so a double
// click or a retry never records twice. A request is pending until the next run imports it; nothing here trades.
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "../../../../../components/ui/icon.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import {
  newIdempotencyKey, previewCommand, refusalWords, submitCommand, type CommandPreview, type CompanyTool,
} from "../../../../../lib/market-pages/company-commands-client.ts";
import { cleanReason, deleteConfirmed, parseAmount, REASON_MAX_CHARS } from "../../../../../lib/market-pages/companies.ts";
import { fmtDateYear, money } from "../../../../../lib/ui/format.ts";
import "./command-dialog.css";
import type { CompanyRecord } from "../../../../../lib/ui/types.ts";

export type Intent =
  | { kind: "add" }
  | { kind: "amount" | "deactivate" | "reactivate" | "delete" | "manage"; company: CompanyRecord };

export interface Recorded { tool: CompanyTool; summary: string; message: string | null; result: string }

type Stage = "form" | "checking" | "confirm" | "sending";

const NO_ANSWER_PREVIEW = "No answer from the server; nothing was checked or written. Try again.";
const NO_ANSWER_CONFIRM = "No answer from the server, so it is not known whether the request was recorded. Press Confirm again: this dialog sends the same request key, so it is never recorded twice.";

const TOOL_OF: Record<Exclude<Intent["kind"], "manage">, CompanyTool> = {
  add: "add_company", amount: "set_paper_amount", deactivate: "deactivate_company", reactivate: "reactivate_company", delete: "delete_company",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label>{label}{children}</label>;
}

export function CommandDialog({ intent, market, currency, defaultAmount, onClose, onRecorded, onSwitch }: {
  intent: Intent; market: Market; currency: string; defaultAmount: number;
  onClose: () => void; onRecorded: (r: Recorded) => void; onSwitch: (next: Intent) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [key] = useState(() => newIdempotencyKey());
  const [stage, setStage] = useState<Stage>("form");
  const [preview, setPreview] = useState<CommandPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  const [amountText, setAmountText] = useState(intent.kind === "amount" ? String(intent.company.amount ?? "") : "");
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);

  const company = intent.kind === "add" ? null : intent.company;
  const busy = stage === "checking" || stage === "sending";

  function argumentsOf(): Record<string, unknown> | string {
    switch (intent.kind) {
      case "add": {
        const s = symbol.trim().toUpperCase();
        if (!/^[A-Z0-9.&-]{1,20}$/.test(s)) return "Type the exchange symbol (letters, digits, '.', '&' or '-', at most 20).";
        if (!amountText.trim()) return { symbol: s };
        const a = parseAmount(amountText);
        return a === null ? `The amount must be a number of at least 1 ${currency}.` : { symbol: s, amount: a };
      }
      case "amount": {
        const a = parseAmount(amountText);
        return a === null ? `The amount must be a number of at least 1 ${currency}.` : { ticker: intent.company.ticker, amount: a };
      }
      case "deactivate": {
        const r = cleanReason(reason);
        return r ? { ticker: intent.company.ticker, reason: r } : { ticker: intent.company.ticker };
      }
      case "reactivate":
        return { ticker: intent.company.ticker };
      case "delete":
        return deleteConfirmed(typed, intent.company.ticker) ? { ticker: intent.company.ticker, confirm: intent.company.ticker } : `Type ${intent.company.ticker} to confirm.`;
      default:
        return "";
    }
  }

  async function check() {
    if (intent.kind === "manage") return;
    const args = argumentsOf();
    if (typeof args === "string") { setError(args); return; }
    setStage("checking"); setError(null); setNote(null);
    try {
      const res = await previewCommand(market, key, TOOL_OF[intent.kind], args);
      if (res.ok) { setPreview(res.preview); setStage("confirm"); }
      else { setError(refusalWords(res.status, res.receipt)); setStage("form"); }
    } catch {
      setError(NO_ANSWER_PREVIEW); setStage("form");
    }
  }

  async function confirm() {
    if (!preview) return;
    setStage("sending"); setError(null);
    try {
      const res = await submitCommand(market, key, preview);
      if (res.kind === "recorded") {
        onRecorded({ tool: preview.tool, summary: preview.summary, message: res.receipt.message, result: res.receipt.result });
        ref.current?.close();
        return;
      }
      if (res.kind === "stale") {
        const again = await previewCommand(market, key, preview.tool, preview.arguments);
        if (again.ok) { setPreview(again.preview); setNote("The summary changed since you checked it, so nothing was written. Read the new summary and confirm again."); setStage("confirm"); }
        else { setError(refusalWords(again.status, again.receipt)); setStage("form"); }
        return;
      }
      setError(refusalWords(res.status, res.receipt));
      setStage("confirm");
    } catch {
      // The server may have recorded it before the answer was lost: Confirm again sends the same key, so it is never
      // recorded twice (the route answers the stored receipt). The key lives as long as this dialog.
      setError(NO_ANSWER_CONFIRM);
      setStage("confirm");
    }
  }

  const title = (() => {
    if (stage === "confirm" || stage === "sending") return intent.kind === "add" ? `Confirm: add ${preview?.preview?.symbol ?? symbol.trim().toUpperCase()}?` : "Confirm the request";
    switch (intent.kind) {
      case "add": return "Add a company";
      case "amount": return `Change the amount for ${intent.company.name}`;
      case "deactivate": return `Deactivate ${intent.company.name}?`;
      case "reactivate": return `Reactivate ${intent.company.name}?`;
      case "delete": return `Delete ${intent.company.name}?`;
      default: return `${intent.company.ticker} · ${intent.company.name}`;
    }
  })();

  let body: ReactNode = null;
  let actions: ReactNode = null;
  const cancel = <button className="md-btn text" type="button" onClick={() => ref.current?.close()}>{intent.kind === "manage" ? "Close" : "Cancel"}</button>;

  if (stage === "confirm" || stage === "sending") {
    const r = preview?.preview;
    body = (
      <>
        {note ? <div className="dmsg err" role="status">{note}</div> : null}
        <div className="summ" aria-label="Summary">
          {r ? (
            <>
              <div className="r"><span>Symbol</span><b>{r.symbol}</b></div>
              <div className="r"><span>Name</span><span>{r.name}</span></div>
              <div className="r"><span>Exchange · sector</span><span>{`${r.exchange} · ${r.sector ?? "sector not resolved"}`}</span></div>
              <div className="r"><span>{market === "india" ? "Yahoo · NSE" : "Yahoo · CIK"}</span><span>{`${r.yahoo} · ${(market === "india" ? r.nse_symbol : r.cik) ?? "—"}`}</span></div>
              <div className="r"><span>Amount</span><b>{money(r.currency, r.amount)}{r.amount_is_default ? <span className="muted"> (default)</span> : null}</b></div>
            </>
          ) : null}
          <div className="r"><span>Request</span><span>{preview?.summary}</span></div>
        </div>
        <div className="muted" style={{ fontSize: 12.5 }}>
          Confirm records this request with your sign-in and an idempotency key; a double click never records twice. It is pending until the next run imports it.
        </div>
      </>
    );
    actions = (
      <>
        {cancel}
        <button className="md-btn filled" type="submit" disabled={busy}>{stage === "sending" ? "Recording…" : intent.kind === "delete" ? "Delete for good" : "Confirm"}</button>
      </>
    );
  } else if (intent.kind === "manage") {
    const c = intent.company;
    const btn = (text: string, icon: string, next: Intent, cls = "outlined") => (
      <button className={`md-btn ${cls}`} type="button" style={{ justifyContent: "flex-start" }} onClick={() => onSwitch(next)}><Icon name={icon} />{text}</button>
    );
    body = (
      <>
        <div className="muted" style={{ fontSize: 12.5 }}>
          {`${c.sector ?? "—"} · ${c.exchange ?? "—"} · ${money(currency, c.amount)} per paper trade${c.amount_overridden ? " (custom)" : ""} · ${c.state}${c.state === "inactive" ? ` since ${fmtDateYear(c.state_since)}` : ""}`}
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {btn("Change the amount", "account_balance_wallet", { kind: "amount", company: c })}
          {c.state === "active" ? btn("Deactivate", "pending", { kind: "deactivate", company: c }) : btn("Reactivate", "check", { kind: "reactivate", company: c }, "tonal")}
          {btn("Delete (typed confirmation)", "close", { kind: "delete", company: c }, "outlined danger")}
        </div>
      </>
    );
    actions = cancel;
  } else {
    const checkLabel = stage === "checking" ? "Checking…" : intent.kind === "add" ? "Check the symbol" : "Check the request";
    switch (intent.kind) {
      case "add":
        body = (
          <>
            <div>{`Takes the exchange symbol and an optional amount (F8.3). The onboarding checks the identifiers (${market === "india" ? "NSE and Yahoo symbols" : "ticker, Yahoo symbol and SEC CIK"}), refuses ETFs, ${market === "india" ? "BSE-only and unknown" : "unknown"} symbols, sets the sector, backfills prices, news and filings, runs the collect gate, and only then appends the add event. The company is predicted from the next pre-open run.`}</div>
            <Field label="Exchange symbol">
              <input type="text" autoFocus value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder={market === "india" ? "NSE symbol, e.g. TCS" : "NYSE or Nasdaq ticker, e.g. AMZN"} aria-label="Exchange symbol" />
            </Field>
            <Field label={`Amount per paper trade (${currency}, optional)`}>
              <input type="number" min="1" step="1" value={amountText} onChange={(e) => setAmountText(e.target.value)} placeholder={String(defaultAmount)} aria-label="Amount" />
            </Field>
            <div className="muted" style={{ fontSize: 12.5 }}>Next: the identifiers are checked and a summary (name, exchange, sector, Yahoo symbol, CIK, amount) is shown with Confirm and Cancel; only Confirm starts the onboarding (F8.7).</div>
          </>
        );
        break;
      case "amount":
        body = (
          <>
            <div>{`Money per paper trade. Today ${money(currency, intent.company.amount)}${intent.company.amount_overridden ? " (set for this company)" : " (the default)"}. In India a trade is skipped when one share costs more than the amount. Takes effect at the next pre-open run.`}</div>
            <Field label={`New amount (${currency})`}>
              <input type="number" min="1" step="1" autoFocus value={amountText} onChange={(e) => setAmountText(e.target.value)} aria-label="New amount" />
            </Field>
          </>
        );
        break;
      case "deactivate":
      case "reactivate":
        body = (
          <>
            <div>{intent.kind === "deactivate" ? "It stays collected (prices, news, filings) but gets no new prediction or paper trade; its open paper trades still settle. Takes effect at the next pre-open run (F8.4)." : "Predictions and paper trades resume from the next pre-open run (F8.4)."}</div>
            {intent.kind === "deactivate" ? (
              <Field label="Reason">
                <input type="text" maxLength={REASON_MAX_CHARS} value={reason} onChange={(e) => setReason(e.target.value)} placeholder={`optional, in your words (at most ${REASON_MAX_CHARS} characters)`} aria-label="Reason" />
              </Field>
            ) : null}
            <div className="muted" style={{ fontSize: 12.5 }}>Recorded with your sign-in and an idempotency key; pending until the next run imports it.</div>
          </>
        );
        break;
      case "delete":
        body = (
          <>
            <div className="warn"><Icon name="warning" /><div><b>This cannot be undone from the cockpit.</b> A delete appends a tombstone: the company is excluded on read everywhere, the warehouse and the graph drop it at the next sync, and every scoreboard and track record is computed without it from then on (F8.5, decision 12). Raw records stay in git history. Delete is available here only, never from Slack.</div></div>
            <Field label={`Type ${intent.company.ticker} to confirm`}>
              <input type="text" autoFocus autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={intent.company.ticker} aria-label={`Type ${intent.company.ticker} to confirm`} />
            </Field>
          </>
        );
        break;
    }
    const blocked = busy || (intent.kind === "delete" && company !== null && !deleteConfirmed(typed, company.ticker));
    actions = (
      <>
        {cancel}
        <button className="md-btn filled" type="submit" disabled={blocked}>{checkLabel}</button>
      </>
    );
  }

  return (
    <dialog ref={ref} className="md-dialog mb-cmd-dialog" aria-labelledby={titleId} onClose={onClose}>
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); if (stage === "confirm") void confirm(); else if (stage === "form") void check(); }}>
        <div className="dbody">
          <h3 id={titleId}>{title}</h3>
          {body}
          {error ? <div className="dmsg err" role="alert">{error}</div> : null}
        </div>
        <div className="dact">{actions}</div>
      </form>
    </dialog>
  );
}
