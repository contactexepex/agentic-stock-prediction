import { test } from "node:test";
import assert from "node:assert/strict";
import { FakeConversationStore, assistantRig, finalAnswer, toolUse } from "./fakes.ts";
import { ToolLayer } from "../../tools/executor.ts";
import { type AssistantApiDeps, LIMITS, getConversation, postQuestion } from "../api.ts";
import { formatSlackAnswer } from "../slack.ts";
import { asksForAdvice, readsAsAdvice, verifyCitations } from "../guard.ts";
import { spendLine, spendState } from "../cost.ts";
import { HISTORY_TURNS, QUESTION_MAX, RETENTION_DAYS } from "../constants.ts";
import type { CallContext, ToolOutcome } from "../../tools/types.ts";

function outcome(fields: Partial<ToolOutcome>): ToolOutcome {
  return { command_id: "cmd-1", tool: "explain", result: "accepted", refusal_code: null, message: null, record_ids: [],
    inbox_id: null, budget_left: null, ...fields };
}

function apiRig(answer: ToolOutcome = outcome({ data: { answer: { id: "ask-1" }, spend: null } })) {
  const calls: { ctx: CallContext; tool: string; args: unknown }[] = [];
  const tools = { execute: async (ctx: CallContext, tool: string, args: unknown) => { calls.push({ ctx, tool, args }); return answer; } };
  const store = new FakeConversationStore();
  const deps: AssistantApiDeps = { tools: tools as unknown as ToolLayer, store, clock: () => new Date("2026-10-07T10:00:00Z"),
    gatewayMode: false, origins: ["https://omenix.vercel.app"] };
  return { deps, calls, store };
}

const post = (body: string, headers: Record<string, string> = { "content-type": "application/json" }) =>
  new Request("https://omenix.vercel.app/api/assistant", { method: "POST", body, headers });

test("POST runs the explain tool as the dashboard's assistant agent; identity never comes from the body", async () => {
  const r = apiRig();
  const res = await postQuestion(post(JSON.stringify({ market: "us", question: "Why?", actor: "slack:U1" })), r.deps);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("cache-control"), "no-store");
  assert.equal(r.calls[0].tool, "explain");
  assert.deepEqual(r.calls[0].ctx, { channel: "dashboard", actor: "dashboard:owner", agent: "assistant" });
  const body = await res.json();
  assert.equal(body.answer.id, "ask-1");
  assert.deepEqual(body.limits, LIMITS);
  assert.deepEqual(LIMITS, { question_max: 500, history_turns: 4, retention_days: 90 });
});

test("POST maps refusals to HTTP statuses and refuses other origins, other types, big bodies and the gateway", async () => {
  for (const [code, status] of [["budget_exceeded", 429], ["kill_switch", 503], ["validation_failed", 422], ["not_allowed_in_channel", 403]] as const) {
    const r = apiRig(outcome({ result: "refused", refusal_code: code, message: "no" }));
    assert.equal((await postQuestion(post('{"market":"us","question":"q"}'), r.deps)).status, status, code);
  }
  assert.equal((await postQuestion(post("{}"), apiRig(outcome({ result: "failed" })).deps)).status, 503);
  const r = apiRig();
  assert.equal((await postQuestion(post("{}", { "content-type": "text/plain" }), r.deps)).status, 415);
  assert.equal((await postQuestion(post("{}", { "content-type": "application/json", origin: "https://evil.example" }), r.deps)).status, 403);
  assert.equal((await postQuestion(post("{}", { "content-type": "application/json", origin: "https://omenix.vercel.app" }), r.deps)).status, 200);
  assert.equal((await postQuestion(post("x".repeat(5000)), r.deps)).status, 413);
  assert.equal((await postQuestion(post("not json"), r.deps)).status, 400);
  assert.equal((await postQuestion(post("[1]"), r.deps)).status, 400);
  assert.equal((await postQuestion(post("{}"), { ...r.deps, gatewayMode: true })).status, 404);
  assert.equal(r.calls.length, 1, "only the same-origin request reached the tool layer");
});

