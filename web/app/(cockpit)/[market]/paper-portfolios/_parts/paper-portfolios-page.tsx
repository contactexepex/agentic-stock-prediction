"use client";
// Page 07, the Paper portfolio (B16's page, redesigned by UX3: docs/ux/paper_portfolio_redesign.md v3, approved by the
// owner on 2026-10-12). It answers a retail reader's questions in order: am I up or down (the hero), which bets are
// working (the three kinds of strategy side by side, the Rule vs AI picks, your own), why (finished trades and every
// open hold, losing trades first with a one-line reason and a "Full story" link), and what the system learns. Reads
// GET /api/v1/markets/{market}/portfolios (B13's rm.portfolio) and, per hold and per sell day, GET .../portfolios/open/{k}
// and .../portfolios/finished/{date}. Every view stays apart, never added together. A paper trade is a record, never an
// order; nothing here is advice.
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageFooter, PageHead, SignalsBand } from "../../../../../components/blocks/page-head.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Label, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { ErrorState, LoadingState, PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import { PAPER_LABEL } from "../../../../../lib/ui/constants.ts";
import { fmtDate, fmtLocal, moneyDecimals } from "../../../../../lib/ui/format.ts";
import { companyPath, lifecyclePath } from "../../../../../lib/ui/routes.ts";
import type { GoLive, PageBase } from "../../../../../lib/ui/types.ts";
import { useApi, usePage } from "../../../../../lib/ui/use-api.ts";
import type { CostView } from "../../../../../lib/strategy-pages/scoreboard.ts";
import { summaryRow, type AllTrades } from "../../../../../lib/strategy-pages/all-trades.ts";
import type { PaperPortfoliosPayload } from "../../../../../lib/strategy-pages/paper-portfolios.ts";
import {
  byHold, mergeRows, PICK_SIDES, ruleNoneWords, ruleStayedOut, settledCause, SIDE_ABOUT, SIDES, splitOf, storyHash,
  type FinishedPage, type FinishedSession, type HoldPage, type Learning, type OpenHold, type Side, type StoryRow,
} from "../../../../../lib/strategy-pages/portfolio-v3.ts";
import { CostSwitch } from "../../_b16/parts.tsx";
import { H2hCard } from "./h2h-card.tsx";
import { AccuracyHold, PickHold, type BlockCtx } from "./hold-block.tsx";
import { OwnerCard, type Sent } from "./owner-card.tsx";
import { InfoTip, Money, SideTag, WinLoseBar, WinLoseCounts } from "./story-ui.tsx";
import "./paper-portfolios.css";

type V3Trades = AllTrades & { open_holds?: OpenHold[]; finished_sessions?: FinishedSession[]; learning?: Learning };
type Payload = PageBase & PaperPortfoliosPayload & { go_live: GoLive | null; all_trades: V3Trades | null };

export function PaperPortfoliosPage({ market }: { market: Market }) {
  const res = usePage<Payload>(market, "portfolios");
  return (
    <div className="p-portfolios">
      <PageState result={res}>{(p) => <Portfolio key={p.market} p={p} />}</PageState>
    </div>
  );
}

function blockCtx(p: Payload): BlockCtx {
  const names = new Map(p.companies.map((c) => [c.ticker, c.name]));
  return {
    market: p.market,
    currency: p.currency,
    decimals: moneyDecimals(p.currency),
    localTime: p.status.session.local_time,
    benchmark: p.status.benchmark?.name ?? "the market",
    strategyName: (id) => (id ? p.strategies[id]?.name ?? id : "—"),
    companyName: (t) => names.get(t) ?? t,
    rule: p.all_trades?.learning?.rule_today ?? null,
  };
}

