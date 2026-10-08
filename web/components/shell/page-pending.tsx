"use client";
// The placeholder of a page whose session has not landed it yet (Wave 4): it reads the page's endpoint and shows the
// shared head, the signals band and the owner, so the shell, the data hooks and the states are exercised end to end.
// Each page session replaces its page.tsx; nothing imports this once every page is built.
import type { Market } from "../../lib/data/constants.ts";
import { pageByKey } from "../../lib/ui/routes.ts";
import type { GoLive, PageBase, StrategyMap } from "../../lib/ui/types.ts";
import { usePage } from "../../lib/ui/use-api.ts";
import { PageFooter, PageHead, SignalsBand } from "../blocks/page-head.tsx";
import { EmptyState, PageState } from "../ui/states.tsx";

type Pending = PageBase & { go_live?: GoLive; strategies?: StrategyMap };

function Body({ pageKey, payload, endpoint }: { pageKey: string; payload: Pending; endpoint: string }) {
  const page = pageByKey(pageKey);
  return (
    <>
      <PageHead page={payload} title={page.label} subtitle={`${payload.name} · data as of the ${payload.as_of ?? "—"} close`} />
      <SignalsBand page={payload} goLive={payload.go_live} strategies={payload.strategies ? Object.keys(payload.strategies).length : undefined} />
      <section className="card" style={{ marginTop: 16 }} aria-label="Being built">
        <EmptyState title="This page is being built" icon="construction">
          Its layout is the approved mockup design/mockups/{page.mockup}/; session {page.owner} builds it on this endpoint.
        </EmptyState>
      </section>
      <PageFooter page={payload} endpoint={endpoint} />
    </>
  );
}

export function PagePending({ market, pageKey, ticker }: { market: Market; pageKey: string; ticker?: string }) {
  const page = pageByKey(pageKey);
  const endpoint = page.endpoint || "status";
  const res = usePage<Pending>(market, endpoint, { ticker });
  return (
    <PageState result={res}>
      {(payload) =>
        page.endpoint ? (
          <Body pageKey={pageKey} payload={payload} endpoint={endpoint.replace("{ticker}", ticker ?? "")} />
        ) : (
          <section className="card" style={{ marginTop: 22 }} aria-label="Being built">
            <h1 className="mb-pending-h1">{page.label}</h1>
            <EmptyState title="This page is being built" icon="construction">
              Its layout is the approved mockup design/mockups/{page.mockup}/; session {page.owner} builds it.
            </EmptyState>
          </section>
        )
      }
    </PageState>
  );
}
