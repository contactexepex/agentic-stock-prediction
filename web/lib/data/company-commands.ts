// The Companies page's commands (B11; api/paths/companies.yaml previewCompanyCommand, createCompanyCommand): add,
// deactivate, reactivate, change amount and delete, as thin calls into B5's governed tool layer (agent `dashboard`,
// identity from the dashboard's Vercel Authentication, never from the body; refused in gateway mode).
// POST .../companies/preview returns the plain-words summary (and, for add_company, the resolved identifiers) and
// writes nothing. POST .../companies/commands runs the preview again on the server and writes only when the summary
// the owner confirmed is exactly the one it gives now, so what is appended to the inbox is what the owner saw; the
// browser never sends resolved identifiers. Delete also needs the ticker typed in `arguments.confirm` (decision 20).
// Pending until `company.py import-inbox` validates and appends the event (onboard.yml).
import type {
  CallContext, CommandResult, ExecuteOptions, PreviewOutcome, RefusalCode, ToolArgs, ToolKind, ToolOutcome,
} from "../tools/types.ts";
import { isMarket } from "./handler.ts";
import { crossSite, receipt, statusOf } from "./paper-trades.ts";
import { notFound, problem } from "./problem.ts";

export const COMPANY_TOOLS = [
  "add_company", "deactivate_company", "reactivate_company", "set_paper_amount", "delete_company",
] as const;
export const PREVIEW_FIELDS = ["tool", "arguments"] as const;
export const COMMAND_FIELDS = ["tool", "arguments", "confirmed_summary"] as const;
/** Set by the route from the path and the header, never by the body. */
const ROUTE_ARGUMENTS = ["market", "idempotency_key"];
const KEY_HEADER = "idempotency-key";
const NO_STORE = { "Cache-Control": "no-store" };
export const STALE_SUMMARY = "The summary changed since the preview, so nothing was written; preview again";

export interface CompanyCommandLayer {
  preview(ctx: CallContext, toolName: string, raw: unknown): Promise<PreviewOutcome>;
  execute(ctx: CallContext, toolName: string, raw: unknown, opts?: ExecuteOptions): Promise<ToolOutcome>;
  record(ctx: CallContext, fields: { tool: string | null; kind: ToolKind | null; market: string | null; args: unknown;
    result: CommandResult; code: RefusalCode | null; message: string }): Promise<ToolOutcome>;
}

type Parsed = { ok: true; tool: string; args: ToolArgs; body: Record<string, unknown> } | { ok: false; response: Response };

function isCompanyTool(name: unknown): name is string {
  return typeof name === "string" && (COMPANY_TOOLS as readonly string[]).includes(name);
}

/** The checks both routes share: market, same-site JSON, the key header, a known company tool and its arguments.
 * Refusals after the probes (cross-site, content type) are logged in inbox.command_log like the tool layer's own. */
async function parse(request: Request, market: string, layer: CompanyCommandLayer, caller: CallContext,
  fields: readonly string[]): Promise<Parsed> {
  if (!isMarket(market)) return { ok: false, response: notFound("Unknown market") };
  if (crossSite(request)) return { ok: false, response: problem(403, "Forbidden", "Cross-site requests are refused") };
  if (!(request.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return { ok: false, response: problem(415, "Unsupported media type", "Send the command as application/json") };
  }
  let tool: string | null = null;
  const refuse = async (message: string): Promise<Parsed> => {
    const outcome = await layer.record(caller, { tool, kind: tool ? "write" : null, market, args: {},
      result: "refused", code: "validation_failed", message });
    return { ok: false, response: Response.json(receipt(outcome), { status: 422, headers: NO_STORE }) };
  };
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return refuse("The body is not JSON");
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return refuse("The body must be an object");
  const record = body as Record<string, unknown>;
  if (isCompanyTool(record.tool)) tool = record.tool;
  const unknown = Object.keys(record).filter((name) => !fields.includes(name));
  if (unknown.length) return refuse(`Unknown fields: ${unknown.slice(0, 5).join(", ")}`);
  if (tool === null) return refuse(`tool must be one of ${COMPANY_TOOLS.join(", ")}`);
  const key = request.headers.get(KEY_HEADER);
  if (!key) return refuse("The Idempotency-Key header is required");
  const args = record.arguments;
  if (typeof args !== "object" || args === null || Array.isArray(args)) return refuse("arguments must be an object");
  const routeSet = Object.keys(args).filter((name) => ROUTE_ARGUMENTS.includes(name));
  if (routeSet.length) return refuse(`Set by the route, not the body: ${routeSet.join(", ")}`);
  return { ok: true, tool, args: { ...(args as ToolArgs), market, idempotency_key: key }, body: record };
}

function refusedPreview(outcome: ToolOutcome | undefined): Response {
  if (!outcome) return problem(503, "Unavailable", "The preview could not be made now");
  return Response.json(receipt(outcome), { status: statusOf(outcome), headers: NO_STORE });
}

/** The arguments the preview validated, without the ones the route sets. */
function shownArguments(args: ToolArgs | undefined): ToolArgs {
  return Object.fromEntries(Object.entries(args ?? {}).filter(([name]) => !ROUTE_ARGUMENTS.includes(name)));
}

export async function previewCompanyCommand(
  request: Request, market: string, layer: CompanyCommandLayer, caller: CallContext,
): Promise<Response> {
  const parsed = await parse(request, market, layer, caller, PREVIEW_FIELDS);
  if (!parsed.ok) return parsed.response;
  const preview = await layer.preview(caller, parsed.tool, parsed.args);
  if (!preview.ok) return refusedPreview(preview.outcome);
  return Response.json({ tool: parsed.tool, summary: preview.summary ?? null, preview: preview.preview ?? null,
    arguments: shownArguments(preview.args), paper: true }, { status: 200, headers: NO_STORE });
}

export async function submitCompanyCommand(
  request: Request, market: string, layer: CompanyCommandLayer, caller: CallContext,
): Promise<Response> {
  const parsed = await parse(request, market, layer, caller, COMMAND_FIELDS);
  if (!parsed.ok) return parsed.response;
  const { tool, args, body } = parsed;
  const confirmed = body.confirmed_summary;
  const refuse = async (message: string): Promise<Response> => {
    const outcome = await layer.record(caller, { tool, kind: "write", market, args: {}, result: "refused",
      code: "validation_failed", message });
    return Response.json(receipt(outcome), { status: 422, headers: NO_STORE });
  };
  if (typeof confirmed !== "string" || confirmed === "") return refuse("confirmed_summary is required");
  const preview = await layer.preview(caller, tool, args);
  if (!preview.ok) return refusedPreview(preview.outcome);
  if (preview.summary !== confirmed) return refuse(STALE_SUMMARY);
  const outcome = await layer.execute(caller, tool, args, { confirmedSummary: true, preview: preview.preview ?? null });
  return Response.json(receipt(outcome), { status: statusOf(outcome), headers: NO_STORE });
}
