// What every section of the company pages needs besides its own records: the payload, its currency and the market's
// clock (status.session.local_time) for times.
import { fmtLocal, moneyDecimals } from "../../../../../../lib/ui/format.ts";
import type { Market } from "../../../../../../lib/data/constants.ts";
import type { PageBase, StrategyMap } from "../../../../../../lib/ui/types.ts";

export interface PageCtx {
  market: Market;
  currency: string;
  /** Decimals of money in the currency (whole rupees, cents). */
  decimals: number;
  strategies: StrategyMap;
  /** A UTC time on the market's clock: "09:15 IST" or with the date "7 Oct 09:15 IST". */
  at: (iso: string | null | undefined, withDate?: boolean) => string;
}

export function pageCtx(p: PageBase & { strategies: StrategyMap }): PageCtx {
  return {
    market: p.market,
    currency: p.currency,
    decimals: moneyDecimals(p.currency),
    strategies: p.strategies,
    at: (iso, withDate = false) => fmtLocal(iso, p.market, p.status.session.local_time, withDate),
  };
}
