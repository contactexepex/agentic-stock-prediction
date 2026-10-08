"use client";
// Page 09, News (design/mockups/09-news/): the market movers of the window first, then every story of the window
// newest first with its verification status and a link to the outlet's article; the coming week's calendar and the
// news per company beside it. The window and its cap are the server's (rm.news); the page computes the movers, the
// filters, the pages and the day groups (lib/market-pages/news.ts). Research only: the cockpit stores headlines,
// scores and statuses, never the text.
import Link from "next/link";
import { useState } from "react";
import { PageFooter, PageHead } from "../../../../../components/blocks/page-head.tsx";
import { FilterChips, Pager } from "../../../../../components/ui/filters.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Card, CardHead, Label, SentimentSquare, StatusBadge } from "../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import {
  agoWords, CAN_CARRY, companiesWithNews, companyRail, dayGroups, filterNews, isMarketWide, isRecent, kindWord,
  localDate, missingSummaries, movers, NEWS_MOVERS_MAX, NEWS_PAGE_SIZE, NEWS_RECENT_HOURS, offsetMinutes, paginate,
  stories, type NewsFilter, type NewsItem, type RailCompany,
} from "../../../../../lib/market-pages/news.ts";
import { DOW, fmtDate, fmtLocal, MONTH } from "../../../../../lib/ui/format.ts";
import { companyPath, pagePath } from "../../../../../lib/ui/routes.ts";
import type { CompanyRecord, GoLive, PageBase } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import "./news.css";

export interface NewsWindow { days: number; from: string; to: string; max_items: number; stored_in_window: number; older_hidden: number }
export interface CalendarEvent {
  market: Market; date: string; type: string; name: string; ticker: string | null; timing: string | null;
  major: boolean; widens: "market" | "company" | null; provisional: boolean; release: string | null; source: string;
  event_id: string | null;
}
export type NewsPayload = PageBase & {
  go_live: GoLive;
  window: NewsWindow;
  news: (NewsItem & { source_domain: string | null })[];
  calendar: CalendarEvent[];
  calendar_days: number;
  companies: (CompanyRecord & RailCompany)[];
};

interface Ctx { p: NewsPayload; market: Market; lt: string | null | undefined; names: Map<string, string> }

function ItemBody({ c, n }: { c: Ctx; n: NewsItem }) {
  const mkt = isMarketWide(n);
  const kind = kindWord(n);
  const at = (iso: string | null) => fmtLocal(iso, c.market, c.lt, true);
  return (
    <div className="ni">
      <div>
        <span className={`kind${mkt ? " mkt" : ""}`} data-tip={mkt ? "A market-wide story: no single company, it moves the whole market." : `A company story (${n.tickers.join(", ")}).`}>
          <Icon name={mkt ? "public" : "apartment"} />
          {mkt ? `market · ${kind}` : kind}
        </span>
      </div>
      <h3>
        {n.url ? (
          <a href={n.url} rel="noopener noreferrer" target="_blank" data-tip={`Opens the article at ${n.source_domain ?? "the outlet"} in a new tab. Stored here: the headline, its scores and status, never the text.`}>{n.title}</a>
        ) : n.title}
      </h3>
      {n.summary ? <p className="sum">{n.summary}</p> : null}
      <div className="meta">
        <span data-tip={`Published by ${n.source ?? "the outlet"} ${at(n.published_at)}; first stored here ${at(n.first_seen_at)}.`}>
          {`${n.source ?? "Unknown outlet"} · published ${agoWords(c.p.cutoff ?? c.p.window.to, n.published_at)}`}
        </span>
        {n.status ? <StatusBadge status={n.status} /> : <Label tone="neutral" tip="Market-wide stories carry no verification status: verification is per company (DESIGN 3b).">not verified per company</Label>}
        <span data-tip="The news analyst’s materiality: how much the story can move the price.">{`${n.enrichment.materiality ?? "unscored"} materiality`}</span>
        {n.market_moving ? <Label tone="warn" icon="warning" tip="The engine’s market-moving flag: high materiality and market-wide or a results item.">market moving</Label> : null}
        {n.enrichment.geopolitical ? <Label tone="neutral" tip="The news analyst marked it geopolitical.">geopolitical</Label> : null}
        {(n.independent_origins ?? 0) > 1 ? <span data-tip="Independent vetted outlets carrying the same story (copies of one agency story count once).">{`${n.independent_origins} outlets`}</span> : null}
        {n.primary_tickers.map((t) => (
          <Link key={t} className="tk" href={companyPath(c.market, t)} data-tip={`${c.names.get(t) ?? t}: open the company page`}>{t}</Link>
        ))}
        {n.url ? (
          <a className="go" href={n.url} rel="noopener noreferrer" target="_blank">Open article<Icon name="open_in_new" /></a>
        ) : null}
      </div>
    </div>
  );
}

