"""Dark colour roles of the cockpit design system (B7): writes design/system/tokens-dark.css.

The same token names as tokens.css, colour roles only (sizes, type, motion stay in tokens.css). Opt-in: a page that
wants a dark scheme inlines tokens-dark.css after tokens.css; the app does not import it. Applied when the reader's
system asks for dark (`prefers-color-scheme: dark`, unless the page sets data-theme="light") or when the page sets
data-theme="dark". Every text pair a page reads is checked for WCAG AA (4.5:1) by `python design/system/dark_tokens.py
--check` and by web/lib/ui/tests/dark-tokens.test.ts. Deterministic: run `python design/system/dark_tokens.py` to
rewrite the CSS from DARK below.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "tokens-dark.css"

# Scheme v2 dark: the sidebar's navy family for surfaces (page #25293c, cards #2f3349), the same periwinkle accent
# lifted for dark, up/down/warn/info as light tones on dark tints. Never colour alone still holds: the components
# carry the signs, arrows and words.
DARK: dict[str, str] = {
    "color-scheme": "dark",
    "--md-sys-color-primary": "#9a9cf8",
    "--md-sys-color-on-primary": "#1d1f45",
    "--md-sys-color-primary-container": "#3a3d73",
    "--md-sys-color-on-primary-container": "#d4d5ff",
    "--md-sys-color-secondary": "#a3a9bd",
    "--md-sys-color-on-secondary": "#25293c",
    "--md-sys-color-secondary-container": "#3b4057",
    "--md-sys-color-on-secondary-container": "#d7d9e6",
    "--md-sys-color-tertiary": "#b9a3fb",
    "--md-sys-color-on-tertiary": "#2a1d52",
    "--md-sys-color-tertiary-container": "#3d3170",
    "--md-sys-color-on-tertiary-container": "#ddd2ff",
    "--md-sys-color-error": "#fb8585",
    "--md-sys-color-on-error": "#3b0d0d",
    "--md-sys-color-error-container": "#4c2429",
    "--md-sys-color-on-error-container": "#fecaca",
    "--md-sys-color-surface": "#2f3349",
    "--md-sys-color-on-surface": "#dfe0ec",
    "--md-sys-color-surface-variant": "#363b53",
    "--md-sys-color-on-surface-variant": "#aab0c5",
    "--md-sys-color-surface-dim": "#25293c",
    "--md-sys-color-surface-bright": "#3b4057",
    "--md-sys-color-surface-container-lowest": "#2f3349",
    "--md-sys-color-surface-container-low": "#25293c",
    "--md-sys-color-surface-container": "#363b53",
    "--md-sys-color-surface-container-high": "#3d4259",
    "--md-sys-color-surface-container-highest": "#464c66",
    "--md-sys-color-outline": "#7a809a",
    "--md-sys-color-outline-variant": "#464c66",
    "--md-sys-color-inverse-surface": "#e7e8f0",
    "--md-sys-color-inverse-on-surface": "#2f3349",
    "--md-sys-color-inverse-primary": "#5a5ee6",
    "--md-sys-color-surface-tint": "#9a9cf8",
    "--md-sys-color-background": "#25293c",
    "--md-sys-color-on-background": "#dfe0ec",
    "--md-sys-color-scrim": "#000000",
    "--md-sys-color-shadow": "#000000",
    "--mb-sidebar-bg": "#1f2233",
    "--mb-sidebar-ink": "#d7d8e5",
    "--mb-sidebar-muted": "#a3a7bd",
    "--mb-color-up": "#4ade80",
    "--mb-color-on-up": "#0b2a17",
    "--mb-color-up-container": "#1e3d2c",
    "--mb-color-on-up-container": "#a7f3c0",
    "--mb-color-down": "#fb8585",
    "--mb-color-on-down": "#3b0d0d",
    "--mb-color-down-container": "#4c2429",
    "--mb-color-on-down-container": "#fecaca",
    "--mb-color-neutral": "#a3a9bd",
    "--mb-color-on-neutral": "#25293c",
    "--mb-color-neutral-container": "#3b4057",
    "--mb-color-on-neutral-container": "#d7d9e6",
    "--mb-color-warn": "#f5a524",
    "--mb-color-on-warn": "#2e1c00",
    "--mb-color-warn-container": "#4a3517",
    "--mb-color-on-warn-container": "#fcd88a",
    "--mb-color-info": "#38bdd3",
    "--mb-color-info-container": "#173f49",
    "--mb-color-on-info-container": "#a5ecf6",
    "--mb-verdict-no-bg": "#4c2429",
    "--mb-verdict-no-box": "#fb8585",
    "--mb-verdict-no-ink": "#fecaca",
    "--mb-verdict-strong-bg": "#1b5232",
    "--mb-verdict-strong-box": "#4ade80",
    "--mb-verdict-strong-ink": "#d1fadf",
    "--mb-verdict-ok-bg": "#1e3d2c",
    "--mb-verdict-ok-box": "#22c55e",
    "--mb-verdict-ok-ink": "#a7f3c0",
    "--mb-color-backtest-container": "repeating-linear-gradient(135deg, rgba(154,156,248,.18) 0 3px, transparent 3px 6px)",
    "--mb-chart-1": "#9a9cf8",
    "--mb-chart-2": "#f5a524",
    "--mb-chart-3": "#38bdd3",
    "--mb-chart-4": "#f06aae",
    "--mb-chart-1-fill": "rgba(154,156,248,.32)",
    "--mb-chart-2-fill": "rgba(245,165,36,.26)",
    "--mb-chart-3-fill": "rgba(56,189,211,.26)",
    "--mb-chart-band-50": "rgba(154,156,248,.40)",
    "--mb-chart-band-80": "rgba(154,156,248,.18)",
    "--mb-chart-fan": "rgba(154,156,248,.14)",
    "--mb-card-shadow": "0 2px 8px rgba(0, 0, 0, .35), 0 0 1px rgba(0, 0, 0, .5)",
    "--mb-card-shadow-hover": "0 6px 18px rgba(0, 0, 0, .45), 0 0 1px rgba(0, 0, 0, .5)",
    "--md-sys-elevation-2": "0 4px 14px rgba(0, 0, 0, .4), 0 0 1px rgba(0, 0, 0, .5)",
    "--md-sys-elevation-3": "0 8px 24px rgba(0, 0, 0, .45), 0 0 1px rgba(0, 0, 0, .55)",
    "--md-sys-elevation-4": "0 12px 32px rgba(0, 0, 0, .5)",
    "--md-sys-elevation-5": "0 16px 40px rgba(0, 0, 0, .55)",
}

# Text (or icon) colour on background pairs a page reads, each WCAG AA 4.5:1 in the dark scheme.
PAIRS: list[tuple[str, str]] = [
    ("--md-sys-color-on-surface", "--md-sys-color-surface-container-lowest"),
    ("--md-sys-color-on-surface", "--md-sys-color-surface-container-low"),
    ("--md-sys-color-on-surface", "--md-sys-color-surface-container"),
    ("--md-sys-color-on-surface-variant", "--md-sys-color-surface-container-lowest"),
    ("--md-sys-color-on-surface-variant", "--md-sys-color-surface-container-low"),
    ("--md-sys-color-on-surface-variant", "--md-sys-color-surface-container"),
    ("--md-sys-color-primary", "--md-sys-color-surface-container-lowest"),
    ("--md-sys-color-primary", "--md-sys-color-surface-container-low"),
    ("--md-sys-color-on-primary", "--md-sys-color-primary"),
    ("--md-sys-color-on-primary-container", "--md-sys-color-primary-container"),
    ("--md-sys-color-on-secondary-container", "--md-sys-color-secondary-container"),
    ("--md-sys-color-on-tertiary-container", "--md-sys-color-tertiary-container"),
    ("--md-sys-color-on-error-container", "--md-sys-color-error-container"),
    ("--md-sys-color-inverse-on-surface", "--md-sys-color-inverse-surface"),
    ("--mb-sidebar-ink", "--mb-sidebar-bg"),
    ("--mb-sidebar-muted", "--mb-sidebar-bg"),
    ("--mb-color-up", "--md-sys-color-surface-container-lowest"),
    ("--mb-color-down", "--md-sys-color-surface-container-lowest"),
    ("--mb-color-warn", "--md-sys-color-surface-container-lowest"),
    ("--mb-color-info", "--md-sys-color-surface-container-lowest"),
    ("--mb-color-on-up-container", "--mb-color-up-container"),
    ("--mb-color-on-down-container", "--mb-color-down-container"),
    ("--mb-color-on-neutral-container", "--mb-color-neutral-container"),
    ("--mb-color-on-warn-container", "--mb-color-warn-container"),
    ("--mb-color-on-info-container", "--mb-color-info-container"),
    ("--mb-color-on-up", "--mb-color-up"),
    ("--mb-color-on-down", "--mb-color-down"),
    ("--mb-color-on-warn", "--mb-color-warn"),
    ("--mb-verdict-no-ink", "--mb-verdict-no-bg"),
    ("--mb-verdict-strong-ink", "--mb-verdict-strong-bg"),
    ("--mb-verdict-ok-ink", "--mb-verdict-ok-bg"),
]
AA = 4.5


def luminance(hex_colour: str) -> float:
    hex_colour = hex_colour.lstrip("#")
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def failures() -> list[str]:
    out = []
    for fg, bg in PAIRS:
        ratio = contrast(DARK[fg], DARK[bg])
        if ratio < AA:
            out.append(f"{fg} on {bg}: {ratio:.2f}:1")
    return out


def css() -> str:
    body = "".join(f"  {name}: {value};\n" for name, value in DARK.items())
    indented = "".join(f"    {name}: {value};\n" for name, value in DARK.items())
    return (
        "/* market-brief cockpit: DARK colour roles of the design tokens (generated by design/system/dark_tokens.py; edit\n"
        "   the DARK table there and rerun). Same token names as tokens.css, colour roles only. Opt-in: inline this file after\n"
        "   tokens.css; the web app does not import it. Applies when the reader's system asks for dark (unless the page sets\n"
        "   data-theme=\"light\") or when the page sets data-theme=\"dark\". Every text pair is WCAG AA (4.5:1), checked by\n"
        "   `python design/system/dark_tokens.py --check`. */\n"
        f":root[data-theme=\"dark\"] {{\n{body}}}\n"
        "@media (prefers-color-scheme: dark) {\n"
        f"  :root:not([data-theme=\"light\"]) {{\n{indented}  }}\n}}\n"
    )


def main(argv: list[str]) -> int:
    bad = failures()
    if "--check" in argv:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != css()
        for line in bad:
            print("below AA:", line)
        if stale:
            print("tokens-dark.css is out of date: run python design/system/dark_tokens.py")
        print(f"{len(PAIRS)} pairs checked, {len(bad)} below AA")
        return 1 if bad or stale else 0
    if bad:
        print("\n".join("below AA: " + line for line in bad))
        return 1
    OUT.write_text(css(), encoding="utf-8")
    print(f"wrote {OUT.name}: {len(DARK)} declarations, {len(PAIRS)} pairs AA")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
