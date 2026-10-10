"use client";
// The company line under the page head and the "at a glance" decision card (design/mockups/03-company coHead,
// decision): last close, sector, amount, state and the page's actions; then who would buy at N+k, the reference
// strategy's published range, today's head-to-head picks with their cost views, open trades and the next event, and
// the plain-words line ending with the Paper caveat. Never advice.
import Link from "next/link";
import type { ReactNode } from "react";
import { CostLabels, viableLine } from "../../../../../../components/blocks/costs.tsx";
import { strategyOf } from "../../../../../../components/blocks/records.tsx";
import { RangeBar } from "../../../../../../components/charts/small.tsx";
import { HorizonTabs } from "../../../../../../components/ui/controls.tsx";
import { HelpTip, Icon } from "../../../../../../components/ui/icon.tsx";
import { Card, CardHead, Delta, FamilyLabel, Label, MoneyDelta, Odds } from "../../../../../../components/ui/primitives.tsx";
import { FAMILY, FAMILY_SHORT, PICK_RULE, type Family } from "../../../../../../lib/ui/constants.ts";
import { fmtDate, fmtDateYear, money, pct, price, signed } from "../../../../../../lib/ui/format.ts";
import { stockStrategiesPath } from "../../../../../../lib/ui/routes.ts";
import { bandsOf, companyEventEffect, nextCompanyEvent, openSummary, publishedRangeAt, publishedRanges, referencePrediction } from "../../../../../../lib/company-pages/company-logic.ts";
import { agreementAt, buyShare, expectedGainMoney } from "../../../../../../lib/company-pages/strategies-logic.ts";
import type { CompanyPayload, HeadToHeadPick } from "../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "./context.ts";
import { eventWords, plural } from "./labels.ts";

const FAMILIES: Family[] = ["rule", "baseline", "ai"];

export function CompanyLine({ p, ctx, actions }: { p: CompanyPayload; ctx: PageCtx; actions: ReactNode }) {
  const co = p.company;
  return (
    <div className="cohead">
      <div className="px">
        {price(ctx.currency, co.last_close)}
        <small>last close, {fmtDate(co.last_close_date)}</small>
      </div>
      <Delta value={co.change_pct} />
      <span className="md-chip" data-tip="Sector set at onboarding; exchange where it is listed.">
        {co.sector ?? "sector not set"} · {co.exchange ?? "exchange not stored"}
      </span>
      <span className="md-chip" data-tip={co.amount_overridden ? "Money per paper trade, set by the owner for this company (differs from the default)." : "Money per paper trade (the market’s default amount)."}>
        <Icon name="account_balance_wallet" />
        {money(ctx.currency, co.amount)} per paper trade{co.amount_overridden ? <b> · custom</b> : null}
      </span>
      {co.state === "active" ? (
        <Label tone="success" icon="check" tip="Active: predicted every session and traded on paper.">active</Label>
      ) : (
        <Label tone="neutral" icon="pending" tip={`Inactive since ${fmtDateYear(co.state_since)}: still collected, never predicted or traded (decision 13).`}>
          inactive since {fmtDate(co.state_since, false)}
        </Label>
      )}
      <div className="acts">
        <Link className="md-btn tonal small" href={stockStrategiesPath(ctx.market, co.ticker)} data-tip="Every strategy on this company, ranked by profit after costs (page 4).">
          <Icon name="science" />
          Strategies
        </Link>
        {actions}
      </div>
    </div>
  );
}

function PickLine({ k, ctx }: { k: HeadToHeadPick; ctx: PageCtx }) {
  const st = strategyOf(ctx.strategies, k.strategy_id ?? "");
  const tip = `${PICK_RULE[k.pick_rule] ?? k.pick_rule}: ${st.name} (${FAMILY[k.family][0]}, ranked on ${k.strongest_basis === "all_companies" ? "all companies" : "this company"}) picks N+${k.horizon_days}: chance ${pct(k.prob_up, 1)}, move if up ${signed(k.move_pct)}, loss if down ${signed(-k.loss_pct)}, market costs ${k.costs_pct.toFixed(2)}%.`;
  return (
    <div className="p">
      <span className="p1" data-tip={tip}>
        <FamilyLabel family={k.family}>{FAMILY_SHORT[k.family]}</FamilyLabel>
        <small className="muted">{PICK_RULE[k.pick_rule] ?? k.pick_rule}</small>
        <span className="h-lab">N+{k.horizon_days}</span>
      </span>
      <span className="p2">
        <Odds p={k.prob_up} />
        <span className="g">
          <MoneyDelta currency={ctx.currency} value={expectedGainMoney(k.expected_gain_pct, k.amount)} decimals={ctx.decimals} />
        </span>
        <CostLabels currency={ctx.currency} pick={k} />
      </span>
    </div>
  );
}

