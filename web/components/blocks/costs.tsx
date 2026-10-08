// The cost labels of a head-to-head pick (the mockups' costLabels): the market-cost label it was ranked on
// (success when the expected gain after market costs is above zero) and decision 51's label at the owner's own cost
// when that view is stored. Icons and words carry the meaning, never colour alone; the flag never blocks a trade.
import { money, pct, signed } from "../../lib/ui/format.ts";
import { pickCandidate, type Pick } from "../../lib/ui/costs.ts";
import { Label } from "../ui/primitives.tsx";

export { viableLine, yourViable, pickCandidate } from "../../lib/ui/costs.ts";

export function CostLabels({ currency, pick }: { currency: string; pick: Pick }) {
  const clears = pick.expected_gain_pct > 0;
  const c = pickCandidate(pick);
  return (
    <>
      <Label
        tone={clears ? "success" : "neutral"}
        icon={clears ? "check" : "close"}
        tip={`Expected gain after market costs ${signed(pick.expected_gain_pct)} of ${money(currency, pick.amount)}: ${pct(pick.prob_up, 1)} × ${signed(pick.move_pct)} − ${pct(1 - pick.prob_up, 1)} × ${pick.loss_pct}% − ${pick.costs_pct}% (brokerage, taxes and fees of config/costs.yaml; strategies are ranked on this view).`}
      >
        {`${signed(pick.expected_gain_pct)} · ${clears ? "clears market costs" : "below market costs"}`}
      </Label>
      {c && c.cost_viable != null ? (
        <Label
          tone={c.cost_viable ? "success" : "warn"}
          icon={c.cost_viable ? "check" : "warning"}
          tip={`Decision 51, your own costs: with your broker’s extra charges the round trip is ${c.your_cost_pct}% and the expected gain ${signed(c.expected_gain_your_pct)}, so this pick is ${c.cost_viable ? "viable" : "not viable"} at your cost. The flag never blocks a paper trade.`}
        >
          {c.cost_viable ? "viable at your cost" : "not viable at your cost"}
        </Label>
      ) : null}
    </>
  );
}
