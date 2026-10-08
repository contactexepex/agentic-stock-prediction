"use client";
// Page 10, Companies (design/mockups/10-companies/): the watchlist as data. The active and inactive companies with
// their amounts and identifiers, every company command with its result, the lifecycle history, and the request dialogs
// (B7's shared CommandDialog, components/blocks/company-command-dialog.tsx, on B11's routes). A request is pending
// until the next run imports it; the page lists the ones sent from this tab for as long as the tab is open (#287).
// Research only: nothing here trades.
import Link from "next/link";
import { useState } from "react";
import { PageFooter, PageHead } from "../../../../../components/blocks/page-head.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Avatar, Card, CardHead, Delta, Kpi, KpiRow, Label, Quiet } from "../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import {
  CHANNEL, commandArguments, companiesCounts, deactivation, EVENT_TONE, EVENT_WORDS, newsSince, onboardingWords, RESULT,
  TOOL, type Command, type LifecycleEvent,
} from "../../../../../lib/market-pages/companies.ts";
import { NEWS_STATUS } from "../../../../../lib/ui/constants.ts";
import { fmtDate, fmtDateYear, fmtLocal, money, price } from "../../../../../lib/ui/format.ts";
import { companyPath } from "../../../../../lib/ui/routes.ts";
import type { CompanyRecord, GoLive, PageBase } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import { CommandDialog, type Intent, type Recorded } from "../../../../../components/blocks/company-command-dialog.tsx";
import "./companies.css";

export interface InactiveNewsItem { id: string; tickers: string[]; title: string; status: string | null; first_seen_at: string }
export type CompaniesPayload = PageBase & {
  go_live: GoLive;
  default_amount: number;
  companies: CompanyRecord[];
  lifecycle: (LifecycleEvent & { effective_from: string })[];
  commands: (Command & { received_at: string; channel: string | null; actor: string | null; message: string | null })[];
  news_inactive: InactiveNewsItem[];
  deleted_count: number;
};

const s = (n: number, one: string, many: string) => (n === 1 ? one : many);

function ActButtons({ c, open }: { c: CompanyRecord; open: (i: Intent) => void }) {
  const active = c.state === "active";
  return (
    <span className="acts">
      {active ? (
        <>
          <button className="md-btn outlined many" type="button" aria-label={`Change the amount for ${c.name}`} onClick={() => open({ kind: "amount", company: c })}><Icon name="account_balance_wallet" /><span>Amount</span></button>
          <button className="md-btn outlined many" type="button" aria-label={`Deactivate ${c.name}`} onClick={() => open({ kind: "deactivate", company: c })}><Icon name="pending" /><span>Deactivate</span></button>
        </>
      ) : (
        <button className="md-btn tonal many" type="button" aria-label={`Reactivate ${c.name}`} onClick={() => open({ kind: "reactivate", company: c })}><Icon name="check" /><span>Reactivate</span></button>
      )}
      <button className="md-btn outlined danger many" type="button" aria-label={`Delete ${c.name}`} onClick={() => open({ kind: "delete", company: c })}><Icon name="close" /><span>Delete</span></button>
      <button className="md-btn outlined one" type="button" aria-label={`Manage ${c.name}`} onClick={() => open({ kind: "manage", company: c })}><Icon name="settings" /><span>Manage</span></button>
    </span>
  );
}

