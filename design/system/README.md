# Cockpit design system (Material 3 light)

Shared look of every cockpit page: tokens, components, icons and the app shell. Living style guide:
`styleguide.html` (built from `styleguide.template.html` by `python design/system/build_styleguide.py`;
screenshots `styleguide-1280-full.png`, `styleguide-390-full.png`, `styleguide-390-viewport.png`).

## Files
| File | What |
|---|---|
| `tokens.css`, `tokens-variant-*.css` | `:root` custom properties: M3 colour roles (`--md-sys-color-*`), tonal-palette steps, semantic finance tokens (`--mb-color-up/down/neutral/warn`, hit/miss, Live/Back-test/Mock/Paper), chart tokens (`--mb-chart-*`), the M3 type scale (`--md-sys-typescale-*` + `.md-body-medium` style classes), shape, elevation, state-layer opacities, spacing, motion, focus ring |
| `components.css` | App shell (`.mb-app`, `.mb-rail`, `.mb-navbar`, `.mb-topbar`, `.mb-content`), cards (`.md-card.elevated/filled/outlined`), buttons (`.md-btn.filled/tonal/outlined/text`, `.md-icon-btn`, `.md-help`), segmented buttons (`.md-segmented[.dense]`), chips (`.md-chip.assist/filter/small`), provenance tags (`.mb-tag.live/bt/mock/paper/derived/coming`), badges (`.md-badge` incl. verification statuses), direction squares (`.mb-dir.up/dn/flat/unk`), outcome marks (`.mb-mark.ok/no/na`), tooltip (`.md-tooltip`), data table (`.md-table`), key-value list (`.md-kv`), odds meter (`.mb-odds`), strength bar (`.mb-bar`), progress (`.md-progress`), KPI tile (`.mb-kpi`), expansion panel (`details.md-expansion`), `.md-pre` |
| `icons.svg` | 40 Material Symbols Outlined glyphs as `<symbol id="ms-NAME">` (Apache 2.0, `LICENSE-material-symbols.txt`, copied unchanged from google/material-design-icons) |
| `system.py` | `inline_system(html, icons=None)`: replaces `<!--@@SYSTEM_CSS@@-->` with both stylesheets and `<!--@@ICONS@@-->` with the sprite (all icons or a named subset) |
| `check_page.js` | Playwright check of a built page at 1280 and 390 px (console errors, external requests, horizontal overflow) with screenshots; uses the pre-installed Chromium |

## Palette
One seed, `#1A73E8` (HCT hue 265.6, chroma 65.1, tone 49.9), through Google's `@material/material-color-utilities`
0.4.0 `SchemeVibrant` (the high-chroma Material You scheme) at contrast level 0. Light scheme only. The first
pass used a muted seed with the tonal-spot scheme and read grey; the owner rejected it, so the system now uses
the vibrant scheme, white cards on a tinted `surface-container-low` page, 24 px card corners, pill chips and
tags, and the primary container for the decision header. Two alternative schemes with the same structure are
kept as override files for mockups: `tokens-variant-indigo.css` (seed `#4F46E5`) and `tokens-variant-teal.css`
(seed `#00796B`, tonal spot); build a page with `MB_TOKENS_EXTRA=design/system/tokens-variant-indigo.css` to
see it. Side by side on the real HDFC Bank page: `mockup-variants.png` (blue, indigo, teal).

Key roles and WCAG contrast on their "on" colour (text on a container needs 4.5:1):

| Role | Hex | On | Contrast |
|---|---|---|---|
| primary | `#005bc0` | `#ffffff` | 7.2:1 |
| primary container (decision header, selected states) | `#d8e2ff` | `#004493` | 8.4:1 |
| secondary | `#585c7e` | `#ffffff` | 6.3:1 |
| secondary container | `#dfe0ff` | `#414465` | 7.6:1 |
| tertiary container (Paper tag) | `#e7deff` | `#4d4273` | 7.4:1 |
| error | `#ba1a1a` | `#ffffff` | 6.5:1 |
| surface | `#f9f9ff` | `#191b23` | 16.1:1 |
| surface container low (page) / container (tiles) | `#f1f3ff` / `#ebedfa` | `#191b23` | 14.6:1 / 13.8:1 |
| outline on surface | `#727785` | | 4.5:1 |
| inverse surface (tooltips) | `#2c303a` | `#f0f0fb` | 12.4:1 |

