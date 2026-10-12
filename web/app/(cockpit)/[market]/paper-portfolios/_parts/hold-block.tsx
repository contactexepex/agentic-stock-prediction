"use client";
// One hold's block on the Paper portfolio page v3 (UX3): always visible, never behind a tab. Header (when it sells, how
// far it is towards the sale, the result so far before fees), the sides compared (count, win/lose bar, result so far),
// then the trades going against the prediction first, each with its one-line reason and a "Full story" link, then the
// trades going as predicted and those without a price yet; 3 lines each, then "Show N more". Identical trades of one
// side are one line (×2). Paper only: a paper trade is a record, never an order.
import Link from "next/link";
import { useState } from "react";
import { RangeBar } from "../../../../../components/charts/small.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Quiet } from "../../../../../components/ui/primitives.tsx";
import { ErrorState, LoadingState } from "../../../../../components/ui/states.tsx";
import { fmtDate, fmtLocal, holdLabel, price } from "../../../../../lib/ui/format.ts";
import { companyPath, lifecyclePath } from "../../../../../lib/ui/routes.ts";
import { rowBands } from "../../../../../lib/strategy-pages/all-trades.ts";
import {
  goingOf, mergeRows, openCause, ordered, ruleNoneWords, ruleStayedOut, SIDE_SHORT, storyHash, type Going, type Learning, type MergedRow,
  type OpenHold, type OpenSplit, type Side, type StoryRow,
} from "../../../../../lib/strategy-pages/portfolio-v3.ts";
import type { ApiState } from "../../../../../lib/ui/use-api.ts";
import { HoldProgress, InfoTip, Money, SideTag, WinLoseBar, WinLoseCounts } from "./story-ui.tsx";

export interface BlockCtx {
  market: string;
  currency: string;
  decimals: number;
  localTime: string | null;
  benchmark: string;
  strategyName: (id: string | null) => string;
  companyName: (ticker: string) => string;
  rule: Learning["rule_today"] | null;
}

const SHOWN = 3;
const GROUPS: Array<{ going: Going; icon: string; tone: string; title: string }> = [
  { going: "against", icon: "close", tone: "bad", title: "Going against the prediction" },
  { going: "with", icon: "check", tone: "ok", title: "Going as predicted" },
  { going: "pending", icon: "pending", tone: "muted", title: "No price yet" },
];

/** The hold's ⓘ: what a k-day hold means. */
const holdTip = (k: number) =>
  `Bought at the open of the entry session and sold at the close of the ${k === 1 ? "next" : `${k}th`} session after it (N+${k}). The result so far is before fees; fees are taken when a trade sells.`;

function popover(row: StoryRow, ctx: BlockCtx): string {
  const parts: string[] = [];
  const chance = row.prob_up !== null && row.prob_up !== undefined ? `a ${Math.round(row.prob_up * 100)}% chance of a rise` : "a rise (this one buys without a forecast)";
  const range = row.lo80 != null && row.hi80 != null ? `; price at the sale ${price(ctx.currency, row.lo80)} to ${price(ctx.currency, row.hi80)} (8 in 10 times)` : "";
  parts.push(`Expected: ${chance}${range}.`);
  if (!row.price_pending && row.entry_price !== null) {
    const when = row.last_price_source === "intraday_check" && row.last_price_time ? `at ${fmtLocal(row.last_price_time, ctx.market, ctx.localTime)}` : row.last_price_date ? `at the close of ${fmtDate(row.last_price_date, false)}` : "";
    parts.push(`So far: bought ${price(ctx.currency, row.entry_price)} at the open of ${fmtDate(row.entry_date)}, now ${price(ctx.currency, row.exit_or_last_price)} ${when}.`.replace(" .", "."));
  } else parts.push(`Bought at the open of ${fmtDate(row.entry_date)}; no price stored or checked yet.`);
  const cause = openCause(row.why, ctx.benchmark);
  if (cause) parts.push(`Why: ${cause}`);
  if (row.reason) parts.push(`In the AI trader’s words: “${row.reason}”`);
  parts.push(`Sells at the close of ${fmtDate(row.exit_date)}. Paper only.`);
  return parts.join(" ");
}

