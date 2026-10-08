// Slash commands /company, /trade and /ask (docs/SPEC.md F8.7, F10, F11). The request was verified with Slack's
// signing secret before this runs; identity is the signed request's user id. Any member of #market-brief may give
// commands (decision 15): commands are accepted only in that channel (its id is unique across workspaces, so it also
// pins the workspace). Only Confirm writes.
import type { ToolLayer } from "../../../lib/tools/executor.ts";
import type { CallContext, RefusalCode, ToolOutcome } from "../../../lib/tools/types.ts";
import { slackContext } from "../../../lib/tools/identity.ts";
import type { SlackApi } from "./api.ts";
import { RESULT_HEADINGS, USAGE, companyAddModal, confirmMessage, ephemeral, tradeModal } from "./views.ts";

export interface SlackDeps {
  tools: ToolLayer;
  slack: SlackApi;
  defer: (task: () => Promise<void>) => void;
  channelId: string;
  newKey: () => string;
  /** The Slack message body of an /ask answer; B8's formatter when wired, else `plainAnswer`. */
  formatAnswer?: (outcome: ToolOutcome) => unknown;
}

export const ASK_USAGE = "Usage: /ask india|us <question>. Answers come from the stored data only; never advice.";
export const ASK_WAIT = "Looking that up in the stored data…";

/** An /ask answer as plain text (no mrkdwn, so nothing in it can ping or link): the answer text with its cited ids and
 * as-of time, or the refusal or failure. */
export function plainAnswer(outcome: ToolOutcome): unknown {
  const data = outcome.data && typeof outcome.data === "object" ? outcome.data as Record<string, unknown> : null;
  if (outcome.result !== "accepted" || typeof data?.text !== "string") {
    const heading = RESULT_HEADINGS[outcome.result] ?? outcome.result;
    return ephemeral(`${heading}: ${outcome.message ?? "no answer"}`);
  }
  const cited = Array.isArray(data.cited_ids) ? data.cited_ids.filter((id) => typeof id === "string") : [];
  const lines = [data.text];
  if (cited.length) lines.push(`Sources: ${cited.join(", ")}`);
  if (typeof data.as_of === "string") lines.push(`As of ${data.as_of}`);
  lines.push("Research only, not advice.");
  return ephemeral(lines.join("\n"));
}

export interface SlackReply {
  status: number;
  body: unknown | null;
}

const ok = (body: unknown | null = null): SlackReply => ({ status: 200, body });
const SLACK_USER = /^[UW][A-Z0-9]{2,20}$/;

function market(token: string | undefined): "india" | "us" | null {
  const lower = (token ?? "").toLowerCase();
  if (lower === "india" || lower === "in") return "india";
  if (lower === "us" || lower === "usa") return "us";
  return null;
}

function amount(token: string | undefined): number | null | string {
  if (token === undefined) return "missing";
  if (token.toLowerCase() === "default") return null;
  const parsed = Number(token.replace(/[,_₹$]/g, ""));
  return Number.isFinite(parsed) ? parsed : token;
}

/** The channel check; a refusal is logged (the user id comes from the signed request). */
async function admitted(params: URLSearchParams, deps: SlackDeps, tool: string | null): Promise<CallContext | SlackReply> {
  const userId = params.get("user_id") ?? "";
  if (!SLACK_USER.test(userId)) return ok(ephemeral("This request has no Slack user."));
  const ctx = slackContext(userId);
  const refuse = async (code: RefusalCode, message: string) => {
    await deps.tools.record(ctx, { tool, kind: null, market: null, args: { text: params.get("text") ?? "" }, result: "refused", code, message });
    return ok(ephemeral(message));
  };
  if (params.get("channel_id") !== deps.channelId) {
    return refuse("not_allowed_in_channel", "market-brief commands work in #market-brief only.");
  }
  return ctx;
}

/** Logs a command that only opened a form or showed help (no tool call yet); a form that failed to open is a failure. */
async function logStep(ctx: CallContext, deps: SlackDeps, params: URLSearchParams, tool: string | null, done: boolean,
  message: string): Promise<void> {
  await deps.tools.record(ctx, { tool, kind: null, market: null, args: { text: params.get("text") ?? "" },
    result: done ? "accepted" : "failed", code: null, message: done ? message : message.replace(" opened", " not opened (Slack refused)") });
}

