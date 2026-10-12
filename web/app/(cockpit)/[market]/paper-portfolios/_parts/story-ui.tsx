"use client";
// Small shared pieces of the Paper portfolio page v3 (UX3): a side's tag, the ⓘ popover button, a signed money result
// with an arrow (colour plus icon, never colour alone), the win/lose bar and the bar towards the sell date. Paper only.
import { Icon } from "../../../../../components/ui/icon.tsx";
import { DASH, money } from "../../../../../lib/ui/format.ts";
import { SIDE_ABOUT, SIDE_NAME, SIDE_SHORT, type Side } from "../../../../../lib/strategy-pages/portfolio-v3.ts";

export function SideTag({ side, short = false }: { side: Side; short?: boolean }) {
  return <span className={`pp-side ${side}`} data-tip={SIDE_ABOUT[side]}><i aria-hidden="true" />{short ? SIDE_SHORT[side] : SIDE_NAME[side]}</span>;
}

/** The ⓘ button: its text shows in the app's tooltip layer on hover, focus or tap. */
export function InfoTip({ tip, label = "Details" }: { tip: string; label?: string }) {
  return (
    <button className="pp-info" type="button" data-tip={tip} aria-label={label}>
      <Icon name="info" />
    </button>
  );
}

/** A signed money result: coloured, with an up or down arrow and the sign, so it never relies on colour. */
export function Money({ currency, value, decimals = 0, big = false, pct }: { currency: string; value: number | null | undefined; decimals?: number; big?: boolean; pct?: number | null }) {
  if (value === null || value === undefined) return <span className="muted">{DASH}</span>;
  const dir = value > 0 ? "up" : value < 0 ? "down" : "flat";
  return (
    <span className="pp-money-wrap">
      <span className={`pp-money ${dir}${big ? " big" : ""}`}>
        <Icon name={dir === "up" ? "arrow_upward" : dir === "down" ? "arrow_downward" : "remove"} />
        {money(currency, value, decimals, true)}
      </span>
      {pct !== null && pct !== undefined ? <span className="pp-pct">{(pct > 0 ? "+" : pct < 0 ? "−" : "") + Math.abs(pct).toFixed(1)}%</span> : null}
    </span>
  );
}

/** Going as predicted (green) against going the other way (red) and no price yet (grey), as one bar. */
export function WinLoseBar({ win, lose, pending = 0, label }: { win: number; lose: number; pending?: number; label: string }) {
  const n = win + lose + pending;
  return (
    <div className={`pp-wl${n ? "" : " empty"}`} role="img" aria-label={label}>
      {win ? <span className="w" style={{ flex: win }} /> : null}
      {lose ? <span className="l" style={{ flex: lose }} /> : null}
      {pending ? <span className="p" style={{ flex: pending }} /> : null}
    </div>
  );
}

/** The counts under a win/lose bar, with icons. */
export function WinLoseCounts({ win, lose, pending = 0, words = true }: { win: number; lose: number; pending?: number; words?: boolean }) {
  return (
    <div className="pp-wlc">
      <span className="ok"><Icon name="check" />{win}{words ? " going as predicted" : ""}</span>
      <span className="bad"><Icon name="close" />{lose}{words ? " going against" : ""}</span>
      {pending ? <span className="muted"><Icon name="pending" />{pending}{words ? " no price yet" : ""}</span> : null}
    </div>
  );
}

/** How far a hold is towards its sell date: sessions held of the k + 1 sessions from the buy to the sale. */
export function HoldProgress({ held, total, tip }: { held: number; total: number; tip: string }) {
  const share = total > 0 ? Math.min(1, Math.max(0, held / total)) : 0;
  return (
    <span className="pp-prog" data-tip={tip} tabIndex={0} role="img" aria-label={tip}>
      <span style={{ width: `${Math.round(share * 100)}%` }} />
    </span>
  );
}
