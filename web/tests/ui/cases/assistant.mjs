// UI cases of page 11, Assistant, and the chat panel (B8), at the mockup's widths
// (design/mockups/11-assistant/shot-{1280,390}-full.png). GET and POST /api/assistant answer from fixtures built on the
// mockup's answers (W1's catalogue entity assistant_answer); nothing reaches Claude or MotherDuck.
import { mockupPayload } from "../fixtures.mjs";

const SPEND = { day: { spent_usd: 0.04, starts_at: "2026-10-07T00:00:00Z" }, month: { spent_usd: 1.25, starts_at: "2026-10-01T00:00:00Z" }, enabled: true };
const LIMITS = { question_max: 500, history_turns: 4, retention_days: 90 };

/** The mockup's answers in the API's shape: the state from not_in_data / declined, each answer its own conversation. */
function answers(market) {
  return (mockupPayload("11-assistant", market)?.answers ?? []).map((a) => ({
    ...a,
    status: a.declined ? "declined" : a.not_in_data ? "not_in_data" : "answered",
    cited: a.cited.map((c) => ({ ...c, source: "rm.trades _" })),
    sources: [],
    cost_usd: 0.01,
    conversation_id: a.id,
    history_turns: 0,
  }));
}

/** A route map for the harness: GET the conversation; POST answers with a follow-up in the same conversation. */
function assistantApi({ posted = [], getStatus = 200, off = false } = {}) {
  return {
    "/api/assistant": async (request) => {
      const market = new URL(request.url()).searchParams.get("market") ?? "india";
      if (request.method() === "GET") {
        if (getStatus !== 200) return { status: getStatus, body: { title: "Conversation log unavailable", status: getStatus } };
        return { status: 200, body: { market, answers: answers(market), spend: { ...SPEND, enabled: off ? false : true }, limits: LIMITS } };
      }
      const body = JSON.parse(request.postData() ?? "{}");
      posted.push(body);
      const prior = answers(body.market).at(-1);
      return {
        status: 200,
        body: {
          result: "accepted", refusal_code: null, message: "not in the data", command_id: "cmd-1", limits: LIMITS,
          spend: { ...SPEND, day: { ...SPEND.day, spent_usd: 0.05 } },
          answer: {
            id: `ask-${body.market}-2026-10-07-00000000a1`, market: body.market, channel: "dashboard", asked_at: "2026-10-07T11:58:00Z",
            question: body.question, text: "Not in the data: the stored prices end with the 6 Oct close.", cited_ids: [], cited: [],
            as_of: "2026-10-07T11:58:00Z", not_in_data: true, declined: null, status: "not_in_data", sources: [], cost_usd: 0.01,
            conversation_id: body.conversation_id ?? prior?.conversation_id, history_turns: body.conversation_id ? 1 : 0,
          },
        },
      };
    },
  };
}

const posted = [];

const ask = async (page, scope, text) => {
  await page.fill(`${scope} textarea`, text);
  await page.click(`${scope} .composer button:has-text("Ask")`);
};

export const cases = [
  {
    name: "assistant-india",
    path: "/india/assistant",
    mockup: "11-assistant",
    widths: [1280, 390],
    routes: assistantApi(),
    waitFor: ".chat .msg.a",
    expectText: ["Assistant", "Ask the data", "answered from the data", "not in the data", "How it answers", "Records cited", "Spend", "$0.04", "$1.25", "Questions asked so far", "nse-ann-7790412"],
    expectSelector: [".cite[href='/india/paper-portfolios']", ".mb-tag.paper", "textarea[maxlength='500']"],
  },
  {
    name: "assistant-us-declined",
    path: "/us/assistant",
    market: "us",
    mockup: "11-assistant",
    widths: [1280],
    routes: assistantApi(),
    waitFor: ".chat .msg.a",
    expectText: ["declined: no advice on real trades", "I can't advise real trades"],
    expectSelector: [".bub.dec"],
  },
  {
    name: "assistant-ask-continues",
    path: "/india/assistant",
    widths: [1280],
    routes: assistantApi(),
    waitFor: ".chat .msg.a",
    check: async (page) => {
      const problems = [];
      await page.fill(".composer textarea", "x".repeat(600));
      const length = await page.$eval(".composer textarea", (t) => t.value.length);
      if (length !== 500) problems.push(`the box kept ${length} characters, not 500`);
      if (!(await page.textContent(".composer .cnt"))?.includes("500 / 500")) problems.push("the counter does not show 500 / 500");
      await ask(page, "", "What did Reliance close at on 8 Oct?");
      await page.waitForSelector("text=Not in the data: the stored prices end", { timeout: 5000 }).catch(() => problems.push("the answer did not appear"));
      if (!(await page.textContent("body"))?.includes("$0.05")) problems.push("the spend did not update");
      return problems;
    },
  },
  {
    name: "assistant-log-down",
    path: "/india/assistant",
    widths: [1280],
    routes: assistantApi({ getStatus: 503 }),
    allowConsole: [/^Failed to load resource: the server responded with a status of 503/],
    waitFor: ".chat .quiet",
    expectText: ["The conversation log cannot be read right now", "The spend cannot be read right now"],
  },
  {
    name: "assistant-switched-off",
    path: "/india/assistant",
    widths: [1280],
    routes: assistantApi({ off: true }),
    waitFor: ".chat .msg.a",
    expectText: ["switched off by the owner"],
    expectSelector: [".composer button[disabled]"],
  },
  {
    name: "chat-panel",
    path: "/india/stocks/RELIANCE",
    widths: [1280, 390],
    routes: assistantApi({ posted }),
    waitFor: ".phead",
    check: async (page) => {
      const problems = [];
      if (await page.$(".mb-chat-slot *")) problems.push("the panel is on screen before Ask");
      const askButton = 'button[aria-controls="mb-chat-slot"]';
      if (!(await page.$(askButton))) return ["the Ask button does not control the panel (not registered)"];
      await page.click(askButton);
      await page.waitForSelector(".chat-panel textarea", { timeout: 5000 }).catch(() => problems.push("Ask did not open the panel"));
      if ((await page.getAttribute(askButton, "aria-expanded")) !== "true") problems.push("Ask is not aria-expanded while open");
      const focused = await page.evaluate(() => document.activeElement?.tagName);
      if (focused !== "TEXTAREA") problems.push(`focus went to ${focused}, not the question box`);
      if (!(await page.textContent(".chat-panel"))?.includes("Asked about the page of RELIANCE")) problems.push("the panel does not name the company in view");
      await ask(page, ".chat-panel", "Why did it move?");
      if (posted.at(-1)?.ticker !== "RELIANCE") problems.push(`the panel sent ticker ${posted.at(-1)?.ticker}`);
      await page.waitForSelector(".chat-panel .msg.a", { timeout: 5000 }).catch(() => problems.push("no answer in the panel"));
      await page.keyboard.press("Escape");
      if (await page.$(".chat-panel")) problems.push("Escape did not close the panel");
      return problems;
    },
  },
];
