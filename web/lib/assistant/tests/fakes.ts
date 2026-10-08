// Offline fakes of the assistant: an in-memory conversation log with the SQL's budget rule, and a mocked Claude
// client that replays scripted responses. Nothing here reaches the network.
import type Anthropic from "@anthropic-ai/sdk";
import { AssistantExplainer } from "../explainer.ts";
import { recordFrom } from "../store.ts";
import type { AnswerRecord, AnswerRow, ConversationStore, ModelClient, QuestionRow } from "../types.ts";
import { rig } from "../../tools/tests/fakes.ts";
import { dashboardContext } from "../../tools/identity.ts";
import type { CallContext, ToolArgs } from "../../tools/types.ts";

export class FakeConversationStore implements ConversationStore {
  questions: QuestionRow[] = [];
  answers: AnswerRow[] = [];
  /** Spend from before the test (e.g. earlier questions this day or month), added to the rows' spend. */
  prior = { day: 0, month: 0 };
  kill: boolean | null = null;
  down = false;
  purged: string[] = [];

  private spent(since: string, extra: number): number {
    return extra + this.questions.filter((q) => q.asked_at >= since)
      .reduce((sum, q) => sum + (this.answers.find((a) => a.id === q.id)?.cost_usd ?? q.reserved_usd), 0);
  }

  async reserve(row: QuestionRow, caps: { dayStart: string; monthStart: string; dayUsd: number; monthUsd: number }) {
    if (this.down) throw new Error("log down");
    if (this.spent(caps.dayStart, this.prior.day) + row.reserved_usd > caps.dayUsd + 1e-9) return false;
    if (this.spent(caps.monthStart, this.prior.month) + row.reserved_usd > caps.monthUsd + 1e-9) return false;
    this.questions.push(structuredClone(row));
    return true;
  }

  async answer(row: AnswerRow) {
    if (this.down) throw new Error("log down");
    this.answers.push(structuredClone(row));
  }

  async spend(dayStart: string, monthStart: string) {
    if (this.down) throw new Error("log down");
    return { day: this.spent(dayStart, this.prior.day), month: this.spent(monthStart, this.prior.month) };
  }

  async enabled() {
    if (this.down) throw new Error("log down");
    return this.kill;
  }

  async list(market: string, since: string, limit: number): Promise<AnswerRecord[]> {
    if (this.down) throw new Error("log down");
    return this.questions.filter((q) => q.market === market && q.asked_at >= since)
      .sort((a, b) => (a.asked_at < b.asked_at ? 1 : -1)).slice(0, limit)
      .map((q) => {
        const a = this.answers.find((item) => item.id === q.id);
        return recordFrom({ ...q, ...(a ?? {}), cost_usd: a?.cost_usd ?? q.reserved_usd, status: a?.status ?? null });
      });
  }

  async purge(before: string) {
    this.purged.push(before);
  }
}

type Script = Partial<Anthropic.Message> & { content: Anthropic.ContentBlock[] };

export class FakeModel implements ModelClient {
  calls: Anthropic.MessageCreateParamsNonStreaming[] = [];
  script: (Script | Error)[] = [];

  async create(params: Anthropic.MessageCreateParamsNonStreaming): Promise<Anthropic.Message> {
    this.calls.push(structuredClone(params));
    const next = this.script.shift();
    if (!next) throw new Error("no scripted response");
    if (next instanceof Error) throw next;
    return {
      id: `msg_${this.calls.length}`, type: "message", role: "assistant", model: "claude-sonnet-5-5", stop_sequence: null,
      stop_reason: "end_turn", usage: usage(1000, 200), ...next,
    } as Anthropic.Message;
  }
}

export function usage(input: number, output: number, cacheWrite = 0, cacheRead = 0): Anthropic.Usage {
  return { input_tokens: input, output_tokens: output, cache_creation_input_tokens: cacheWrite,
    cache_read_input_tokens: cacheRead } as Anthropic.Usage;
}

export function toolUse(name: string, input: Record<string, unknown>, id = `toolu_${name}`): Script {
  return { stop_reason: "tool_use", content: [{ type: "tool_use", id, name, input } as Anthropic.ToolUseBlock] };
}

export function finalAnswer(answer: { text: string; cited?: { id: string; kind: string }[]; not_in_data?: boolean; declined?: string }): Script {
  const body = { cited: [], not_in_data: false, declined: "none", ...answer };
  return { stop_reason: "end_turn", content: [{ type: "text", text: JSON.stringify(body), citations: null } as Anthropic.TextBlock] };
}

export const ASSISTANT = dashboardContext("assistant");

/** B5's tool layer (fakes) plus the assistant, its log and its model; reads go through the real executor. */
export function assistantRig(opts: { withModel?: boolean } = {}) {
  const tools = rig({ gatewayMode: false });
  const store = new FakeConversationStore();
  const model = new FakeModel();
  let counter = 0;
  const explainer = new AssistantExplainer({
    store, model: opts.withModel === false ? null : model, clock: () => tools.now.value,
    secrets: ["sk-ant-api03-SECRETSECRETSECRET", "md-inbox-SECRET-0987654321"],
    newId: () => `t${String(++counter).padStart(4, "0")}`,
  });
  const readAs = (ctx: CallContext) => (tool: string, args: ToolArgs) => tools.layer.execute(ctx, tool, args);
  const read = readAs(ASSISTANT);
  const ask = (args: ToolArgs, ctx: CallContext = ASSISTANT) => explainer.explain(ctx, args, readAs(ctx));
  return { ...tools, store, model, explainer, read, ask };
}
