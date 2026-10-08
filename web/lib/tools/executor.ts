// The policy enforcement point of every channel (ARCHITECTURE.md section 10; docs/SPEC.md F10). Order of checks:
// identity -> tool exists -> channel permission -> kill switch (agent file, then the inbox controls table) ->
// arguments -> read budget (reads; writes: the summary step only) -> confirmation -> idempotency, write budget and
// inbox append in one statement (a key already stored answers duplicate even over budget) -> workflow dispatch. Every call is logged
// in the inbox command log; refusals and failures are reported to the owner in Slack; nothing is retried here.
import type {
  AgentDefinition,
  AgentUsage,
  CallContext,
  CompanyPreview,
  CommandLogRow,
  CommandResult,
  ExecuteOptions,
  PreviewOutcome,
  RefusalCode,
  ToolArgs,
  ToolDefinition,
  ToolDeps,
  ToolKind,
  ToolOutcome,
} from "./types.ts";
import { agentTools, allowedInChannel, getAgent, getTool, writeKind } from "./registry.ts";
import { actorMatchesChannel } from "./identity.ts";
import { validateArguments } from "./validate.ts";
import { commandId, utcDayStart } from "./ids.ts";
import { sha256Hex, stableJson } from "./crypto.ts";
import { loggableArguments, redact } from "./text.ts";
import { runRead } from "./reads.ts";
import { writeSummary } from "./summaries.ts";

const MARKETS = new Set(["india", "us"]);
export const COMING_SOON = "The assistant is coming soon (session B8); nothing was looked up.";

interface Passed {
  ok: true;
  tool: ToolDefinition;
  agent: AgentDefinition;
  args: ToolArgs;
  usage: AgentUsage;
}
interface Stopped {
  ok: false;
  result: CommandResult;
  code: RefusalCode | null;
  message: string;
  tool: ToolDefinition | null;
  agent: AgentDefinition | null;
  usage: AgentUsage | null;
}

interface LogFields {
  tool: string | null;
  kind: ToolKind | null;
  market: string | null;
  args: unknown;
  key: string | null;
  result: CommandResult;
  code: RefusalCode | null;
  message: string | null;
  data?: unknown;
  inboxId?: string | null;
  recordIds?: string[];
  budgetLeft: number | null;
}

function marketOf(raw: unknown): string | null {
  const market = raw && typeof raw === "object" ? (raw as ToolArgs).market : null;
  return typeof market === "string" && MARKETS.has(market) ? market : null;
}

function keyOf(raw: unknown): string | null {
  const key = raw && typeof raw === "object" ? (raw as ToolArgs).idempotency_key : null;
  return typeof key === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(key) ? key : null;
}

/** The Slack thread a confirmation replies in: only for the slack channel, and only well-formed ids. */
function slackThread(ctx: CallContext, opts: ExecuteOptions): { slack_channel: string | null; slack_ts: string | null } {
  const thread = opts.slackThread;
  if (ctx.channel !== "slack" || !thread || !/^[CG][A-Z0-9]{2,20}$/.test(thread.channel) || !/^\d{1,12}\.\d{1,8}$/.test(thread.ts)) {
    return { slack_channel: null, slack_ts: null };
  }
  return { slack_channel: thread.channel, slack_ts: thread.ts };
}

function safeToolName(name: unknown): string | null {
  return typeof name === "string" && /^[a-z_]{1,40}$/.test(name) ? name : null;
}

export class ToolLayer {
  readonly deps: ToolDeps;

  constructor(deps: ToolDeps) {
    this.deps = deps;
  }

  /** The tools this caller may see and call (MCP tools/list, Slack help). */
  listTools(ctx: CallContext): ToolDefinition[] {
    const agent = getAgent(ctx.agent);
    if (!agent || !actorMatchesChannel(ctx) || this.dashboardInGateway(ctx)) return [];
    return agentTools(agent, ctx.channel);
  }

  private dashboardInGateway(ctx: CallContext): boolean {
    return this.deps.settings.gatewayMode && ctx.channel === "dashboard";
  }

  private budgetLeft(agent: AgentDefinition | null, usage: AgentUsage | null, kind: ToolKind | null, extra = 0) {
    if (!agent || !usage || kind !== "write") return null;
    return Math.max(0, agent.daily_write_budget - usage.writes - extra);
  }