function Portfolio({ p }: { p: Payload }) {
  const [sent, setSent] = useState<Sent[]>([]);
  const ctx = useMemo(() => blockCtx(p), [p]);
  const label = p.status.paper_label || PAPER_LABEL;
  const all = p.all_trades;
  const v3 = !!all && Array.isArray(all.open_holds);
  return (
    <>
      <PageHead page={p} title="Paper portfolio" subtitle={`${p.name} · how the paper trades are doing, why, and what the system learns · research only, nothing is an order or advice`} />
      <SignalsBand page={p} goLive={p.go_live} strategies={Object.keys(p.strategies).length} />
      {!all || !v3 ? (
        <section className="pp-card" aria-label="Paper trades"><Quiet>{`This page fills after the next data sync of ${p.name}: the read model in use was built before this page’s new layout.`}</Quiet></section>
      ) : (
        <>
          <Hero p={p} all={all} ctx={ctx} />
          <h2 className="pp-q">Which bets are working?<small>The three kinds of strategy side by side. Never added together with the daily picks or your own trades.</small></h2>
          <div className="pp-sides">{SIDES.map((s) => <SideCard key={s} side={s} all={all} ctx={ctx} />)}</div>
          <div className="pp-duo">
            <PicksCard p={p} all={all} ctx={ctx} />
            <OwnSummary p={p} all={all} ctx={ctx} />
          </div>
          <h2 className="pp-q">Finished trades<small>Did each one work, and why.</small></h2>
          <FinishedCard p={p} all={all} ctx={ctx} />
          <h2 className="pp-q">Open trades, by how long they’re held<small>Losing trades first, each with a one-line reason. The sides compared in every block.</small></h2>
          {all.open_holds!.length ? all.open_holds!.map((h) => <HoldLoader key={h.horizon_days} hold={h} ctx={ctx} />)
            : <section className="pp-card"><EmptyState icon="event" title="No open paper trade right now" text={nextBuyWords(p)} /></section>}
          <h2 className="pp-q">Open daily picks: Rule vs AI<small>The same predictions, picked once a day per company by the strongest rule strategy and the strongest AI trader.</small></h2>
          <PickHolds p={p} all={all} ctx={ctx} />
          <h2 className="pp-q">What the system learns<small>Honestly: only part of it learns by itself.</small></h2>
          <LearningCards p={p} all={all} />
        </>
      )}
      <h2 className="pp-q" id="own">Your own paper trades</h2>
      <OwnerCard p={p} sent={sent} onSent={(s) => setSent((list) => [...list, s])} />
      <div className="pp-legend" aria-label="Legend">
        <SideTag side="rule" /><SideTag side="baseline" /><SideTag side="ai" />
        <span><Icon name="check" className="ms ok" /> going as predicted / won</span>
        <span><Icon name="close" className="ms bad" /> going against / lost</span>
        <span><Icon name="warning" className="ms bad" /> flagged at the latest check</span>
        <PaperTag label={label} />
      </div>
      <PageFooter page={p} endpoint="portfolios" />
    </>
  );
}

function nextBuyWords(p: Payload): string {
  const open = p.status.session.session_open_utc;
  return open ? `New paper trades are bought at the open of the next session, ${fmtLocal(open, p.market, p.status.session.local_time, true)}, after the morning run.` : "New paper trades are bought at the open of the next session, after the morning run.";
}

/** When the first results come: the earliest planned sale, and the after-close run's time when it is that day. */
function firstResultsWords(p: Payload, all: V3Trades): string | null {
  const exits = (all.open_holds ?? []).flatMap((h) => h.exit_dates).sort();
  if (!exits.length) return null;
  const next = p.status.runs?.post_close?.next_at ?? null;
  const lt = p.status.session.local_time;
  const sameDay = next && fmtLocal(next, p.market, lt, true).startsWith(fmtDate(exits[0], false));
  return `first results ${fmtDate(exits[0])}${sameDay ? `, ~${fmtLocal(next, p.market, lt)}` : ", after the after-close run"}`;
}

