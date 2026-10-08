"use client";
// The F11 chat panel on every page (B8), rendered by the parallel route @chat into the shell's slot (B7,
// components/shell/chat-panel.tsx). It registers itself so the top bar's Ask button toggles it; closed, it renders
// nothing (the slot stays empty and hidden). It shows the current conversation and sends the page in view (company
// ticker, strategy id) as hints with the question. Same tool, rules and log as page 11.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { useRegisterChatPanel } from "../../../../../components/shell/chat-panel.tsx";
import { Icon } from "../../../../../components/ui/icon.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import { TICKER_PATTERN } from "../../../../../lib/data/constants.ts";
import { spendLine } from "../../../../../lib/assistant/cost.ts";
import { pageOfPath, pagePath } from "../../../../../lib/ui/routes.ts";
import type { StatusBlock } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import { Composer, Messages, STARTERS } from "./conversation.tsx";
import { conversationOf, useAssistant } from "./use-assistant.ts";
import "./assistant.css";

const STRATEGY_ID = /^[a-z][a-z0-9_.-]{1,79}$/;

/** The company and strategy in view: the ticker of a company page, the strategy of /strategy-lab#<id>. */
export function viewContext(pathname: string, hash: string): { ticker: string | null; strategyId: string | null } {
  const page = pageOfPath(pathname).key;
  const parts = pathname.split("/").filter(Boolean);
  const raw = page === "company" || page === "strategies" ? decodeURIComponent(parts[2] ?? "") : "";
  const ticker = TICKER_PATTERN.test(raw) ? raw : null;
  const id = page === "lab" ? decodeURIComponent(hash.replace(/^#/, "")) : "";
  return { ticker, strategyId: STRATEGY_ID.test(id) ? id : null };
}

export function AssistantPanel({ market }: { market: Market }) {
  const panel = useRegisterChatPanel();
  if (!panel.open) return null;
  const close = () => {
    panel.setOpen(false);
    // focus goes back to the top bar's Ask button that opened the panel
    requestAnimationFrame(() => document.querySelector<HTMLElement>('button[aria-controls="mb-chat-slot"]')?.focus());
  };
  return <OpenPanel market={market} close={close} />;
}

function OpenPanel({ market, close }: { market: Market; close: () => void }) {
  const pathname = usePathname() ?? `/${market}`;
  const a = useAssistant(market);
  const status = usePage<StatusBlock>(market, "status");
  const localTime = status.state === "ready" ? status.envelope.payload.session.local_time : null;
  const view = viewContext(pathname, typeof window === "undefined" ? "" : window.location.hash);
  const onPage11 = pageOfPath(pathname).key === "assistant";
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    panelRef.current?.querySelector("textarea")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);
  const shown = conversationOf(a.answers, a.conversationId);
  return (
    <section className="chat-panel" aria-label="Assistant" ref={panelRef}>
      <div className="ph">
        <Icon name="bolt" />
        <h2>Assistant</h2>
        <span className="mb-tag paper">paper</span>
        <div className="end">
          <button className="md-btn text small" type="button" onClick={a.newConversation} disabled={!a.conversationId}>New</button>
          {!onPage11 ? (
            <Link className="md-btn text small" href={pagePath(market, "assistant")} data-tip="The full Assistant page: every conversation, the records cited and the spend.">
              Full page
            </Link>
          ) : null}
          <button className="md-icon-btn" type="button" aria-label="Close the assistant" onClick={close}>
            <Icon name="close" />
          </button>
        </div>
      </div>
      <div className="pb">
        {a.state === "loading" ? <div className="quiet">Reading the conversation…</div> : (
          <Messages
            market={market}
            localTime={localTime}
            answers={shown}
            pending={a.pending}
            empty={a.state === "error"
              ? "The conversation log cannot be read right now; a question can still be asked."
              : "A new conversation. The answer reads only the stored data, cites its records and never advises."}
          />
        )}
        {a.notice ? <div className="mb-label warn notice" role="alert"><Icon name="warning" />{a.notice}</div> : null}
      </div>
      <div className="pf">
        <Composer
          max={a.limits?.question_max ?? 500}
          busy={Boolean(a.pending)}
          disabled={a.spend?.enabled === false ? "The assistant is switched off by the owner." : null}
          onAsk={(q) => void a.ask(q, view)}
          starters={shown.length ? [] : STARTERS}
          startersLabel="Ways to start"
        />
        <div className="ctx">
          {view.ticker ? `Asked about the page of ${view.ticker}. ` : view.strategyId ? `Asked about strategy ${view.strategyId}. ` : ""}
          {a.spend ? spendLine(a.spend) : ""} Research only, never advice.
        </div>
      </div>
    </section>
  );
}
