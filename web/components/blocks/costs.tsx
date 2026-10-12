// The cost labels of a head-to-head pick (the mockups' costLabels): the expected gain after the market fees it was
// ranked on, and whether it is still worth it after the owner's own broker's fees when that view is stored. Every
// value is labelled "Expected" and never styled like a result (docs/ux/plain_language_review.md W2). Icons and words
// carry the meaning, never colour alone; the flag never blocks a paper trade.
import { EXPECTED_MEANS } from "../../lib/ui/constants.ts";
import { money, pct, signed } from "../../lib/ui/format.ts";
import { pickCandidate, type Pick } from "../../lib/ui/costs.ts";
import { Label } from "../ui/primitives.tsx";

export { viableLine, yourViable, pickCandidate } from "../../lib/ui/costs.ts";

/** "Expected: −1.16% · costs are bigger than the likely gain" (the market-fee view a pick is ranked on). */
export function expectedWords(expectedGainPct: number): string {
  return `Expected ${signed(expectedGainPct)} · ${expectedGainPct > 0 ? "likely gain beats the fees" : "costs are bigger than the likely gain"}`;
}

export function CostLabels({ currency, pick }: { currency: string; pick: Pick }) {
  const clears = pick.expected_gain_pct > 0;
  const c = pickCandidate(pick);
  return (
    <>
      <Label
        tone="neutral"
        icon={clears ? "check" : "close"}
        tip={`${EXPECTED_MEANS} Expected after market fees (brokerage, taxes and exchange fees) ${signed(pick.expected_gain_pct)} of ${money(currency, pick.amount)}: ${pct(pick.prob_up, 1)} chance × ${signed(pick.move_pct)} if right − ${pct(1 - pick.prob_up, 1)} × ${pick.loss_pct}% if wrong − ${pick.costs_pct}% fees. Strategies are ranked on this view.`}
      >
        {expectedWords(pick.expected_gain_pct)}
      </Label>
      {c && c.cost_viable != null ? (
        <Label
          tone={c.cost_viable ? "success" : "warn"}
          icon={c.cost_viable ? "check" : "warning"}
          tip={`Your broker charges more than the basic market fees (for example, currency markup and reporting charges): the round trip costs ${c.your_cost_pct}%. After those, the expected gain is ${signed(c.expected_gain_your_pct)}. The flag never blocks a paper trade.`}
        >
          {c.cost_viable ? "Worth it after your broker’s fees" : "Not worth it after your broker’s fees"}
        </Label>
      ) : null}
    </>
  );
}
