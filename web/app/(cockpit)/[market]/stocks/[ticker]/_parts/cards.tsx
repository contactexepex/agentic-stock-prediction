"use client";
// The company page's narrative cards (design/mockups/03-company reasons, news, results, events, lifecycle): the EOD
// analyst's notes (F6.1), news with its verification status (DESIGN 3b), the latest results digest (WS6), what is
// coming in the next 60 days, and the company's watchlist settings (F8) with the call history by day.
import Link from "next/link";
import type { ReactNode } from "react";
import { strategyOf } from "../../../../../../components/blocks/records.tsx";
import { Card, CardHead, Delta, GoLink, Label, Quiet, SentimentSquare, StatusBadge } from "../../../../../../components/ui/primitives.tsx";
import { CURRENCY_SYMBOL, LOCALE } from "../../../../../../lib/ui/constants.ts";
import { DOW, fmtDate, fmtDateYear, money, signed } from "../../../../../../lib/ui/format.ts";
import { lifecyclePath, pagePath } from "../../../../../../lib/ui/routes.ts";
import { companyEventEffect, horizonOfId, nextCompanyEvent } from "../../../../../../lib/company-pages/company-logic.ts";
import type { AiReason, CompanyPayload, NewsItem } from "../../../../../../lib/company-pages/types.ts";
import type { PageCtx } from "./context.ts";
import { eventWords, NOTE_KIND, plural } from "./labels.ts";

