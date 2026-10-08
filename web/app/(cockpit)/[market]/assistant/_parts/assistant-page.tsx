"use client";
// Page 11, Assistant (design/mockups/11-assistant/; SPEC F11): the market's conversation with the cited records under
// each answer, beside how it answers, the records cited so far and the spend. The page head reads the status block
// (GET /api/v1/markets/{market}/status); the conversation and the spend read GET /api/assistant (B8). Research only:
// the assistant explains stored data and never advises.
import { PageFooter, PageHead } from "../../../../../components/blocks/page-head.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Avatar, Card, CardHead, Quiet } from "../../../../../components/ui/primitives.tsx";
import { LoadingState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import type { AnswerRecord, CitedRecord, SpendState } from "../../../../../lib/assistant/types.ts";
import { kindIcon, kindPage, kindWords } from "../../../../../lib/assistant/words.ts";
import { MARKET_LABEL } from "../../../../../lib/ui/constants.ts";
import { fmtLocal } from "../../../../../lib/ui/format.ts";
import { pagePath } from "../../../../../lib/ui/routes.ts";
import type { PageBase, StatusBlock } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import Link from "next/link";
import { Composer, Messages, startersOf } from "./conversation.tsx";
import { type Limits, useAssistant } from "./use-assistant.ts";
import "./assistant.css";

const usd = (x: number) => `$${x.toFixed(2)}`;

function RulesCard({ limits }: { limits: Limits | null }) {
  return (
    <Card label="How it answers">
      <CardHead title="How it answers" />
      <ul className="rules">
        <li><b>Stored data only.</b> It reads what the pages read, through the read tools; it cannot write, trade or fetch the web.</li>
        <li><b>Every answer cites its records</b> (the chips under it) and the as-of time it read up to; nothing stored later is used. A cited id that is not in the data read is removed.</li>
        <li><b>&quot;Not in the data&quot;</b> when the question is outside what is stored, for example a close after the last stored session.</li>
        <li><b>Never advice.</b> A question about real money is declined; the assistant points to the paper record instead.</li>
        <li><b>A conversation remembers</b> its last {limits?.history_turns ?? 4} questions and answers; &quot;New conversation&quot; starts afresh. Numbers are always read again from the data.</li>
        <li><b>Same answers everywhere.</b> The panel on every page, this page and Slack /ask call the same tool.</li>
        <li><b>Kept {limits?.retention_days ?? 90} days.</b> Conversations are an operational log, not a fact store.</li>
      </ul>
    </Card>
  );
}

function RecordsCard({ market, localTime, answers }: { market: Market; localTime: string | null; answers: AnswerRecord[] }) {
  const seen = new Map<string, CitedRecord>();
  for (const a of answers) for (const c of a.cited) if (!seen.has(c.id)) seen.set(c.id, c);
  const list = [...seen.values()].sort((x, y) => (x.as_of ?? "").localeCompare(y.as_of ?? "") || x.id.localeCompare(y.id));
  return (
    <Card label="Records cited">
      <CardHead title="Records cited" help="Every record the conversation rests on, with the as-of time of the data it was read from. Open one on its page." end={<span className="muted">{list.length} record{list.length === 1 ? "" : "s"}</span>} />
      {!list.length ? <Quiet>No record cited yet.</Quiet> : (
        <div className="src">
          {list.map((c) => (
            <div className="row" key={c.id}>
              <Avatar icon={kindIcon(c.kind)} tone="neutral" size="sm" />
              <div>
                <div>{kindWords(c.kind)}</div>
                <code data-tip={c.id}>{c.id}</code>
                <div className="when">data as of {fmtLocal(c.as_of, market, localTime, true)}</div>
              </div>
              <Link className="md-btn text small" href={pagePath(market, kindPage(c.kind))}>
                Open <Icon name="chevron_right" />
              </Link>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** The spend (owner decision 2026-10-08: shown, never enforced in code; the Anthropic console's limit is the cap). */
export function SpendCard({ spend, state }: { spend: SpendState | null; state: "loading" | "ready" | "error" }) {
  return (
    <Card label="Spend">
      <CardHead title="Spend" help="What the assistant's answers cost on the Claude API, from each answer's logged token use, in every channel and both markets together. There is no cap in the cockpit; the owner's spend limit is set in the Anthropic console." />
      {spend ? (
        <>
          <div className="budget">
            <div><div className="l">Today (UTC)</div><div className="v">{usd(spend.day.spent_usd)}</div></div>
            <div><div className="l">This month (UTC)</div><div className="v">{usd(spend.month.spent_usd)}</div></div>
          </div>
          {spend.enabled === false ? (
            <div className="mb-label warn"><Icon name="block" />switched off by the owner: questions are not answered</div>
          ) : null}
        </>
      ) : <Quiet>{state === "error" ? "The spend cannot be read right now." : "Reading the spend…"}</Quiet>}
    </Card>
  );
}

export function AssistantPage({ market }: { market: Market }) {
  const status = usePage<StatusBlock>(market, "status");
  const s = status.state === "ready" ? status.envelope.payload : null;
  const head: PageBase | null = s ? { market, name: s.name, currency: s.currency, as_of: s.as_of, status: s,
    built_at: s.freshness?.built_at ?? undefined } : null;
  const localTime = s?.session.local_time ?? null;
  const a = useAssistant(market);
  const max = a.limits?.question_max ?? 500;
  const starters = startersOf(a.answers);
  const name = s?.name ?? MARKET_LABEL[market];
  const subtitle = `${name} · ask the stored data in plain words · answers cite ids and as-of times · never advice · research only`;
  return (
    <>
      {head ? <PageHead page={head} title="Assistant" subtitle={subtitle} /> : (
        <section className="phead" aria-label="Page">
          <div>
            <h1>Assistant</h1>
            <div className="sub">{subtitle}</div>
          </div>
        </section>
      )}
      <div className="grid asst">
        <Card label="Conversation">
          <CardHead
            title="Ask the data"
            help="The assistant reads the cockpit's stored data through its read tools only and answers in plain words. It cites the ids and as-of times it used, says &quot;not in the data&quot; when the data cannot answer, and never advises a real trade. Nothing it says is a signal."
            end={
              <>
                <button className="md-btn text small" type="button" onClick={a.newConversation} disabled={!a.conversationId} data-tip="The next question starts a new conversation (earlier answers stay below).">
                  New conversation
                </button>
                <span className="mb-tag paper">paper</span>
              </>
            }
          />
          {a.state === "loading" ? <LoadingState label="Reading the conversation" cards={1} /> : (
            <Messages
              market={market}
              localTime={localTime}
              answers={a.answers}
              pending={a.pending}
              empty={a.state === "error"
                ? "The conversation log cannot be read right now; a question can still be asked."
                : `No question asked in ${name} in the last ${a.limits?.retention_days ?? 90} days. Ask one below; the answer reads only the stored data.`}
            />
          )}
          {a.notice ? <div className="mb-label warn notice" role="alert"><Icon name="warning" />{a.notice}</div> : null}
          <Composer
            max={max}
            busy={Boolean(a.pending)}
            disabled={a.spend?.enabled === false ? "The assistant is switched off by the owner." : null}
            onAsk={(q) => void a.ask(q)}
            starters={starters.list}
            startersLabel={starters.label}
          />
          <div className="note">
            {a.conversationId ? "The next question continues this conversation." : "The next question starts a new conversation."}
          </div>
        </Card>
        <div className="col">
          <RulesCard limits={a.limits} />
          <RecordsCard market={market} localTime={localTime} answers={a.answers} />
          <SpendCard spend={a.spend} state={a.state} />
        </div>
      </div>
      {head ? <PageFooter page={head} /> : null}
    </>
  );
}
