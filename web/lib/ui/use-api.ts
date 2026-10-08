"use client";
// The shared client data hooks over /api/v1 (B7). A page calls usePage(market, endpoint, params) and renders the
// three states with <PageState> (components/ui/states.tsx): loading, error (the problem with its fallback links and a
// retry) and ready (the envelope's payload). Reads revalidate with the row's ETag (api-client.ts).
import { useCallback, useEffect, useRef, useState } from "react";
import type { Market } from "../data/constants.ts";
import { readPage } from "./api-client.ts";
import { apiPath } from "./routes.ts";
import type { Envelope, Problem } from "./types.ts";

export type ApiState<P> =
  | { state: "loading"; envelope: null; problem: null; reload: () => void }
  | { state: "error"; envelope: null; problem: Problem; reload: () => void }
  | { state: "ready"; envelope: Envelope<P>; problem: null; reload: () => void };

/** Read one URL under /api/v1. `url` null skips the read (stays loading), e.g. while a ticker is unknown. */
export function useApi<P>(url: string | null): ApiState<P> {
  const [result, setResult] = useState<{ url: string; envelope: Envelope<P> | null; problem: Problem | null } | null>(null);
  const [nonce, setNonce] = useState(0);
  // A reload shows the loading state again, so a retry is visibly doing something.
  const reload = useCallback(() => {
    setResult(null);
    setNonce((n) => n + 1);
  }, []);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    if (url === null) return;
    const controller = new AbortController();
    readPage<P>(url, { signal: controller.signal })
      .then((res) => {
        if (!live.current) return;
        setResult(res.ok ? { url, envelope: res.envelope, problem: null } : { url, envelope: null, problem: res.problem });
      })
      .catch(() => undefined); // aborted
    return () => {
      live.current = false;
      controller.abort();
    };
  }, [url, nonce]);
  if (url === null || result === null || result.url !== url) return { state: "loading", envelope: null, problem: null, reload };
  if (result.problem) return { state: "error", envelope: null, problem: result.problem, reload };
  return { state: "ready", envelope: result.envelope as Envelope<P>, problem: null, reload };
}

/** Read a page of a market: usePage<HomePayload>("india", "home"), usePage(m, "stocks/{ticker}", {ticker}). */
export function usePage<P>(market: Market, endpoint: string, params: { ticker?: string; date?: string } = {}): ApiState<P> {
  let url: string | null = null;
  try {
    url = apiPath(market, endpoint, params);
  } catch {
    url = null;
  }
  const state = useApi<P>(url);
  if (url === null) {
    const problem: Problem = { title: "Not found", status: 404, detail: "That is not a ticker of this market." };
    return { state: "error", envelope: null, problem, reload: state.reload };
  }
  return state;
}