function MoversCard({ c }: { c: Ctx }) {
  const { p } = c;
  const list = movers(p.news, NEWS_MOVERS_MAX);
  return (
    <Card label="Market movers">
      <CardHead
        title={`Market movers · last ${p.window.days} days`}
        help={`At most ${NEWS_MOVERS_MAX} stories that can move the whole market or a watchlist company's price. First the stories the engine flags as market moving (high materiality and market-wide or a results item), then, to fill the band, market-wide stories (rates, inflation and jobs, commodities, geopolitics, an index moving sharply anywhere), the watchlist's results and anything scored high materiality, newest first within each rank. The verification status says how far a story can be trusted; the Help page explains each status.`}
        end={<span className="mb-tag paper">paper</span>}
      />
      {list.length ? (
        <div className="mv">
          {list.map((n, i) => (
            <div className="it" key={n.id}>
              <span className="rk" role="img" aria-label={`rank ${i + 1}`}>{i + 1}</span>
              <ItemBody c={c} n={n} />
            </div>
          ))}
        </div>
      ) : (
        <div className="empty">{`No market-moving story in the last ${p.window.days} days: ${stories(p.news.length)} stored in the window, none flagged, market-wide, results or high materiality.`}</div>
      )}
    </Card>
  );
}

const FEED_ID = "news-feed";