test("GET returns the market's conversation oldest first, within 90 days, with the spend", async () => {
  const r = apiRig();
  const q = (id: string, market: string, at: string) => ({ id, market, channel: "slack", actor: "slack:U1",
    agent: "assistant", question: id, ticker: null, strategy_id: null, asked_at: at, conversation_id: id });
  r.store.questions.push(q("old", "us", "2026-06-01T00:00:00Z"), q("a", "us", "2026-10-07T09:00:00Z"),
    q("b", "us", "2026-10-07T09:30:00Z"), q("in", "india", "2026-10-07T09:00:00Z"));
  r.store.answers.push({ id: "a", status: "answered", text: "A.", cited: [], sources: [], not_in_data: false, declined: null,
    model: "m", input_tokens: 1, cache_write_tokens: 0, cache_read_tokens: 0, output_tokens: 1, model_calls: 1, tool_calls: 0,
    cost_usd: 0.02, completed_at: "2026-10-07T09:00:05Z" });
  const res = await getConversation(new Request("https://omenix.vercel.app/api/assistant?market=us"), r.deps);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.deepEqual(body.answers.map((a: { id: string }) => a.id), ["a", "b"]);
  assert.equal(body.answers[1].status, "pending", "a question without an answer yet");
  assert.equal(body.spend.day.spent_usd, 0.02, "the logged answers' real costs, both markets together");
  assert.equal(body.spend.month.spent_usd, 0.02);
  assert.equal(body.answers[1].cost_usd, 0, "a pending question has no logged cost");
  assert.equal((await getConversation(new Request("https://omenix.vercel.app/api/assistant?market=eu"), r.deps)).status, 404);
  r.store.down = true;
  assert.equal((await getConversation(new Request("https://omenix.vercel.app/api/assistant?market=us"), r.deps)).status, 503);
});

test("the spend state and line show the day and the month in UTC, with no cap", () => {
  const state = spendState({ day: 0.1234567, month: 1.5 }, new Date("2026-10-31T12:00:00Z"), true);
  assert.deepEqual(state, { day: { spent_usd: 0.123457, starts_at: "2026-10-31T00:00:00Z" },
    month: { spent_usd: 1.5, starts_at: "2026-10-01T00:00:00Z" }, enabled: true });
  assert.equal(spendLine(state), "Assistant spend: $0.12 today and $1.50 this month (UTC).");
  assert.deepEqual([QUESTION_MAX, RETENTION_DAYS, HISTORY_TURNS], [500, 90, 4]);
});

test("the Slack answer escapes stored and model text, lists the records and the spend, and says paper", () => {
  const answer = { id: "ask-1", market: "us", channel: "slack", asked_at: "2026-10-07T10:00:00Z", question: "q",
    text: "Gain <!channel> & <https://x.example|click>", cited_ids: ["id<1>"], cited: [{ id: "id<1>", kind: "news", as_of: "2026-10-07T01:00:00Z", source: "rm.news _" }],
    as_of: "2026-10-07T10:00:00Z", not_in_data: false, declined: null, status: "answered", sources: [], cost_usd: 0.01 };
  const spend = spendState({ day: 0.01, month: 0.01 }, new Date("2026-10-07T10:00:00Z"), null);
  const msg = formatSlackAnswer(outcome({ data: { answer, spend } }));
  assert.equal(msg.response_type, "ephemeral");
  assert.doesNotMatch(msg.text, /<!channel>|<https/);
  assert.match(msg.text, /Gain &lt;!channel&gt; &amp; &lt;https:\/\/x\.example\|click&gt;/);
  assert.match(msg.text, /^\*Answered from the data\*/);
  assert.match(msg.text, /news item `id&lt;1&gt;` \(data as of 2026-10-07T01:00:00Z\)/);
  assert.match(msg.text, /Assistant spend: \$0\.01 today and \$0\.01 this month \(UTC\)/);
  assert.match(msg.text, /Paper only, research, never advice\./);
  const refused = formatSlackAnswer(outcome({ result: "refused", refusal_code: "kill_switch", message: "Off <now>" }));
  assert.match(refused.text, /^Not answered: Off &lt;now&gt;/);
});

test("advice is recognised in questions and answers, plain research questions are not", () => {
  for (const q of ["Should I buy NVDA tomorrow with real money?", "Is it a good time to sell RELIANCE?", "Which stock should I buy?"]) {
    assert.equal(asksForAdvice(q), true, q);
  }
  for (const q of ["Why did the N+3 paper trade in NVDA end as it did?", "Rule or AI: who did better on 2026-10-06?",
    "What did Reliance close at on 8 Oct?", "How did the buy signals do last week?"]) {
    assert.equal(asksForAdvice(q), false, q);
  }
  assert.equal(readsAsAdvice("I recommend selling."), true);
  assert.equal(readsAsAdvice("You might want to buy before the results."), true);
  assert.equal(readsAsAdvice("The strategy bought at the open and sold at the close: +1.2 % after costs."), false);
});

