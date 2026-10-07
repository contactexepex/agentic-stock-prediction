import { test } from "node:test";
import assert from "node:assert/strict";
import { CHANNEL, MSFT, SECRETS, TEAM, USER, commandParams, slackRig } from "./fakes.ts";
import { hmacHex } from "../crypto.ts";
import { SLACK_CHANNEL_ID } from "../constants.ts";
import { MAX_AGE_SECONDS, verifiedBody, verifySlackRequest } from "../../../app/slack/_lib/verify.ts";
import { handleCommand } from "../../../app/slack/_lib/commands.ts";
import { handleInteraction } from "../../../app/slack/_lib/interactions.ts";

const secret = SECRETS.SLACK_SIGNING_SECRET;
async function sign(body: string, timestamp: number) {
  return `v0=${await hmacHex(secret, `v0:${timestamp}:${body}`)}`;
}

test("Slack signatures are verified, and requests older than 5 minutes are refused", async () => {
  const body = "command=%2Fcompany&text=help";
  const now = 1_790_000_000;
  assert.deepEqual(await verifySlackRequest(secret, String(now), await sign(body, now), body, now), { ok: true });
  assert.deepEqual(await verifySlackRequest(secret, String(now - MAX_AGE_SECONDS), await sign(body, now - MAX_AGE_SECONDS), body, now), { ok: true });
  const stale = now - MAX_AGE_SECONDS - 1;
  assert.deepEqual(await verifySlackRequest(secret, String(stale), await sign(body, stale), body, now), { ok: false, reason: "stale" });
  assert.deepEqual(await verifySlackRequest(secret, String(now + 400), await sign(body, now + 400), body, now), { ok: false, reason: "stale" });
  assert.deepEqual(await verifySlackRequest(secret, String(now), await sign(body + "x", now), body, now), { ok: false, reason: "bad_signature" });
  assert.deepEqual(await verifySlackRequest("other-secret", String(now), await sign(body, now), body, now), { ok: false, reason: "bad_signature" });
  assert.deepEqual(await verifySlackRequest(secret, null, await sign(body, now), body, now), { ok: false, reason: "missing_headers" });
  assert.deepEqual(await verifySlackRequest(secret, String(now), "v0=zz", body, now), { ok: false, reason: "bad_signature" });
  assert.deepEqual(await verifySlackRequest(null, String(now), await sign(body, now), body, now), { ok: false, reason: "no_secret" });
  const request = new Request("https://gw.example/slack/commands", { method: "POST", body,
    headers: { "x-slack-request-timestamp": String(now), "x-slack-signature": await sign(body, now) } });
  assert.equal(await verifiedBody(request, secret, now), body);
});

