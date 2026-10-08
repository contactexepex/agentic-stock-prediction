"use client";
// Page 12, Help (design/mockups/12-help/): how to read the cockpit, in plain words. One scrolling page with an anchor
// chip row. The text is the approved mockup's; the few data values (strategy list, the go-live checklist, the default
// amount, the agreement example) come from the Strategy lab and Companies reads (lib/ui/help.ts). The explanations
// stay readable when a read fails: only the data parts then say they are not available.
import Link from "next/link";
import type { ReactNode } from "react";
import { PageFooter, PageHead } from "../../../../../components/blocks/page-head.tsx";
import { RangeBar } from "../../../../../components/charts/small.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Avatar, Odds, SentimentSquare, StatusBadge } from "../../../../../components/ui/primitives.tsx";
import { ErrorState, LoadingState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import {
  BAND,
  BAND_SHORT,
  FAMILY,
  FLAG,
  FLAG_SHORT,
  GO_LIVE_MONTHS,
  GO_LIVE_TRADES_ABOUT,
  INTRADAY_CHECKS_PER_SESSION,
  LUCK_INTERVAL_PCT,
  MARKET_LABEL,
  MIN_TRADES_TO_RANK,
  NEWS_STATUS,
  REASON_MAX_WORDS,
  type Family,
} from "../../../../../lib/ui/constants.ts";
import { horizonWords, money, moneyDecimals, pct } from "../../../../../lib/ui/format.ts";
import { agreementExample, aiHorizons, goLiveChecks, referenceGoLive, type CompaniesForHelp, type LabForHelp } from "../../../../../lib/ui/help.ts";
import { pagePath } from "../../../../../lib/ui/routes.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import "./help.css";

const SECTIONS: [string, string][] = [
  ["paper", "Paper and the go-live bar"], ["horizons", "Horizons, chances and ranges"], ["strategies", "The strategies"],
  ["scores", "Scores and the luck test"], ["h2h", "Head-to-head and costs"], ["news", "News and its status"],
  ["intraday", "Intraday checks"], ["pages", "The pages"], ["numbers", "Where the numbers come from"], ["glossary", "Glossary"],
];

function HelpCard({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="card help" aria-labelledby={`h-${id}`} id={id}>
      <div className="head">
        <h2 id={`h-${id}`}>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Terms({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl>
      {rows.map(([t, d], i) => [<dt key={`t${i}`}>{t}</dt>, <dd key={`d${i}`}>{d}</dd>])}
    </dl>
  );
}

const NA = <span className="muted">not available right now</span>;

function Paper({ market, lab }: { market: Market; lab: LabForHelp | null }) {
  const g = lab ? referenceGoLive(lab) : null;
  const cur = lab?.currency ?? "INR";
  // Company and Stock strategies need a ticker, so they are named without a link (they open from the watchlist).
  const signalPages: [string, string | null][] = [["Home", "home"], ["Watchlist", "watchlist"], ["Company", null], ["Stock strategies", null], ["Strategy lab", "lab"], ["Rule vs AI", "compare"], ["Paper portfolios", "portfolios"]];
  const words: Record<string, string> = {
    trades: `About ${GO_LIVE_TRADES_ABOUT} settled trades per strategy`,
    months: `${GO_LIVE_MONTHS} months of forward paper trading`,
    baseline: "Beats the best baseline after your cost, with the corrected luck test excluding zero",
    drawdown: "Its worst fall from a peak stays within the limit",
    regimes: "Holds up in calm and in volatile markets",
  };
  const detail = (key: string): string => {
    if (!g) return "";
    if (key === "trades") return `${g.trades_needed} still to go`;
    if (key === "months") return `${g.months_forward} so far`;
    if (key === "baseline") return `best baseline ${money(cur, g.best_baseline_net_pnl, moneyDecimals(cur), true)}`;
    if (key === "drawdown") return `limit ${money(cur, g.drawdown_limit)}`;
    return g.holds_in_calm_and_volatile == null ? "not enough data yet" : "";
  };
  const checks = g ? goLiveChecks(g, GO_LIVE_MONTHS) : Object.keys(words).map((key) => ({ key, passed: null }));
  return (
    <HelpCard id="paper" title="Paper, and the go-live bar">
      <p>
        Everything in this cockpit is a <b>paper trade</b>: a record of what a strategy would have done, settled against the stored prices. Nothing is bought or sold, no broker is connected, and no page ever tells you to buy or sell. The <span className="mb-tag paper">paper</span> tag on a figure means &quot;measured, not acted on&quot;.
      </p>
      <p>
        A strategy stays Paper until it meets the <b>go-live bar</b> (measured on your own costs, decision 50). Until one does, the pages that rank signals (
        {signalPages.map(([t, key], i) => (
          <span key={t}>
            {i ? (i === signalPages.length - 1 ? " and " : ", ") : ""}
            {key ? <Link href={pagePath(market, key)}>{t}</Link> : <span data-tip="Opens from a company on the watchlist.">{t}</span>}
          </span>
        ))}
        ) say &quot;No proven strong signals today&quot;. The bar has {checks.length} checks; here is where the reference strategy stands in {lab?.name ?? MARKET_LABEL[market]}:
      </p>
      <ul className="chk">
        {checks.map(({ key, passed }) => (
          <li key={key} className={passed == null ? "na" : passed ? "ok" : "no"}>
            <Icon name={passed == null ? "remove" : passed ? "check" : "close"} />
            <span>
              {words[key]}
              <small className="muted" style={{ display: "block" }}>
                {g ? detail(key) : NA}
              </small>
            </span>
          </li>
        ))}
      </ul>
      <p>
        <b>Proven</b> means all {checks.length} hold. A proven strategy may show a &quot;Strong&quot; signal; everything else is a ranking of who agrees, never a recommendation.
      </p>
    </HelpCard>
  );
}

function Horizons({ lab, companies }: { lab: LabForHelp | null; companies: CompaniesForHelp | null }) {
  const horizons = lab?.horizons ?? [1, 2, 3, 4, 5];
  const first = horizons[0], last = horizons[horizons.length - 1];
  const ref = lab ? lab.strategies[lab.reference_strategy] : null;
  const ex = companies ? agreementExample(companies) : null;
  const cur = lab?.currency ?? "INR";
  return (
    <HelpCard id="horizons" title="Horizons, chances, targets and ranges">
      <p>
        Every prediction names a <b>horizon</b>: buy at the open of the first market session after the prediction (called D, the entry session), sell at the close of the k-th market session after D. The pages write it N+k, for example <span className="h-lab">N+{horizons[2] ?? 3}</span>. Weekends and holidays are skipped. N+{first} is {horizonWords(first)}, N+{last} is {horizonWords(last)}. Every page with a horizon selector opens on N+{lab?.default_horizon ?? 1}.
      </p>
      <p>
        The <b>chance of a rise</b> is the strategy’s probability that the close at the horizon is above the entry. The odds meter shows it against the 50% coin-flip mark:{" "}
        <span className="sample">
          <Odds p={0.57} tip="A sample: 57% chance of a rise." />
          <span className="l muted">(sample value)</span>
        </span>
        . A rule strategy buys only when the chance clears its own bar (the reference strategy’s bar is {ref?.threshold != null ? pct(ref.threshold) : "set per strategy"}); below it, &quot;no trade&quot;.
      </p>
      <p>
        The <b>target</b> is the expected exit close. The <b>50% and 80% ranges</b> are where the close is expected to land that often. The range bar draws them around the last close:{" "}
        <span className="sample">
          <RangeBar currency={cur} bands={{ lo80: 96, lo50: 98.5, hi50: 102, hi80: 104, target_price: 101 }} last={100} />
          <span className="l muted">(sample: the triangle is the target, the dark line the last close)</span>
        </span>
        . Ranges are computed by a script, never by hand; an AI trader may widen one, never narrow it.
      </p>
      <p>
        &quot;<b>Agreement</b>&quot; counts how many strategies would buy a company at a horizon
        {ex ? ` (today ${ex.name}: ${ex.agreement_n1.buy} of ${ex.agreement_n1.of} at N+1)` : ""}. A majority means they lean the same way; it does not mean they are right. The track record says that.
      </p>
    </HelpCard>
  );
}

const FAMILY_NOTE: Record<Family, string> = {
  rule: "Fixed rules on the signal model and verified news. Each differs from the reference in exactly one setting, so a difference in results points to that setting.",
  baseline: "Yardsticks, not contenders: a strategy must beat the best of them after your cost to go live.",
  ai: `Claude traders that read the day’s evidence and write a probability and a reason of at most ${REASON_MAX_WORDS} words; two see the signal model, two are blind to it.`,
};

function Strategies({ market, lab, problem }: { market: Market; lab: LabForHelp | null; problem: ReactNode }) {
  if (!lab) {
    return (
      <HelpCard id="strategies" title="The strategies">
        {problem}
      </HelpCard>
    );
  }
  const all = Object.values(lab.strategies);
  const ref = lab.reference_strategy;
  const lab_ = pagePath(market, "lab");
  return (
    <HelpCard id="strategies" title="The strategies">
      <p>
        {all.length} strategies, in three families, predict or abstain for every active company every session (the AI traders at {aiHorizons(lab.strategies).map((k) => `N+${k}`).join(", ")} only). Hover a name for what it does; click it for its page in the Strategy lab.
      </p>
      <div className="fam">
        {(["rule", "baseline", "ai"] as Family[]).map((f) => {
          const list = all.filter((s) => s.family === f);
          return (
            <div className="f" key={f}>
              <div className="h">
                <Avatar icon={FAMILY[f][1]} tone={f === "ai" ? "info" : f === "baseline" ? "warn" : ""} size="sm" />
                {FAMILY[f][0]}
                <span className="muted" style={{ fontWeight: 400 }}>
                  · {list.length}
                </span>
              </div>
              <small>{FAMILY_NOTE[f]}</small>
              <ul>
                {list.map((s) => (
                  <li key={s.id}>
                    <Link className="tk" href={`${lab_}#${encodeURIComponent(s.id)}`} data-tip={s.description}>
                      {s.name}
                    </Link>
                    <small className="muted">
                      {s.id === ref
                        ? "the reference"
                        : s.differs_in
                          ? `differs in ${s.differs_in.replace(/_/g, " ")}${s.compared_to && s.compared_to !== ref ? ` from ${lab.strategies[s.compared_to]?.name ?? s.compared_to}` : ""}`
                          : s.threshold != null
                            ? `bar ${pct(s.threshold)}`
                            : "no probability"}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
      <p>A strategy never changes behaviour after its first live day; a change is a new strategy with a new id, proposed by the weekly research director and approved by the owner.</p>
    </HelpCard>
  );
}

function Scores({ companies, currency }: { companies: CompaniesForHelp | null; currency: string }) {
  const amount = companies?.default_amount != null ? money(currency, companies.default_amount) : null;
  return (
    <HelpCard id="scores" title="Scores, and the luck test">
      <Terms
        rows={[
          ["Profit after costs", "The headline. Market cost = brokerage, taxes and fees; strategies are ranked on it. Your cost adds the charges only you pay (in India the NRI reporting and depository charges, in the US the currency markup and the pro-rated portfolio fee); the go-live bar and your own decisions use it."],
          ["Return per trade", `Profit as a percent of the amount per paper trade (${amount ? `${amount} by default` : "the market’s default amount"}, or the company’s own amount), so companies with different amounts compare.`],
          ["Win rate", "The share of trades that made money after costs."],
          ["Target reached", "The share of trades whose price touched the target at some point in the window, and the typical session it happened."],
          ["In range", "The share of exit closes that landed inside the 80% range: how honest the ranges are."],
          ["Drawdown", "The deepest fall of cumulative profit from its peak, and the worst losing streak."],
          ["Too few to rank", `Fewer than ${MIN_TRADES_TO_RANK} settled trades. A handful of trades is mostly luck, so such rows are greyed and a per-company "best strategy" is never trusted on its own.`],
        ]}
      />
      <p>
        <b>The luck test.</b> The pages draw it as a bar: a thin line for the {LUCK_INTERVAL_PCT}% interval of the mean return per trade, a thick line for the same interval corrected for how many strategies were compared at once (the more you compare, the more one looks good by chance), and a tick at zero. Only when the thick bar clears zero does the label say <span className="mb-label success">edge</span>; otherwise <span className="mb-label neutral">luck?</span>. On fewer than {MIN_TRADES_TO_RANK} trades the label is qualified.
      </p>
    </HelpCard>
  );
}

function HeadToHead({ horizon }: { horizon: number }) {
  return (
    <HelpCard id="h2h" title="Head-to-head picks, and the two cost views">
      <p>
        Besides the <b>accuracy view</b> (every qualifying prediction is its own paper trade), there is a <b>head-to-head view</b>: every session, for each company, the strongest rule strategy and the strongest AI trader each pick one horizon under two pick rules, <b>best expected gain</b> (chance × move up − (1 − chance) × move down − costs, per session held) and <b>highest probability</b>. Up to four paper trades a day per company, on identical company-days, so rule and AI compare fairly.
      </p>
      <p>
        Each pick shows two cost labels: <span className="mb-label success">clears market costs</span> or <span className="mb-label neutral">below market costs</span> (the expected gain after the market charges, the ranking view), and <span className="mb-label success">viable at your cost</span> or <span className="mb-label warn">not viable at your cost</span> (after the charges only you pay too, decision 51). The flag never blocks a paper trade; it tells you whether the same trade would be worth it for you.
      </p>
      <div className="ex">
        <span className="l">Labels on a trade:</span>
        <span className="h-lab">N+{horizon}</span>
        the horizon
        <span className="mb-label neutral mb-h2h" style={{ marginLeft: 0 }}>
          H2H
        </span>
        a head-to-head trade in a list of open trades
      </div>
    </HelpCard>
  );
}

function News() {
  return (
    <HelpCard id="news" title="News, and what its status allows">
      <p>
        Headlines are collected from the configured feeds; the material ones about watchlist companies are read where their outlet is on the vetted list and the page is freely accessible (a paywalled page gives only its summary; a few vetted outlets that refuse automated reading are never fetched and their headlines count as unread; an unlisted outlet is never fetched and never counts). Each story is then checked: how many independent verified origins carry it (copies of one agency story count once), whether a filing or company release confirms it, whether it is a rumour or a promotion. The status is computed, not guessed, and shown as of the time it was known.
      </p>
      <Terms rows={Object.entries(NEWS_STATUS).map(([k, v]) => [<StatusBadge key={k} status={k} />, v[1]])} />
      <p>
        Only a confirmed or corroborated item may be the main evidence of a call; a single-source or unverified item lowers the confidence; rumours and promotional items never support a call; a contradicted item may only widen a range. The arrow beside a headline is the news analyst’s sentiment:{" "}
        <span className="sample">
          <SentimentSquare value={0.6} />
          <SentimentSquare value={0} />
          <SentimentSquare value={-0.6} />
          <span className="l muted">(sample values: positive, neutral, negative)</span>
        </span>
        .
      </p>
    </HelpCard>
  );
}

function Intraday() {
  const rows: [ReactNode, ReactNode][] = [
    ...Object.entries(BAND).map(([k, v]): [ReactNode, ReactNode] => [BAND_SHORT[k], `The price is ${v[0]} of the trade’s own prediction.`]),
    ...Object.entries(FLAG).map(([k, v]): [ReactNode, ReactNode] => [
      <span key={k} className="st flag" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        <Icon name="warning" />
        {FLAG_SHORT[k]}
      </span>,
      `Flagged: the trade is ${v}.`,
    ]),
  ];
  return (
    <HelpCard id="intraday" title="Intraday checks">
      <p>
        {INTRADAY_CHECKS_PER_SESSION} times per session every open paper trade is compared with its own prediction at that moment’s price: where it sits in its range, how far it is from its target, and whether it moves against the prediction. Monitoring only: nothing is traded on a check. A company with a flagged trade gets a short note (at most {REASON_MAX_WORDS} words) from the deviation explainer, citing only stored causes (the market, the sector, news, events).
      </p>
      <Terms rows={rows} />
    </HelpCard>
  );
}

function Pages({ market }: { market: Market }) {
  const rows: [string, string, string, string][] = [
    ["home", "home", "Home", "the day at a glance: who agrees, today’s head-to-head trades, rule vs AI, open trades, alerts, the runs"],
    ["watchlist", "format_list_bulleted", "Watchlist", "every active company with price, move, agreement, range and open trades; filter by sector"],
    ["watchlist", "apartment", "Company", "one company: the decision card, the chart with targets and ranges, today’s path, settled results and why, news, results, events, settings (open one from the watchlist)"],
    ["watchlist", "query_stats", "Stock strategies", "every strategy on one company, ranked by profit after costs, with the luck guard (open one from a company)"],
    ["lab", "science", "Strategy lab", "all strategies on one scoreboard, each in plain words, cumulative lines and heatmaps"],
    ["compare", "layers", "Rule vs AI", "the head-to-head: scorecard, matches, the analyst’s reasons, the weekly review"],
    ["portfolios", "account_balance_wallet", "Paper portfolios", "head-to-head portfolios, open trades by strategy, your own paper trades with a euro view"],
    ["track", "query_stats", "Track record", "accuracy over time, calibration, scoring bases apart"],
    ["news", "newspaper", "News", "the last 3 days of news: the market movers first, every story with its status and its article, the week’s calendar"],
    ["companies", "apartment", "Companies", "the watchlist as data: add, pause, amounts, delete, requests, history"],
    ["assistant", "bolt", "Assistant", "ask in plain words; answers cite ids and as-of times and never advise real trades"],
  ];
  return (
    <HelpCard id="pages" title="The pages">
      <p>Every page shows the session, the regime and its freshness in the chips at the top and its &quot;as of&quot; time in the footer, works on a phone and with the keyboard, and marks every signal Paper.</p>
      <div className="pages">
        {rows.map(([key, ico, title, text]) => (
          <Link key={title} href={pagePath(market, key)}>
            <Avatar icon={ico} tone="neutral" size="sm" />
            <span>
              <b>{title}</b>
              {text}
            </span>
          </Link>
        ))}
      </div>
    </HelpCard>
  );
}

function Numbers() {
  return (
    <HelpCard id="numbers" title="Where the numbers come from">
      <p>
        Prices, news, filings and events are collected from free public sources every session; predictions are made before the open; trades are settled after the close against the stored closes; the scoreboard, the luck test and the go-live bar are recomputed from the settled trades. No figure on a page is typed in by hand: prices, outcomes and scores come from the stored records. The hand-entered records are your own: the watchlist and each company’s paper amount (the Companies page), your own paper trades, and the broker cost rates (marked &quot;verify&quot; until a contract note confirms them); the chances, targets and ranges are the strategies’ estimates, and the pages say so.
      </p>
      <p>
        Every page reads data only up to its cut-off time (nothing stored after it), so a page about a past day never uses anything learned later; its &quot;as of&quot; is the newest trading date inside that. The <b>freshness</b> chip says when the page was built and how old its data is; a stale page says so.
      </p>
      <p>The assistant answers in plain words from the same data, cites the ids and as-of times it used, says &quot;not in the data&quot; when it is not, and never advises a real trade.</p>
    </HelpCard>
  );
}

function Glossary() {
  return (
    <HelpCard id="glossary" title="Glossary">
      <details className="gl">
        <summary>The terms, A to Z</summary>
        <Terms
          rows={[
            ["As of", "The newest trading date with stored indicators; every number on a page is computed to it."],
            ["Cut-off", "The time after which nothing is read for a page; stops look-ahead."],
            ["D", "The entry session: the first market session after the prediction is made; a trade enters at its open and N+k sells at the close of the k-th session after D."],
            ["Regime", "The market mood label stored by the daily run: CALM, TRENDING, EVENT_HEAVY or UNSTABLE. Rule strategies either skip the last two or not; AI traders lower their probability in them."],
            ["Signal model", "The explainable up/down probability built from the stored indicators and verified news, refitted monthly; the reference rule strategy trades it as is."],
            ["Baseline", "A yardstick strategy: always buy, follow yesterday, or the signal model without news."],
            ["Pick rule", "How a family chooses one horizon for its head-to-head trade: best expected gain or highest probability."],
            ["Cost view", "Market cost (the ranking view) or your cost (market cost plus the charges only you pay)."],
            ["Settled", "A paper trade whose exit close is stored; its profit after costs is final unless a later split correction re-settles it as a new record."],
            ["Unrealised", "The profit of an open paper trade at the latest stored close, before costs."],
            ["Reason split", "A settled trade’s move split into what the market explains, the sector, verified news, and the company itself."],
            ["EOD analyst", `The Claude agent that writes a reason of at most ${REASON_MAX_WORDS} words per head-to-head trade and the day’s biggest wins and misses, after the close.`],
            ["Research director", "The Claude agent that writes the weekly research review (apart from the weekly review of the ranges) and proposes changes as config diffs; it changes nothing itself."],
            ["Inactive company", "Still collected, never predicted or traded; its open paper trades still settle."],
          ]}
        />
      </details>
    </HelpCard>
  );
}

export function HelpPage({ market }: { market: Market }) {
  const labRes = usePage<LabForHelp>(market, "strategies");
  const coRes = usePage<CompaniesForHelp>(market, "companies");
  const lab = labRes.state === "ready" ? labRes.envelope.payload : null;
  const companies = coRes.state === "ready" ? coRes.envelope.payload : null;
  const head = lab ?? companies;
  const loading = labRes.state === "loading" || coRes.state === "loading";
  const problem =
    labRes.state === "error" ? <ErrorState problem={labRes.problem} onRetry={labRes.reload} /> : labRes.state === "loading" ? <LoadingState label="Loading the strategy list" cards={1} /> : null;
  const currency = head?.currency ?? (market === "us" ? "USD" : "INR");
  return (
    <>
      {head ? (
        <PageHead page={head} title="How to read the cockpit" subtitle={`in plain words · the examples below use ${head.name}'s numbers · research only, nothing here is advice`} />
      ) : (
        <section className="phead" aria-label="Page">
          <div>
            <h1>How to read the cockpit</h1>
            <div className="sub">in plain words · research only, nothing here is advice{loading ? " · loading the examples…" : ""}</div>
          </div>
        </section>
      )}
      <nav className="toc" aria-label="On this page">
        {SECTIONS.map(([id, title]) => (
          <a key={id} className="md-chip assist" href={`#${id}`}>
            {title}
          </a>
        ))}
      </nav>
      <Paper market={market} lab={lab} />
      <Horizons lab={lab} companies={companies} />
      <Strategies market={market} lab={lab} problem={problem} />
      <Scores companies={companies} currency={currency} />
      <HeadToHead horizon={lab?.horizons?.[2] ?? 3} />
      <News />
      <Intraday />
      <Pages market={market} />
      <Numbers />
      <Glossary />
      <div className="note2">
        <Icon name="info" />
        <div>
          <b>Research only.</b> This is a personal research project. Nothing here is investment advice, nothing trades, and no broker is connected. Every figure is a paper record until a strategy meets the go-live bar; even then the cockpit ranks and explains, it never instructs.
        </div>
      </div>
      {head ? (
        <PageFooter page={head} endpoint={undefined} />
      ) : null}
    </>
  );
}
