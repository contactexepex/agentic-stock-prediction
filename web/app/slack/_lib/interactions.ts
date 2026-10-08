// Slack interactivity: modal submissions (add form -> summary -> Confirm; paper trade) and the Confirm / Cancel
// buttons of /company deactivate, reactivate and amount. The payload was verified with Slack's signing secret; the
// actor is the payload's user id. Buttons are honoured only in #market-brief; a modal can only have been opened by a
// command given there. Work that may take longer than Slack's 3 seconds runs after the answer (defer).
import type { CompanyPreview, ToolArgs, ToolOutcome } from "../../../lib/tools/types.ts";
import { slackContext } from "../../../lib/tools/identity.ts";
import { writeSummary } from "../../../lib/tools/summaries.ts";
import { slackEscape } from "../../../lib/tools/text.ts";
import type { ExecuteOptions } from "../../../lib/tools/types.ts";
import type { CallContext } from "../../../lib/tools/types.ts";
import type { SlackDeps, SlackReply } from "./commands.ts";
import { RESULT_HEADINGS, confirmModal, statusModal } from "./views.ts";

const SLACK_USER = /^[UW][A-Z0-9]{2,20}$/;
const BUTTON_TOOLS = new Set(["deactivate_company", "reactivate_company", "set_paper_amount"]);

interface StateValue {
  value?: string | null;
  selected_option?: { value?: string } | null;
  selected_date?: string | null;
}

interface Payload {
  type?: string;
  user?: { id?: string; team_id?: string };
  team?: { id?: string } | null;
  channel?: { id?: string } | null;
  response_url?: string;
  actions?: { action_id?: string; value?: string }[];
  view?: { id?: string; callback_id?: string; private_metadata?: string; state?: { values?: Record<string, Record<string, StateValue>> } };
}

const ok = (body: unknown | null = null): SlackReply => ({ status: 200, body });

function parseJson(text: string | undefined): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text ?? "");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function field(payload: Payload, block: string): string | null {
  const state = payload.view?.state?.values?.[block]?.value;
  const raw = state?.selected_option?.value ?? state?.selected_date ?? state?.value ?? null;
  return raw === null || raw === undefined || raw.trim() === "" ? null : raw.trim();
}

function numberOrText(raw: string | null): number | string | undefined {
  if (raw === null) return undefined;
  const parsed = Number(raw.replace(/[,_₹$]/g, ""));
  return Number.isFinite(parsed) ? parsed : raw;
}

function outcomeText(outcome: ToolOutcome): string {
  const heading = RESULT_HEADINGS[outcome.result] ?? outcome.result;
  const message = outcome.message ?? "";
  return message.startsWith(`${heading}:`) ? message : `${heading}: ${message}`.trim();
}

/** A confirmed company command: post a visible "request received" message in #market-brief first, so B6's onboarding
 * confirmation can reply in its thread (its channel and ts go into the inbox with the request); a request that is not
 * accepted edits that message to say why. A key already in the inbox (a second Confirm click) posts no message: the
 * answer goes to the clicker only. Without the message (Slack refused it) the request is still sent. */
async function confirmedWrite(deps: SlackDeps, ctx: CallContext, userId: string, tool: string, args: ToolArgs,
  opts: ExecuteOptions): Promise<ToolOutcome> {
  const summary = writeSummary(tool, args, opts.preview ?? null);
  const asked = `<@${userId}> asked: ${slackEscape(summary)}`;
  const ts = await deps.tools.isStored(args) ? null
    : await deps.slack.postMessage(deps.channelId, `:inbox_tray: ${asked}. Pending until the onboarding imports it.`)
      .catch(() => null);
  const outcome = await deps.tools.execute(ctx, tool, args, { ...opts, slackThread: ts ? { channel: deps.channelId, ts } : null });
  if (ts && outcome.result !== "pending") {
    await deps.slack.updateMessage(deps.channelId, ts, `${asked}. ${slackEscape(outcomeText(outcome))}`).catch(() => false);
  }
  return outcome;
}

function update(view: unknown): SlackReply {
  return ok({ response_action: "update", view });
}

