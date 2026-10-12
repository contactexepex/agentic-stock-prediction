// The company page's opening (docs/ux/plain_language_review.md L3): one plain sentence on what the strategies think
// for the selected hold and how sure they are, then, after the chart, what the paper trades on this company did.
// Paper only: it says how the strategies lean, never what to do.
import { firstExit } from "../../../../../../lib/ui/empty.ts";
import { fmtDate, holdLabel, money, pct } from "../../../../../../lib/ui/format.ts";
import { settledSummary } from "../../../../../../lib/company-pages/company-logic.ts";
import { agreementAt } from "../../../../../../lib/company-pages/strategies-logic.ts";
import type { CompanyPayload } from "../../../../../../lib/company-pages/types.ts";
import { Icon } from "../../../../../../components/ui/icon.tsx";
import { PaperTag } from "../../../../../../components/ui/primitives.tsx";
import type { PageCtx } from "./context.ts";

export const SETTLED_ANCHOR = "settled-trades";

export function CompanySummary({ p, horizon }: { p: CompanyPayload; horizon: number }) {
  const co = p.company, a = agreementAt(p.agreement, horizon);
  const lean = co.state !== "active"
    ? `${co.name} is inactive: still collected, never predicted or traded.`
    : a
      ? `${a.buy} of ${a.of} strategies would buy ${co.name} for a ${holdLabel(horizon)}.${a.avg_prob_up != null ? ` Their average chance of a rise is ${pct(a.avg_prob_up)} (50% = coin flip).` : ""}`
      : `No strategy has a prediction for ${co.name} for a ${holdLabel(horizon)} today.`;
  return (
    <section className="mb-alert band info co-sum" aria-label="What the strategies think">
      <Icon name="info" />
      <div>
        <b className="t">{lean}</b>
        <div className="s">
          Not proven: <a href={`#${SETTLED_ANCHOR}`}>see how often they’ve been right</a>. It helps you judge the company; it never tells you to buy or sell. <PaperTag label={p.status.paper_label} />
        </div>
      </div>
    </section>
  );
}

export function CompanyTradesSoFar({ p, ctx }: { p: CompanyPayload; ctx: PageCtx }) {
  const sum = settledSummary(p.settled), co = p.company;
  const first = firstExit(p.open_trades);
  const lost = sum.trades - sum.won;
  return (
    <section className="md-card co-sofar" aria-label="What our paper trades did">
      <h2>{`What our paper trades on ${co.name} did`}</h2>
      <p>
        {sum.trades
          ? `${sum.trades} finished · ${sum.won} made money · ${lost} did not · net ${money(ctx.currency, sum.net, ctx.decimals, true)} after fees.`
          : `None finished yet${first ? `; the first on ${co.name} finishes on ${fmtDate(first)}` : ""}.`}
        {` ${p.open_trades.length} running now. `}
        <a href={`#${SETTLED_ANCHOR}`}>Every finished trade</a>
      </p>
    </section>
  );
}
