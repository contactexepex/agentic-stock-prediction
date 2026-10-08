"use client";
// The conversation of the assistant as the approved mockup draws it (design/mockups/11-assistant/): each question as a
// bubble with its channel and time, each answer with its state in words and an icon (never colour alone), the time it
// read up to and its cited records as chips that open the page where the kind lives. Shared by page 11 and the panel.
import Link from "next/link";
import { useRef, useState } from "react";
import { Icon } from "../../../../../components/ui/icon.tsx";
import { Avatar } from "../../../../../components/ui/primitives.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import type { AnswerRecord, CitedRecord } from "../../../../../lib/assistant/types.ts";
import { kindIcon, kindPage, kindWords, stateWords } from "../../../../../lib/assistant/words.ts";
import { fmtLocal } from "../../../../../lib/ui/format.ts";
import { pagePath } from "../../../../../lib/ui/routes.ts";
import type { Pending } from "./use-assistant.ts";

const CHANNEL: Record<string, [string, string]> = {
  dashboard: ["dashboard", "home"],
  slack: ["Slack /ask", "public"],
  claude_app: ["Claude app", "bolt"],
};

/** The state of an answer: bubble class, badge tone, icon, words and the explanation in the tooltip. */
function stateOf(a: AnswerRecord): [string, string, string, string, string] {
  const words = stateWords(a);
  switch (a.status) {
    case "answered":
      return ["", "success", "check", "answered from the data", "Every number in the answer comes from the cited records; nothing stored after the as-of time was used."];
    case "not_in_data":
      return ["nid", "warn", "info", "not in the data", "The stored data cannot answer this; the answer says what the data covers and never guesses."];
    case "declined":
      return ["dec", "paper", "close", words.toLowerCase(), "The assistant never advises a real trade or a real buy or sell; it offers the paper record instead."];
    case "pending":
      return ["nid", "neutral", "pending", "no answer logged", "The question was logged but its answer was not (it may have been cut off); ask again."];
    default:
      return ["nid", "warn", "warning", words.toLowerCase(), "No answer was given; nothing was invented. Ask again or narrow the question."];
  }
}

export function CiteChip({ market, localTime, cite }: { market: Market; localTime: string | null; cite: CitedRecord }) {
  const label = kindWords(cite.kind);
  const tip = `${label} ${cite.id}, from ${cite.source}${cite.as_of ? `, data as of ${fmtLocal(cite.as_of, market, localTime, true)}` : ""}; the answer used nothing stored after its as-of time.`;
  return (
    <Link className="cite" href={pagePath(market, kindPage(cite.kind))} data-tip={tip}>
      <Icon name={kindIcon(cite.kind)} />
      <span className="k">{label}</span>
      <code>{cite.id}</code>
    </Link>
  );
}

function Question({ market, localTime, text, channel, at, pending }: { market: Market; localTime: string | null; text: string; channel: string; at: string; pending?: boolean }) {
  const [words, icon] = CHANNEL[channel] ?? [channel, "home"];
  return (
    <div className={`msg q${pending ? " pend" : ""}`}>
      <div>
        <div className="bub">{text}</div>
        <div className="meta end">
          {pending ? <span className="mb-label neutral"><Icon name="pending" />answering…</span> : (
            <span className="md-chip small"><Icon name={icon} />{words}</span>
          )}
          asked {fmtLocal(at, market, localTime, true)}
        </div>
      </div>
      <span className="mb-avatar neutral sm you" aria-hidden="true">You</span>
    </div>
  );
}

