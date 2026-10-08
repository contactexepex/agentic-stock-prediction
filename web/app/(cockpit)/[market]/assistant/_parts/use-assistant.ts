"use client";
// The client side of the assistant (F11): the market's conversation and spend from GET /api/assistant, and ask()
// through POST /api/assistant (same origin, no-store; identity comes from the dashboard's Vercel Authentication, never
// from here). Shared by page 11 and the chat panel. The current conversation is the newest answer's, until the reader
// starts a new one.
import { useCallback, useEffect, useMemo, useState } from "react";
import type { Market } from "../../../../../lib/data/constants.ts";
import type { AnswerRecord, SpendState } from "../../../../../lib/assistant/types.ts";

export interface Limits {
  question_max: number;
  history_turns: number;
  retention_days: number;
}

export interface Pending {
  question: string;
  asked_at: string;
}

export interface AssistantState {
  /** loading the conversation, ready, or the log could not be read */
  state: "loading" | "ready" | "error";
  answers: AnswerRecord[];
  spend: SpendState | null;
  limits: Limits | null;
  /** The question being answered now, shown at once. */
  pending: Pending | null;
  /** The last question that was not answered: refused, failed or not sent. */
  notice: string | null;
  /** The conversation the next question continues (null: a new one). */
  conversationId: string | null;
  ask: (question: string, hints?: { ticker?: string | null; strategyId?: string | null }) => Promise<void>;
  newConversation: () => void;
  reload: () => void;
}

const FALLBACK_LIMITS: Limits = { question_max: 500, history_turns: 4, retention_days: 90 };

export function useAssistant(market: Market): AssistantState {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [answers, setAnswers] = useState<AnswerRecord[]>([]);
  const [spend, setSpend] = useState<SpendState | null>(null);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [fresh, setFresh] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    setState("loading");
    fetch(`/api/assistant?market=${market}`, { cache: "no-store", headers: { accept: "application/json" } })
      .then(async (res) => {
        if (!res.ok) throw new Error(String(res.status));
        const body = await res.json();
        if (!live) return;
        setAnswers(Array.isArray(body.answers) ? body.answers : []);
        setSpend(body.spend ?? null);
        setLimits(body.limits ?? null);
        setState("ready");
      })
      .catch(() => {
        if (live) setState("error");
      });
    return () => {
      live = false;
    };
  }, [market, nonce]);

  const conversationId = useMemo(() => {
    if (fresh) return null;
    const last = answers.at(-1);
    return last && last.status !== "pending" ? last.conversation_id : null;
  }, [answers, fresh]);

  const ask = useCallback(async (question: string, hints: { ticker?: string | null; strategyId?: string | null } = {}) => {
    const text = question.trim();
    if (!text || pending) return;
    setNotice(null);
    setPending({ question: text, asked_at: new Date().toISOString() });
    const body: Record<string, string> = { market, question: text };
    if (hints.ticker) body.ticker = hints.ticker;
    if (hints.strategyId) body.strategy_id = hints.strategyId;
    if (conversationId) body.conversation_id = conversationId;
    try {
      const res = await fetch("/api/assistant", {
        method: "POST", cache: "no-store", headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(body),
      });
      const answer = await res.json().catch(() => null);
      if (answer?.answer) {
        setAnswers((list) => [...list, answer.answer as AnswerRecord]);
        setFresh(false);
      }
      if (answer?.spend) setSpend(answer.spend);
      if (answer?.limits) setLimits(answer.limits);
      if (!res.ok || answer?.result !== "accepted") {
        setNotice(`Not answered: ${answer?.message ?? (answer?.detail || `the assistant answered ${res.status}`)}`);
      }
    } catch {
      setNotice("Not answered: the assistant could not be reached. Nothing was asked; try again.");
    } finally {
      setPending(null);
    }
  }, [market, pending, conversationId]);

  const newConversation = useCallback(() => setFresh(true), []);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { state, answers, spend, limits: limits ?? (state === "ready" ? FALLBACK_LIMITS : null), pending, notice,
    conversationId, ask, newConversation, reload };
}

/** The answers of one conversation, oldest first. */
export function conversationOf(answers: AnswerRecord[], conversationId: string | null): AnswerRecord[] {
  return conversationId ? answers.filter((a) => a.conversation_id === conversationId) : [];
}