function Hero({ p, all, ctx }: { p: Payload; all: V3Trades; ctx: BlockCtx }) {
  const r = summaryRow(all, "all", "all", "to_date");
  const holds = all.open_holds ?? [];
  const win = holds.reduce((s, h) => s + h.going_with, 0), lose = holds.reduce((s, h) => s + h.going_against, 0), pend = holds.reduce((s, h) => s + h.pending, 0);
  const finished = r?.closed ?? 0;
  const first = finishedSoonWords(p, all, finished);
  return (
    <section className="pp-card pp-hero" aria-label="Am I up or down?">
      <div>
        <div className="pp-hl">Every strategy’s paper trades{finished ? "" : ", open now"} <InfoTip tip="Each strategy’s every qualifying prediction is one paper trade of the company’s amount, bought at the open and sold at the close k sessions later. Open trades are before fees; finished ones after market fees." label="About this number" /></div>
        <div className="pp-hv">
          {finished ? <Money currency={ctx.currency} value={r?.net_pnl_market ?? null} decimals={ctx.decimals} big /> : <Money currency={ctx.currency} value={r?.unrealised_pnl ?? null} decimals={ctx.decimals} big />}
        </div>
        <div className="pp-hs">{finished ? `after market fees on ${finished} finished ${finished === 1 ? "trade" : "trades"}` : `so far on ${r?.open ?? 0} open trades, before fees`}</div>
        {finished ? <div className="pp-hs">Open trades so far <Money currency={ctx.currency} value={r?.unrealised_pnl ?? null} decimals={ctx.decimals} /> before fees</div> : null}
        {first ? <div className="pp-next"><Icon name="event" />{first}</div> : null}
      </div>
      <div>
        <div className="pp-facts">
          <div><b>{r?.open ?? 0}</b><span>open</span></div>
          <div><b>{finished}</b><span>finished</span></div>
          <div><b>{`${r?.wins ?? 0} · ${r?.losses ?? 0}`}</b><span>won · lost</span></div>
        </div>
        <WinLoseBar win={win} lose={lose} pending={pend} label={`${win} open trades going as predicted, ${lose} going against`} />
        <WinLoseCounts win={win} lose={lose} pending={pend} />
      </div>
    </section>
  );
}

function finishedSoonWords(p: Payload, all: V3Trades, finished: number): string | null {
  if (finished) return null;
  const first = firstResultsWords(p, all);
  return first ? `Nothing finished yet — ${first}` : "Nothing finished yet";
}

function SideCard({ side, all, ctx }: { side: Side; all: V3Trades; ctx: BlockCtx }) {
  const r = summaryRow(all, "all", side, "to_date");
  const splits = (all.open_holds ?? []).flatMap((h) => h.by_family.filter((f) => f.family === side));
  const open = splits.reduce((s, f) => s + f.open, 0), win = splits.reduce((s, f) => s + f.going_with, 0), lose = splits.reduce((s, f) => s + f.going_against, 0);
  const pend = splits.reduce((s, f) => s + f.pending, 0);
  const foot = (
    <div className="pp-scf"><span>Finished</span><b>{r?.closed ?? 0}</b><span>Won · lost</span><b>{`${r?.wins ?? 0} · ${r?.losses ?? 0}`}</b>
      {r?.closed ? <><span>After fees</span><Money currency={ctx.currency} value={r.net_pnl_market} decimals={ctx.decimals} /></> : null}</div>
  );
  if (!open) {
    const why = side === "rule" && ruleStayedOut(ctx.rule) ? ruleNoneWords(ctx.rule) : null;
    return (
      <section className="pp-card pp-sc none" aria-label={SIDE_ABOUT[side]}>
        <div className="pp-sch"><SideTag side={side} /><InfoTip tip={SIDE_ABOUT[side]} label="About this side" /></div>
        <div className="pp-sce"><Icon name="remove" /><div>{why ? <>{why.line} <InfoTip tip={why.tip} label="Why no rule trades" /></> : "No open trade right now."}</div></div>
        {foot}
      </section>
    );
  }
  return (
    <section className="pp-card pp-sc">
      <div className="pp-sch"><SideTag side={side} /><InfoTip tip={SIDE_ABOUT[side]} label="About this side" /></div>
      <Money currency={ctx.currency} value={r?.unrealised_pnl ?? null} decimals={ctx.decimals} big />
      <div className="pp-scl">{`so far on ${open} open trades, before fees`}</div>
      <WinLoseBar win={win} lose={lose} pending={pend} label={`${win} going as predicted, ${lose} going against`} />
      <WinLoseCounts win={win} lose={lose} pending={pend} />
      {foot}
    </section>
  );
}

