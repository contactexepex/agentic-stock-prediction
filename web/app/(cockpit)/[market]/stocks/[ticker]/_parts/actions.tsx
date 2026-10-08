"use client";
// The company page's watchlist actions (design/mockups/03-company openDialog, F8, F10): Change amount, Deactivate and
// Reactivate open a confirm dialog. The server's preview gives the plain-words summary; Confirm submits exactly that
// summary with the same Idempotency-Key (B11's routes into B5's tool layer), and the request shows as pending on the
// card until the next run imports it. Nothing is bought or sold. Delete stays on the Companies page (typed, F8).
import { useRef, useState } from "react";
import { Icon } from "../../../../../../components/ui/icon.tsx";
import { money } from "../../../../../../lib/ui/format.ts";
import type { CompanyRecord } from "../../../../../../lib/ui/types.ts";
import { newKey, pendingWords, previewCommand, submitCommand, type CompanyCommand } from "../../../../../../lib/company-pages/commands.ts";
import type { PageCtx } from "./context.ts";

export type ActionKind = "amount" | "deactivate" | "reactivate";

type Step =
  | { at: "form" }
  | { at: "checking" }
  | { at: "confirm"; summary: string }
  | { at: "sending"; summary: string }
  | { at: "error"; message: string; summary: string | null };

const TOOL = { amount: "set_paper_amount", deactivate: "deactivate_company", reactivate: "reactivate_company" } as const;

/** The dialog and the pending requests; `open(kind)` starts one. */
export function useWatchlistActions(company: CompanyRecord, ctx: PageCtx) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState<ActionKind>("amount");
  const [step, setStep] = useState<Step>({ at: "form" });
  const [amount, setAmount] = useState(String(company.amount ?? ""));
  const [reason, setReason] = useState("");
  const [key, setKey] = useState("");
  const [pending, setPending] = useState<string[]>([]);

  const command = (k: ActionKind): CompanyCommand => k === "amount"
    ? { tool: TOOL.amount, arguments: { ticker: company.ticker, amount: Number(amount) } }
    : k === "deactivate"
      ? { tool: TOOL.deactivate, arguments: { ticker: company.ticker, ...(reason.trim() ? { reason: reason.trim() } : {}) } }
      : { tool: TOOL.reactivate, arguments: { ticker: company.ticker } };

  const preview = async (k: ActionKind, useKey: string) => {
    setStep({ at: "checking" });
    const out = await previewCommand(ctx.market, command(k), useKey);
    setStep(out.ok ? { at: "confirm", summary: out.summary } : { at: "error", message: out.message, summary: null });
  };

  const open = (k: ActionKind) => {
    const fresh = newKey();
    setKind(k);
    setKey(fresh);
    setAmount(String(company.amount ?? ""));
    setReason("");
    setStep({ at: "form" });
    dialog.current?.showModal();
  };

  const confirm = async (summary: string) => {
    setStep({ at: "sending", summary });
    const cmd = command(kind);
    const out = await submitCommand(ctx.market, cmd, summary, key);
    if (out.ok) {
      setPending((p) => [...p, pendingWords(cmd, out.receipt, (x) => money(ctx.currency, x))]);
      dialog.current?.close();
    } else {
      setStep({ at: "error", message: out.message, summary });
    }
  };

  const amountValid = Number.isFinite(Number(amount)) && Number(amount) >= 1 && amount.trim() !== "";
  const co = company;
  const title = kind === "amount" ? `Change the amount for ${co.name}` : kind === "deactivate" ? `Deactivate ${co.name}?` : `Reactivate ${co.name}?`;
  const text = kind === "amount"
    ? `Money per paper trade. Today ${money(ctx.currency, co.amount)}${co.amount_overridden ? " (set for this company)" : " (the default)"}. In India a trade is skipped when one share costs more than the amount.`
    : kind === "deactivate"
      ? "It stays collected (prices, news, filings) but gets no new prediction or paper trade; its open paper trades still settle. Reactivate any time from here or the Companies page."
      : "Predictions and paper trades resume from the next pre-open run.";
  const label = kind === "amount" ? "Record amount" : kind === "deactivate" ? "Record deactivation" : "Record reactivation";
  const busy = step.at === "checking" || step.at === "sending";

  const element = (
    <dialog className="md-dialog" ref={dialog} aria-labelledby="act-title" onClose={() => setStep({ at: "form" })}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <div className="dbody">
          <h3 id="act-title">{title}</h3>
          <div>{text}</div>
          {kind === "amount" ? (
            <label>
              New amount ({ctx.currency})
              <input type="number" min={1} step={1} value={amount} disabled={step.at !== "form" && step.at !== "error"} onChange={(e) => setAmount(e.target.value)} aria-invalid={!amountValid} />
            </label>
          ) : kind === "deactivate" ? (
            <label>
              Reason (optional)
              <input type="text" maxLength={200} value={reason} disabled={step.at !== "form" && step.at !== "error"} onChange={(e) => setReason(e.target.value)} />
            </label>
          ) : null}
          {step.at === "checking" ? <div className="muted" role="status">Checking the request…</div> : null}
          {step.at === "confirm" || step.at === "sending" ? (
            <div className="mb-alert" role="status" style={{ padding: "10px 14px" }}>
              <Icon name="info" />
              <div><b className="t">You are about to record:</b><div className="s">{step.summary}</div></div>
            </div>
          ) : null}
          {step.at === "error" ? (
            <div className="mb-alert danger" role="alert" style={{ padding: "10px 14px" }}>
              <Icon name="warning" />
              <div><b className="t">Nothing was recorded</b><div className="s">{step.message}</div></div>
            </div>
          ) : null}
          <div className="muted" style={{ fontSize: 12.5 }}>This records a request with your sign-in and an idempotency key; the next run imports it. Nothing is bought or sold.</div>
        </div>
        <div className="dact">
          <button className="md-btn text" type="button" onClick={() => dialog.current?.close()}>Cancel</button>
          {step.at === "confirm" || step.at === "sending" ? (
            <button className="md-btn filled" type="button" disabled={busy} onClick={() => confirm(step.summary)}>{label}</button>
          ) : step.at === "error" && step.summary ? (
            <button className="md-btn filled" type="button" onClick={() => { const fresh = newKey(); setKey(fresh); void preview(kind, fresh); }}>Review again</button>
          ) : (
            <button className="md-btn filled" type="button" disabled={busy || (kind === "amount" && !amountValid)} onClick={() => void preview(kind, key)}>Review</button>
          )}
        </div>
      </form>
    </dialog>
  );
  return { open, element, pending };
}
