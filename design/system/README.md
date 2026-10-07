# Cockpit design system ("terminal light")

Shared look of every cockpit page: tokens, components, icons and the app shell. One light scheme, modelled on the
trading terminals the owner pointed at (Meridian Terminal, TradingView symbol pages): a cool light-grey page, white
cards with hairline borders, one indigo accent, vivid green/red for signals and signed numbers, uppercase
micro-labels over large bold numerals, compact pill controls, tiny tinted LIVE / BACK-TEST / MOCK / PAPER tags.
Token names keep the Material role vocabulary (`--md-sys-color-*`) so nothing needed renaming. Living style guide:
`styleguide.html` (built from `styleguide.template.html` by `python design/system/build_styleguide.py`;
screenshots `styleguide-1280-full.png`, `styleguide-390-full.png`, `styleguide-390-viewport.png`).

## Files
| File | What |
|---|---|
| `tokens.css` | `:root` custom properties: colour roles (`--md-sys-color-*`), semantic finance tokens, verdict tokens (`--mb-verdict-*`) (`--mb-color-up/down/neutral/warn`, hit/miss, Live/Back-test/Mock/Paper), chart tokens (`--mb-chart-*`), the M3 type scale (`--md-sys-typescale-*` + `.md-body-medium` style classes), shape, elevation, state-layer opacities, spacing, motion, focus ring |
| `components.css` | App shell (`.mb-app`, `.mb-rail`, `.mb-navbar`, `.mb-topbar`, `.mb-content`), cards (`.md-card.elevated/filled/outlined`), buttons (`.md-btn.filled/tonal/outlined/text`, `.md-icon-btn`, `.md-help`), segmented buttons (`.md-segmented[.dense]`), chips (`.md-chip.assist/filter/small`), provenance tags (`.mb-tag.live/bt/mock/paper/derived/coming`), badges (`.md-badge` incl. verification statuses), direction squares (`.mb-dir.up/dn/flat/unk`), outcome marks (`.mb-mark.ok/no/na`), tooltip (`.md-tooltip`), data table (`.md-table`), key-value list (`.md-kv`), odds meter (`.mb-odds`), strength bar (`.mb-bar`), progress (`.md-progress`), KPI tile (`.mb-kpi`), expansion panel (`details.md-expansion`), `.md-pre` |
| `icons.svg` | 40 Material Symbols Outlined glyphs as `<symbol id="ms-NAME">` (Apache 2.0, `LICENSE-material-symbols.txt`, copied unchanged from google/material-design-icons) |
| `system.py` | `inline_system(html, icons=None)`: replaces `<!--@@SYSTEM_CSS@@-->` with both stylesheets and `<!--@@ICONS@@-->` with the sprite (all icons or a named subset) |
| `check_page.js` | Playwright check of a built page at 1280 and 390 px (console errors, external requests, horizontal overflow) with screenshots; uses the pre-installed Chromium |

## Palette (one scheme)
| Role | Hex | Use | Contrast |
|---|---|---|---|
| page | `#f5f6fa` | `surface-container-low`, the background | ink 16.4:1 |
| card | `#ffffff` with border `#e5e7eb` | `surface-container-lowest` + `--mb-card-border` | |
| tile | `#f3f4f6` | `surface-container`, tiles and columns inside a card | |
| ink | `#111827` | `on-surface` | 16.4:1 on the page |
| muted | `#6b7280` | `on-surface-variant`: labels, metadata | 4.8:1 on white |
| accent | `#4f46e5` | `primary`: active nav, section numbers, chart series 1, links | 6.3:1 on white |
| accent tint | `#eef2ff` / `#3730a3` | `primary-container` / on | 8.9:1 |
| up / hit | `#15803d` (tint `#dcfce7`, ink `#166534`) | green text, fills, LIVE tag | 5.0:1 on white; 6.5:1 on tint |
| down / miss | `#dc2626` (tint `#fee2e2`, ink `#991b1b`) | red text, fills | 4.8:1; 6.8:1 on tint |
| unclear | `#d97706` (tint `#fef3c7`, ink `#b45309`) | direction unknown | 4.5:1 on tint |
| Paper | `#f3e8ff` / `#5b21b6` | tertiary container | |
| tooltip | `#111827` / `#f9fafb` | inverse surface | 17.7:1 |

**Verdict (owner's rule):** NO is red (`--mb-verdict-no-*`: bg `#fee2e2`, box `#dc2626`, ink `#991b1b`, 6.8:1);
YES is green, darker for a strong signal (`--mb-verdict-strong-*`: bg `#bbf7d0`, box `#166534`, ink `#14532d`,
7.5:1) and lighter for an okay one (`--mb-verdict-ok-*`: bg `#dcfce7`, box `#15803d`, ink `#166534`, 6.5:1).
Strong = forecaster confidence >= 0.75 or anchored probability (model_prob + agent_adjustment) >= 0.65; the
decision builder sets `page.verdict.strength`. Components: `.mb-verdict.no | .yes-ok | .yes-strong`.

**Never colour alone.** Up/down/hit/miss always carry a glyph (arrow, tick, cross, or the sign on a number via
`.mb-delta`) and the word; provenance tags carry a texture (Back-test hatched, Mock dashed, derived dotted)
besides the colour. The dataviz checker (`scripts/validate_palette.js` of the dataviz skill) passes up `#15803d`
vs down `#dc2626` vs accent `#4f46e5` on every gate (all pairs, white surface; worst CVD dE 8.6 deutan).

## Chart colours (dataviz skill)
Series 1 is the accent `#4f46e5` (bands at alpha .32 for the 50% band and .13 for the 80% band, the fan .10);
the actual line is the ink; hit/miss dots use up/down. Slots 2-4 (`#d97706`, `#0891b2`, `#db2777`) are reserved
and must be run through the validator before a chart uses more than one series. Gridlines `surface-container`,
axis labels muted, the future area `surface-container-low`.

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
Surfaces: the page is `surface-container-low`, cards are white with a hairline border and 12 px corners, no
shadow; tiles and columns inside a card are bordered panels (8 px); the rail, top bar and navigation bar are white
with hairline borders. Breakpoints: shell rail from 600 px (navigation bar below); pages keep their own content breakpoint (the
decision page uses 760 px). Phone gutter 16 px, no horizontal page scroll.
