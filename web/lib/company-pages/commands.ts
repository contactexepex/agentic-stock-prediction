// The company page's watchlist commands (change amount, deactivate, reactivate) through B11's routes into B5's tool
// layer (api/paths/companies.yaml): POST .../companies/preview returns the plain-words summary the owner confirms and
// writes nothing; POST .../companies/commands, with the same Idempotency-Key and that summary, appends the command to
// the inbox, pending until the next import records it. Identity comes from the dashboard's sign-in, never from here.
// Nothing here buys or sells. Pure apart from the injected fetch.
import type { Market } from "../data/constants.ts";

export type CommandTool = "set_paper_amount" | "deactivate_company" | "reactivate_company";
export interface CompanyCommand {
  tool: CommandTool;
  arguments: { ticker: string; amount?: number | null; reason?: string };
}

export interface CommandReceipt {
  command_id?: string;
  result: "pending" | "accepted" | "duplicate" | "refused" | "failed";
  refusal_code?: string | null;
  message?: string | null;
  inbox_id?: string | null;
}

export type PreviewResult = { ok: true; summary: string } | { ok: false; message: string };
/** `unknown`: no readable answer, so whether the command was recorded is not known (retry with the same key). */
export type SubmitResult = { ok: true; receipt: CommandReceipt } | { ok: false; message: string; receipt: CommandReceipt | null; unknown: boolean };

type Fetch = (url: string, init: RequestInit) => Promise<Response>;

/** A fresh Idempotency-Key (a UUID: 36 characters of hex and dashes, as the API's pattern asks). */
export const newKey = (): string => crypto.randomUUID();

const commandUrl = (market: Market, step: "preview" | "commands") => `/api/v1/markets/${market}/companies/${step}`;

function post(fetchFn: Fetch, url: string, key: string, body: unknown): Promise<Response> {
  return fetchFn(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key, Accept: "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
}

async function readJson(res: Response): Promise<Record<string, unknown> | null> {
  try {
    const body = await res.json();
    return body && typeof body === "object" ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** A submit without an answer: whether it was recorded is not known; a retry with the same key never records twice. */
export const NO_ANSWER_ON_SUBMIT = "The data service did not answer, so it is not known whether the request was recorded. Confirm again: the same request key never records it twice.";

/** Why a request failed, in plain words: the receipt's or problem's message, else the HTTP status. */
function failure(res: Response | null, body: Record<string, unknown> | null): string {
  const said = body && (typeof body.message === "string" ? body.message : typeof body.detail === "string" ? body.detail : typeof body.title === "string" ? body.title : null);
  if (said) return said;
  if (!res) return "The data service did not answer; nothing was recorded.";
  return `The request was refused (HTTP ${res.status}); nothing was recorded.`;
}

/** Step 1: the summary to confirm. Nothing is written. */
export async function previewCommand(market: Market, command: CompanyCommand, key: string, fetchFn: Fetch = fetch): Promise<PreviewResult> {
  let res: Response | null = null;
  try {
    res = await post(fetchFn, commandUrl(market, "preview"), key, command);
  } catch {
    return { ok: false, message: failure(null, null) };
  }
  const body = await readJson(res);
  if (res.ok && body && typeof body.summary === "string" && body.summary) return { ok: true, summary: body.summary };
  return { ok: false, message: failure(res, body) };
}

/** Step 2: submit the confirmed command with the summary the owner saw (same key as the preview). */
export async function submitCommand(market: Market, command: CompanyCommand, summary: string, key: string, fetchFn: Fetch = fetch): Promise<SubmitResult> {
  let res: Response | null = null;
  try {
    res = await post(fetchFn, commandUrl(market, "commands"), key, { ...command, confirmed_summary: summary });
  } catch {
    return { ok: false, message: NO_ANSWER_ON_SUBMIT, receipt: null, unknown: true };
  }
  const body = await readJson(res);
  const receipt = body && typeof body.result === "string" ? (body as unknown as CommandReceipt) : null;
  if (res.ok && receipt && (receipt.result === "pending" || receipt.result === "accepted" || receipt.result === "duplicate")) return { ok: true, receipt };
  if (!body) return { ok: false, message: NO_ANSWER_ON_SUBMIT, receipt: null, unknown: true };
  return { ok: false, message: failure(res, body), receipt, unknown: false };
}

/** The pending line a confirmed command leaves on the card. */
export function pendingWords(command: CompanyCommand, receipt: CommandReceipt, amountWords: (x: number | null | undefined) => string): string {
  const what = command.tool === "set_paper_amount"
    ? `set the amount to ${command.arguments.amount == null ? "the market’s default" : amountWords(command.arguments.amount)}`
    : command.tool === "deactivate_company" ? "deactivate" : "reactivate";
  const state = receipt.result === "duplicate" ? "already requested" : receipt.result === "accepted" ? "accepted" : "pending";
  return `${what} (${state}${receipt.inbox_id ? `, request ${receipt.inbox_id.slice(0, 8)}` : ""})`;
}