function FeedCard({ c, filter, ticker, page, onFilter, onPage }: {
  c: Ctx; filter: NewsFilter; ticker: string | null; page: number;
  onFilter: (f: NewsFilter, t: string | null) => void; onPage: (n: number) => void;
}) {
  const { p, market } = c;
  const cutoff = p.cutoff ?? p.window.to;
  const offset = offsetMinutes(c.lt);
  const last24 = p.news.filter((n) => isRecent(cutoff, n)).length;
  const withNews = companiesWithNews(p.companies, p.news);
  const noSummary = missingSummaries(p.news);
  const items = filterNews(p.news, filter, cutoff, ticker);
  const paged = paginate(items, page, NEWS_PAGE_SIZE);
  const groups = dayGroups(paged.items, items, cutoff, offset);
  const chipValue = filter === "company" ? null : filter;
  return (
    <section className="card" aria-label="All stories of the window" id={FEED_ID}>
      <CardHead
        title={`Last ${p.window.days} days`}
        help={`Every story first seen in the ${p.window.days} days before the cut-off, the latest stored first (the time shown is the outlet's publish time; the day groups follow the day the story was stored), ${NEWS_PAGE_SIZE} a page and at most ${p.window.max_items} in all (the owner's rule: a short trading window needs no older news). Older stories stay in the data; the Company page shows every stored story about a company. Filters: published in the last ${NEWS_RECENT_HOURS} hours, market-wide, the engine's market-moving flag, one company, or only stories that can carry a call (confirmed or corroborated).`}
        end={<span className="muted">{`${stories(p.news.length)} · ${last24} in the last ${NEWS_RECENT_HOURS} h`}</span>}
      />
      <div className="toolbar">
        <FilterChips<Exclude<NewsFilter, "company">>
          label="Filter the stories"
          value={chipValue}
          onChange={(f) => onFilter(f, null)}
          options={[
            { value: "all", label: "All", tip: "Every story of the window." },
            { value: "24h", label: `Last ${NEWS_RECENT_HOURS} h`, tip: `Published in the ${NEWS_RECENT_HOURS} hours before the cut-off.` },
            { value: "market", label: "Market-wide", tip: "Stories about no single company." },
            { value: "moving", label: "Market moving", tip: "The engine’s flag: high materiality and market-wide or a results item." },
            { value: "carry", label: "Can carry a call", tip: "Confirmed by a filing or corroborated by independent outlets: the only statuses that may be the main evidence of a call." },
          ]}
        />
        {withNews.length ? (
          <select aria-label="Company" value={ticker ?? ""} onChange={(e) => onFilter(e.target.value ? "company" : "all", e.target.value || null)}>
            <option value="">Company…</option>
            {withNews.map((co) => <option key={co.ticker} value={co.ticker}>{`${co.ticker} · ${co.name}`}</option>)}
          </select>
        ) : null}
      </div>
      {noSummary !== null ? (
        <p className="note" style={{ margin: "8px 0 0" }}>
          {`${noSummary} of the ${p.news.length} stories have no summary line yet (the analyst’s summaries were templated), so they show the headline alone; the article is one click away.`}
        </p>
      ) : null}
      {!items.length ? (
        <div className="empty" style={{ marginTop: 12 }}>
          {p.news.length
            ? filter === "carry"
              ? "No story in the window is confirmed by a filing or corroborated by independent outlets yet: the stored statuses so far are unverified, single source, rumour and promotional. Such stories lower a call’s confidence and never carry it."
              : "No story matches this filter in the window."
            : `No story first seen in the last ${p.window.days} days (${p.window.older_hidden} older ${p.window.older_hidden === 1 ? "story is" : "stories are"} hidden by the window; the Company page shows them).`}
        </div>
      ) : (
        <>
          <div className="feed">
            {groups.map((g) => [
              <div className="day" key={`d-${g.date}`}>
                <b>{g.today ? "Today" : fmtDate(g.date, false)}</b>{` · ${stories(g.count)}`}
              </div>,
              ...g.items.map((n) => {
                const sameDay = n.published_at && localDate(n.published_at, offset) === localDate(n.first_seen_at, offset);
                return (
                  <div className="row" key={n.id}>
                    <span className="tm" data-tip={`Published ${fmtLocal(n.published_at, market, c.lt, true)}; first stored here ${fmtLocal(n.first_seen_at, market, c.lt, true)} (the order of the feed).`}>
                      {fmtLocal(n.published_at, market, c.lt, !sameDay)}
                    </span>
                    <SentimentSquare value={n.enrichment.sentiment} />
                    <ItemBody c={c} n={n} />
                  </div>
                );
              }),
            ])}
          </div>
          <Pager
            page={paged.page}
            pages={paged.pages}
            summary={`Page ${paged.page} of ${paged.pages} · ${stories(items.length)}, ${NEWS_PAGE_SIZE} a page`}
            onPage={onPage}
          />
        </>
      )}
    </section>
  );
}