/** The EOD analyst's notes; `news` names the cited news ids in their tooltips. */
export function ReasonsCard({ reasons, news, ctx }: { reasons: AiReason[]; news: NewsItem[]; ctx: PageCtx }) {
  const titles = new Map(news.map((n) => [n.id, n.title]));
  return (
    <Card label="Why it moved, in words">
      <CardHead
        title="In words: the end-of-day analyst"
        help="After the close, the EOD analyst writes at most 60 words for every head-to-head trade settled that day and for the day’s 5 biggest wins and misses (F6.1). Each note rests on the trade’s automatic reason split and cites ids; a deterministic gate checks it. It explains, it never predicts."
      />
      {reasons.length ? (
        <ul className="rl">
          {reasons.map((r) => {
            const [words, tone] = NOTE_KIND[r.kind] ?? [r.kind, "neutral"];
            const h = r.trade_id ? horizonOfId(r.trade_id) : null;
            return (
              <li key={r.id}>
                <div className="rh">
                  <Label tone={tone}>{words}{r.rank ? ` #${r.rank}` : ""}</Label>
                  {r.strategy_id ? <b>{strategyOf(ctx.strategies, r.strategy_id).name}</b> : null}
                  {h ? <span className="h-lab">N+{h}</span> : null}
                  <span>· settled {fmtDate(r.session_date)}</span>
                </div>
                <div>{r.text}</div>
                <div className="ids" aria-label="Cited ids">
                  {r.cited_ids.map((id) => (
                    <code key={id} tabIndex={0} data-tip={titles.has(id) ? `News item ${id}: ${titles.get(id)}` : `Cited id ${id} (a trade or news record).`}>{id}</code>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <Quiet>No analyst note on this company yet: notes are written for settled head-to-head trades and the day’s biggest wins and misses.</Quiet>
      )}
    </Card>
  );
}

export function NewsCard({ p, ctx }: { p: CompanyPayload; ctx: PageCtx }) {
  return (
    <Card label="News">
      <CardHead
        title="News with its status"
        help="Stories about this company first seen in the last 30 days (the newest 50), newest first, with their verification status (DESIGN 3b): confirmed by a filing, corroborated by independent outlets, single source, unverified, rumour, promotional or contradicted. Only confirmed or corroborated items can be the main evidence of a call. The arrow is the news analyst’s sentiment."
        end={`${p.news.length} by the cut-off`}
      />
      {p.news.length ? (
        <ul className="nl">
          {p.news.map((n) => {
            const e = n.enrichment ?? {}, origins = n.independent_origins ?? 0, filings = n.primary_ids?.length ?? 0;
            const history = n.headline_history ?? [];
            const meta = [
              n.source ?? "source not stored",
              e.materiality ? `${e.materiality} materiality` : "not scored",
              e.event_type,
              `${origins} independent ${plural(origins, "origin")}${filings ? `, ${filings} ${plural(filings, "filing")}` : ""}`,
              `published ${ctx.at(n.published_at, true)}, first seen ${ctx.at(n.first_seen_at, true)}`,
              e.priced_in ? "priced in" : null,
            ].filter(Boolean).join(" · ");
            return (
              <li key={n.id}>
                <SentimentSquare value={e.sentiment ?? null} />
                <div className="hd">
                  {n.url ? <a className="t" href={n.url} rel="noopener noreferrer" target="_blank">{n.title}</a> : <span className="t">{n.title}</span>}
                  {n.status ? <StatusBadge status={n.status} /> : <span className="md-badge unverified">status not computed</span>}
                  <small>{meta}</small>
                  {history.length ? (
                    <small tabIndex={0} data-tip={history.map((h) => `“${h.title}” seen ${ctx.at(h.seen_at, true)}`).join(" · ")}>
                      {history.length} earlier {plural(history.length, "headline")} at this link
                    </small>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <Quiet>No story about this company first seen in the last 30 days.</Quiet>
      )}
    </Card>
  );
}

function bigMoney(currency: string, v: number | null | undefined): string {
  if (v == null) return "—";
  const sym = CURRENCY_SYMBOL[currency] ?? "", loc = LOCALE[currency] ?? "en-US";
  if (Math.abs(v) >= 1e9) return `${sym}${(v / 1e9).toLocaleString(loc, { maximumFractionDigits: 1 })} bn`;
  if (Math.abs(v) >= 1e6) return `${sym}${(v / 1e6).toLocaleString(loc, { maximumFractionDigits: 1 })} mn`;
  return money(currency, v, 2);
}

function NumberTile({ label, value, yoy, tip }: { label: string; value: string; yoy: number | null | undefined; tip: string }) {
  return (
    <div className="n" data-tip={tip} tabIndex={0}>
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {yoy != null ? <div className="d"><Delta value={yoy} /><span className="muted"> vs a year ago</span></div> : null}
    </div>
  );
}

export function ResultsCard({ p, ctx }: { p: CompanyPayload; ctx: PageCtx }) {
  const d = p.results[0];
  const head = (end?: ReactNode) => (
    <CardHead
      title="Latest results"
      help="The company’s latest quarterly results as reported at the release (never later restatements), with the consensus collected before the release (context only), the stock’s reaction against the market, and at most 5 quoted bullets from the filing text (WS6). India filings have numbers only until a PDF reader is added."
      end={end}
    />
  );
  if (!d) {
    const next = nextCompanyEvent(p.events, p.company.ticker, "earnings");
    return <Card label="Results">{head()}<Quiet>No results digest stored for this company yet.{next ? ` Next results ${fmtDateYear(next.date)}.` : ""}</Quiet></Card>;
  }
  const N = d.numbers, cur = d.currency ?? ctx.currency;
  const margin = N.net_margin_pct;
  return (
    <Card label="Results">
      {head(`${d.fiscal_label ?? "latest period"} · released ${fmtDate(d.release_date)}${d.release_timing ? ` ${d.release_timing.replace("_", " ")}` : ""}`)}
      <div className="nums">
        <NumberTile label="Revenue" value={bigMoney(cur, N.revenue)} yoy={N.revenue_yoy_pct} tip={`Revenue ${bigMoney(cur, N.revenue)} for the period to ${fmtDateYear(d.period_end)} (${d.basis ?? "basis not stored"}).`} />
        <NumberTile label="Net profit" value={bigMoney(cur, N.net_profit)} yoy={N.net_profit_yoy_pct} tip={`Net profit ${bigMoney(cur, N.net_profit)}; margin ${margin != null ? margin.toFixed(1) + "%" : "—"}.`} />
        <NumberTile label="EPS (diluted)" value={N.eps_diluted != null ? money(cur, N.eps_diluted, 2) : "—"} yoy={N.eps_yoy_pct} tip="Earnings per share, diluted, as reported." />
      </div>
      <div className="rline">
        {margin != null ? <span>net margin <b>{margin.toFixed(1)}%</b></span> : null}
        {N.revenue_qoq_pct != null ? <span>revenue vs last quarter <b>{signed(N.revenue_qoq_pct)}</b></span> : null}
        {d.consensus && d.consensus.eps_estimate != null ? (
          <span tabIndex={0} data-tip="Yahoo’s consensus EPS collected before the release; context only, no call is scored on it.">
            consensus EPS <b>{money(cur, d.consensus.eps_estimate, 2)}</b> → reported <b>{money(cur, d.consensus.eps_reported, 2)}</b> (<Delta value={d.consensus.surprise_pct} /> surprise)
          </span>
        ) : (
          <span>consensus: <b>none collected before the release</b></span>
        )}
        {d.reaction ? (
          <span tabIndex={0} data-tip={`Close of ${fmtDate(d.reaction.from, false)} to close of ${fmtDate(d.reaction.to, false)}: stock ${signed(d.reaction.stock_pct)}, benchmark ${signed(d.reaction.benchmark_pct)}, beyond the market ${signed(d.reaction.excess_pct)}.`}>
            reaction <b>{signed(d.reaction.stock_pct)}</b> stock, <b>{signed(d.reaction.excess_pct)}</b> beyond the market
          </span>
        ) : null}
      </div>
      {d.bullets?.length ? (
        <ul className="bul">{d.bullets.map((b, i) => <li key={i}>{b.text || b.quote}</li>)}</ul>
      ) : (
        <div className="note">{d.status === "text_unavailable" ? "Numbers only: the filing text could not be read (no PDF reader for NSE attachments yet), so there are no quoted bullets." : `No quoted bullets (status ${d.status.replace(/_/g, " ")}).`}</div>
      )}
      <div className="note">
        Sources:{" "}
        {(d.sources ?? []).map((s, i) => (
          <span key={s.id}>
            {i ? ", " : ""}
            {s.url ? <a href={s.url} rel="noopener noreferrer" target="_blank">{`${s.kind.replace(/_/g, " ")} ${s.doc ?? ""}`.trim()}</a> : `${s.kind.replace(/_/g, " ")} ${s.doc ?? ""}`.trim()}
          </span>
        ))}
        {` · numbers as of ${ctx.at(d.numbers_as_of, true)}`}
      </div>
    </Card>
  );
}

export function EventsCard({ p }: { p: CompanyPayload }) {
  const ticker = p.company.ticker;
  return (
    <Card label="Coming events">
      <CardHead
        title="Coming up"
        help="What is scheduled from the session being predicted to 60 days after it, as known at the as-of time: this company’s results (they widen its ranges; no new call within a day of them) and ex-dividend dates (the ranges are centred lower by the dividend), the market’s major events (they raise the regime to EVENT_HEAVY two days before and widen every range whose window contains them) and closed days."
        end={`${p.events.length} in 60 days`}
      />
      {p.events.length ? (
        <ul className="ev">
          {p.events.map((e, i) => {
            const mine = e.ticker === ticker, effect = mine ? companyEventEffect(e.type) : null;
            const detail = [
              eventWords(e.type) + (e.timing ? ` · ${e.timing.replace("_", " ")}` : mine && e.type === "earnings" ? " · timing not known yet" : ""),
              e.reaction_sessions?.length ? `reaction in ${e.reaction_sessions.map((d) => fmtDate(d, false)).join(" and ")}` : null,
              e.release ?? null,
            ].filter(Boolean).join(" · ");
            return (
              <li key={`${e.date}-${e.type}-${e.ticker ?? ""}-${i}`} className={mine ? "me" : undefined}>
                <div className="d">{fmtDate(e.date, false)}<small>{DOW[new Date(e.date + "T00:00:00Z").getUTCDay()]}</small></div>
                <div className="t">
                  <span>
                    {e.name}
                    {e.provisional ? <span style={{ marginLeft: 6 }}><Label tone="neutral" tip="The date is not confirmed yet.">provisional</Label></span> : null}
                    {effect ? <span style={{ marginLeft: 6 }}><Label tone={effect.tone} tip={effect.tip}>{effect.label}</Label></span>
                      : e.major ? <span style={{ marginLeft: 6 }}><Label tone="neutral" tip="A major market event: the regime becomes EVENT_HEAVY within 2 days before it and every range whose window contains it is widened.">major</Label></span> : null}
                  </span>
                  <small>{detail}</small>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <Quiet>Nothing scheduled.</Quiet>
      )}
    </Card>
  );
}

export function WatchlistCard({ p, ctx, onChangeAmount, pending, historyDates }: {
  p: CompanyPayload; ctx: PageCtx; onChangeAmount: (() => void) | null; pending: ReactNode; historyDates: string[];
}) {
  const co = p.company, first = p.lifecycle[0];
  const ids = [co.yahoo ? `Yahoo ${co.yahoo}` : null, co.nse_symbol ? `NSE ${co.nse_symbol}` : null, co.cik ? `SEC CIK ${co.cik}` : null].filter(Boolean).join(" · ");
  const history = p.lifecycle.slice().reverse().map((e) => `${fmtDate(e.recorded_at, false)}: ${e.event.replace("_", " ")}${e.amount != null ? ` to ${money(ctx.currency, e.amount)}` : ""}${e.reason ? ` (“${e.reason}”)` : ""} · ${e.channel}`);
  return (
    <Card label="Watchlist settings">
      <CardHead
        title="On the watchlist"
        help="The company’s lifecycle (F8): when it was added, its state, the money per paper trade and every change, each an append-only event with who asked and from which channel. Changing the amount or the state records a request; the next run imports it. Nothing here places an order."
        end={<GoLink href={pagePath(ctx.market, "companies")}>All companies</GoLink>}
      />
      <div className="lc">
        <div className="row">
          <span className="l">State</span>
          {co.state === "active" ? <Label tone="success" icon="check">active</Label> : <Label tone="neutral">inactive</Label>}
          <span className="muted">since {fmtDateYear(co.state_since)}</span>
        </div>
        <div className="row">
          <span className="l">Added</span>
          <span>{fmtDateYear(co.added_at)}</span>
          <span className="muted">{first ? `· ${first.channel === "seed" ? "seeded from the config" : `by ${first.requested_by ?? "unknown"} via ${first.channel}`}` : ""}</span>
        </div>
        <div className="row">
          <span className="l">Per paper trade</span>
          <b>{money(ctx.currency, co.amount)}</b>
          <span className="muted">{co.amount_overridden ? "· set for this company" : "· the market’s default"}</span>
          {onChangeAmount ? <button className="md-btn text small" type="button" onClick={onChangeAmount}>Change</button> : null}
        </div>
        <div className="row">
          <span className="l">Identifiers</span>
          <span className="muted">{ids || "none stored"}</span>
        </div>
        <div className="hist">History: {history.length ? history.join(" · ") : "no event recorded by the cut-off"}.</div>
        {historyDates.length ? (
          <div className="row">
            <span className="l">Calls by day</span>
            <span className="days" data-tip="Each session’s predictions on this company and what became of them: made, checked during the session, settled, explained (the last 30 sessions).">
              {historyDates.map((d, i) => (
                <span key={d}>{i ? " · " : ""}<Link href={lifecyclePath(ctx.market, co.ticker, d)}>{fmtDate(d, false)}</Link></span>
              ))}
            </span>
          </div>
        ) : null}
      </div>
      {pending}
    </Card>
  );
}
