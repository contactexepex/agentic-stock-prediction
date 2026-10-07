// The plain-words summary a caller confirms before a write (F8.7), and the text of the pending answer.
import type { CompanyPreview, ToolArgs } from "./types.ts";
import { DEFAULT_AMOUNT, money } from "./text.ts";

type Market = "india" | "us";

export function companyLine(preview: CompanyPreview): string {
  const parts = [preview.exchange, preview.sector ?? "sector set at onboarding", `Yahoo ${preview.yahoo}`];
  if (preview.nse_symbol) parts.push(`NSE ${preview.nse_symbol}`);
  if (preview.market === "us") parts.push(preview.cik ? `CIK ${preview.cik}` : "CIK resolved at onboarding");
  const amount = `${money(preview.market, preview.amount)} per trade${preview.amount_is_default ? " (default)" : ""}`;
  return `${preview.name} (${parts.join(", ")}), ${amount}`;
}

export function writeSummary(tool: string, args: ToolArgs, preview: CompanyPreview | null): string {
  const market = args.market as Market;
  const where = `${String(args.ticker ?? args.symbol)} (${market === "india" ? "India" : "US"})`;
  switch (tool) {
    case "add_company":
      return preview ? `Add ${companyLine(preview)}` : `Add ${where}`;
    case "deactivate_company":
      return `Deactivate ${where} from the next pre-open run; collection continues and open trades still settle`;
    case "reactivate_company":
      return `Reactivate ${where} from the next pre-open run`;
    case "set_paper_amount":
      return args.amount === null
        ? `Set ${where} back to the default ${money(market, DEFAULT_AMOUNT[market])} per trade from the next pre-open run`
        : `Set ${where} to ${money(market, Number(args.amount))} per trade from the next pre-open run`;
    case "delete_company":
      return `Delete ${where} everywhere (tombstone); raw records stay in git history`;
    case "add_paper_trade": {
      const basis = args.price_basis === "manual" ? `at ${money(market, Number(args.price))}` : `at the ${args.price_basis}`;
      return `Paper ${args.side} ${args.quantity} ${where} on ${args.trade_date} ${basis} (a record, not an order)`;
    }
    default:
      return `${tool} ${where}`;
  }
}