function CalendarCard({ c }: { c: Ctx }) {
  const { p, market } = c;
  return (
    <Card label="Coming up">
      <CardHead
        title={`Coming up · ${p.calendar_days} days`}
        help="Scheduled events from the session being predicted: the market’s own (policy decisions, inflation and jobs prints, expiries, holidays) and the active companies’ results and ex-dividend dates. A major market event raises the regime to EVENT_HEAVY within two days before it and widens every range whose window contains it; a company’s results widen its own ranges and block a new call within a day."
      />
      {!p.calendar.length ? (
        <div className="empty">{`Nothing scheduled in the next ${p.calendar_days} days.`}</div>
      ) : (
        <div className="cal">
          {p.calendar.map((e, i) => {
            const d = new Date(e.date.slice(0, 10) + "T00:00:00Z");
            return (
              <div className={`ev${e.major ? " major" : ""}`} key={`${e.date}-${e.type}-${e.ticker ?? ""}-${i}`}>
                <div className="d">{DOW[d.getUTCDay()]}<b>{d.getUTCDate()}</b>{MONTH[d.getUTCMonth()]}</div>
                <div>
                  <div className="nm">{e.name}</div>
                  <div className="sub">
                    {e.major ? <Label tone="warn" icon="warning" tip="Major: widens every range of this market whose window contains it (F2, major_event_factor).">major</Label> : null}
                    {e.widens === "company" ? <Label tone="neutral" tip="Widens this company’s ranges; no new call within a day of it.">widens its ranges</Label> : null}
                    {e.ticker ? <Link className="tk" href={companyPath(market, e.ticker)}>{e.ticker}</Link> : null}
                    {e.release ? <span>{`release ${e.release}`}</span> : null}
                    {e.provisional ? <Label tone="neutral">date provisional</Label> : null}
                    <span className="muted" data-tip={`Source: ${e.source}.`}>{e.type.replace(/_/g, " ")}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function CompaniesCard({ c, onCompany }: { c: Ctx; onCompany: (t: string) => void }) {
  const { p, market } = c;
  const rows = companyRail(p.companies, p.news);
  return (
    <Card label="By company">
      <CardHead
        title={`By company · ${p.window.days} days`}
        help="Each watchlist company with a story in the window: how many, the tone mix of the news analyst’s sentiment (green up, red down, grey flat), its open paper trades, and the latest headline. Click the ticker for the company page, the count to filter the feed."
      />
      {!rows.length ? (
        <div className="empty">No watchlist company has a story in the window.</div>
      ) : (
        <div className="cos">
          {rows.map(({ company: co, count, up, flat, down, latest }) => {
            const words = `${up} positive, ${flat} neutral, ${down} negative`;
            return (
              <div className="co" key={co.ticker}>
                <Link className="tk" href={companyPath(market, co.ticker)} data-tip={co.name}>{co.ticker}</Link>
                <div className="nm">
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span className="mix" role="img" aria-label={words} data-tip={`${words} by the news analyst’s sentiment.`}>
                      {([["up", up], ["flat", flat], ["dn", down]] as const).map(([k, v]) => (v ? <i key={k} className={k} style={{ width: `${(v / count) * 100}%` }} /> : null))}
                    </span>
                    {co.open_trades ? <Label tone="paper" tip={`${co.open_trades} open paper trade${co.open_trades === 1 ? "" : "s"} on this company.`}>{`${co.open_trades} open`}</Label> : null}
                    {co.state !== "active" ? <Label tone="neutral">{co.state}</Label> : null}
                  </div>
                  <small>{latest.title}</small>
                </div>
                <button type="button" className="md-btn text small ct" data-tip="Show only this company in the feed." aria-label={`Show only ${co.ticker} in the feed (${stories(count)})`} onClick={() => onCompany(co.ticker)}>
                  {count}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function Legend({ c }: { c: Ctx }) {
  return (
    <div className="legend2" aria-label="Legend">
      <span><span className="mb-tag paper">paper</span> news informs paper calls; nothing here is advice</span>
      <span>
        {"Statuses: "}
        {CAN_CARRY.map((s) => <StatusBadge key={s} status={s} />)}
        {" can carry a call; the others (single source, unverified, rumour, promotional, contradicted) cannot ("}
        <Link href={`${pagePath(c.market, "help")}#news`}>Help</Link>)
      </span>
      <span><b>Open article</b> opens the outlet’s page in a new tab; the cockpit stores headlines, scores and statuses, never the text</span>
      <span>{`Window: ${fmtLocal(c.p.window.from, c.market, c.lt, true)} to ${fmtLocal(c.p.window.to, c.market, c.lt, true)}`}</span>
    </div>
  );
}

export function NewsView({ p, market }: { p: NewsPayload; market: Market }) {
  const [filter, setFilter] = useState<NewsFilter>("all");
  const [ticker, setTicker] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const c: Ctx = { p, market, lt: p.status.session.local_time, names: new Map(p.companies.map((co) => [co.ticker, co.name])) };
  const toFeed = () => document.getElementById(FEED_ID)?.scrollIntoView({ block: "start" });
  return (
    <>
      <PageHead page={p} title="News" subtitle={`${p.name} · the last ${p.window.days} days, the market movers first, the newest first · every story links to its article · research only`} />
      <MoversCard c={c} />
      <div className="grid news">
        <FeedCard
          c={c} filter={filter} ticker={ticker} page={page}
          onFilter={(f, t) => { setFilter(f); setTicker(t); setPage(1); }}
          onPage={(n) => { setPage(n); toFeed(); }}
        />
        <div className="col">
          <CalendarCard c={c} />
          <CompaniesCard c={c} onCompany={(t) => { setFilter("company"); setTicker(t); setPage(1); toFeed(); }} />
        </div>
      </div>
      <Legend c={c} />
      <PageFooter page={p} endpoint="news" />
    </>
  );
}

export function NewsPage({ market }: { market: Market }) {
  const res = usePage<NewsPayload>(market, "news");
  return <PageState result={res}>{(p) => <NewsView key={market} p={p} market={market} />}</PageState>;
}