async function confirmStep(ctx: CallContext, deps: SlackDeps, tool: string, args: Record<string, unknown>): Promise<SlackReply> {
  const preview = await deps.tools.preview(ctx, tool, args);
  if (!preview.ok) return ok(ephemeral(`Not done: ${preview.outcome?.message ?? "refused"}`));
  return ok(confirmMessage(preview.summary ?? tool, JSON.stringify({ tool, args: preview.args })));
}

async function company(ctx: CallContext, params: URLSearchParams, deps: SlackDeps): Promise<SlackReply> {
  const words = (params.get("text") ?? "").trim().split(/\s+/).filter(Boolean);
  const sub = (words[0] ?? "add").toLowerCase();
  const key = deps.newKey();
  const ticker = words[2]?.toUpperCase();
  switch (sub) {
    case "add": {
      const chosen = market(words[1]);
      const rest = chosen ? words.slice(2) : words.slice(1);   // "/company add MSFT" works without a market
      const opened = await deps.slack.viewsOpen(params.get("trigger_id") ?? "",
        companyAddModal(key, { market: chosen, symbol: rest[0]?.toUpperCase() ?? null, amount: rest[1] ?? null }));
      await logStep(ctx, deps, params, "add_company", opened, "add form opened");
      return opened ? ok() : ok(ephemeral("The add form could not be opened; please try again."));
    }
    case "deactivate": {
      const reason = words.slice(3).join(" ");
      return confirmStep(ctx, deps, "deactivate_company",
        { market: market(words[1]), ticker, ...(reason ? { reason } : {}), idempotency_key: key });
    }
    case "reactivate":
      return confirmStep(ctx, deps, "reactivate_company", { market: market(words[1]), ticker, idempotency_key: key });
    case "amount":
      return confirmStep(ctx, deps, "set_paper_amount", { market: market(words[1]), ticker, amount: amount(words[3]), idempotency_key: key });
    case "delete": {
      const outcome = await deps.tools.execute(ctx, "delete_company", { market: market(words[1]), ticker });
      return ok(ephemeral(`Not done: ${outcome.message ?? "refused"}. Delete is only on the dashboard, with a typed confirmation.`));
    }
    case "help":
      await logStep(ctx, deps, params, null, true, "help shown");
      return ok(ephemeral(USAGE));
    default:
      await deps.tools.record(ctx, { tool: null, kind: null, market: null, args: { text: params.get("text") ?? "" },
        result: "refused", code: "validation_failed", message: "Unknown /company command" });
      return ok(ephemeral(`Unknown /company command.\n${USAGE}`));
  }
}

export async function handleCommand(params: URLSearchParams, deps: SlackDeps): Promise<SlackReply> {
  const command = params.get("command");
  const tool = command === "/trade" ? "add_paper_trade" : command === "/ask" ? "explain" : null;
  const ctx = await admitted(params, deps, tool);
  if (!("channel" in ctx)) return ctx;
  switch (command) {
    case "/company":
      return company(ctx, params, deps);
    case "/trade": {
      const opened = await deps.slack.viewsOpen(params.get("trigger_id") ?? "", tradeModal(deps.newKey()));
      await logStep(ctx, deps, params, "add_paper_trade", opened, "trade form opened");
      return opened ? ok() : ok(ephemeral("The trade form could not be opened; please try again."));
    }
    case "/ask": {
      const text = (params.get("text") ?? "").trim();
      const first = text.split(/\s+/)[0] ?? "";
      const askMarket = market(first);
      const question = text.slice(first.length).trim();
      if (askMarket === null || question === "") {
        await deps.tools.record(ctx, { tool: "explain", kind: "read_ai", market: askMarket, args: { text: text.slice(0, 500) },
          result: "refused", code: "validation_failed", message: ASK_USAGE });
        return ok(ephemeral(ASK_USAGE));
      }
      const assistant = slackContext(params.get("user_id") ?? "", "assistant");
      const responseUrl = params.get("response_url") ?? "";
      deps.defer(async () => {
        const outcome = await deps.tools.execute(assistant, "explain", { market: askMarket, question });
        await deps.slack.respond(responseUrl, (deps.formatAnswer ?? plainAnswer)(outcome));
      });
      return ok(ephemeral(ASK_WAIT));
    }
    default:
      await deps.tools.record(ctx, { tool: null, kind: null, market: null, args: { command: (command ?? "").slice(0, 40) },
        result: "refused", code: "validation_failed", message: "Unknown command" });
      return ok(ephemeral(USAGE));
  }
}
