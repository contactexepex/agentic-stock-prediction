// The page head every 2.0 page opens with (the mockups' pageHead): the title and subtitle, then the chips of the
// shared status block: session (open now / opens at / closed / no session), regime, freshness of the page data with
// the cut-off, and the Paper tag. The signals band (go-live) and the footer are here too.
import Link from "next/link";
import type { ReactNode } from "react";
import { GO_LIVE_MONTHS, NO_PROVEN_SIGNALS, PAPER_LABEL, REGIME_TIP, RESEARCH_ONLY } from "../../lib/ui/constants.ts";
import { fmtLocal } from "../../lib/ui/format.ts";
import { pagePath } from "../../lib/ui/routes.ts";
import type { GoLive, PageBase, StatusBlock } from "../../lib/ui/types.ts";
import { Icon } from "../ui/icon.tsx";
import { PaperTag } from "../ui/primitives.tsx";

/** The session chip's words from the status block (evaluated at the build's cut-off, not at request time). */
export function sessionWords(status: StatusBlock): { open: boolean; text: ReactNode; tip: string } {
  const s = status.session, m = status.market, lt = s.local_time;
  const tip = `Session ${fmtLocal(s.session_open_utc, m, lt)}–${fmtLocal(s.session_close_utc, m, lt)}.`;
  if (!s.trading_day) return { open: false, text: "No session today", tip };
  if (s.in_session) return { open: true, text: <b>Open now</b>, tip };
  if (s.late_run) return { open: false, text: "Closed for today", tip };
  return { open: false, text: <span>Opens <b>{fmtLocal(s.session_open_utc, m, lt)}</b></span>, tip };
}

export function StatusChips({ status, cutoff }: { status: StatusBlock; cutoff?: string }) {
  const session = sessionWords(status);
  const fr = status.freshness;
  const m = status.market, lt = status.session.local_time;
  return (
    <div className="chips">
      <span className="md-chip" data-tip={session.tip}>
        <span className={`dot${session.open ? " open" : ""}`} aria-hidden="true" />
        {session.text}
      </span>
      <span className="md-chip" data-tip={REGIME_TIP}>
        Regime <b>{status.regime ?? "not stored"}</b>
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
          <b>{fr.state}</b>
          {fr.built_at ? ` · built ${fmtLocal(fr.built_at, m, lt)}` : ""}
        </span>
      ) : null}
      <PaperTag label={status.paper_label || PAPER_LABEL} />
    </div>
  );
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

/** The signals band: "No proven strong signals today" until a strategy meets the go-live bar (then the success band).
 *  `context` ends the sentence for the page ("The ranking below says who agrees; it is not advice."). */
export function SignalsBand({ page, goLive, strategies, context = "Nothing here is advice." }: { page: PageBase; goLive: GoLive | null | undefined; strategies?: number; context?: string }) {
  const label = page.status.paper_label || PAPER_LABEL;
  const track = pagePath(page.market, "track");
  if (goLive?.proven) {
    return (
      <section className="mb-alert band success" aria-label="Signals">
        <Icon name="check" />
        <div>
          <b className="t">A strategy has met the go-live bar</b>
          <div className="s">{label}. Strong signals may now appear on the strategy pages; the rankings still say who agrees, not what to do.</div>
        </div>
        <Link className="md-btn text act" href={track} style={{ color: "inherit" }}>
          Track record <Icon name="chevron_right" />
        </Link>
      </section>
    );
  }
  const bar = goLive
    ? ` None of the ${strategies ?? "registered"} strategies has met the go-live bar (${goLive.trades_needed} settled trades, ${goLive.months_forward} of ${GO_LIVE_MONTHS} months forward so far, beating the best baseline after costs).`
    : "";
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

/** The page footer: research only, the build's as_of, cutoff and built_at, and the endpoint read. */
export function PageFooter({ page, endpoint }: { page: PageBase; endpoint?: string }) {
  return (
    <footer>
      {RESEARCH_ONLY} as_of {page.as_of ?? "—"} · cutoff {page.cutoff ?? "—"} · built_at {page.built_at ?? "—"}
      {endpoint ? (
        <>
          {" · "}
          <code>{`/api/v1/markets/${page.market}/${endpoint}`}</code>
        </>
      ) : null}
    </footer>
  );
}
