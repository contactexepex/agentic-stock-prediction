// The assistant API of the dashboard (web/app/api/assistant/route.ts), served only behind Vercel Authentication
// (the app project; a 404 in gateway mode). Identity: dashboardContext("assistant"), never from the request.
//   POST /api/assistant {market, question, ticker?, strategy_id?} -> the explain tool through B5's tool layer.
//   GET  /api/assistant?market=india|us -> the market's conversation (90 days, newest 100) and the spend.
import type { ToolLayer } from "../tools/executor.ts";
import { dashboardContext } from "../tools/identity.ts";
import type { ToolOutcome } from "../tools/types.ts";
import { spendState, utcDayStart, utcMonthStart } from "./cost.ts";
import { HISTORY_TURNS, QUESTION_MAX, RETENTION_DAYS } from "./constants.ts";
import type { ConversationStore } from "./types.ts";

export interface AssistantApiDeps {
  /** The tool layer with the assistant as its explainer (withAssistant). */
  tools: ToolLayer;
  store: ConversationStore;
  clock: () => Date;
  gatewayMode: boolean;
  /** Origins a browser POST may come from (the app's own). */
  origins: string[];
}

const NO_STORE = { "Cache-Control": "no-store" };
const MAX_BODY = 4096;
export const HISTORY_LIMIT = 100;

/** The fixed numbers the panel shows (question length and retention as in design/mockups/_shared/shell.js; no money
 * budget since the owner's decision of 2026-10-08). */
export const LIMITS = { question_max: QUESTION_MAX, history_turns: HISTORY_TURNS, retention_days: RETENTION_DAYS };

const json = (status: number, body: unknown) => Response.json(body, { status, headers: NO_STORE });
const problem = (status: number, title: string, detail: string) =>
  new Response(JSON.stringify({ title, status, detail }), { status, headers: { ...NO_STORE, "Content-Type": "application/problem+json" } });

/** budget_exceeded: the tool layer's day budget of reads (mcp/agents/assistant.yaml), not money. */
const STATUS: Record<string, number> = { budget_exceeded: 429, kill_switch: 503, validation_failed: 422 };

function httpStatus(outcome: ToolOutcome): number {
  if (outcome.result === "accepted") return 200;
  if (outcome.result === "failed") return 503;
  return STATUS[outcome.refusal_code ?? ""] ?? 403;
}

export async function postQuestion(request: Request, deps: AssistantApiDeps): Promise<Response> {
  if (deps.gatewayMode) return problem(404, "Not found", "Not served here");
  if (!(request.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return problem(415, "Unsupported media type", "Send the question as application/json");
  }
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== new URL(request.url).origin && !deps.origins.includes(origin)) {
    return problem(403, "Forbidden", "Questions are taken from the app's own pages only");
  }
  const raw = await request.text();
  if (new TextEncoder().encode(raw).length > MAX_BODY) return problem(413, "Too large", `A question has at most ${QUESTION_MAX} characters`);
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return problem(400, "Bad request", "The body is not JSON");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return problem(400, "Bad request", "Send an object");
  const outcome = await deps.tools.execute(dashboardContext("assistant"), "explain", body);
  const data = (outcome.data ?? {}) as Record<string, unknown>;
  return json(httpStatus(outcome), {
    result: outcome.result, refusal_code: outcome.refusal_code, message: outcome.message, command_id: outcome.command_id,
    answer: data.answer ?? null, spend: data.spend ?? null, limits: LIMITS,
  });
}

export async function getConversation(request: Request, deps: AssistantApiDeps): Promise<Response> {
  if (deps.gatewayMode) return problem(404, "Not found", "Not served here");
  const market = new URL(request.url).searchParams.get("market") ?? "";
  if (market !== "india" && market !== "us") return problem(404, "Not found", "Unknown market");
  const now = deps.clock();
  const since = new Date(now.getTime() - RETENTION_DAYS * 86400000).toISOString();
  try {
    const [answers, spent, enabled] = await Promise.all([
      deps.store.list(market, since, HISTORY_LIMIT),
      deps.store.spend(utcDayStart(now), utcMonthStart(now)),
      deps.store.enabled(),
    ]);
    return json(200, { market, answers: [...answers].reverse(), spend: spendState(spent, now, enabled),
      limits: LIMITS, read_at: now.toISOString() });
  } catch {
    return problem(503, "Conversation log unavailable", "The assistant's log cannot be read right now");
  }
}
