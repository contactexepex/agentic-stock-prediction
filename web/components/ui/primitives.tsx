// Small shared parts of every page, as the approved mockups draw them (design/mockups/_shared/shell.js) on the
// design system's classes (web/styles/components.css, page.css). Never colour alone: every up/down carries its sign or
// an arrow and every status its word; every signal carries the Paper tag.
import Link from "next/link";
import type { ReactNode } from "react";
import { FAMILY, FAMILY_TONE, NEWS_STATUS, SENTIMENT_FLAT_BAND, type Family } from "../../lib/ui/constants.ts";
import { DASH, direction, money, oddsPosition, pct, sentimentClass, signed } from "../../lib/ui/format.ts";
import { Icon } from "./icon.tsx";

/** A signed percent (or other unit) with its direction class: "+1.20%" green, "−0.40%" red, sign always shown. */
export function Delta({ value, decimals = 2, unit = "%" }: { value: number | null | undefined; decimals?: number; unit?: string }) {
  if (value === null || value === undefined) return <span className="muted">{DASH}</span>;
  return <span className={`mb-delta ${direction(value)}`}>{signed(value, decimals, unit)}</span>;
}

/** A signed money amount with its direction class. */
export function MoneyDelta({ currency, value, decimals = 0 }: { currency: string; value: number | null | undefined; decimals?: number }) {
  if (value === null || value === undefined) return <span className="muted">{DASH}</span>;
  return <span className={`mb-delta ${direction(value)}`}>{money(currency, value, decimals, true)}</span>;
}

/** The odds meter: a probability of a rise on a 30%..70% track with the coin-flip mark in the middle. */
export function Odds({ p, tip }: { p: number | null | undefined; tip?: string }) {
  if (p === null || p === undefined) return <span className="muted" data-tip={tip}>{DASH}</span>;
  return (
    <span className="mb-odds" data-tip={tip ?? `Chance of a rise ${pct(p, 1)}; 50% is a coin flip.`}>
      <svg viewBox="0 0 64 14" aria-hidden="true">
        <rect className="track" x={0} y={5} width={64} height={4} rx={2} />
        <line className="mid" x1={32} x2={32} y1={1} y2={13} />
        <circle className={`dot ${p > 0.5 ? "up" : "dn"}`} cx={oddsPosition(p)} cy={7} r={4.5} />
      </svg>
      <b>{pct(p)}</b>
    </span>
  );
}

/** The Paper tag every signal carries; its tooltip is the payload's paper label. */
export function PaperTag({ label }: { label: string }) {
  return (
    <span className="mb-tag paper" data-tip={label}>
      paper
    </span>
  );
}

export type Tone = "" | "success" | "danger" | "warn" | "info" | "neutral" | "paper";

/** A label badge (tint plus ink), optionally with an icon. */
export function Label({ tone = "", icon, tip, children }: { tone?: Tone; icon?: string; tip?: string; children: ReactNode }) {
  return (
    <span className={`mb-label${tone ? " " + tone : ""}`} data-tip={tip}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </span>
  );
}

/** A family's colour swatch (rule, baseline, AI). */
export function FamilySwatch({ family }: { family: Family }) {
  return <i className={`sw ${FAMILY[family][2]}`} aria-hidden="true" />;
}

/** A label in the family's tone with its swatch: <FamilyLabel family="ai">AI trader</FamilyLabel>. */
export function FamilyLabel({ family, children }: { family: Family; children: ReactNode }) {
  return (
    <span className={`mb-label${FAMILY_TONE[family] ? " " + FAMILY_TONE[family] : ""}`}>
      <FamilySwatch family={family} />
      {children}
    </span>
  );
}

/** A news item's verification status as a badge with its word, icon and explanation. */
export function StatusBadge({ status }: { status: string }) {
  const [word, tip, icon] = NEWS_STATUS[status] ?? [status, "", null];
  return (
    <span className={`md-badge ${status}`} data-tip={tip || undefined}>
      {icon ? <Icon name={icon} /> : null}
      {word}
    </span>
  );
}

/** The news analyst's sentiment as a direction square with an arrow (flat inside the ±0.05 band). */
export function SentimentSquare({ value }: { value: number | null | undefined }) {
  const s = sentimentClass(value, SENTIMENT_FLAT_BAND);
  const tip = value === null || value === undefined
    ? "sentiment not scored"
    : `sentiment ${value > 0 ? "+" : ""}${value} (−1 very negative to +1 very positive), the news analyst’s score`;
  return (
    <span className={`mb-dir ${s}`} role="img" aria-label={`sentiment ${value ?? "n/a"}`} data-tip={tip}>
      <Icon name={s === "up" ? "arrow_upward" : s === "dn" ? "arrow_downward" : "remove"} />
    </span>
  );
}

/** An icon tile (KPI cards, company cells). */
export function Avatar({ icon, tone = "", size = "" }: { icon: string; tone?: Tone; size?: "" | "sm" | "lg" }) {
  return (
    <span className={["mb-avatar", tone, size].filter(Boolean).join(" ")} aria-hidden="true">
      <Icon name={icon} />
    </span>
  );
}

/** A KPI card: icon tile, label, value, sub line. */
export function Kpi({ icon, tone = "", label, value, sub, tip }: { icon: string; tone?: Tone; label: ReactNode; value: ReactNode; sub?: ReactNode; tip?: string }) {
  return (
    <div className="mb-kpi" data-tip={tip}>
      <Avatar icon={icon} tone={tone} />
      <div>
        <div className="l">{label}</div>
        <div className="v">{value}</div>
      </div>
      {sub !== undefined ? <div className="s">{sub}</div> : null}
    </div>
  );
}

/** The KPI row (four across on desktop, two on tablets, one column of compact cards on phones). */
export function KpiRow({ label = "At a glance", children }: { label?: string; children: ReactNode }) {
  return (
    <section className="kpis" aria-label={label}>
      {children}
    </section>
  );
}

/** A white card section. `label` names it for screen readers when it has no heading. */
export function Card({ label, id, className = "", children }: { label?: string; id?: string; className?: string; children: ReactNode }) {
  return (
    <section className={`card${className ? " " + className : ""}`} aria-label={label} id={id}>
      {children}
    </section>
  );
}

/** A card head: the h2 title, an optional explain button, and items pushed to the end (tabs, links, notes). */
export function CardHead({ title, help, end, id }: { title: ReactNode; help?: string; end?: ReactNode; id?: string }) {
  return (
    <div className="head">
      <h2 id={id}>{title}</h2>
      {help ? (
        <button className="md-help" type="button" data-tip={help} aria-label="Explain">
          ?
        </button>
      ) : null}
      {end !== undefined ? <div className="end">{end}</div> : null}
    </div>
  );
}

/** The quiet dashed panel of an empty part of a card ("No strategy buys any company at N+1 today."). */
export function Quiet({ children }: { children: ReactNode }) {
  return <div className="quiet">{children}</div>;
}

/** A "go to" link at the end of a card head. */
export function GoLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link className="go" href={href}>
      {children}
      <Icon name="chevron_right" />
    </Link>
  );
}