  private async gate(ctx: CallContext, toolName: string, raw: unknown, now: Date, writeBudget = false): Promise<Passed | Stopped> {
    const agent = getAgent(ctx.agent);
    const tool = getTool(toolName);
    const stop = (code: RefusalCode | null, message: string, usage: AgentUsage | null = null, result: CommandResult = "refused"): Stopped => ({
      ok: false, result, code, message, tool, agent, usage,
    });
    if (!agent || !actorMatchesChannel(ctx) || !agent.channels.includes(ctx.channel) || this.dashboardInGateway(ctx)) {
      return stop("unknown_actor", "The caller's identity is not accepted in this channel");
    }
    if (!tool) return stop("validation_failed", "Unknown tool");
    if (!allowedInChannel(tool, ctx.channel) || !agent.tools.includes(tool.name)) {
      return stop("not_allowed_in_channel", `${tool.name} is not available in ${ctx.channel}`);
    }
    if (!agent.enabled) return stop("kill_switch", `The ${agent.agent} agent is switched off`);
    let usage: AgentUsage;
    try {
      usage = await this.deps.inbox.usage(agent.agent, utcDayStart(now));
    } catch {
      return stop(null, "The command log is unavailable, so nothing was done", null, "failed");
    }
    if (usage.enabled === false) return stop("kill_switch", `The ${agent.agent} agent is switched off`, usage);
    const validation = validateArguments(tool, raw, now.toISOString().slice(0, 10));
    if (!validation.ok) return stop("validation_failed", validation.message, usage);
    const overBudget = tool.kind === "write"
      ? writeBudget && usage.writes >= agent.daily_write_budget   // execute checks it atomically with the inbox append
      : usage.reads >= agent.daily_read_budget;
    if (overBudget) {
      return stop("budget_exceeded", `The ${agent.agent} agent has used today's ${tool.kind === "write" ? "write" : "read"} budget`, usage);
    }
    return { ok: true, tool, agent, args: validation.args, usage };
  }

  /** Runs one tool call for a caller whose identity the channel adapter verified. */
  async execute(ctx: CallContext, toolName: string, raw: unknown, opts: ExecuteOptions = {}): Promise<ToolOutcome> {
    const now = this.deps.clock();
    const gate = await this.gate(ctx, toolName, raw, now);
    if (!gate.ok) return this.stopped(ctx, now, toolName, raw, gate);
    const { tool, args } = gate;
    if (tool.kind === "write") return this.write(ctx, now, gate, opts);
    if (tool.kind === "read_ai") {
      const data = { text: COMING_SOON, cited_ids: [], as_of: null, not_in_data: true };
      return this.finish(ctx, now, { tool: tool.name, kind: tool.kind, market: marketOf(args), args, key: null,
        result: "accepted", code: null, message: "coming soon", data, budgetLeft: null });
    }
    try {
      const data = await runRead(this.deps.readStore, tool.name, args);
      const found = data.sources.some((source) => source.found);
      return this.finish(ctx, now, { tool: tool.name, kind: tool.kind, market: marketOf(args), args, key: null,
        result: "accepted", code: null, message: found ? null : "not in the data", data, budgetLeft: null });
    } catch {
      return this.finish(ctx, now, { tool: tool.name, kind: tool.kind, market: marketOf(args), args, key: null,
        result: "failed", code: null, message: "The data service is unavailable", budgetLeft: null });
    }
  }

  /** The summary a caller confirms before a `confirm: summary` write. Nothing is written; a refusal is logged and
   * reported like any other (e.g. an ETF asked to be added). */
  async preview(ctx: CallContext, toolName: string, raw: unknown): Promise<PreviewOutcome> {
    const now = this.deps.clock();
    const gate = await this.gate(ctx, toolName, raw, now, true);
    if (!gate.ok) return { ok: false, outcome: await this.stopped(ctx, now, toolName, raw, gate) };
    const { tool, args } = gate;
    if (tool.kind !== "write") {
      const outcome = await this.stopped(ctx, now, toolName, raw, { ...gate, ok: false, result: "refused",
        code: "validation_failed", message: `${tool.name} is not a write` });
      return { ok: false, outcome };
    }
    const secrets = this.deps.settings.secrets;
    if (tool.name !== "add_company") return { ok: true, summary: redact(writeSummary(tool.name, args, null), secrets), preview: null, args };
    let resolved;
    try {
      resolved = await this.deps.resolver.resolve(args.market as "india" | "us", String(args.symbol),
        typeof args.amount === "number" ? args.amount : null);
    } catch {
      resolved = { ok: false as const, code: "ambiguous" as const, message: "The identifiers could not be resolved now" };
    }
    if (!resolved.ok) {
      const outcome = await this.stopped(ctx, now, toolName, raw, { ...gate, ok: false, result: "refused",
        code: resolved.code, message: resolved.message });
      return { ok: false, outcome };
    }
    const preview = Object.fromEntries(Object.entries(resolved.preview).map(([key, item]) =>
      [key, typeof item === "string" ? redact(item, secrets) : item])) as unknown as CompanyPreview;
    return { ok: true, summary: writeSummary(tool.name, args, preview), preview, args };
  }