function Answer({ market, localTime, answer }: { market: Market; localTime: string | null; answer: AnswerRecord }) {
  const [bubble, tone, icon, words, tip] = stateOf(answer);
  return (
    <div className="msg a">
      <Avatar icon="bolt" tone="info" size="sm" />
      <div>
        <div className={`bub ${bubble}`}>{answer.text || "No answer text was logged."}</div>
        <div className="meta">
          <span className={`mb-label ${tone}`} data-tip={tip}>
            <Icon name={icon} />
            {words}
          </span>
          data as of {fmtLocal(answer.as_of, market, localTime, true)}
          {answer.history_turns ? <span className="muted"> · follows {answer.history_turns} earlier question{answer.history_turns === 1 ? "" : "s"}</span> : null}
        </div>
        {answer.cited.length ? (
          <div className="cites" aria-label="Records cited">
            {answer.cited.map((c) => <CiteChip key={c.id} market={market} localTime={localTime} cite={c} />)}
          </div>
        ) : answer.status === "answered" ? <div className="meta">no record cited</div> : null}
      </div>
    </div>
  );
}

/** The questions and answers, oldest first, plus the question being answered. */
export function Messages({ market, localTime, answers, pending, empty }: { market: Market; localTime: string | null; answers: AnswerRecord[]; pending: Pending | null; empty: string }) {
  return (
    <div className="chat" role="log" aria-live="polite" aria-label="Questions and answers">
      {!answers.length && !pending ? <div className="quiet">{empty}</div> : null}
      {answers.map((a) => (
        <div className="turn" key={a.id}>
          <Question market={market} localTime={localTime} text={a.question} channel={a.channel} at={a.asked_at} />
          <Answer market={market} localTime={localTime} answer={a} />
        </div>
      ))}
      {pending ? <Question market={market} localTime={localTime} text={pending.question} channel="dashboard" at={pending.asked_at} pending /> : null}
    </div>
  );
}

/** The question box (at most `max` characters, counter, Ask button, Ctrl/Cmd+Enter) and the chips that fill it. */
export function Composer({ max, busy, disabled, onAsk, starters, startersLabel }: { max: number; busy: boolean; disabled?: string | null; onAsk: (q: string) => void; starters: string[]; startersLabel: string }) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const submit = () => {
    const q = text.trim();
    if (!q) {
      box.current?.focus();
      return;
    }
    if (busy || disabled) return;
    onAsk(q);
    setText("");
  };
  return (
    <>
      <div className="composer">
        <div>
          <textarea
            ref={box}
            aria-label="Your question"
            placeholder="Ask about a company, a trade, a strategy or the news, in plain words…"
            maxLength={max}
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, max))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="cnt" aria-live="polite">{text.length} / {max}</div>
        </div>
        <button className="md-btn filled" type="button" onClick={submit} disabled={busy || Boolean(disabled)} aria-disabled={busy || Boolean(disabled)} data-tip={disabled ?? undefined}>
          <Icon name="arrow_upward" />
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>
      {disabled ? <div className="note">{disabled}</div> : null}
      {starters.length ? (
        <>
          <div className="note">{startersLabel} (click to fill):</div>
          <div className="sugg" aria-label={startersLabel}>
            {starters.map((q) => (
              <button key={q} className="md-chip assist" type="button" onClick={() => {
                setText(q.slice(0, max));
                box.current?.focus();
              }}>
                {q}
              </button>
            ))}
          </div>
        </>
      ) : null}
    </>
  );
}

/** Generic starters for a market with no question yet (page copy: no company, date or number). */
export const STARTERS = [
  "Why did a paper trade end as it did?",
  "Rule or AI: who did better on the last settled day?",
  "Which strategies agree on a company today, and why?",
];

/** The questions asked so far (newest first, distinct, at most 6), or the starters. */
export function startersOf(answers: AnswerRecord[]): { list: string[]; label: string } {
  if (!answers.length) return { list: STARTERS, label: "Ways to start" };
  const seen = new Set<string>();
  const list: string[] = [];
  for (const a of [...answers].reverse()) {
    if (!seen.has(a.question)) {
      seen.add(a.question);
      list.push(a.question);
    }
    if (list.length === 6) break;
  }
  return { list, label: "Questions asked so far" };
}
