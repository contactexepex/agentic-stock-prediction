"use client";
// "The full story" of one paper trade (UX3, docs/ux/paper_portfolio_redesign.md v3), opened from the Paper portfolio
// page's "Full story" link (`#story=<prediction id>&trade=<trade id>` on this session's lifecycle view): what was
// predicted and why, what happened step by step through the intraday checks to the settlement, what moved the price
// (the whole market, its sector, news, the company itself), and what the system learned, from B12's rm.lifecycle with
// UX3's additions (checks_attribution, deviation_notes, lessons, prediction_reasons). Research only: a paper trade is a
// record, never an order; nothing here is advice.
import { useEffect, useState } from "react";
import { RangeBar } from "../../../../../../../../components/charts/small.tsx";
import { Icon } from "../../../../../../../../components/ui/icon.tsx";
import { Label, PaperTag } from "../../../../../../../../components/ui/primitives.tsx";
import { PAPER_LABEL } from "../../../../../../../../lib/ui/constants.ts";
import { fmtDate, holdLabel, money, price } from "../../../../../../../../lib/ui/format.ts";
import { parseStoryHash, pct1, REASON_WORDS, SIDE_ONE, type Side } from "../../../../../../../../lib/strategy-pages/portfolio-v3.ts";
import type { LifecyclePayload, TradeCheck } from "../../../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "../../../_parts/context.ts";

const LESSON_READER = "ai.combined.opus.v1";