export function DecisionCard({ p, ctx, horizon, onHorizon }: { p: CompanyPayload; ctx: PageCtx; horizon: number; onHorizon: (k: number) => void }) {
  const co = p.company, a = agreementAt(p.agreement, horizon), pr = referencePrediction(p.predictions, p.reference_strategy, horizon);
  const reference = strategyOf(ctx.strategies, p.reference_strategy);
  const picked = p.head_to_head.filter((x) => x.status === "picked");
  const open = openSummary(p.open_trades, p.trade_checks);
  const next = nextCompanyEvent(p.events, co.ticker);
  const effect = next ? companyEventEffect(next.type) : null;
  const check0 = p.trade_checks[0];
  // The published range (ranges.py) is shown whatever the strategies' live_from; the chance of a rise and "would
  // buy" are the reference strategy's own and appear only when it has a prediction at this horizon.
  const range = publishedRangeAt(publishedRanges(p), horizon);
  const bands = range ? bandsOf(range) : null;
  return (
    <Card label="At a glance">
      <CardHead
        title={`${co.name} at a glance`}
        help="What the strategies say about this company for the selected horizon, today’s head-to-head picks, the reference strategy’s published range, and what is coming. It helps you judge the company; it never tells you to buy or sell. Every signal is Paper until a strategy meets the go-live bar."
        end={
          <>
            <span className="muted">Horizon <HelpTip tip="N+k: buy at the open of the session being predicted, sell at the close of the k-th market session after it. Opens on N+1 (decision 39)." /></span>
            <HorizonTabs horizons={p.horizons} value={horizon} onChange={onHorizon} />
          </>
        }
      />
      <div className="dec">
        <div className="cell">
          <div className="l"><Icon name="trending_up" />Who would buy at N+{horizon}</div>
          {a ? (
            <>
              <div className="v">{a.buy} of {a.of}<small> strategies</small></div>
              <div className="s">
                {a.avg_prob_up != null ? (
                  <span>buyers’ average chance <Odds p={a.avg_prob_up} tip={`Average probability of a rise given by the buyers that give one: ${pct(a.avg_prob_up, 1)}. 50% is a coin flip.`} /></span>
                ) : "buyers give a direction, not a probability"}
              </div>
              <div className="fb">
                {FAMILIES.map((f) => {
                  const x = a.by_family[f];
                  return (
                    <div className="r" key={f}>
                      <span className="l">{FAMILY_SHORT[f]}</span>
                      <div className="bar" role="img" aria-label={`${FAMILY[f][0]}: ${x.buy} of ${x.of} buy`}>
                        <i className={`ser-${FAMILY[f][2]}`} style={{ width: `${buyShare(x).toFixed(1)}%` }} />
                      </div>
                      <b>{x.buy}/{x.of}</b>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <>
              <div className="v muted">—</div>
              <div className="s">No agreement row at this horizon.</div>
            </>
          )}
        </div>
        <div className="cell">
          <div className="l">
            <Icon name="query_stats" />Published range at N+{horizon}
            <button className="md-help" type="button" aria-label="Explain" data-tip={`The published range for this horizon, computed by ranges.py: the target is the expected exit close; the 50% and 80% ranges are where the close is expected to land that often. Drawn on the chart. The chance of a rise is the reference rule strategy’s (${reference.name}), when it has a prediction.`}>?</button>
          </div>
          {range && bands ? (
            <>
              <div className="v">{price(ctx.currency, range.target_price)}<small> target</small></div>
              <RangeBar currency={ctx.currency} bands={bands} last={co.last_close ?? null} />
              <div className="s">
                80% range {price(ctx.currency, range.lo80)}–{price(ctx.currency, range.hi80)} · exit {fmtDate(range.exit_date)}
                {pr ? ` · chance of a rise ${pct(pr.prob_up)}${pr.qualifies ? " · would buy" : " · no trade"}` : " · no strategy prediction yet"}
              </div>
            </>
          ) : (
            <>
              <div className="v muted">—</div>
              <div className="s">{co.state !== "active" ? "Inactive companies get no published range." : `No published range stored for this company at N+${horizon} today.`}</div>
            </>
          )}
        </div>
        <div className="cell">
          <div className="l">
            <Icon name="layers" />Today’s head-to-head picks
            <button className="md-help" type="button" aria-label="Explain" data-tip="Up to four paper trades a day per company: the strongest rule strategy and the strongest AI trader, each by two pick rules (best expected gain, highest probability). Expected gain = chance × move − (1 − chance) × loss − costs; “clears costs” when it is above zero (decisions 41-42, 51).">?</button>
          </div>
          {picked.length ? (
            <>
              <div className="v">{picked.length}<small> paper {plural(picked.length, "trade")}</small></div>
              <div className="s">{viableLine(picked)}</div>
              <div className="pkl">{picked.map((k) => <PickLine key={k.id} k={k} ctx={ctx} />)}</div>
            </>
          ) : (
            <>
              <div className="v muted">None</div>
              <div className="s">
                {co.state !== "active" ? "Inactive companies get no picks." : p.head_to_head.length ? `No candidate: no rule strategy and no AI trader buys ${co.name} at any horizon today.` : "No head-to-head pick stored for this session."}
              </div>
            </>
          )}
        </div>
        <div className="cell">
          <div className="l"><Icon name="event" />Open trades and what is coming</div>
          <div className="v">{open.count}<small> open paper {plural(open.count, "trade")}</small></div>
          <div className="s">
            {open.count ? (
              <span>
                unrealised <MoneyDelta currency={ctx.currency} value={open.unrealised} decimals={ctx.decimals} /> before costs
                {check0 ? ` · ${open.flagged ? `${open.flagged} flagged` : "none flagged"} at the ${ctx.at(check0.check_at)} check` : " · no intraday check yet"}
              </span>
            ) : "nothing open"}
          </div>
          {next ? (
            <div
              className="s"
              data-tip={`${next.name} on ${fmtDateYear(next.date)}${next.timing ? ` (${next.timing.replace("_", " ")})` : " (timing unknown)"}: ${effect ? effect.tip.replace(/\.$/, "") : "a scheduled company event"}${next.reaction_sessions?.length ? `; the reaction lands in the session${next.reaction_sessions.length > 1 ? "s" : ""} ${next.reaction_sessions.map((d) => fmtDate(d, false)).join(" and ")}` : ""}.`}
            >
              <Icon name="event" /> {eventWords(next.type)} {fmtDate(next.date)}{next.provisional ? " (date not confirmed)" : ""}
            </div>
          ) : (
            <div className="s">No company event in the next 60 days.</div>
          )}
        </div>
      </div>
      <div className="plain">
        <Icon name="info" />
        <div>
          {a ? `${a.buy} of ${a.of} strategies would buy ${co.name} at N+${horizon}${a.avg_prob_up != null ? ` with an average chance of ${pct(a.avg_prob_up)}` : ""}. ` : ""}
          {picked.length ? `Of today’s ${picked.length} head-to-head picks, ${viableLine(picked)}. ` : "No head-to-head pick today. "}
          {next ? `${eventWords(next.type).replace(/^./, (c) => c.toUpperCase())} due ${fmtDate(next.date)}${effect ? `: ${effect.plain}` : ""}. ` : ""}
          <b>
            {p.status.paper_label}: {a && a.buy > a.of / 2 ? "a majority says the strategies lean the same way, not that they are right" : "agreement says how the strategies lean, not whether they are right"}; nothing here is advice.
          </b>
        </div>
      </div>
    </Card>
  );
}