function viewSubmission(payload: Payload, deps: SlackDeps, userId: string): SlackReply {
  const ctx = slackContext(userId);
  const viewId = payload.view?.id ?? "";
  const meta = parseJson(payload.view?.private_metadata) ?? {};
  const key = typeof meta.key === "string" ? meta.key : "";
  switch (payload.view?.callback_id) {
    case "mb_company_add": {
      const amount = numberOrText(field(payload, "amount"));
      const args: ToolArgs = { market: field(payload, "market"), symbol: field(payload, "symbol")?.toUpperCase() ?? null,
        ...(amount === undefined ? {} : { amount }), idempotency_key: key };
      deps.defer(async () => {
        const preview = await deps.tools.preview(ctx, "add_company", args);
        await deps.slack.viewsUpdate(viewId, preview.ok
          ? confirmModal(preview.summary ?? "", { tool: "add_company", args: preview.args, preview: preview.preview })
          : statusModal("Not added", preview.outcome?.message ?? "Refused"));
      });
      return update(statusModal("Checking", `Resolving ${String(args.symbol ?? "the symbol")}...`));
    }
    case "mb_company_confirm": {
      const args = meta.args as ToolArgs | undefined;
      if (meta.tool !== "add_company" || !args) return update(statusModal("Not done", "This form expired; start again."));
      deps.defer(async () => {
        const outcome = await confirmedWrite(deps, ctx, userId, "add_company", args,
          { confirmedSummary: true, preview: (meta.preview ?? null) as CompanyPreview | null });
        await deps.slack.viewsUpdate(viewId, statusModal(RESULT_HEADINGS[outcome.result] ?? "Result", outcome.message ?? ""));
      });
      return update(statusModal("Sending", "Sending the request to the onboarding..."));
    }
    case "mb_trade": {
      const price = numberOrText(field(payload, "price"));
      const note = field(payload, "note");
      const args: ToolArgs = {
        market: field(payload, "market"), ticker: field(payload, "ticker")?.toUpperCase() ?? null, side: field(payload, "side"),
        quantity: numberOrText(field(payload, "quantity")) ?? null, trade_date: field(payload, "trade_date"),
        price_basis: field(payload, "price_basis"), ...(price === undefined ? {} : { price }),
        ...(note === null ? {} : { note }), idempotency_key: key,
      };
      deps.defer(async () => {
        const outcome = await deps.tools.execute(ctx, "add_paper_trade", args);
        await deps.slack.viewsUpdate(viewId, statusModal(RESULT_HEADINGS[outcome.result] ?? "Result", outcome.message ?? ""));
      });
      return update(statusModal("Recording", "Recording the paper trade..."));
    }
    default:
      return ok();
  }
}

function blockAction(payload: Payload, deps: SlackDeps, userId: string): SlackReply {
  const action = payload.actions?.[0];
  const responseUrl = payload.response_url ?? "";
  if (action?.action_id === "mb_cancel") {
    deps.defer(async () => {
      await deps.slack.respond(responseUrl, { replace_original: true, text: "Cancelled; nothing was written." });
    });
    return ok();
  }
  if (action?.action_id !== "mb_confirm") return ok();
  const ctx = slackContext(userId);
  const value = parseJson(action.value);
  deps.defer(async () => {
    if (payload.channel?.id !== deps.channelId) {
      const outcome = await deps.tools.record(ctx, { tool: null, kind: null, market: null, args: {}, result: "refused",
        code: "not_allowed_in_channel", message: "market-brief commands work in #market-brief only" });
      await deps.slack.respond(responseUrl, { replace_original: true, text: outcomeText(outcome) });
      return;
    }
    const tool = typeof value?.tool === "string" && BUTTON_TOOLS.has(value.tool) ? value.tool : null;
    const outcome = tool
      ? await confirmedWrite(deps, ctx, userId, tool, (value?.args ?? {}) as ToolArgs, { confirmedSummary: true })
      : await deps.tools.record(ctx, { tool: null, kind: null, market: null, args: {}, result: "refused",
        code: "validation_failed", message: "Unknown confirmation" });
    await deps.slack.respond(responseUrl, { replace_original: true, text: outcomeText(outcome) });
  });
  return ok();
}

export async function handleInteraction(payload: Payload, deps: SlackDeps): Promise<SlackReply> {
  const userId = payload.user?.id ?? "";
  if (!SLACK_USER.test(userId)) return ok();
  if (payload.type === "view_submission") return viewSubmission(payload, deps, userId);
  if (payload.type === "block_actions") return blockAction(payload, deps, userId);
  return ok();
}
