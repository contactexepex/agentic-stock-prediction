import { test } from "node:test";
import assert from "node:assert/strict";
import { FakeConversationStore, assistantRig, finalAnswer, toolUse } from "./fakes.ts";
import { ToolLayer } from "../../tools/executor.ts";
import { type AssistantApiDeps, LIMITS, getConversation, postQuestion } from "../api.ts";
import { formatSlackAnswer } from "../slack.ts";
import { asksForAdvice, readsAsAdvice, verifyCitations } from "../guard.ts";
import { budgetState, callCeilingUsd } from "../budget.ts";
import { DAILY_USD, MONTHLY_USD, QUESTION_MAX, RETENTION_DAYS } from "../constants.ts";
import type { CallContext, ToolOutcome } from "../../tools/types.ts";

function outcome(fields: Partial<ToolOutcome>): ToolOutcome {
  return { command_id: "cmd-1", tool: "explain", result: "accepted", refusal_code: null, message: null, record_ids: [],
    inbox_id: null, budget_left: null, ...fields };
}

function apiRig(answer: ToolOutcome = outcome({ data: { answer: { id: "ask-1" }, budget: null } })) {
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
  assert.deepEqual([LIMITS.question_max, LIMITS.daily_usd, LIMITS.monthly_usd, LIMITS.retention_days], [500, 0.65, 20, 90]);
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

test("GET returns the market's conversation oldest first, within 90 days, with the budget state", async () => {
  const r = apiRig();
  const q = (id: string, market: string, at: string, reserved = 0.1) => ({ id, market, channel: "slack", actor: "slack:U1",
    agent: "assistant", question: id, ticker: null, strategy_id: null, asked_at: at, reserved_usd: reserved });
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
  assert.equal(body.budget.day.spent_usd, 0.22, "both markets share the budget; an unanswered question counts its reservation");
  assert.equal(body.budget.month.spent_usd, 0.22);
  assert.equal((await getConversation(new Request("https://omenix.vercel.app/api/assistant?market=eu"), r.deps)).status, 404);
  r.store.down = true;
  assert.equal((await getConversation(new Request("https://omenix.vercel.app/api/assistant?market=us"), r.deps)).status, 503);
});

test("the budget state says over budget when less than one question's reservation is left", () => {
  const at = new Date("2026-10-31T12:00:00Z");
  assert.equal(budgetState({ day: 0.5, month: 3 }, at, null).over_budget, false);
  assert.equal(budgetState({ day: 0.56, month: 3 }, at, null).over_budget, true);
  assert.equal(budgetState({ day: 0, month: 19.95 }, at, true).over_budget, true);
  const state = budgetState({ day: 0.1, month: 1 }, at, true);
  assert.equal(state.month.starts_at, "2026-10-01T00:00:00Z");
  assert.equal(state.day.starts_at, "2026-10-31T00:00:00Z");
  assert.deepEqual([DAILY_USD, MONTHLY_USD, QUESTION_MAX, RETENTION_DAYS], [0.65, 20, 500, 90]);
});

test("a call's cost ceiling grows with its input and covers the full output", () => {
  const small = callCeilingUsd({ model: "m", max_tokens: 1500, messages: [{ role: "user", content: "hi" }] });
  const big = callCeilingUsd({ model: "m", max_tokens: 1500, messages: [{ role: "user", content: "x".repeat(20000) }] });
  assert.ok(small >= 1500 * 10 / 1e6);
  assert.ok(big - small >= 9990 * 2.5 / 1e6);
});

test("the Slack answer escapes stored and model text, lists the records and the budget, and says paper", () => {
  const answer = { id: "ask-1", market: "us", channel: "slack", asked_at: "2026-10-07T10:00:00Z", question: "q",
    text: "Gain <!channel> & <https://x.example|click>", cited_ids: ["id<1>"], cited: [{ id: "id<1>", kind: "news", as_of: "2026-10-07T01:00:00Z", source: "rm.news _" }],
    as_of: "2026-10-07T10:00:00Z", not_in_data: false, declined: null, status: "answered", sources: [], cost_usd: 0.01 };
  const budget = budgetState({ day: 0.01, month: 0.01 }, new Date("2026-10-07T10:00:00Z"), null);
  const msg = formatSlackAnswer(outcome({ data: { answer, budget } }));
  assert.equal(msg.response_type, "ephemeral");
  assert.doesNotMatch(msg.text, /<!channel>|<https/);
  assert.match(msg.text, /Gain &lt;!channel&gt; &amp; &lt;https:\/\/x\.example\|click&gt;/);
  assert.match(msg.text, /^\*Answered from the data\*/);
  assert.match(msg.text, /news item `id&lt;1&gt;` \(data as of 2026-10-07T01:00:00Z\)/);
  assert.match(msg.text, /\$0\.01 of \$0\.65 used today/);
  assert.match(msg.text, /Paper only, research, never advice\./);
  const refused = formatSlackAnswer(outcome({ result: "refused", refusal_code: "budget_exceeded", message: "Over <budget>" }));
  assert.match(refused.text, /^Not answered: Over &lt;budget&gt;/);
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
  assert.equal(body.budget.day.budget_usd, 0.65);
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
