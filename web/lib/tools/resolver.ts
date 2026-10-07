// Resolves an add request's identifiers for the summary the caller confirms (F8.7): name, exchange, sector, Yahoo
// symbol, NSE symbol (India), CIK (US), amount. A preview only: the onboarding pipeline (session B1) resolves and
// checks everything again with the Python validators before the add event is written.
import type { CompanyPreview, CompanyResolver, ResolveResult } from "./types.ts";
import type { FetchLike } from "./http.ts";
import { CURRENCY, DEFAULT_AMOUNT } from "./text.ts";

interface YahooQuote {
  symbol?: string;
  shortname?: string;
  longname?: string;
  exchange?: string;
  quoteType?: string;
  sector?: string;
  sectorDisp?: string;
}

const NASDAQ = new Set(["NMS", "NGM", "NCM", "NAS"]);
const NYSE = new Set(["NYQ", "NYS"]);
const SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search";
const SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json";

function yahooSymbol(market: "india" | "us", symbol: string): string {
  return market === "india" ? `${symbol}.NS` : symbol.replace(/\./g, "-");
}

export class YahooSecResolver implements CompanyResolver {
  readonly fetcher: FetchLike;
  readonly secUserAgent: string | null;

  constructor(fetcher: FetchLike, secUserAgent: string | null) {
    this.fetcher = fetcher;
    this.secUserAgent = secUserAgent;
  }

  private async search(symbol: string): Promise<YahooQuote[]> {
    const url = `${SEARCH_URL}?q=${encodeURIComponent(symbol)}&quotesCount=10&newsCount=0&listsCount=0`;
    const response = await this.fetcher(url, { headers: { Accept: "application/json", "User-Agent": "market-brief-gateway" } });
    if (!response.ok) throw new Error(`search answered ${response.status}`);
    const body = (await response.json()) as { quotes?: YahooQuote[] };
    return Array.isArray(body.quotes) ? body.quotes : [];
  }

  private async cik(symbol: string): Promise<string | null> {
    if (!this.secUserAgent) return null;
    const response = await this.fetcher(SEC_TICKERS_URL, { headers: { "User-Agent": this.secUserAgent, Accept: "application/json" } });
    if (!response.ok) return null;
    const body = (await response.json()) as { fields?: string[]; data?: unknown[][] };
    const fields = body.fields ?? [];
    const tickerAt = fields.indexOf("ticker");
    const cikAt = fields.indexOf("cik");
    const wanted = symbol.replace(/\./g, "-").toUpperCase();
    const row = (body.data ?? []).find((entry) => String(entry[tickerAt]).toUpperCase() === wanted);
    return row ? String(row[cikAt]).padStart(10, "0") : null;
  }

  async resolve(market: "india" | "us", symbol: string, amount: number | null): Promise<ResolveResult> {
    const quotes = await this.search(symbol);
    const target = yahooSymbol(market, symbol);
    const match = quotes.find((quote) => quote.symbol?.toUpperCase() === target.toUpperCase());
    if (!match) {
      if (market === "india" && quotes.some((quote) => quote.symbol?.toUpperCase() === `${symbol}.BO`)) {
        return { ok: false, code: "validation_failed", message: `${symbol} is listed on BSE only; only NSE stocks can be added` };
      }
      return { ok: false, code: "validation_failed", message: `${symbol} was not found on ${market === "india" ? "NSE" : "NYSE or Nasdaq"}` };
    }
    if (match.quoteType !== "EQUITY") {
      const what = match.quoteType === "ETF" ? "an ETF" : `a ${String(match.quoteType ?? "non-stock").toLowerCase()}`;
      return { ok: false, code: "validation_failed", message: `${symbol} is ${what}; only common stocks can be added` };
    }
    const exchange = market === "india"
      ? (match.exchange === "NSI" ? "NSE" : null)
      : NASDAQ.has(match.exchange ?? "") ? "NASDAQ" : NYSE.has(match.exchange ?? "") ? "NYSE" : null;
    if (!exchange) {
      return { ok: false, code: "validation_failed", message: `${symbol} is not listed on ${market === "india" ? "NSE" : "NYSE or Nasdaq"}` };
    }
    const name = (match.longname ?? match.shortname ?? "").trim();
    if (!name) return { ok: false, code: "ambiguous", message: `${symbol} has no company name in the search; the owner should check it` };
    const preview: CompanyPreview = {
      market, symbol, name: name.slice(0, 120), exchange, sector: (match.sectorDisp ?? match.sector ?? null)?.slice(0, 60) ?? null,
      yahoo: target, nse_symbol: market === "india" ? symbol : null,
      cik: market === "us" ? await this.cik(symbol).catch(() => null) : null,
      amount: amount ?? DEFAULT_AMOUNT[market], amount_is_default: amount === null, currency: CURRENCY[market],
    };
    return { ok: true, preview };
  }
}
