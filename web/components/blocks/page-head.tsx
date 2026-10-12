// The page head every 2.0 page opens with (the mockups' pageHead): the title and subtitle, then the chips of the
// shared status block: session (open now / opens at / closed / no session, decided at view time: session-chip.tsx),
// market mood, freshness of the page data with
// the cut-off, and the Paper tag. The signals band (go-live) and the footer are here too.
import Link from "next/link";
import type { ReactNode } from "react";
import {
  GO_LIVE_MONTHS, GO_LIVE_TRADES_ABOUT, NO_PROVEN_SIGNALS, PAPER_LABEL, REFERENCE_STRATEGY_WORDS, REGIME_TIP, RESEARCH_ONLY,
  regimeWords,
} from "../../lib/ui/constants.ts";
import { fmtDate, fmtLocal } from "../../lib/ui/format.ts";
import { pagePath } from "../../lib/ui/routes.ts";
import type { GoLive, PageBase, StatusBlock } from "../../lib/ui/types.ts";
import { Icon } from "../ui/icon.tsx";
import { SessionChip } from "./session-chip.tsx";
import { PaperTag } from "../ui/primitives.tsx";

export function StatusChips({ status, cutoff }: { status: StatusBlock; cutoff?: string }) {
  const fr = status.freshness;
  const m = status.market, lt = status.session.local_time;
  return (
    <div className="chips">
      <SessionChip status={status} cutoff={cutoff} />
      <span className="md-chip" data-tip={REGIME_TIP}>
        Market mood: <b>{regimeWords(status.regime)}</b>
      </span>
      {fr ? (
        <span
          className="md-chip"
          data-tip={
            fr.state === "unknown"
              ? "The build time of this page is not known."
              : `Page data built ${fmtLocal(fr.built_at, m, lt, true)}, ${fr.age_minutes} min ago${cutoff ? `; cut-off ${fmtLocal(cutoff, m, lt, true)}` : ""}. Nothing stored after the cut-off is used. Stale after 8 hours.`
          }
        >
          <Icon name={fr.state === "fresh" ? "check" : "warning"} />
          {freshnessWords(fr.state, fr.built_at ? fmtLocal(fr.built_at, m, lt) : null, status.as_of)}
        </span>
      ) : null}
      <PaperTag label={status.paper_label || PAPER_LABEL} />
    </div>
  );
}

/** "Updated 08:41 IST (data up to the 9 Oct close)"; an old page says so first. */
export function freshnessWords(state: string, builtAt: string | null, asOf: string | null | undefined): string {
  const data = asOf ? ` (data up to the ${fmtDate(asOf, false)} close)` : "";
  if (state === "unknown" || !builtAt) return `Update time not known${data}`;
  return `${state === "stale" ? "Out of date: updated" : "Updated"} ${builtAt}${data}`;
}

/** <PageHead page={payload} title="Watchlist" subtitle="..."/>: the h1 of the page and the status chips. */
export function PageHead({ page, title, subtitle, children }: { page: PageBase; title: ReactNode; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <section className="phead" aria-label="Session and freshness">
      <div>
        <h1>{title}</h1>
        {subtitle ? <div className="sub">{subtitle}</div> : null}
      </div>
      <StatusChips status={page.status} cutoff={page.cutoff} />
      {children}
    </section>
  );
}

/** The go-live sentence of the signals band: whose numbers they are (the reference strategy, rm_common.go_live) and
 *  where it stands against each part of the bar (docs/ux/plain_language_review.md W7). */
export function goLiveSentence(goLive: GoLive): string {
  const done = Math.max(0, GO_LIVE_TRADES_ABOUT - goLive.trades_needed);
  const months = `${goLive.months_forward.toFixed(1)} of ${GO_LIVE_MONTHS} months`;
  const beats = goLive.beats_best_baseline === true
    ? "has beaten the simple benchmarks after fees"
    : goLive.beats_best_baseline === false
      ? "has not yet beaten the simple benchmarks (like always buying) after fees"
      : "it is too early to say whether it beats the simple benchmarks (like always buying) after fees";
  return `No strategy has passed the test yet. ${REFERENCE_STRATEGY_WORDS} has finished ${done} of about ${GO_LIVE_TRADES_ABOUT} test trades and ${months}, and ${beats}.`;
}

/** The signals band: "Not proven yet: these are tests, not tips." until a strategy meets the go-live bar (then the
 *  success band). `context` ends the sentence for the page ("The ranking below says who agrees; it is not advice."). */
export function SignalsBand({ page, goLive, strategies, context = "Nothing here is advice." }: { page: PageBase; goLive: GoLive | null | undefined; strategies?: number; context?: string }) {
  const label = page.status.paper_label || PAPER_LABEL;
  const track = pagePath(page.market, "track");
  if (goLive?.proven) {
    return (
      <section className="mb-alert band success" aria-label="Signals">
        <Icon name="check" />
        <div>
          <b className="t">A strategy has passed the test</b>
          <div className="s">{label}. It still shows what a tested strategy would do on paper, not what to do with your money; the rankings say who agrees. This is not advice.</div>
        </div>
        <Link className="md-btn text act" href={track} style={{ color: "inherit" }}>
          Track record <Icon name="chevron_right" />
        </Link>
      </section>
    );
  }
  const bar = goLive ? ` ${goLiveSentence(goLive)}` : strategies ? ` None of the ${strategies} strategies has passed the test yet.` : "";
  return (
    <section className="mb-alert band" aria-label="Signals">
      <Icon name="block" />
      <div>
        <b className="t">{NO_PROVEN_SIGNALS}</b>
        <div className="s">{`${label}.${bar} ${context}`}</div>
      </div>
      <Link className="md-btn text act" href={track} style={{ color: "inherit" }}>
        Track record <Icon name="chevron_right" />
      </Link>
    </section>
  );
}

/** The page footer: research only, then the build's as_of, cutoff and built_at and the endpoint read behind a
 *  "Technical details" toggle (L5). */
export function PageFooter({ page, endpoint }: { page: PageBase; endpoint?: string }) {
  return (
    <footer>
      {RESEARCH_ONLY}{" "}
      <details className="mb-tech">
        <summary>Technical details</summary>
        as_of {page.as_of ?? "—"} · cutoff {page.cutoff ?? "—"} · built_at {page.built_at ?? "—"}
        {endpoint ? (
          <>
            {" · "}
            <code>{`/api/v1/markets/${page.market}/${endpoint}`}</code>
          </>
        ) : null}
      </details>
    </footer>
  );
}