function ActiveCard({ p, market, open }: { p: CompaniesPayload; market: Market; open: (i: Intent) => void }) {
  const cur = p.currency, rows = p.companies.filter((c) => c.state === "active");
  return (
    <Card label="Active companies">
      <CardHead
        title={`Active companies (${rows.length})`}
        help="Every company that is predicted and traded on paper. Amount = money per paper trade (the market’s default unless set for the company). Actions record a request: deactivate (takes effect at the next pre-open run; open paper trades still settle), change the amount, or delete (dashboard only, with a typed confirmation; the company is then excluded everywhere, decision 12)."
        end={<button className="md-btn filled small" type="button" onClick={() => open({ kind: "add" })}><Icon name="apartment" />Add company</button>}
      />
      {!rows.length ? <Quiet>No active company: add one to start predicting it.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl co">
            <thead>
              <tr>
                <th scope="col">Company</th><th scope="col" className="num">Last close</th><th scope="col" className="num cp">Per paper trade</th>
                <th scope="col" className="num cw">Buy at N+1</th><th scope="col" className="num cw">Open trades</th><th scope="col" className="cm">On the list since</th>
                <th scope="col" className="c3">Identifiers</th><th scope="col" className="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.ticker}>
                  <td>
                    <span className="nm">
                      <Avatar icon="apartment" tone="neutral" size="sm" />
                      <span className="t">
                        <b><Link className="tk" href={companyPath(market, c.ticker)} data-tip={`${c.name}: open its company page.`}>{c.ticker}</Link></b>
                        <small>{`${c.name} · ${c.sector ?? "—"} · ${c.exchange ?? "—"}`}</small>
                        <small className="ph">{`${money(cur, c.amount)} per paper trade${c.amount_overridden ? " (custom)" : ""}`}</small>
                      </span>
                    </span>
                  </td>
                  <td className="num last"><b>{price(cur, c.last_close)}</b><Delta value={c.change_pct} /></td>
                  <td className="num amt cp"><b>{money(cur, c.amount)}</b>{c.amount_overridden ? <Label tone="neutral" tip="Set for this company; differs from the market’s default (decision 44).">custom</Label> : null}</td>
                  <td className="num cw">
                    {c.agreement_n1 ? <span data-tip={`${c.agreement_n1.buy} of ${c.agreement_n1.of} strategies would buy ${c.name} at N+1 today (decision 30).`}>{`${c.agreement_n1.buy} of ${c.agreement_n1.of}`}</span> : <span className="muted">—</span>}
                  </td>
                  <td className="num cw">{String(c.open_trades ?? 0)}</td>
                  <td className="cm">
                    <span data-tip={`Added ${fmtDateYear(c.added_at)}${c.added_at?.startsWith("2011") ? " (the seed: the start of stored history)" : ""}; active since ${fmtDateYear(c.state_since)}.`}>{fmtDateYear(c.added_at)}</span>
                  </td>
                  <td className="c3"><small className="muted">{[c.yahoo ? `Yahoo ${c.yahoo}` : null, c.nse_symbol ? `NSE ${c.nse_symbol}` : null, c.cik ? `CIK ${c.cik}` : null].filter(Boolean).join(" · ")}</small></td>
                  <td className="num"><ActButtons c={c} open={open} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function InactiveCard({ p, market, open }: { p: CompaniesPayload; market: Market; open: (i: Intent) => void }) {
  const cur = p.currency, rows = p.companies.filter((c) => c.state === "inactive"), lt = p.status.session.local_time;
  return (
    <Card label="Inactive companies">
      <CardHead title={`Inactive companies (${rows.length})`} help="Still collected (prices, news, filings, announcements) but never predicted or traded; their open paper trades settle normally. Reactivate takes effect at the next pre-open run (F8.4). Only this page lists them (decision 13)." />
      {!rows.length ? <Quiet>No inactive company.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl co">
            <thead>
              <tr><th scope="col">Company</th><th scope="col">Inactive since</th><th scope="col" className="num">Last close</th><th scope="col" className="cm">News since</th><th scope="col" className="num cw">Open trades</th><th scope="col" className="num">Actions</th></tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const ev = deactivation(p.lifecycle, c.ticker);
                const news = newsSince(p.news_inactive, c.ticker);
                const stories = `${news.length} ${s(news.length, "story", "stories")}`;
                return (
                  <tr key={c.ticker}>
                    <td>
                      <span className="nm">
                        <Avatar icon="apartment" tone="neutral" size="sm" />
                        <span className="t">
                          <b><Link className="tk" href={companyPath(market, c.ticker)}>{c.ticker}</Link></b>
                          <small>{`${c.name} · ${c.sector ?? "—"} · ${c.exchange ?? "—"}`}</small>
                          <small className="ph2">{`news since: ${news.length ? stories : "none stored"} · open trades ${c.open_trades ?? 0}`}</small>
                        </span>
                      </span>
                    </td>
                    <td>
                      <span data-tip={ev ? `Deactivated via ${CHANNEL[ev.channel ?? ""] ?? ev.channel ?? "an unknown channel"} by ${ev.requested_by ?? "—"}, recorded ${fmtLocal(ev.recorded_at, market, lt, true)}, effective ${fmtLocal(ev.effective_from, market, lt, true)}.` : "The deactivation event is not in the stored history."}>{fmtDateYear(c.state_since)}</span>
                      {ev?.reason ? <small className="muted" style={{ display: "block", fontSize: 11.5 }}>{`“${ev.reason}”`}</small> : null}
                    </td>
                    <td className="num last"><b>{price(cur, c.last_close)}</b><Delta value={c.change_pct} /></td>
                    <td className="cm">
                      {news.length ? <span data-tip={news.map((n) => `${n.title} (${(NEWS_STATUS[n.status ?? ""] ?? [n.status ?? "no status"])[0]}, ${fmtDate(n.first_seen_at, false)})`).join(" · ")}>{stories}</span> : <span className="muted">none stored</span>}
                    </td>
                    <td className="num cw">{String(c.open_trades ?? 0)}</td>
                    <td className="num"><ActButtons c={c} open={open} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RequestsCard({ p, market, sent }: { p: CompaniesPayload; market: Market; sent: Recorded[] }) {
  const lt = p.status.session.local_time;
  return (
    <Card label="Requests">
      <CardHead
        title="Requests"
        help="Every company command from any channel (the dashboard, Slack, the command line, the Claude app) is logged with who asked (from the channel’s sign-in, never typed in), its result and the reason when refused (F10). Accepted writes are pending until the next run imports them. A deleted company is masked here (decision 12)."
        end={`${sent.length} sent from this page · ${p.commands.length} recent`}
      />
      {sent.length ? (
        <div className="pend" role="status">
          {sent.map((r, i) => (
            <div className="mb-alert" style={{ padding: "10px 14px" }} key={i}>
              <Icon name="pending" />
              <div>
                <b className="t">{`${r.result === "duplicate" ? "Already recorded" : "Pending"}: ${r.summary}`}</b>
                <div className="s">{r.message ?? "Appended to the inbox with your sign-in and an idempotency key; the next run imports it (F10)."}</div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {!p.commands.length ? (
        <div className="quiet" style={sent.length ? { marginTop: 10 } : undefined}>No company command recorded for this market yet.</div>
      ) : (
        <ul className="ev cmd" style={sent.length ? { marginTop: 12 } : undefined}>
          {p.commands.map((c) => {
            const [word, tone] = RESULT[c.result ?? ""] ?? [c.result ?? "unknown", "neutral"];
            const tail = [
              `via ${CHANNEL[c.channel ?? ""] ?? c.channel ?? "an unknown channel"}`,
              c.actor ?? "—",
              c.refusal_code ? c.refusal_code.replace(/_/g, " ") : null,
              c.record_ids.length ? `wrote ${c.record_ids.length} record${c.record_ids.length === 1 ? "" : "s"}` : null,
            ].filter(Boolean).join(" · ");
            return (
              <li key={c.id}>
                <span className="when">{fmtLocal(c.received_at, market, lt, true)}</span>
                <span className="what">
                  <Label tone={tone}>{word}</Label>
                  {` ${TOOL[c.tool] ?? c.tool}: `}
                  <code>{commandArguments(c)}</code>
                  {c.message ? <small>{c.message}</small> : null}
                  <small>{tail}</small>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function HistoryCard({ p, market }: { p: CompaniesPayload; market: Market }) {
  const cur = p.currency, lt = p.status.session.local_time;
  return (
    <Card label="Lifecycle history">
      <CardHead
        title="Lifecycle history"
        help="The watchlist is data (F8): every add, deactivate, reactivate and amount change is an append-only event with who asked, the channel, when it was recorded and when it counts (the next pre-open run; seeded adds count from the start of stored history). Events of a deleted company are excluded on read (decision 12)."
        end={`${p.lifecycle.length} events${p.deleted_count ? ` · ${p.deleted_count} deleted ${s(p.deleted_count, "company", "companies")} excluded` : ""}`}
      />
      {!p.lifecycle.length ? <Quiet>No event stored.</Quiet> : (
        <ul className="ev">
          {p.lifecycle.map((e) => {
            const onboarding = onboardingWords(e);
            const counts = e.channel === "seed" ? `the start of stored history (${fmtDateYear(e.effective_from)})` : fmtDateYear(e.effective_from);
            return (
              <li key={e.id}>
                <span className="when">{fmtLocal(e.recorded_at, market, lt, true)}</span>
                <span className="what">
                  <Label tone={EVENT_TONE[e.event] ?? "neutral"}>{EVENT_WORDS[e.event] ?? e.event}</Label>{" "}
                  <Link className="tk" href={companyPath(market, e.ticker)}>{e.ticker}</Link>
                  {e.event === "set_amount" && e.amount != null ? ` to ${money(cur, e.amount)}` : ""}
                  {e.reason ? ` · “${e.reason}”` : ""}
                  <small>{`via ${CHANNEL[e.channel ?? ""] ?? e.channel ?? "an unknown channel"} · ${e.requested_by ?? "—"} · counts from ${counts}${onboarding ? ` · onboarding: ${onboarding}` : ""}`}</small>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function Legend() {
  return (
    <div className="legend2" aria-label="Legend">
      <span>Legend (sample values): <span className="mb-delta up">+1.2%</span> up, <span className="mb-delta down">−1.2%</span> down, always with the sign</span>
      <span><Label tone="neutral">custom</Label> an amount set for the company</span>
      <span><Label tone="success">accepted</Label> <Label tone="warn">pending</Label> <Label tone="danger">refused</Label> a request’s result</span>
      <span><span className="mb-tag paper">paper</span> every trade is a paper record; nothing here is advice</span>
    </div>
  );
}

export function CompaniesView({ p, market }: { p: CompaniesPayload; market: Market }) {
  const [intent, setIntent] = useState<Intent | null>(null);
  const [dialogId, setDialogId] = useState(0);
  const [sent, setSent] = useState<Recorded[]>([]);
  const open = (i: Intent) => { setIntent(i); setDialogId((n) => n + 1); };
  const counts = companiesCounts(p.companies, p.commands, sent.filter((r) => r.result !== "duplicate").length);
  const inactive = p.companies.filter((c) => c.state === "inactive");
  const cur = p.currency;
  return (
    <div className="mb-companies">
      <PageHead page={p} title="Companies" subtitle={`the watchlist as data: ${p.companies.length} ${s(p.companies.length, "company", "companies")} · ${p.name} · data as of the ${fmtDate(p.as_of, false)} close · research only`} />
      <KpiRow>
        <Kpi icon="apartment" tone="success" label="Active" value={String(counts.active)} sub="predicted and traded on paper every session" tip="Active companies are collected, predicted and traded on paper (F8.2)." />
        <Kpi icon="pending" tone={counts.inactive ? "neutral" : ""} label="Inactive" value={String(counts.inactive)} sub={counts.inactive ? `still collected, never predicted: ${inactive.map((c) => c.ticker).join(", ")}` : "none"} tip="Inactive companies stay collected (prices, news, filings) but get no prediction or paper trade; their open paper trades still settle (decision 13)." />
        <Kpi icon="account_balance_wallet" tone="paper" label="Default per paper trade" value={money(cur, p.default_amount)} sub={`${counts.custom} ${s(counts.custom, "company has", "companies have")} a custom amount`} tip="The market’s default money per paper trade (decision 26); a company can have its own amount (decision 44)." />
        <Kpi icon="schedule" tone={counts.pending ? "warn" : "neutral"} label="Pending requests" value={String(counts.pending)} sub={counts.pending ? "waiting for the next import" : "nothing waiting"} tip="Requests from any channel are appended to the inbox and imported by the next run (F10); until then they are pending." />
      </KpiRow>
      <div style={{ marginTop: 16 }}><ActiveCard p={p} market={market} open={open} /></div>
      <div style={{ marginTop: 16 }}><InactiveCard p={p} market={market} open={open} /></div>
      <div className="grid even">
        <RequestsCard p={p} market={market} sent={sent} />
        <HistoryCard p={p} market={market} />
      </div>
      <Legend />
      <PageFooter page={p} endpoint="companies" />
      {intent ? (
        <CommandDialog
          key={dialogId}
          intent={intent}
          market={market}
          currency={cur}
          defaultAmount={p.default_amount}
          onClose={() => setIntent(null)}
          onRecorded={(r) => setSent((list) => [...list, r])}
          onSwitch={open}
        />
      ) : null}
    </div>
  );
}

export function CompaniesPage({ market }: { market: Market }) {
  const res = usePage<CompaniesPayload>(market, "companies");
  return <PageState result={res}>{(p) => <CompaniesView key={market} p={p} market={market} />}</PageState>;
}
