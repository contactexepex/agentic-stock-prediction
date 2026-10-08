// The company pages' legend (design/mockups/03-company and 04-stock-strategies legend): sample values, said so.
import { Icon } from "../../../../../../components/ui/icon.tsx";
import { MIN_TRADES_TO_RANK } from "../../../../../../lib/ui/constants.ts";

const Common = () => (
  <>
    <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
    <span><i className="sw r" />rule <i className="sw b" />baselines <i className="sw a" />AI</span>
  </>
);

export function CompanyLegend() {
  return (
    <div className="legend2" aria-label="Legend">
      <Common />
      <span><span className="h-lab">N+3</span> horizon: sell at the close of the 3rd session after the entry session</span>
      <span><span className="mb-tag paper">paper</span> every signal and trade until proven</span>
      <span><span className="mb-label success">clears costs</span> expected gain after costs above zero; nothing here is advice</span>
    </div>
  );
}

export function StrategiesLegend() {
  return (
    <div className="legend2" aria-label="Legend">
      <Common />
      <span><span className="mb-label success"><Icon name="check" />would buy</span> an up call at or above the strategy’s bar</span>
      <span><span className="mb-label neutral">too few to rank</span> under {MIN_TRADES_TO_RANK} settled trades on this company</span>
      <span><span className="mb-tag paper">paper</span> every signal and trade until proven</span>
    </div>
  );
}