test("citations match whole JSON string values only", () => {
  const source = { read_model: "rm.trades", page_key: "_", found: true, as_of: "2026-10-07T01:00:00Z" };
  const reads = [{ text: JSON.stringify({ a: "abc-123", b: "xabc-1234" }), sources: [{ source, text: JSON.stringify({ a: "abc-123" }) }] }];
  const { kept, dropped } = verifyCitations([{ id: "abc-12", kind: "news" }, { id: "abc-123", kind: "bogus" }, { id: "abc-123", kind: "news" }], reads);
  assert.deepEqual(dropped, ["abc-12"]);
  assert.deepEqual(kept, [{ id: "abc-123", kind: "record", as_of: "2026-10-07T01:00:00Z", source: "rm.trades _" }]);
});

test("end to end through B5's real executor: the dashboard's assistant asks, reads and gets a cited answer", async () => {
  const r = assistantRig();
  r.reads.put("trades", "us", "_", { open: [{ trade_id: "trade-0001" }] });
  r.model.script = [toolUse("get_trades", {}), finalAnswer({ text: "One open paper trade.", cited: [{ id: "trade-0001", kind: "paper_trades_settled" }] })];
  const tools = new ToolLayer({ ...r.layer.deps, explainer: r.explainer });
  const deps: AssistantApiDeps = { tools, store: r.store, clock: () => r.now.value, gatewayMode: false, origins: [] };
  const res = await postQuestion(post(JSON.stringify({ market: "us", question: "How many open trades?" })), deps);
  const body = await res.json();
  assert.equal(res.status, 200, JSON.stringify(body));
  assert.equal(body.answer.status, "answered");
  assert.deepEqual(body.answer.cited_ids, ["trade-0001"]);
  assert.equal(body.spend.day.starts_at, "2026-10-07T00:00:00Z");
  const logged = r.inbox.commands.map((row) => [row.tool, row.agent, row.kind, row.result]);
  assert.deepEqual(logged, [["get_trades", "assistant", "read", "accepted"], ["explain", "assistant", "read_ai", "accepted"]]);

  r.inbox.controls.push({ agent: "assistant", enabled: false });
  const off = await postQuestion(post(JSON.stringify({ market: "us", question: "Again?" })), deps);
  assert.equal(off.status, 503);
  assert.equal((await off.json()).refusal_code, "kill_switch");
  r.inbox.controls.push({ agent: "assistant", enabled: true });
  const long = await postQuestion(post(JSON.stringify({ market: "us", question: "x".repeat(501) })), deps);
  assert.equal(long.status, 422, "the 500-character limit is the tools.yaml max_length, checked by the gate");
});

test("end to end: the panel continues a conversation through the gate with conversation_id; a bad id is refused", async () => {
  const r = assistantRig();
  const tools = new ToolLayer({ ...r.layer.deps, explainer: r.explainer });
  const deps: AssistantApiDeps = { tools, store: r.store, clock: () => r.now.value, gatewayMode: false, origins: [] };
  r.model.script = [finalAnswer({ text: "First answer.", not_in_data: true })];
  const first = await (await postQuestion(post(JSON.stringify({ market: "us", question: "First?" })), deps)).json();
  r.model.script = [finalAnswer({ text: "Second answer.", not_in_data: true })];
  const res = await postQuestion(post(JSON.stringify({ market: "us", question: "And then?", conversation_id: first.answer.id })), deps);
  const second = await res.json();
  assert.equal(res.status, 200, JSON.stringify(second));
  assert.equal(second.answer.conversation_id, first.answer.id);
  assert.equal(second.answer.history_turns, 1);
  assert.equal(r.model.calls[1].messages[1].content, "First answer.");
  const bad = await postQuestion(post(JSON.stringify({ market: "us", question: "x", conversation_id: "../etc" })), deps);
  assert.equal(bad.status, 422, "the tools.yaml pattern is checked by the gate");
});