test("commands outside #market-brief (C0C6REB7QS2, config/settings.yaml) are refused and logged", async () => {
  const s = slackRig();
  assert.equal(CHANNEL, SLACK_CHANNEL_ID);
  for (const command of ["/company", "/trade", "/ask"]) {
    const elsewhere = await handleCommand(commandParams(command, "reactivate us AAPL", { channel_id: "C0OTHER01" }), s.deps);
    assert.match(JSON.stringify(elsewhere.body), /#market-brief only/);
    assert.equal(s.inbox.commands.at(-1)?.refusal_code, "not_allowed_in_channel");
  }
  assert.equal(s.slack.opened.length, 0);
  assert.equal(s.inbox.requests.length, 0);
});

test("/company add opens the form (market, symbol, optional amount) and writes nothing", async () => {
  const s = slackRig();
  const reply = await handleCommand(commandParams("/company", "add MSFT"), s.deps);
  assert.equal(reply.body, null);
  const view = s.slack.opened[0].view;
  assert.equal(view.callback_id, "mb_company_add");
  assert.deepEqual(view.blocks.map((block: { block_id: string }) => block.block_id), ["market", "symbol", "amount"]);
  assert.equal(view.blocks[1].element.initial_value, "MSFT");
  assert.equal(view.blocks[2].optional, true);
  assert.equal(JSON.parse(view.private_metadata).key, "slk-testkey0001");
  assert.equal(s.inbox.requests.length + s.inbox.commands.length, 0);
});

function submission(callback: string, values: Record<string, unknown>, metadata: unknown) {
  const state: Record<string, Record<string, unknown>> = {};
  for (const [block, value] of Object.entries(values)) state[block] = { value };
  return { type: "view_submission", user: { id: USER, team_id: TEAM }, team: { id: TEAM },
    view: { id: "V0VIEW1", callback_id: callback, private_metadata: JSON.stringify(metadata), state: { values: state } } };
}

test("add: submit shows the resolved summary with Confirm and Cancel; only Confirm writes", async () => {
  const s = slackRig();
  const submitted = await handleInteraction(submission("mb_company_add", {
    market: { selected_option: { value: "us" } }, symbol: { value: "msft" }, amount: { value: null },
  }, { key: "slk-addkey0001" }) as never, s.deps);
  assert.equal((submitted.body as { response_action: string }).response_action, "update");
  await s.settle();
  const summary = s.slack.updated[0].view;
  assert.equal(summary.callback_id, "mb_company_confirm");
  assert.equal(summary.submit.text, "Confirm");
  assert.equal(summary.close.text, "Cancel");
  assert.match(summary.blocks[0].text.text, /Microsoft Corporation \(NASDAQ, Technology, Yahoo MSFT, CIK 0000789019\), \$1,000 per trade/);
  assert.equal(summary.blocks[0].text.type, "plain_text");
  assert.equal(s.inbox.requests.length, 0, "nothing written before Confirm");
  const metadata = JSON.parse(summary.private_metadata);
  assert.deepEqual(metadata.preview, MSFT);
  await handleInteraction(submission("mb_company_confirm", {}, metadata) as never, s.deps);
  await s.settle();
  assert.equal(s.inbox.requests.length, 1);
  assert.equal(s.inbox.requests[0].submitted_by, `slack:${USER}`);
  assert.equal(s.inbox.requests[0].inbox_id, "slk-addkey0001");
  assert.equal(s.dispatcher.calls, 1);
  assert.equal(s.slack.updated.at(-1)?.view.title.text, "Pending");
  await handleInteraction(submission("mb_company_confirm", {}, metadata) as never, s.deps);
  await s.settle();
  assert.equal(s.inbox.requests.length, 1, "a second Confirm click is a duplicate");
  assert.equal(s.slack.updated.at(-1)?.view.title.text, "Already received");
});

test("add: an ETF is refused at the summary step, logged and reported", async () => {
  const s = slackRig();
  await handleInteraction(submission("mb_company_add", { market: { selected_option: { value: "us" } }, symbol: { value: "SPY" } },
    { key: "slk-addkey0002" }) as never, s.deps);
  await s.settle();
  assert.equal(s.slack.updated[0].view.title.text, "Not added");
  assert.match(s.slack.updated[0].view.blocks[0].text.text, /ETF/);
  assert.equal(s.inbox.commands.at(-1)?.refusal_code, "validation_failed");
  assert.equal(s.notifier.reports.length, 1);
  assert.equal(s.inbox.requests.length, 0);
});

test("deactivate, reactivate and amount show a confirm step; Confirm writes, Cancel does not", async () => {
  const s = slackRig();
  const reply = await handleCommand(commandParams("/company", "deactivate us AAPL earnings risk"), s.deps);
  const body = reply.body as { blocks: { type: string; elements?: { action_id: string; value: string }[]; text?: { text: string } }[] };
  assert.match(body.blocks[0].text?.text ?? "", /^Deactivate AAPL \(US\)/);
  const confirm = body.blocks[1].elements?.find((element) => element.action_id === "mb_confirm");
  assert.ok(confirm);
  assert.equal(s.inbox.requests.length, 0);
  const click = (actionId: string, value: string, channel = CHANNEL) => ({ type: "block_actions", user: { id: USER, team_id: TEAM }, team: { id: TEAM },
    channel: { id: channel }, response_url: "https://hooks.slack.com/actions/T/1/x", actions: [{ action_id: actionId, value }] });
  await handleInteraction(click("mb_cancel", "cancel") as never, s.deps);
  await s.settle();
  assert.equal(s.slack.responses.at(-1)?.body.text, "Cancelled; nothing was written.");
  assert.equal(s.inbox.requests.length, 0);
  await handleInteraction(click("mb_confirm", confirm.value) as never, s.deps);
  await s.settle();
  assert.equal(s.inbox.requests.length, 1);
  assert.equal(s.inbox.requests[0].tool, "deactivate_company");
  assert.deepEqual(s.inbox.requests[0].arguments, { market: "us", ticker: "AAPL", reason: "earnings risk", idempotency_key: "slk-testkey0001" });
  assert.match(s.slack.responses.at(-1)?.body.text, /^Pending: Deactivate AAPL \(US\)/);
  const amount = await handleCommand(commandParams("/company", "amount india TCS 1,50,000"), s.deps);
  assert.match(JSON.stringify(amount.body), /Set TCS \(India\) to ₹1,50,000 per trade/);
  const back = await handleCommand(commandParams("/company", "amount us AAPL default"), s.deps);
  assert.match(JSON.stringify(back.body), /back to the default \$1,000/);
  const reactivate = await handleCommand(commandParams("/company", "reactivate us AAPL"), s.deps);
  assert.match(JSON.stringify(reactivate.body), /Reactivate AAPL \(US\)/);
  const forged = { tool: "delete_company", args: { market: "us", ticker: "AAPL", confirm: "AAPL", idempotency_key: "forged-key-01" } };
  await handleInteraction(click("mb_confirm", JSON.stringify(forged)) as never, s.deps);
  await s.settle();
  assert.equal(s.inbox.requests.length, 1, "a button can only confirm deactivate, reactivate or amount");
  await handleInteraction(click("mb_confirm", confirm.value, "C0OTHER01") as never, s.deps);
  await s.settle();
  assert.equal(s.inbox.commands.at(-1)?.refusal_code, "not_allowed_in_channel");
});

test("/company delete is refused in Slack and reported; bad input is refused with usage", async () => {
  const s = slackRig();
  const reply = await handleCommand(commandParams("/company", "delete us AAPL"), s.deps);
  assert.match(JSON.stringify(reply.body), /only on the dashboard/);
  assert.equal(s.inbox.commands.at(-1)?.refusal_code, "not_allowed_in_channel");
  assert.equal(s.notifier.reports.at(-1)?.refusal_code, "not_allowed_in_channel");
  const wrong = await handleCommand(commandParams("/company", "deactivate mars AAPL"), s.deps);
  assert.match(JSON.stringify(wrong.body), /Not done: market must be/);
  const unknown = await handleCommand(commandParams("/company", "frobnicate"), s.deps);
  assert.match(JSON.stringify(unknown.body), /Unknown \/company command/);
  assert.equal(s.inbox.requests.length, 0);
});

test("/trade opens the form and its submission records a pending paper trade", async () => {
  const s = slackRig();
  await handleCommand(commandParams("/trade", ""), s.deps);
  const view = s.slack.opened[0].view;
  assert.equal(view.callback_id, "mb_trade");
  await handleInteraction(submission("mb_trade", {
    market: { selected_option: { value: "us" } }, ticker: { value: "aapl" }, side: { selected_option: { value: "buy" } },
    quantity: { value: "2.5" }, trade_date: { selected_date: "2026-10-06" }, price_basis: { selected_option: { value: "close" } },
    price: { value: null }, note: { value: "test" },
  }, JSON.parse(view.private_metadata)) as never, s.deps);
  await s.settle();
  assert.equal(s.inbox.requests[0].tool, "add_paper_trade");
  assert.deepEqual(s.inbox.requests[0].arguments, { market: "us", ticker: "AAPL", side: "buy", quantity: 2.5, trade_date: "2026-10-06",
    price_basis: "close", note: "test", idempotency_key: "slk-testkey0001" });
  assert.equal(s.slack.updated.at(-1)?.view.title.text, "Pending");
});

test("/ask answers coming soon, is logged, and writes nothing", async () => {
  const s = slackRig();
  const reply = await handleCommand(commandParams("/ask", "why did AAPL fall?"), s.deps);
  assert.match(JSON.stringify(reply.body), /coming soon/);
  assert.equal(s.inbox.commands.at(-1)?.tool, "explain");
  assert.equal(s.inbox.commands.at(-1)?.result, "accepted");
  assert.equal(s.inbox.requests.length, 0);
});