Semantic tokens are HCT tonal palettes on fixed hues, so they sit in the same tone system as the roles:
up `#00732e` (hue 150, 5.7:1 on the surface), down `#c92f29` (hue 25, 5.1:1), neutral `#73777d` (4.3:1, icons
and large text only), warn/unclear `#b37800` (3.6:1, icons only; text uses `#624000` on `#ffddb2`, 7.2:1).
Containers: up `#85f496`/`#003913` 9.6:1, down `#ffdad6`/`#7e0007` 8.6:1. Hit = up, miss = down.

**Never colour alone.** Up/down/hit/miss always carry a glyph (arrow, tick, cross) and the word; the provenance
tags carry a texture (Back-test hatched, Mock dashed, derived dotted) besides the colour. The dataviz checker
(`scripts/validate_palette.js` of the dataviz skill) puts up vs down in the CVD warn band (protan ΔE 6.8), which
is why that rule is a rule.

## Chart colours (dataviz skill)
Series 1 is the primary role itself (vibrant enough for the dataviz chroma floor); the other slots are a
validated set:

| Slot | Hex | Note |
|---|---|---|
| series 1 | `#005bc0` | the primary: ranges, the model, everything "ours"; bands at alpha .34 (50%) and .14 (80%) |
| series 2 | `#df7d00` | 2.83:1 on the surface: direct labels or the table view required |
| series 3 | `#876cc8` | |
| series 4 | `#009486` | |

Validator runs: series 2-4 with `#0079d1` as slot 1 (light, surface `#f8f9ff`) pass adjacent (worst CVD ΔE 11.1,
normal-vision 20.4; series 2 contrast WARN) and slots 1, 2, 4 pass all-pairs (worst CVD 12.2, normal-vision
15.8); the primary `#005bc0` against up and down (all pairs, white surface) passes every hard gate with up vs
down in the warn band (ΔE 6.8). Rerun the four-slot check if slots 2-4 are ever used beside the primary in one
chart. Ink line = on-surface, grid =
surface-container-high, labels = on-surface-variant, future area = surface-container-low.

## How a page uses it
1. Template: put `<!--@@SYSTEM_CSS@@-->` in `<head>` and `<!--@@ICONS@@-->` first in `<body>`; write page-local
   layout CSS after it, using only token names (`var(--md-sys-color-...)`, `var(--mb-color-...)`). No page-local
   colours. Icons: `<svg class="ms"><use href="#ms-check"/></svg>`.
2. Builder: `from system import inline_system` (with `design/system` on `sys.path`) and
   `html = inline_system(template_with_data)`. Output is one self-contained file: no CDN, no font, no request.
3. Shell: wrap the page in `.mb-app` with `.mb-rail` (desktop), `.mb-topbar` (title + India/US segmented
   button), `.mb-content > .mb-content-inner`, and `.mb-navbar` (phone). Pages not built yet get `.coming`
   nav items ("soon" pill + tooltip); the segmented button keeps the current market pressed.
4. Check: `node design/system/check_page.js <page.html> <out-dir> <prefix> ['#chart svg']`.
5. Tooltips: `data-tip="..."` on any element plus the small script in `styleguide.template.html` /
   `design/decision/template.html` (hover, focus, tap; Escape closes).

Typography is the system sans stack (no web font); numbers in tables use `.md-numeric` (tabular figures).
Surfaces: the page is `surface-container-low`, cards are `surface-container-lowest` (white, 24 px corners, no
shadow), tiles and columns inside a card are `surface-container` (16 px), the rail and navigation bar are
`surface-container`. Breakpoints: shell rail from 600 px (navigation bar below); pages keep their own content breakpoint (the
decision page uses 760 px). Phone gutter 16 px, no horizontal page scroll.
