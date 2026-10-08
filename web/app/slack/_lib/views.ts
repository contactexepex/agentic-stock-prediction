// Slack modals and messages for /company and /trade. Every text we did not write ourselves (names from the symbol
// search, reasons, notes, refusal messages) goes into plain_text fields, so it cannot ping, link or format.

type Market = "india" | "us";

const plain = (text: string) => ({ type: "plain_text", text: text.slice(0, 2900) || " ", emoji: false });
const title = (text: string) => ({ type: "plain_text", text: text.slice(0, 24) });
const option = (text: string, value: string) => ({ text: plain(text), value });
const MARKET_OPTIONS = [option("India (NSE, ₹)", "india"), option("US (NYSE/Nasdaq, $)", "us")];

function select(blockId: string, label: string, options: ReturnType<typeof option>[], initial?: string | null) {
  const initialOption = options.find((item) => item.value === initial);
  return {
    type: "input", block_id: blockId, label: plain(label),
    element: { type: "static_select", action_id: "value", options, ...(initialOption ? { initial_option: initialOption } : {}) },
  };
}

function textInput(blockId: string, label: string, optional: boolean, initial?: string | null, hint?: string) {
  return {
    type: "input", block_id: blockId, label: plain(label), optional,
    element: { type: "plain_text_input", action_id: "value", max_length: 200, ...(initial ? { initial_value: initial } : {}) },
    ...(hint ? { hint: plain(hint) } : {}),
  };
}

export function companyAddModal(key: string, prefill: { market?: Market | null; symbol?: string | null; amount?: string | null }) {
  return {
    type: "modal", callback_id: "mb_company_add", private_metadata: JSON.stringify({ key }),
    title: title("Add a company"), submit: title("Check"), close: title("Cancel"),
    blocks: [
      select("market", "Market", MARKET_OPTIONS, prefill.market ?? null),
      textInput("symbol", "Exchange symbol", false, prefill.symbol, "NSE symbol (e.g. HDFCBANK) or NYSE/Nasdaq ticker (e.g. MSFT)"),
      textInput("amount", "Paper amount per trade (optional)", true, prefill.amount, "Default ₹1,00,000 (India) or $1,000 (US)"),
    ],
  };
}

export function confirmModal(summary: string, metadata: unknown) {
  return {
    type: "modal", callback_id: "mb_company_confirm", private_metadata: JSON.stringify(metadata),
    title: title("Confirm"), submit: title("Confirm"), close: title("Cancel"),
    blocks: [
      { type: "section", text: plain(summary) },
      { type: "context", elements: [plain("Only Confirm writes. The onboarding checks everything again; until then the request shows as pending. Research only, paper records.")] },
    ],
  };
}

export function statusModal(heading: string, text: string) {
  return {
    type: "modal", title: title(heading), close: title("Close"),
    blocks: [{ type: "section", text: plain(text) }],
  };
}

export function tradeModal(key: string) {
  return {
    type: "modal", callback_id: "mb_trade", private_metadata: JSON.stringify({ key }),
    title: title("Paper trade"), submit: title("Record"), close: title("Cancel"),
    blocks: [
      select("market", "Market", MARKET_OPTIONS),
      textInput("ticker", "Ticker on the watchlist", false),
      select("side", "Side", [option("Buy", "buy"), option("Sell", "sell")]),
      textInput("quantity", "Quantity", false, null, "Whole shares in India; fractions allowed in the US"),
      { type: "input", block_id: "trade_date", label: plain("Trade date (a session)"), element: { type: "datepicker", action_id: "value" } },
      select("price_basis", "Price", [option("The day's open", "open"), option("The day's close", "close"), option("Manual price", "manual")]),
      textInput("price", "Manual price (only with Manual price)", true, null, "Inside that day's low-high range"),
      textInput("note", "Note (optional)", true),
      { type: "context", elements: [plain("A paper record for research, never an order.")] },
    ],
  };
}

export function confirmMessage(summary: string, value: string) {
  return {
    response_type: "ephemeral",
    text: summary.slice(0, 2900),
    blocks: [
      { type: "section", text: plain(summary) },
      {
        type: "actions",
        elements: [
          { type: "button", action_id: "mb_confirm", style: "primary", text: plain("Confirm"), value },
          { type: "button", action_id: "mb_cancel", text: plain("Cancel"), value: "cancel" },
        ],
      },
      { type: "context", elements: [plain("Only Confirm writes. Takes effect from the next pre-open run once imported.")] },
    ],
  };
}

export function ephemeral(text: string) {
  return { response_type: "ephemeral", text: text.slice(0, 2900), blocks: [{ type: "section", text: plain(text) }] };
}

export const RESULT_HEADINGS: Record<string, string> = {
  pending: "Pending",
  duplicate: "Already received",
  accepted: "Done",
  refused: "Not done",
  failed: "Not done",
};

export const USAGE = [
  "/company add [india|us] [SYMBOL] [amount] - opens the add form; a summary to confirm follows",
  "/company deactivate india|us TICKER [reason]",
  "/company reactivate india|us TICKER",
  "/company amount india|us TICKER AMOUNT|default",
  "/trade - opens the paper-trade form (a record, never an order)",
  "/ask india|us QUESTION - asks the assistant (stored data only, never advice)",
  "Delete is only on the dashboard, with a typed confirmation.",
].join("\n");
