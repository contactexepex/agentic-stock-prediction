"use client";
// Loading, error and empty states of every page and card, and <PageState> that picks one from a usePage() result.
// An error says what failed in plain words, offers a retry and lists the static pages that still work (the
// problem's fallback_links, api/openapi.yaml Problem).
import type { ReactNode } from "react";
import type { ApiState } from "../../lib/ui/use-api.ts";
import type { Envelope, Problem } from "../../lib/ui/types.ts";
import { Icon } from "./icon.tsx";

/** A loading placeholder: grey card shapes, announced politely to screen readers. */
export function LoadingState({ label = "Loading the page data", cards = 3 }: { label?: string; cards?: number }) {
  return (
    <div className="mb-state loading" role="status" aria-live="polite" aria-busy="true">
      <span className="mb-sr">{label}…</span>
      {Array.from({ length: cards }, (_, i) => (
        <div key={i} className="card mb-skeleton" aria-hidden="true">
          <div className="mb-skeleton-line w40" />
          <div className="mb-skeleton-line" />
          <div className="mb-skeleton-line w70" />
        </div>
      ))}
    </div>
  );
}

const PLAIN: Record<number, string> = {
  0: "The data service did not answer.",
  404: "There is nothing stored under this address.",
  501: "This part is planned and not built yet.",
  503: "The page data cannot be read right now. The static reports still work.",
};

/** An error panel: what failed, a retry button and the fallback links. */
export function ErrorState({ problem, onRetry }: { problem: Problem; onRetry?: () => void }) {
  const links = problem.fallback_links ?? [];
  return (
    <section className="mb-alert danger mb-state" role="alert" aria-label="Page data error">
      <Icon name="warning" />
      <div>
        <b className="t">{problem.title}</b>
        <div className="s">
          {problem.detail ?? PLAIN[problem.status] ?? "Something went wrong reading the page data."}
          {problem.status ? ` (HTTP ${problem.status})` : ""}
        </div>
        {links.length ? (
          <ul className="mb-state-links">
            {links.map((href) => (
              <li key={href}>
                <a href={href} rel="noopener noreferrer">
                  {href.replace(/^https:\/\//, "")}
                  <Icon name="open_in_new" />
                </a>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {onRetry ? (
        <button className="md-btn outlined act" type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </section>
  );
}

/** An empty state: a whole page or card with nothing to show yet, saying what is missing and why. */
export function EmptyState({ title, children, icon = "info" }: { title: string; children?: ReactNode; icon?: string }) {
  return (
    <div className="mb-empty" role="note">
      <Icon name={icon} />
      <div>
        <b>{title}</b>
        {children ? <div className="s">{children}</div> : null}
      </div>
    </div>
  );
}

/** Render a usePage() result: loading, error, or `children(payload, envelope)` once ready. */
export function PageState<P>({ result, children, loadingLabel }: { result: ApiState<P>; children: (payload: P, envelope: Envelope<P>) => ReactNode; loadingLabel?: string }) {
  if (result.state === "loading") return <LoadingState label={loadingLabel} />;
  if (result.state === "error") return <ErrorState problem={result.problem} onRetry={result.reload} />;
  return <>{children(result.envelope.payload, result.envelope)}</>;
}