function PicksCard({ p, all, ctx }: { p: Payload; all: V3Trades; ctx: BlockCtx }) {
  const [cost, setCost] = useState<CostView>("market");
  const rows = (all.trades as StoryRow[]).filter((t) => t.scope === "head_to_head" && t.state === "open");
  return (
    <section className="pp-card" aria-label="Rule vs AI: the daily picks">
      <div className="pp-cardh"><h3>Rule vs AI: the daily picks</h3><InfoTip tip="Each day the strongest rule strategy and the strongest AI trader each pick one trade per company. These come from the same predictions as the cards above, so they are counted apart, never added to them." label="About the picks" /></div>
      <div className="pp-picks">
        {PICK_SIDES.map((side) => {
          const r = summaryRow(all, "head_to_head", side, "to_date");
          const mine = rows.filter((t) => t.family === side), s = splitOf(mine);
          if (!mine.length && !(r?.closed)) {
            const why = side === "rule" && ruleStayedOut(ctx.rule) ? ruleNoneWords(ctx.rule) : null;
            return <div key={side} className="pp-ps none"><SideTag side={side} /><div className="muted pp-psn">{why ? <>No pick yet: no rule strategy cleared its bar <InfoTip tip={why.tip} label="Why no rule picks" /></> : "No open pick right now."}</div></div>;
          }
          return (
            <div key={side} className="pp-ps">
              <SideTag side={side} />
              <div className="pp-psv"><Money currency={ctx.currency} value={s.unrealised_pnl} decimals={ctx.decimals} big /></div>
              <div className="pp-scl">{`so far on ${mine.length} open picks, before fees`}</div>
              <WinLoseBar win={s.going_with} lose={s.going_against} pending={s.pending} label={`${s.going_with} going as predicted, ${s.going_against} going against`} />
              <WinLoseCounts win={s.going_with} lose={s.going_against} pending={s.pending} words={false} />
              <div className="pp-scf"><span>Finished</span><b>{r?.closed ?? 0}</b><span>Won · lost</span><b>{`${r?.wins ?? 0} · ${r?.losses ?? 0}`}</b></div>
            </div>
          );
        })}
      </div>
      <details className="pp-details">
        <summary>Scoreboard after fees, with the luck test</summary>
        <div className="pp-cost"><CostSwitch value={cost} onChange={setCost} help="Market fees: brokerage and taxes. Your fees: also your own broker’s extra charges. The test that decides whether a strategy is proven uses your fees." /></div>
        <H2hCard p={p} cost={cost} />
      </details>
    </section>
  );
}

function OwnSummary({ p, all, ctx }: { p: Payload; all: V3Trades; ctx: BlockCtx }) {
  const r = summaryRow(all, "mine", "mine", "to_date");
  const open = r?.open ?? 0, closed = r?.closed ?? 0;
  return (
    <section className="pp-card pp-own" aria-label="Your own trades">
      <div className="pp-cardh"><h3>Your own trades</h3><InfoTip tip="Your manual paper trades, after your own broker’s fees. A paper trade is a record, never an order." label="About your trades" /></div>
      {open || closed ? (
        <>
          <div className="pp-facts two"><div><b>{open}</b><span>open</span></div><div><b>{closed}</b><span>finished</span></div></div>
          {closed ? <div className="pp-scl">After your fees <Money currency={ctx.currency} value={r?.net_pnl_your ?? null} decimals={ctx.decimals} /> · won {r?.wins ?? 0}, lost {r?.losses ?? 0}</div> : null}
          {open ? <div className="pp-scl">Open so far <Money currency={ctx.currency} value={r?.unrealised_pnl ?? null} decimals={ctx.decimals} /> before fees</div> : null}
        </>
      ) : <div className="pp-ov">None yet</div>}
      <a className="md-btn tonal" href="#own"><Icon name="receipt_long" />{open || closed ? "Your positions and trades" : "Add a paper trade"}</a>
    </section>
  );
}

function EmptyState({ icon, title, text }: { icon: string; title: string; text: string }) {
  return (
    <div className="pp-empty">
      <div className="pp-ei"><Icon name={icon} /></div>
      <div><b>{title}</b><span>{text}</span></div>
    </div>
  );
}