  /** Whether a write with this idempotency key is already in the inbox, so the Slack confirm step posts its request
   * message only for a new key. Nothing is logged; an unavailable inbox answers false and the write itself decides. */
  async isStored(raw: unknown): Promise<boolean> {
    const key = keyOf(raw);
    if (key === null) return false;
    return this.deps.inbox.findRequest(key).then((stored) => stored !== null, () => false);
  }

  /** Logs a command that maps to no tool call (a malformed Slack command, the /ask stub) and reports refusals. */
  async record(ctx: CallContext, fields: { tool: string | null; kind: ToolKind | null; market: string | null;
    args: unknown; result: CommandResult; code: RefusalCode | null; message: string }): Promise<ToolOutcome> {
    return this.finish(ctx, this.deps.clock(), { ...fields, tool: safeToolName(fields.tool), key: null, budgetLeft: null });
  }

  private stopped(ctx: CallContext, now: Date, toolName: string, raw: unknown, gate: Stopped): Promise<ToolOutcome> {
    const kind = gate.tool?.kind ?? null;
    return this.finish(ctx, now, {
      tool: gate.tool?.name ?? safeToolName(toolName), kind, market: marketOf(raw), args: raw, key: keyOf(raw),
      result: gate.result, code: gate.code, message: gate.message, budgetLeft: this.budgetLeft(gate.agent, gate.usage, kind),
    });
  }

  private async write(ctx: CallContext, now: Date, gate: Passed, opts: ExecuteOptions): Promise<ToolOutcome> {
    const { tool, agent, args, usage } = gate;
    const key = String(args.idempotency_key);
    const base = { tool: tool.name, kind: tool.kind, market: marketOf(args), args, key };
    const refuse = (code: RefusalCode, message: string) => this.finish(ctx, now, { ...base, result: "refused", code,
      message, budgetLeft: this.budgetLeft(agent, usage, tool.kind) });
    if (tool.confirm === "summary" && opts.confirmedSummary !== true) {
      return refuse("validation_failed", "Confirm the summary first; nothing was written");
    }
    const preview = opts.preview ?? null;
    const amount = typeof args.amount === "number" ? args.amount : null;
    if (tool.name === "add_company" && (!preview || preview.market !== args.market || preview.symbol !== args.symbol ||
      preview.amount_is_default !== (amount === null) || (amount !== null && preview.amount !== amount))) {
      return refuse("validation_failed", "An add needs the resolved identifiers the caller confirmed");
    }
    const id = await commandId(now, key, args);
    const secrets = this.deps.settings.secrets;   // caller text (note, reason) is stored with secret values scrubbed
    const stored = Object.fromEntries(Object.entries(args).map(([name, item]) =>
      [name, typeof item === "string" ? redact(item, secrets) : item])) as ToolArgs;
    const { idempotency_key: _key, ...hashed } = args;   // the hash of what was sent, so a reuse with other text is caught
    const argsSha = await sha256Hex(stableJson(hashed));
    let claim;
    try {
      claim = await this.deps.inbox.claimRequest({
        inbox_id: key, kind: writeKind(tool) ?? "unknown", tool: tool.name, market: String(args.market), arguments: stored,
        preview, channel: ctx.channel, submitted_by: ctx.actor, agent: agent.agent, command_id: id,
        submitted_at: now.toISOString(), args_sha256: argsSha, ...slackThread(ctx, opts),
      }, { sinceIso: utcDayStart(now), limit: agent.daily_write_budget });
    } catch {
      return this.finish(ctx, now, { ...base, result: "failed", code: null,
        message: "The inbox is unavailable, so nothing was written", budgetLeft: this.budgetLeft(agent, usage, tool.kind) });
    }
    if (!claim.claimed && claim.existing === null) {
      return this.finish(ctx, now, { ...base, result: "refused", code: "budget_exceeded",
        message: `The ${agent.agent} agent has used today's write budget`, budgetLeft: 0 });
    }
    if (!claim.claimed) return this.duplicate(ctx, now, gate, base, claim.existing, argsSha);
    const summary = writeSummary(tool.name, args, preview);
    // Both kinds have an importer, and onboard.yml and routine step 3 run both (954d34d): company commands
    // `company.py import-inbox` (B1), paper trades `portfolio.py import-inbox` (B2, marketbrief/portfolio/inbox_import.py).
    let dispatched: { ok: boolean; reason: string | null };
    try {
      dispatched = await this.deps.dispatcher.dispatch();
    } catch {
      dispatched = { ok: false, reason: "dispatch error" };
    }
    const message = `Pending: ${summary}. It shows as pending until the import writes it to the record` +
      (dispatched.ok ? "." : "; the onboarding workflow could not be started now, so it waits in the inbox for the next import run.");
    const outcome = await this.finish(ctx, now, { ...base, result: "pending", code: null, message, inboxId: key,
      budgetLeft: this.budgetLeft(agent, usage, tool.kind, 1) }, id);
    if (!dispatched.ok) {
      await this.report({ ...outcome, message: `Workflow dispatch failed (${dispatched.reason ?? "unknown"}); the request waits in the inbox for the next run` }, ctx);
    }
    return outcome;
  }