function TradeLine({ m, ctx }: { m: MergedRow; ctx: BlockCtx }) {
  const row = m.first, going = goingOf(row), flagged = m.rows.some((r) => r.check?.flagged);
  const names = m.rows.map((r) => ctx.strategyName(r.strategy_id)).join(" + ");
  const side = row.family as Side;
  const cause = going === "against" ? openCause(row.why, ctx.benchmark) : null;
  const note = row.why?.note ?? null;
  const bands = rowBands(row);
  const story = lifecyclePath(ctx.market as never, row.ticker, row.entry_date ?? "") + storyHash(row);
  const extra = m.rows.length > 1 ? ` The same trade for: ${names}; the results are added.` : "";
  return (
    <tbody className={`pp-row ${going}${flagged ? " flag" : ""}`}>
      <tr>
        <td>
          <Link className="tk" href={companyPath(ctx.market as never, row.ticker)}>{row.ticker}</Link>
          <small className="nm">{ctx.companyName(row.ticker)}</small>
          <span className="pp-only-s"><SideTag side={side} short />{m.rows.length > 1 ? <span className="pp-x" data-tip={`${m.rows.length} paper trades, one per strategy, added together`}>×{m.rows.length}</span> : null}</span>
        </td>
        <td className="pp-hide-s">
          <SideTag side={side} short />{m.rows.length > 1 ? <span className="pp-x" data-tip={`${m.rows.length} paper trades, one per strategy, added together`}>×{m.rows.length}</span> : null}
          <small className="nm">{names}</small>
        </td>
        <td className="pp-hide-s">{bands ? <RangeBar currency={ctx.currency} bands={bands} last={row.price_pending ? null : row.exit_or_last_price} entry={row.price_pending ? null : row.entry_price} /> : <span className="muted">—</span>}</td>
        <td className="num">
          {flagged ? <span className="bad" data-tip="At the latest intraday check this trade was more than a usual move away from its prediction (flagged)."><Icon name="warning" /></span> : null}
          {going === "pending" ? <span className="muted">no price yet</span> : <Money currency={ctx.currency} value={m.total} decimals={ctx.decimals} pct={row.unrealised_pct} />}
        </td>
        <td className="pp-i"><InfoTip tip={popover(row, ctx) + extra} label={`Why: ${row.ticker}`} /></td>
      </tr>
      {going === "against" ? (
        <tr className="pp-why">
          <td colSpan={5}>
            <div className="pp-why-line">
              <span><Icon name="help" />{cause ?? "No intraday check of this trade yet: the reason shows after the next check."}</span>
              {note ? <button type="button" className="pp-note" data-tip={`AI note at the latest check: ${note}`}><Icon name="description" />AI note</button> : null}
              <Link className="pp-story" href={story}>Full story<Icon name="chevron_right" /></Link>
            </div>
          </td>
        </tr>
      ) : null}
    </tbody>
  );
}

function Group({ rows, going, ctx }: { rows: StoryRow[]; going: Going; ctx: BlockCtx }) {
  const [all, setAll] = useState(false);
  const spec = GROUPS.find((g) => g.going === going)!;
  if (!rows.length) return null;
  const lines = ordered(mergeRows(rows), going);
  const shown = all ? lines : lines.slice(0, SHOWN);
  const sum = rows.reduce((s, r) => s + (r.unrealised_pnl ?? 0), 0);
  return (
    <>
      <tbody>
        <tr className={`pp-gh ${going}`}>
          <td colSpan={5}>
            <span className={`pp-ghl ${spec.tone}`}><Icon name={spec.icon} />{spec.title}<span className="pp-cnt">{rows.length}</span></span>
            {going === "pending" ? null : <span className="pp-ghr"><Money currency={ctx.currency} value={Math.round(sum * 100) / 100} decimals={ctx.decimals} /></span>}
          </td>
        </tr>
      </tbody>
      {shown.map((m) => <TradeLine key={m.key} m={m} ctx={ctx} />)}
      {lines.length > SHOWN ? (
        <tbody>
          <tr className="pp-more">
            <td colSpan={5}>
              <button className="md-btn text small" type="button" aria-expanded={all} onClick={() => setAll(!all)}>
                {all ? "Show fewer" : `Show ${lines.length - SHOWN} more`}<Icon name="expand_more" style={all ? { transform: "rotate(180deg)" } : undefined} />
              </button>
            </td>
          </tr>
        </tbody>
      ) : null}
    </>
  );
}