function FinishedCard({ p, all, ctx }: { p: Payload; all: V3Trades; ctx: BlockCtx }) {
  const sessions = all.finished_sessions ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const day = sessions.find((s) => s.session_date === chosen) ?? sessions[0] ?? null;
  const res = useApi<FinishedPage>(day ? `/api/v1/markets/${p.market}/portfolios/finished/${day.session_date}` : null);
  if (!day) {
    const first = firstResultsWords(p, all);
    return (
      <section className="pp-card" aria-label="Finished trades">
        <EmptyState icon="event" title="Nothing has finished yet" text={first ? `The first sales: ${first.replace(/^first results /, "")}. Each result shows here with the reason it went the way it did.` : "Results show here after the after-close run of each sell day, each with the reason it went the way it did."} />
      </section>
    );
  }
  const rows = res.state === "ready" ? (res.envelope.payload.trades as StoryRow[]).filter((t) => t.state === "closed") : [];
  return (
    <section className="pp-card" aria-label="Finished trades">
      <div className="pp-chips" role="group" aria-label="Sold on">
        {sessions.map((s) => <button key={s.session_date} type="button" className="md-chip filter small" aria-pressed={s.session_date === day.session_date} onClick={() => setChosen(s.session_date)}>{`${fmtDate(s.session_date)} · ${s.closed}`}</button>)}
      </div>
      <div className="pp-fin-sides">
        {SIDES.map((side) => {
          const f = day.by_family.find((x) => x.family === side);
          return (
            <div key={side} className={`pp-ss${f && f.closed ? "" : " none"}`}>
              <SideTag side={side} short />
              {f && f.closed ? (
                <>
                  <WinLoseBar win={f.wins} lose={f.losses + f.flat} label={`${f.wins} won, ${f.losses} lost`} />
                  <div className="pp-ssc"><span className="pp-wlc"><span className="ok"><Icon name="check" />{f.wins} won</span><span className="bad"><Icon name="close" />{f.losses} lost</span></span><Money currency={ctx.currency} value={f.net_pnl_market} decimals={ctx.decimals} /></div>
                </>
              ) : <div className="muted pp-ssv">Nothing finished that day</div>}
            </div>
          );
        })}
      </div>
      {res.state === "loading" ? <LoadingState label="Loading the finished trades" cards={1} />
        : res.state === "error" ? <ErrorState problem={res.problem} onRetry={res.reload} />
          : rows.length ? <FinishedTable rows={rows} ctx={ctx} /> : <Quiet>{day.not_entered ? `${day.not_entered} planned trades never entered that day (no stored open price, or one share cost more than the amount); they are never counted.` : "No finished trade that day."}</Quiet>}
    </section>
  );
}