  private async duplicate(ctx: CallContext, now: Date, gate: Passed, base: Omit<LogFields, "result" | "code" | "message" | "budgetLeft">,
    existing: { submitted_by: string; tool: string; args_sha256: string; command_id: string } | null, argsSha: string) {
    const { tool, agent, usage } = gate;
    const left = this.budgetLeft(agent, usage, tool.kind);
    if (!existing || existing.submitted_by !== ctx.actor || existing.tool !== tool.name || existing.args_sha256 !== argsSha) {
      return this.finish(ctx, now, { ...base, result: "refused", code: "duplicate_key",
        message: "This idempotency key was already used for another request; nothing was written", budgetLeft: left });
    }
    let first = null;
    try {
      first = await this.deps.inbox.findCommand(existing.command_id);
    } catch {
      first = null;
    }
    return this.finish(ctx, now, { ...base, result: "duplicate", code: null, inboxId: base.key,
      message: first?.message ?? "Already received; it shows as pending until the import writes it to the record",
      recordIds: first?.record_ids ?? [], budgetLeft: left });
  }

  private async finish(ctx: CallContext, now: Date, fields: LogFields, id?: string): Promise<ToolOutcome> {
    const secrets = this.deps.settings.secrets;
    const commandIdValue = id ?? (await commandId(now, fields.key, fields.args));
    const message = fields.message === null ? null : redact(fields.message, secrets).slice(0, 1000);
    const outcome: ToolOutcome = {
      command_id: commandIdValue, tool: fields.tool, result: fields.result, refusal_code: fields.code, message,
      record_ids: fields.recordIds ?? [], inbox_id: fields.inboxId ?? null, budget_left: fields.budgetLeft,
    };
    if (fields.data !== undefined) outcome.data = fields.data;
    const row: CommandLogRow = {
      id: commandIdValue, market: fields.market, received_at: now.toISOString(), channel: ctx.channel, actor: ctx.actor,
      agent: ctx.agent.slice(0, 40), tool: fields.tool, kind: fields.kind, arguments: loggableArguments(fields.args, secrets),
      idempotency_key: fields.key, result: fields.result, refusal_code: fields.code, message, record_ids: outcome.record_ids,
      budget_left: fields.budgetLeft, completed_at: this.deps.clock().toISOString(),
    };
    let logged = true;
    try {
      await this.deps.inbox.appendCommand(row);
    } catch {
      logged = false;
    }
    if (fields.result === "refused" || fields.result === "failed") await this.report(outcome, ctx);
    if (!logged) await this.report({ ...outcome, message: `The command log write failed for ${commandIdValue}` }, ctx);
    return outcome;
  }

  private async report(outcome: ToolOutcome, ctx: CallContext): Promise<void> {
    try {
      await this.deps.notifier.notify({
        command_id: outcome.command_id, tool: outcome.tool, channel: ctx.channel, actor: ctx.actor,
        result: outcome.result, refusal_code: outcome.refusal_code,
        message: outcome.message === null ? null : redact(outcome.message, this.deps.settings.secrets),
      });
    } catch {
      // reporting is best effort; the command log row is the record
    }
  }
}