/** The hash's story ids, kept in step with the address bar. */
export function useStoryHash(): { prediction: string | null; trade: string | null } {
  const [ids, setIds] = useState<{ prediction: string | null; trade: string | null }>({ prediction: null, trade: null });
  useEffect(() => {
    const read = () => setIds(parseStoryHash(window.location.hash));
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  return ids;
}

interface Part { label: string; value: number }

function Bars({ parts, total, totalLabel }: { parts: Part[]; total: number | null; totalLabel: string }) {
  const scale = Math.max(0.1, ...parts.map((p) => Math.abs(p.value)), Math.abs(total ?? 0));
  return (
    <div className="st-attr" role="list">
      {parts.map((p) => (
        <div key={p.label} className="st-ar" role="listitem">
          <span>{p.label}</span>
          <div className="st-ab"><i className={p.value < 0 ? "neg" : "pos"} style={{ width: `${Math.round((Math.abs(p.value) / scale) * 100)}%` }} /></div>
          <b className={p.value < 0 ? "bad" : p.value > 0 ? "ok" : ""}>{pct1(p.value)}</b>
        </div>
      ))}
      {total !== null ? <div className="st-ar tot" role="listitem"><span>{totalLabel}</span><div /><b className={total < 0 ? "bad" : total > 0 ? "ok" : ""}>{pct1(total)}</b></div> : null}
    </div>
  );
}

function Step({ icon, when, title, tone = "", children }: { icon: string; when: string; title: string; tone?: string; children?: React.ReactNode }) {
  return (
    <li className={tone}>
      <span className="st-dot"><Icon name={icon} /></span>
      <div><div className="st-when">{when}</div><b>{title}</b>{children ? <div className="st-tb">{children}</div> : null}</div>
    </li>
  );
}

export function StoryCard({ day, ctx, benchmark, companyName, ids }: {
  day: LifecyclePayload; ctx: PageCtx; benchmark: string; companyName: string; ids: { prediction: string | null; trade: string | null };
}) {
  const prediction = day.predictions.find((x) => x.id === ids.prediction) ?? null;
  if (!prediction) {
    return ids.prediction ? <section className="card story-card" aria-label="The full story"><div className="quiet">This trade’s prediction is not on this session’s page any more.</div></section> : null;
  }
  const strategy = ctx.strategies[prediction.strategy_id]?.name ?? prediction.strategy_id;
  const checks: TradeCheck[] = day.trade_checks.filter((c) => c.trade_id === ids.trade).sort((a, b) => a.check_at.localeCompare(b.check_at));
  const settled = day.settled.filter((s) => s.trade_id === ids.trade).sort((a, b) => (b.settled_at ?? "").localeCompare(a.settled_at ?? ""))[0] ?? null;
  const reasons = day.reasons.filter((r) => r.trade_id === ids.trade);
  const words = (day.prediction_reasons ?? []).find((r) => r.prediction_id === prediction.id)?.reason ?? null;
  const attribution = (day.checks_attribution ?? []).filter((a) => a.session_date >= day.session_date);
  const notes = new Map((day.deviation_notes ?? []).map((n) => [n.check_at, n.text]));
  const lessonKey = prediction.strategy_id === LESSON_READER ? prediction.id.split(":").slice(1).join(":") : null;
  const lessons = lessonKey ? (day.lessons ?? []).filter((l) => l.prediction_id === lessonKey) : [];
  const last = checks[checks.length - 1] ?? null;
  const entry = settled?.entry_price ?? last?.entry_price ?? null;
  const now = settled?.exit_price ?? last?.last_price ?? null;
  const movePct = settled ? settled.return_pct : last?.ret_since_entry_pct ?? null;
  const up = prediction.direction !== "down";
  const going = movePct === null ? null : (up ? movePct > 0 : movePct < 0) ? "with" : "against";
  const bands = prediction.lo80 != null && prediction.lo50 != null && prediction.hi50 != null && prediction.hi80 != null && prediction.target_price != null
    ? { lo80: prediction.lo80, lo50: prediction.lo50, hi50: prediction.hi50, hi80: prediction.hi80, target_price: prediction.target_price } : null;
  const latest = attribution[attribution.length - 1] ?? null;
  const parts: Part[] = settled
    ? ([["Whole market", settled.market_pct], ["Its sector", settled.sector_pct], ["News", settled.news_pct], ["The company itself", settled.company_pct]] as const)
      .filter(([, v]) => v !== null).map(([label, value]) => ({ label, value: value as number }))
    : latest && latest.market_pct !== null && latest.own_pct !== null
      ? [{ label: "Whole market", value: latest.market_pull_pct ?? (latest.beta === null ? latest.market_pct : latest.market_pct * latest.beta) }, { label: `${day.ticker} on its own`, value: latest.own_pct }]
      : [];
  const exitWhen = settled?.exit_date_actual ?? prediction.exit_date;
  const bar = prediction.threshold ?? ctx.strategies[prediction.strategy_id]?.threshold ?? null;
  return (
    <section className="card story-card" aria-label="The full story" id="story">
      <div className="st-hero">
        <div>
          <div className="st-kicker">{`${day.ticker} · ${companyName} · ${SIDE_ONE[prediction.family as Side] ?? prediction.family}: ${strategy} · ${holdLabel(prediction.horizon_days)}`}</div>
          <div className={`st-big ${movePct === null ? "" : movePct < 0 ? "bad" : "ok"}`}>
            {movePct === null ? "No price yet" : settled && settled.net_pnl !== null ? money(ctx.currency, settled.net_pnl, ctx.decimals, true) : pct1(movePct)}
          </div>
          <div className="st-sub">
            {settled ? `after market fees (${movePct === null ? "—" : pct1(movePct)}), finished` : movePct === null ? "bought at the open; no price stored or checked yet" : "so far since the buy, before fees"}
            {going ? <> · {going === "with" ? <span className="ok"><Icon name="check" />going as predicted</span> : <span className="bad"><Icon name="close" />going against the prediction</span>}</> : null}
          </div>
          <div className="st-next"><Icon name="event" />{settled ? `Sold at the close of ${fmtDate(exitWhen)}` : `Sells at the close of ${fmtDate(exitWhen)}`}</div>
        </div>
        <div className="st-facts">
          <div><b>{price(ctx.currency, entry)}</b><span>{`bought, ${fmtDate(day.session_date, false)} open`}</span></div>
          <div><b>{price(ctx.currency, now)}</b><span>{settled ? "sold" : last ? `now, ${ctx.at(last.check_at)}` : "now"}</span></div>
          <div><b>{price(ctx.currency, prediction.target_price)}</b><span>middle guess at the sale</span></div>
          {bands ? <div className="st-range"><RangeBar currency={ctx.currency} bands={bands} last={now} entry={entry} /></div> : null}
        </div>
      </div>

      <h3>{going === "against" ? "Why is it going against the prediction?" : going === "with" ? "What moved it?" : "What will move it"}</h3>
      {parts.length ? (
        <>
          <Bars parts={parts} total={settled ? settled.move_pct : latest?.move_pct ?? null} totalLabel={settled ? "Total over the hold" : `Today’s move since the open`} />
          <p className="st-muted">
            {settled
              ? `${settled.reason_code && REASON_WORDS[settled.reason_code] ? `Mostly ${REASON_WORDS[settled.reason_code]}. ` : ""}The automatic reason splits the move over the whole hold into its parts.`
              : latest ? `At the latest check, ${ctx.at(latest.check_at, true)}: ${benchmark} ${pct1(latest.market_pct ?? 0)}; ${day.ticker} usually moves ${latest.beta === null ? "with" : `${latest.beta.toFixed(2)}×`} the market${latest.sector_pct !== null ? `; its sector ${pct1(latest.sector_pct)}` : ""}.` : ""}
          </p>
        </>
      ) : <p className="st-muted">No intraday check of this company since the buy yet: the split shows after the next check.</p>}

      <h3>What happened, step by step</h3>
      <ol className="st-tl">
        <Step icon="description" when={`${ctx.at(prediction.made_at, true)}`} title={`Predicted: ${up ? "a rise" : "a fall"} by the close ${prediction.horizon_days === 1 ? "1 session" : `${prediction.horizon_days} sessions`} after the buy`}>
          {prediction.prob_up != null ? <>Chance of a rise <b>{Math.round(prediction.prob_up * 100)}%</b>{bar != null ? ` (its bar: ${Math.round(bar * 100)}%)` : ""}. </> : "No forecast: this simple benchmark buys every day. "}
          {words ? <q>{words}</q> : null}
        </Step>
        <Step icon="receipt_long" when={`${fmtDate(day.session_date)}, at the open`} title={entry === null ? "Bought at the open" : `Bought at ${price(ctx.currency, entry)}`}>Paper only: the price is the session’s open.</Step>
        {attribution.map((a) => {
          const trade = checks.find((c) => c.check_at === a.check_at);
          const note = notes.get(a.check_at);
          const since = trade?.ret_since_entry_pct ?? null;
          return (
            <Step key={a.check_at} icon="sensors" when={ctx.at(a.check_at, true)} tone={since !== null && (up ? since < 0 : since > 0) ? "bad" : ""}
              title={since === null ? `Check: ${a.move_pct === null ? "—" : pct1(a.move_pct)} since the session’s open` : `Check: ${pct1(since)} since the buy`}>
              {a.market_pct !== null ? `Market ${pct1(a.market_pct)} · sector ${a.sector_pct === null ? "—" : pct1(a.sector_pct)} · on its own ${a.own_pct === null ? "—" : pct1(a.own_pct)}` : null}
              {note ? <><blockquote>{note}</blockquote><small className="st-muted">AI note, checked against the stored data</small></> : null}
            </Step>
          );
        })}
        {settled ? (
          <Step icon="gavel" when={`${fmtDate(exitWhen)}, after the close`} title={`Sold at ${price(ctx.currency, settled.exit_price)}: ${settled.net_pnl === null ? "—" : money(ctx.currency, settled.net_pnl, ctx.decimals, true)} after market fees`} tone={settled.net_pnl !== null && settled.net_pnl < 0 ? "bad" : ""}>
            {reasons.map((r) => <blockquote key={r.id}>{r.text}</blockquote>)}
          </Step>
        ) : (
          <>
            <Step icon="event" when={`Until ${fmtDate(exitWhen)}`} title="More checks, a few times a session" tone="fut">Each adds a line here.</Step>
            <Step icon="gavel" when={`${fmtDate(exitWhen)}, after the close`} title="Sells at the close and is settled" tone="fut">The result after fees, and the automatic reason: the whole market, its sector, news or the company.</Step>
          </>
        )}
      </ol>

      <h3>What the system learned</h3>
      <div className="st-learn">
        <div>
          <h4><Icon name="history" />Lesson</h4>
          {lessons.length ? lessons.map((l) => <blockquote key={l.id}>{l.lesson}</blockquote>)
            : <p className="st-muted">{prediction.strategy_id === LESSON_READER ? (settled ? "Written at the next morning run after this forecast is scored; the AI forecaster reads it from then on." : "Written after this forecast settles; the AI forecaster reads it from its next morning run.") : "This strategy doesn’t get lessons: only the AI forecaster reads them."}</p>}
          <Label tone={prediction.strategy_id === LESSON_READER ? "success" : "neutral"}>{prediction.strategy_id === LESSON_READER ? "Learns automatically" : "No lessons for this strategy"}</Label>
        </div>
        <div>
          <h4><Icon name="description" />End-of-day reason</h4>
          <p className="st-muted">{reasons.length ? "Shown in the step above." : settled ? "None: written only for the day’s Rule vs AI trades and biggest wins and misses." : `Written after it sells, ${fmtDate(exitWhen)}, if it is one of that day’s Rule vs AI trades or biggest wins or misses.`}</p>
          <Label tone="neutral">Explains, changes nothing</Label>
        </div>
        <div>
          <h4><Icon name="science" />Weekly review</h4>
          <p className="st-muted">Its result joins the weekly research review (Friday evening, New York time). Any change it proposes needs the owner’s approval. Rule strategies and simple benchmarks never adjust themselves.</p>
          <Label tone="warn">Needs the owner’s approval</Label>
        </div>
      </div>
      <p className="st-paper"><PaperTag label={PAPER_LABEL} /> A paper trade is a record, never an order. Nothing here is advice.</p>
    </section>
  );
}
