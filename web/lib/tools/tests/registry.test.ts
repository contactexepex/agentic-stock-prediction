import { test } from "node:test";
import assert from "node:assert/strict";
import { AGENTS, TOOLS, agentTools, allowedInChannel, getAgent, getTool } from "../registry.ts";
import { validateArguments } from "../validate.ts";
import { gatewayDecision } from "../gateway.ts";

test("the generated registry carries all 13 tools of mcp/tools.yaml with $ref inputs resolved", () => {
  assert.deepEqual(TOOLS.map((tool) => tool.name), [
    "get_overview", "get_company", "get_scoreboard", "compare_rule_vs_ai", "get_news", "get_trades", "explain",
    "add_company", "deactivate_company", "reactivate_company", "set_paper_amount", "delete_company", "add_paper_trade",
  ]);
  assert.deepEqual(getTool("get_company")?.inputs.ticker.pattern, "^[A-Z0-9.&-]{1,20}$");
  assert.equal(getTool("get_company")?.inputs.ticker.required, true);
  assert.equal(getTool("get_news")?.inputs.ticker.required, false);
});

test("delete is allowed only on the dashboard; the assistant agent has no write tool", () => {
  const remove = getTool("delete_company")!;
  assert.equal(allowedInChannel(remove, "dashboard"), true);
  for (const channel of ["slack", "claude_code", "claude_app"] as const) assert.equal(allowedInChannel(remove, channel), false);
  const assistant = getAgent("assistant")!;
  assert.equal(agentTools(assistant, "slack").some((tool) => tool.kind === "write"), false);
  assert.equal(agentTools(getAgent("claude-app")!, "claude_app").some((tool) => tool.name === "delete_company"), false);
  assert.deepEqual(AGENTS.map((agent) => agent.agent).sort(), ["assistant", "claude-app", "dashboard", "slack-gateway"]);
});

test("validation refuses unknown arguments, bad patterns, types and dates", () => {
  const company = getTool("get_company")!;
  assert.equal(validateArguments(company, { market: "us", ticker: "AAPL" }, "2026-10-07").ok, true);
  for (const bad of [
    { market: "us", ticker: "aapl" },
    { market: "uk", ticker: "AAPL" },
    { market: "us" },
    { market: "us", ticker: "AAPL", actor: "github:owner" },
    "not an object",
  ]) assert.equal(validateArguments(company, bad, "2026-10-07").ok, false, JSON.stringify(bad));
  const news = getTool("get_news")!;
  assert.equal(validateArguments(news, { market: "us", since: "2026-10-01T00:00:00Z" }, "2026-10-07").ok, true);
  assert.equal(validateArguments(news, { market: "us", since: "2026-13-01T00:00:00Z" }, "2026-10-07").ok, false);
  const board = getTool("get_scoreboard")!;
  assert.equal(validateArguments(board, { market: "us", strategy_id: "rule.model_news_1x.v1" }, "2026-10-07").ok, true);
  assert.equal(validateArguments(board, { market: "us", strategy_id: "x'; DROP TABLE rm.home; --" }, "2026-10-07").ok, false);
  const amount = getTool("set_paper_amount")!;
  assert.equal(validateArguments(amount, { market: "us", ticker: "AAPL", amount: null, idempotency_key: "amt-key-0001" }, "2026-10-07").ok, true);
  assert.equal(validateArguments(amount, { market: "us", ticker: "AAPL", amount: 0, idempotency_key: "amt-key-0001" }, "2026-10-07").ok, false);
  assert.equal(validateArguments(amount, { market: "us", ticker: "AAPL", amount: 5, idempotency_key: "short" }, "2026-10-07").ok, false);
});

test("paper trade checks: manual price, whole shares in India, no future dates", () => {
  const trade = getTool("add_paper_trade")!;
  const base = { market: "us", ticker: "AAPL", side: "buy", quantity: 1.5, trade_date: "2026-10-06", price_basis: "open", idempotency_key: "trade-key-0001" };
  assert.equal(validateArguments(trade, base, "2026-10-07").ok, true);
  assert.equal(validateArguments(trade, { ...base, price_basis: "manual" }, "2026-10-07").ok, false);
  assert.equal(validateArguments(trade, { ...base, price: 10 }, "2026-10-07").ok, false);
  assert.equal(validateArguments(trade, { ...base, price_basis: "manual", price: 231.5 }, "2026-10-07").ok, true);
  assert.equal(validateArguments(trade, { ...base, market: "india", ticker: "TCS" }, "2026-10-07").ok, false);
  assert.equal(validateArguments(trade, { ...base, trade_date: "2026-10-08" }, "2026-10-07").ok, false);
  assert.equal(validateArguments(trade, { ...base, trade_date: "2026-02-30" }, "2026-10-07").ok, false);
  assert.equal(validateArguments(trade, { ...base, quantity: 0 }, "2026-10-07").ok, false);
  assert.equal(validateArguments(trade, { ...base, note: "x".repeat(201) }, "2026-10-07").ok, false);
});

test("gateway mode serves only the Slack routes, /mcp and its OAuth routes", () => {
  assert.deepEqual(gatewayDecision("/slack/commands", "POST", true), { action: "slack" });
  assert.deepEqual(gatewayDecision("/slack/interactions", "POST", true), { action: "slack" });
  assert.deepEqual(gatewayDecision("/slack/commands", "GET", true), { action: "not_found" });
  assert.deepEqual(gatewayDecision("/mcp", "POST", true), { action: "next" });
  assert.deepEqual(gatewayDecision("/mcp/oauth/token", "POST", true), { action: "next" });
  assert.deepEqual(gatewayDecision("/mcp/oauth/token", "GET", true), { action: "not_found" });
  assert.deepEqual(gatewayDecision("/.well-known/oauth-protected-resource/mcp", "GET", true), { action: "rewrite", target: "/mcp/oauth/protected-resource" });
  assert.deepEqual(gatewayDecision("/.well-known/oauth-authorization-server", "GET", true), { action: "rewrite", target: "/mcp/oauth/metadata" });
  for (const path of ["/", "/api/v1/markets", "/api/assistant", "/markets/us", "/slack/other", "/mcp/../api", "/_next/static/x.js", "/favicon.ico"]) {
    assert.deepEqual(gatewayDecision(path, "GET", true), { action: "not_found" }, path);
  }
});

test("the dashboard deployment never serves the gateway routes", () => {
  for (const path of ["/slack/commands", "/mcp", "/mcp/oauth/authorize", "/.well-known/oauth-authorization-server"]) {
    assert.deepEqual(gatewayDecision(path, "POST", false), { action: "not_found" }, path);
  }
  assert.deepEqual(gatewayDecision("/", "GET", false), { action: "next" });
  assert.deepEqual(gatewayDecision("/api/v1/markets", "GET", false), { action: "next" });
});
