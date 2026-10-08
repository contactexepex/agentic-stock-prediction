// Material Symbols from the sprite the root layout inlines once (components/icons/sprite.generated.ts).
import type { CSSProperties } from "react";

/** <Icon name="check" /> renders <svg class="ms"><use href="#ms-check"/></svg>, hidden from screen readers. */
export function Icon({ name, className = "ms", style }: { name: string; className?: string; style?: CSSProperties }) {
  const id = name.startsWith("ms-") ? name : `ms-${name}`;
  return (
    <svg className={className} aria-hidden="true" focusable="false" style={style}>
      <use href={`#${id}`} />
    </svg>
  );
}

/** The "?" explain button: its text shows in the tooltip on hover, focus or tap (TooltipLayer). */
export function HelpTip({ tip, label = "Explain" }: { tip: string; label?: string }) {
  return (
    <button className="md-help" type="button" data-tip={tip} aria-label={label}>
      ?
    </button>
  );
}
