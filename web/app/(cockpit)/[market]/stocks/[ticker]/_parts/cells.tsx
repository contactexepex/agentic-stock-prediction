"use client";
// Table cells shared by the company page and its call history: a strategy with its family label (the mockups'
// "name + family" cell) and an intraday check's state with the 03 mockup's full tooltip (band, flags, best and worst
// since entry, target reached). B7's StrategyName / TradeCheckStatus carry Home's shorter variants.
import { strategyOf } from "../../../../../../components/blocks/records.tsx";
import { Icon } from "../../../../../../components/ui/icon.tsx";
import { FamilyLabel } from "../../../../../../components/ui/primitives.tsx";
import { BAND, BAND_SHORT, FAMILY_SHORT, FLAG, FLAG_SHORT } from "../../../../../../lib/ui/constants.ts";
import { price, signed } from "../../../../../../lib/ui/format.ts";
import type { TradeCheck } from "../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "./context.ts";

export function StrategyCell({ id, sub, ctx }: { id: string | null; sub?: string; ctx: PageCtx }) {
  const st = strategyOf(ctx.strategies, id ?? "");
  return (
    <span className="nm">
      <b>{st.name} <FamilyLabel family={st.family}>{FAMILY_SHORT[st.family] ?? st.family}</FamilyLabel></b>
      {sub ? <small>{sub}</small> : null}
    </span>
  );
}

/** A check's band or flags with an icon and words; the tooltip has the check time (with the date when asked). */
export function CheckState({ check, ctx, withDate = false }: { check: TradeCheck; ctx: PageCtx; withDate?: boolean }) {
  const [bandWords, bandClass] = BAND[check.band] ?? [check.band, ""];
  const flags = (check.flags ?? []).map((f) => FLAG[f] ?? f);
  const tip =
    `${ctx.at(check.check_at, withDate)}: ${price(ctx.currency, check.last_price)}, ${signed(check.ret_since_entry_pct)} since entry, ${bandWords}` +
    (flags.length ? `; ${flags.join(", ")}` : "") +
    (check.high_since_entry_pct != null || check.low_since_entry_pct != null ? `. Best so far ${signed(check.high_since_entry_pct)}, worst ${signed(check.low_since_entry_pct)}` : "") +
    (check.target_reached ? `; target reached in session ${check.target_reached_session}` : "") + ".";
  return (
    <span className={`st ${check.flagged ? "flag" : bandClass}`} tabIndex={0} data-tip={tip}>
      <Icon name={check.flagged ? "warning" : "check"} />
      {check.flagged ? (check.flags ?? []).map((f) => FLAG_SHORT[f] ?? f).join(", ") : BAND_SHORT[check.band] ?? check.band}
    </span>
  );
}