function FinishedTable({ rows, ctx }: { rows: StoryRow[]; ctx: BlockCtx }) {
  const [all, setAll] = useState(false);
  const lines = mergeRows(rows).sort((a, b) => (a.total ?? 0) - (b.total ?? 0) || a.key.localeCompare(b.key));
  const shown = all ? lines : lines.slice(0, 8);
  return (
    <div className="md-table-wrap">
      <table className="md-table pp-trades">
        <thead><tr><th>Company</th><th className="pp-hide-s">Who</th><th>Result</th><th className="num">After fees</th><th><span className="mb-sr">Details</span></th></tr></thead>
        {shown.map((m) => {
          const row = m.first, won = row.outcome === "win", lost = row.outcome === "loss";
          const cause = settledCause(row.why);
          const names = m.rows.map((r) => ctx.strategyName(r.strategy_id)).join(" + ");
          const tip = [
            `${won ? "Went as predicted" : lost ? "Went against the prediction" : "Ended level"}. Bought at the open of ${fmtDate(row.entry_date)}, sold at the close of ${fmtDate(row.exit_date)}.`,
            cause ? `Why: ${cause}` : "",
            row.why?.ai_reason ? `End-of-day AI reason: “${row.why.ai_reason}”` : "No end-of-day AI reason for this trade.",
            m.rows.length > 1 ? `The same trade for: ${names}; the results are added.` : "",
          ].filter(Boolean).join(" ");
          const story = lifecyclePath(ctx.market as never, row.ticker, row.entry_date ?? "") + storyHash(row);
          return (
            <tbody key={m.key} className={`pp-row ${won ? "with" : "against"}`}>
              <tr>
                <td><Link className="tk" href={companyPath(ctx.market as never, row.ticker)}>{row.ticker}</Link><small className="nm">{ctx.companyName(row.ticker)}</small><span className="pp-only-s"><SideTag side={row.family as Side} short /></span></td>
                <td className="pp-hide-s"><SideTag side={row.family as Side} short />{m.rows.length > 1 ? <span className="pp-x">×{m.rows.length}</span> : null}<small className="nm">{names}</small></td>
                <td>{won ? <Label tone="success" icon="check">Won</Label> : lost ? <Label tone="danger" icon="close">Lost</Label> : <Label tone="neutral">Level</Label>}</td>
                <td className="num"><Money currency={ctx.currency} value={m.total} decimals={ctx.decimals} pct={row.return_pct_market} /></td>
                <td className="pp-i"><InfoTip tip={tip} label={`Why: ${row.ticker}`} /></td>
              </tr>
              {lost ? (
                <tr className="pp-why"><td colSpan={5}><div className="pp-why-line"><span><Icon name="help" />{cause ?? "The automatic reason is not stored for this trade."}</span>{row.why?.ai_reason ? <button type="button" className="pp-note" data-tip={`End-of-day AI reason: ${row.why.ai_reason}`}><Icon name="description" />AI reason</button> : null}<Link className="pp-story" href={story}>Full story<Icon name="chevron_right" /></Link></div></td></tr>
              ) : null}
            </tbody>
          );
        })}
        {lines.length > 8 ? <tbody><tr className="pp-more"><td colSpan={5}><button className="md-btn text small" type="button" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${lines.length - 8} more`}<Icon name="expand_more" /></button></td></tr></tbody> : null}
      </table>
    </div>
  );
}

function HoldLoader({ hold, ctx }: { hold: OpenHold; ctx: BlockCtx }) {
  const res = useApi<HoldPage>(`/api/v1/markets/${ctx.market}/portfolios/open/${hold.horizon_days}`);
  return <AccuracyHold hold={hold} res={res} ctx={ctx} />;
}

function PickHolds({ p, all, ctx }: { p: Payload; all: V3Trades; ctx: BlockCtx }) {
  const holds = byHold(all.trades as StoryRow[], "head_to_head");
  if (!holds.size) return <section className="pp-card"><EmptyState icon="layers" title="No open daily pick right now" text={nextBuyWords(p)} /></section>;
  return <>{[...holds.entries()].map(([k, rows]) => <PickHold key={k} k={k} rows={rows} ctx={ctx} split={splitOf} />)}</>;
}

function LearningCards({ p, all }: { p: Payload; all: V3Trades }) {
  const l = all.learning!;
  const lt = p.status.session.local_time;
  const lessonsAt = l.lessons.newest?.written_at;
  const reviewDue = fmtLocal(l.next_review_at, p.market, lt, true);
  return (
    <>
      <div className="pp-learn">
        <section className="pp-card pp-lc">
          <h4><Icon name="history" />Lessons on finished AI forecasts</h4>
          <p>After each AI forecast settles, a reviewer writes one short lesson. The AI forecaster reads the lessons from its next morning run.</p>
          <span className="pp-pill auto"><Icon name="bolt" />Learns automatically</span>
          {l.lessons.newest ? (
            <>
              <blockquote>{`“${l.lessons.newest.lesson ?? ""}”`}</blockquote>
              <p className="pp-who">{`${l.lessons.count} ${l.lessons.count === 1 ? "lesson" : "lessons"} so far · newest on ${l.lessons.newest.ticker}${lessonsAt ? `, ${fmtLocal(lessonsAt, p.market, lt, true)}` : ""}`}</p>
            </>
          ) : <p className="pp-who">None yet: the first lesson follows the first AI forecast that settles. The other AI traders don’t read lessons.</p>}
        </section>
        <section className="pp-card pp-lc">
          <h4><Icon name="description" />End-of-day reasons</h4>
          <p>After each close, an AI analyst explains the Rule vs AI trades that finished and the day’s biggest wins and misses. They show beside those trades above.</p>
          <span className="pp-pill never"><Icon name="info" />Explains, changes nothing</span>
        </section>
        <section className="pp-card pp-lc">
          <h4><Icon name="science" />Weekly research review</h4>
          <p>Every Friday evening (New York time) a research director proposes changes. Nothing changes until the owner approves.</p>
          <span className="pp-pill appr"><Icon name="gavel" />Needs the owner’s approval</span>
          {l.review ? (
            <>
              {l.review.first_finding ? <blockquote>{`“${l.review.first_finding}”`}</blockquote> : null}
              <p className="pp-who">{`${l.review.iso_week ?? "Latest week"} · ${l.review.proposals ? `${l.review.proposals} ${l.review.proposals === 1 ? "change" : "changes"} proposed, waiting for approval` : "no change proposed"} · next review ${reviewDue}`}</p>
            </>
          ) : <p className="pp-who">{`No review yet. The next one: ${reviewDue}.`}</p>}
        </section>
      </div>
      <p className="pp-note-line"><Icon name="info" />Rule strategies and simple benchmarks never adjust themselves.</p>
    </>
  );
}
