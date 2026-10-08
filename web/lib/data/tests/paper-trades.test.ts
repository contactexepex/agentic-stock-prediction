// The paper-trade write route (B13): JSON only, same-site, the Idempotency-Key header, known fields only; the tool
// layer gets the market from the path, the key from the header and the dashboard identity; outcomes map to statuses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { dashboardContext } from "../../tools/identity.ts";
import type { CallContext, RefusalCode, ToolOutcome } from "../../tools/types.ts";
import { statusOf, submitPaperTrade } from "../paper-trades.ts";

const OUTCOME: ToolOutcome = {
  command_id: "cmd-1", tool: "add_paper_trade", result: "pending", refusal_code: null, message: "Pending: buy 3 AAPL",
  record_ids: [], inbox_id: "key-0123456789abcdef", budget_left: 49,
};

class FakeLayer {
  calls: { ctx: CallContext; tool: string; raw: unknown }[] = [];
  recorded: { message: string; code: string | null; tool: string | null }[] = [];
  readonly outcome: ToolOutcome;
  constructor(outcome: ToolOutcome = OUTCOME) {
    this.outcome = outcome;
  }
  async execute(ctx: CallContext, tool: string, raw: unknown): Promise<ToolOutcome> {
    this.calls.push({ ctx, tool, raw });
    return this.outcome;
  }
  async record(_ctx: CallContext, fields: { tool: string | null; code: RefusalCode | null; message: string }): Promise<ToolOutcome> {
    this.recorded.push({ message: fields.message, code: fields.code, tool: fields.tool });
    return { ...OUTCOME, result: "refused", refusal_code: fields.code, message: fields.message, inbox_id: null };
  }
}

const BODY = { ticker: "AAPL", side: "buy", quantity: 3, trade_date: "2026-10-06", price_basis: "open" };
function post(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("https://omenix.vercel.app/api/v1/markets/us/paper-trades", {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": "key-0123456789abcdef", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

test("a valid trade goes to add_paper_trade with the path's market, the header's key and the dashboard identity", async () => {
  const layer = new FakeLayer();
  const response = await submitPaperTrade(post(BODY), "us", layer, dashboardContext());
  assert.equal(response.status, 202);
  const body = await response.json();
  assert.equal(body.result, "pending");
  assert.equal(body.paper, true);
  assert.equal(layer.calls.length, 1);
  assert.equal(layer.calls[0].tool, "add_paper_trade");
  assert.deepEqual(layer.calls[0].raw, { ...BODY, market: "us", idempotency_key: "key-0123456789abcdef" });
  assert.equal(layer.calls[0].ctx.actor, "dashboard:owner");
});

test("refused before the tool layer: unknown market, cross-site, not JSON, no key, unknown or identity fields", async () => {
  const layer = new FakeLayer();
  const cases: [Request, string, number][] = [
    [post(BODY), "eu", 404],
    [post(BODY, { origin: "https://evil.example" }), "us", 403],
    [post(BODY, { "content-type": "text/plain" }), "us", 415],
    [new Request("https://omenix.vercel.app/x", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(BODY) }), "us", 422],
    [post("{not json"), "us", 422],
    [post([BODY]), "us", 422],
    [post({ ...BODY, submitted_by: "someone" }), "us", 422],
    [post({ ...BODY, market: "india" }), "us", 422],
  ];
  for (const [request, market, status] of cases) {
    assert.equal((await submitPaperTrade(request, market, layer, dashboardContext())).status, status);
  }
  assert.equal(layer.calls.length, 0);
  // the body refusals (no key, not JSON, not an object, unknown fields) are logged; the probes before them are not
  assert.equal(layer.recorded.length, 5);
  assert.ok(layer.recorded.every((r) => r.code === "validation_failed" && r.tool === "add_paper_trade"));
  const same = await submitPaperTrade(post(BODY, { origin: "https://omenix.vercel.app" }), "us", layer, dashboardContext());
  assert.equal(same.status, 202);
});

test("outcomes map to statuses", () => {
  const of = (result: ToolOutcome["result"], code: ToolOutcome["refusal_code"] = null) =>
    statusOf({ ...OUTCOME, result, refusal_code: code });
  assert.equal(of("pending"), 202);
  assert.equal(of("duplicate"), 200);
  assert.equal(of("failed"), 503);
  assert.equal(of("refused", "duplicate_key"), 409);
  assert.equal(of("refused", "validation_failed"), 422);
  assert.equal(of("refused", "budget_exceeded"), 429);
  assert.equal(of("refused", "kill_switch"), 503);
  assert.equal(of("refused", "unknown_actor"), 403);
});
