// The Companies page's dialogs talk to B11's routes (api/paths/companies.yaml previewCompanyCommand and
// createCompanyCommand): one Idempotency-Key per dialog, sent on the preview and on the confirm; the confirm sends back
// the preview's summary exactly as shown. Nothing here decides; the tool layer refuses or accepts.

export type CompanyTool = "add_company" | "deactivate_company" | "reactivate_company" | "set_paper_amount" | "delete_company";

export interface ResolvedCompany {
  market: string; symbol: string; name: string; exchange: string; sector: string | null; yahoo: string;
  nse_symbol: string | null; cik: string | null; amount: number; amount_is_default: boolean; currency: "INR" | "USD";
}
export interface CommandPreview { tool: CompanyTool; summary: string; preview: ResolvedCompany | null; arguments: Record<string, unknown>; paper: true }
export interface CommandReceipt {
  command_id: string; result: "pending" | "accepted" | "duplicate" | "refused" | "failed"; refusal_code: string | null;
  message: string | null; inbox_id: string | null; record_ids: string[]; budget_left: number | null; paper: true;
}

/** The message of B11's 422 when the summary changed between the preview and the confirm (lib/data/company-commands.ts). */
export const STALE_SUMMARY = "The summary changed since the preview, so nothing was written; preview again";

export type PreviewOutcome = { ok: true; preview: CommandPreview } | { ok: false; status: number; receipt: CommandReceipt | null };
export type SubmitOutcome =
  | { kind: "recorded"; status: number; receipt: CommandReceipt }
  | { kind: "stale"; receipt: CommandReceipt }
  | { kind: "refused"; status: number; receipt: CommandReceipt | null };

/** A fresh key matching ^[A-Za-z0-9_-]{8,64}$: "dash-" and 32 hex characters of a random UUID. */
export function newIdempotencyKey(randomUUID: () => string = () => crypto.randomUUID()): string {
  return `dash-${randomUUID().replace(/-/g, "")}`;
}

const base = (market: string) => `/api/v1/markets/${encodeURIComponent(market)}/companies`;

async function post(fetcher: typeof fetch, url: string, key: string, body: unknown): Promise<{ status: number; json: unknown }> {
  const res = await fetcher(url, {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": key },
    body: JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
  });
  let json: unknown = null;
  try { json = await res.json(); } catch { json = null; }
  return { status: res.status, json };
}

const asReceipt = (json: unknown): CommandReceipt | null =>
  json && typeof json === "object" && "result" in json ? (json as CommandReceipt) : null;

/** The summary to confirm; nothing is written. */
export async function previewCommand(market: string, key: string, tool: CompanyTool, args: Record<string, unknown>, fetcher: typeof fetch = fetch): Promise<PreviewOutcome> {
  const { status, json } = await post(fetcher, `${base(market)}/preview`, key, { tool, arguments: args });
  if (status === 200 && json && typeof json === "object" && "summary" in json) return { ok: true, preview: json as CommandPreview };
  return { ok: false, status, receipt: asReceipt(json) };
}

/** Records the confirmed command (pending until the next import); a changed summary asks for a new preview. */
export async function submitCommand(market: string, key: string, preview: CommandPreview, fetcher: typeof fetch = fetch): Promise<SubmitOutcome> {
  const { status, json } = await post(fetcher, `${base(market)}/commands`, key, { tool: preview.tool, arguments: preview.arguments, confirmed_summary: preview.summary });
  const receipt = asReceipt(json);
  if (receipt && (status === 200 || status === 202) && (receipt.result === "pending" || receipt.result === "accepted" || receipt.result === "duplicate")) {
    return { kind: "recorded", status, receipt };
  }
  if (status === 422 && receipt?.message === STALE_SUMMARY) return { kind: "stale", receipt };
  return { kind: "refused", status, receipt };
}

/** Words for a refusal: the tool layer's message, else the HTTP status in plain words. */
export function refusalWords(status: number, receipt: CommandReceipt | null): string {
  if (receipt?.message) return receipt.message;
  const words: Record<number, string> = {
    403: "This channel may not make that change.", 404: "Unknown market.", 409: "This request key was already used for another request.",
    415: "The request was not sent as JSON.", 422: "The request was refused as invalid.", 429: "Today's budget for changes is used up.",
    503: "The request log is unavailable or changes are switched off; nothing was written.",
  };
  return words[status] ?? `The request failed (HTTP ${status}); nothing was confirmed.`;
}
