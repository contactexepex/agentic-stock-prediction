// POST /api/v1/markets/{market}/paper-trades (B13, the Paper portfolios page's add-trade form; api/paths/paper-portfolios.yaml
// createPaperTrade): a thin call into B5's governed tool layer (`add_paper_trade`, agent `dashboard`, identity from the
// dashboard's Vercel Authentication, never from the body). The tool layer validates, appends the request to the
// inbox (pending until `portfolio.py import-inbox` validates and stores it) and logs the call. A paper trade is a
// record, never an order: nothing is sent to any broker.
import type { CallContext, ToolArgs, ToolOutcome } from "../tools/types.ts";
import { isMarket } from "./handler.ts";
import { invalid, notFound, problem } from "./problem.ts";

export const PAPER_TRADE_TOOL = "add_paper_trade";
/** The body fields a submission may carry (mcp/tools.yaml add_paper_trade, without market and the key). */
export const BODY_FIELDS = ["ticker", "side", "quantity", "trade_date", "price_basis", "price", "note"] as const;
const KEY_HEADER = "idempotency-key";
const NO_STORE = { "Cache-Control": "no-store" };

export interface PaperTradeExecutor {
  execute(ctx: CallContext, toolName: string, raw: unknown): Promise<ToolOutcome>;
}

/** The HTTP status of a tool outcome: 202 pending (in the inbox), 200 the receipt of an earlier identical request,
 * 409 a key reused for another request, 422 invalid, 403 refused for the caller (channel, kill switch), 429 over
 * the day's write budget, 503 the inbox or log unavailable. */
export function statusOf(outcome: ToolOutcome): number {
  switch (outcome.result) {
    case "pending":
    case "accepted":
      return 202;
    case "duplicate":
      return 200;
    case "failed":
      return 503;
    default:
      switch (outcome.refusal_code) {
        case "duplicate_key":
          return 409;
        case "validation_failed":
        case "ambiguous":
          return 422;
        case "budget_exceeded":
          return 429;
        default:
          return 403;
      }
  }
}

/** The caller's view of an outcome (the tool layer's fields, no data). */
export function receipt(outcome: ToolOutcome): Record<string, unknown> {
  return {
    command_id: outcome.command_id,
    result: outcome.result,
    refusal_code: outcome.refusal_code,
    message: outcome.message,
    inbox_id: outcome.inbox_id,
    record_ids: outcome.record_ids,
    budget_left: outcome.budget_left,
    paper: true,
  };
}

/** A browser form of another site cannot post here: JSON only, and an Origin header (when sent) must be this host. */
function crossSite(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).host !== new URL(request.url).host;
  } catch {
    return true;
  }
}

export async function submitPaperTrade(
  request: Request, market: string, layer: PaperTradeExecutor, caller: CallContext,
): Promise<Response> {
  if (!isMarket(market)) return notFound("Unknown market");
  if (crossSite(request)) return problem(403, "Forbidden", "Cross-site requests are refused");
  if (!(request.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return problem(415, "Unsupported media type", "Send the trade as application/json");
  }
  const key = request.headers.get(KEY_HEADER);
  if (!key) return invalid("The Idempotency-Key header is required");
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return invalid("The body is not JSON");
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return invalid("The body must be an object");
  const unknown = Object.keys(body).filter((name) => !(BODY_FIELDS as readonly string[]).includes(name));
  if (unknown.length) return invalid(`Unknown fields: ${unknown.slice(0, 5).join(", ")}`);
  const args: ToolArgs = { ...(body as ToolArgs), market, idempotency_key: key };
  const outcome = await layer.execute(caller, PAPER_TRADE_TOOL, args);
  return Response.json(receipt(outcome), { status: statusOf(outcome), headers: NO_STORE });
}