/** The sides compared within a hold: count, win/lose bar, counts and result so far; a side without trades says why. */
function SideStrip({ splits, sides, ctx }: { splits: Map<Side, OpenSplit>; sides: readonly Side[]; ctx: BlockCtx }) {
  return (
    <div className="pp-strip" style={{ ["--n" as string]: sides.length }}>
      {sides.map((side) => {
        const s = splits.get(side);
        if (!s || !s.open) {
          const why = side === "rule" && ruleStayedOut(ctx.rule) ? ruleNoneWords(ctx.rule) : null;
          return (
            <div key={side} className="pp-ss none">
              <SideTag side={side} short />
              <div className="muted pp-ssv">{why ? <>{why.line} <InfoTip tip={why.tip} label="Why no rule trades" /></> : "No trade in this hold"}</div>
            </div>
          );
        }
        return (
          <div key={side} className="pp-ss">
            <div className="pp-ssh"><SideTag side={side} short /><span className="muted"><b>{s.open}</b> open</span></div>
            <WinLoseBar win={s.going_with} lose={s.going_against} pending={s.pending} label={`${SIDE_SHORT[side]}: ${s.going_with} going as predicted, ${s.going_against} going against`} />
            <div className="pp-ssc">
              <WinLoseCounts win={s.going_with} lose={s.going_against} pending={s.pending} words={false} />
              <Money currency={ctx.currency} value={s.unrealised_pnl} decimals={ctx.decimals} />
            </div>
            {s.profit !== null || s.loss !== null ? (
              <div className="pp-pl"><span>Profit so far <Money currency={ctx.currency} value={s.profit} decimals={ctx.decimals} /></span><span>Loss so far <Money currency={ctx.currency} value={s.loss} decimals={ctx.decimals} /></span></div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function Header({ k, summary, rows, ctx }: { k: number; summary: OpenSplit & { exit_dates: string[] }; rows: StoryRow[]; ctx: BlockCtx }) {
  const progress = rows.find((r) => r.exit_date === summary.exit_dates[0])?.sessions ?? null;
  return (
    <header className="pp-bh">
      <div className="pp-bt">
        <h3>{holdLabel(k)} <InfoTip tip={holdTip(k)} label={`About the ${holdLabel(k)}`} /></h3>
        <div className="pp-bs">
          <Icon name="event" />
          {`Sells at the close of ${summary.exit_dates.map((d) => fmtDate(d)).join(" · ") || "—"}`}
          {progress ? <HoldProgress held={progress.held} total={progress.total} tip={`${progress.held} of the ${progress.total} sessions from the buy to the sale have started.`} /> : null}
        </div>
      </div>
      <div className="pp-bn">
        <Money currency={ctx.currency} value={summary.unrealised_pnl} decimals={ctx.decimals} big />
        <div className="pp-bl">{`so far on ${summary.open} open, before fees`}</div>
      </div>
    </header>
  );
}

function Lists({ rows, ctx }: { rows: StoryRow[]; ctx: BlockCtx }) {
  return (
    <div className="md-table-wrap">
      <table className="md-table pp-trades">
        <thead>
          <tr>
            <th>Company</th>
            <th className="pp-hide-s">Who</th>
            <th className="pp-hide-s" data-tip="Where the price sits in the trade’s own expected range at the sale: the bands are the 50% and 80% ranges, the dotted line the buy price, the dark line now.">Price vs expected</th>
            <th className="num">So far</th>
            <th><span className="mb-sr">Details</span></th>
          </tr>
        </thead>
        {GROUPS.map((g) => <Group key={g.going} going={g.going} rows={rows.filter((r) => goingOf(r) === g.going)} ctx={ctx} />)}
      </table>
    </div>
  );
}

/** A hold of every strategy's trades: the index gives the header and the sides at once; the list loads on its own. */
export function AccuracyHold({ hold, res, ctx }: { hold: OpenHold; res: ApiState<{ trades: StoryRow[] }>; ctx: BlockCtx }) {
  const rows = res.state === "ready" ? res.envelope.payload.trades : [];
  const splits = new Map(hold.by_family.map((f) => [f.family, f] as const));
  return (
    <article className="pp-card pp-hold" aria-label={holdLabel(hold.horizon_days)}>
      <Header k={hold.horizon_days} summary={hold} rows={rows} ctx={ctx} />
      <SideStrip splits={splits} sides={["rule", "baseline", "ai"]} ctx={ctx} />
      {res.state === "loading" ? <LoadingState label={`Loading the ${holdLabel(hold.horizon_days)} trades`} cards={1} />
        : res.state === "error" ? <ErrorState problem={res.problem} onRetry={res.reload} />
          : rows.length ? <Lists rows={rows} ctx={ctx} /> : <Quiet>No open trade in this hold any more.</Quiet>}
    </article>
  );
}

/** A hold of the Rule vs AI picks, from the rows on the page itself (Rule and AI sides only: benchmarks never pick). */
export function PickHold({ k, rows, ctx, split }: { k: number; rows: StoryRow[]; ctx: BlockCtx; split: (rows: StoryRow[]) => OpenSplit }) {
  const summary = { ...split(rows), exit_dates: [...new Set(rows.map((r) => r.exit_date).filter((d): d is string => !!d))].sort() };
  const splits = new Map((["rule", "ai"] as const).map((f) => [f, split(rows.filter((r) => r.family === f))] as const));
  return (
    <article className="pp-card pp-hold" aria-label={`Rule vs AI picks, ${holdLabel(k)}`}>
      <Header k={k} summary={summary} rows={rows} ctx={ctx} />
      <SideStrip splits={splits} sides={["rule", "ai"]} ctx={ctx} />
      <Lists rows={rows} ctx={ctx} />
    </article>
  );
}
