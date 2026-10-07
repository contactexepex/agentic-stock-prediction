# Cockpit design system (Material 3 light)

Shared look of every cockpit page: tokens, components, icons and the app shell. Living style guide:
`styleguide.html` (built from `styleguide.template.html` by `python design/system/build_styleguide.py`;
screenshots `styleguide-1280-full.png`, `styleguide-390-full.png`, `styleguide-390-viewport.png`).

## Files
| File | What |
|---|---|
| `tokens.css` | `:root` custom properties: M3 colour roles (`--md-sys-color-*`), tonal-palette steps, semantic finance tokens (`--mb-color-up/down/neutral/warn`, hit/miss, Live/Back-test/Mock/Paper), chart tokens (`--mb-chart-*`), the M3 type scale (`--md-sys-typescale-*` + `.md-body-medium` style classes), shape, elevation, state-layer opacities, spacing, motion, focus ring |
| `components.css` | App shell (`.mb-app`, `.mb-rail`, `.mb-navbar`, `.mb-topbar`, `.mb-content`), cards (`.md-card.elevated/filled/outlined`), buttons (`.md-btn.filled/tonal/outlined/text`, `.md-icon-btn`, `.md-help`), segmented buttons (`.md-segmented[.dense]`), chips (`.md-chip.assist/filter/small`), provenance tags (`.mb-tag.live/bt/mock/paper/derived/coming`), badges (`.md-badge` incl. verification statuses), direction squares (`.mb-dir.up/dn/flat/unk`), outcome marks (`.mb-mark.ok/no/na`), tooltip (`.md-tooltip`), data table (`.md-table`), key-value list (`.md-kv`), odds meter (`.mb-odds`), strength bar (`.mb-bar`), progress (`.md-progress`), KPI tile (`.mb-kpi`), expansion panel (`details.md-expansion`), `.md-pre` |
| `icons.svg` | 40 Material Symbols Outlined glyphs as `<symbol id="ms-NAME">` (Apache 2.0, `LICENSE-material-symbols.txt`, copied unchanged from google/material-design-icons) |
| `system.py` | `inline_system(html, icons=None)`: replaces `<!--@@SYSTEM_CSS@@-->` with both stylesheets and `<!--@@ICONS@@-->` with the sprite (all icons or a named subset) |
| `check_page.js` | Playwright check of a built page at 1280 and 390 px (console errors, external requests, horizontal overflow) with screenshots; uses the pre-installed Chromium |

## Palette
One seed, `#3B6EA8` (HCT hue 256.4, chroma 42.1, tone 45.5), through Google's `@material/material-color-utilities`
0.4.0 `SchemeTonalSpot` (the Material You default) at contrast level 0. Light scheme only. Key roles and WCAG
contrast on their "on" colour (text on a container needs 4.5:1):

| Role | Hex | On | Contrast |
|---|---|---|---|
| primary | `#39608f` | `#ffffff` | 6.5:1 |
| primary container | `#d3e4ff` | `#1e4875` | 7.3:1 |
| secondary | `#545f70` | `#ffffff` | 6.5:1 |
| secondary container | `#d7e3f8` | `#3c4758` | 7.3:1 |
| tertiary | `#6c5677` | `#ffffff` | 6.5:1 |
| tertiary container (Paper tag) | `#f5d9ff` | `#533f5e` | 7.3:1 |
| error | `#ba1a1a` | `#ffffff` | 6.5:1 |
| surface | `#f8f9ff` | `#191c20` | 16.3:1 |
| surface variant | `#dfe2eb` | `#43474e` | 7.2:1 |
| outline | `#73777f` | on surface | 4.3:1 |
| inverse surface (tooltips) | `#2e3035` | `#eff0f7` | 11.6:1 |

Semantic tokens are HCT tonal palettes on fixed hues, so they sit in the same tone system as the roles:
up `#00732e` (hue 150, 5.7:1 on the surface), down `#c92f29` (hue 25, 5.1:1), neutral `#73777d` (4.3:1, icons
and large text only), warn/unclear `#b37800` (3.6:1, icons only; text uses `#624000` on `#ffddb2`, 7.2:1).
Containers: up `#85f496`/`#003913` 9.6:1, down `#ffdad6`/`#7e0007` 8.6:1. Hit = up, miss = down.

**Never colour alone.** Up/down/hit/miss always carry a glyph (arrow, tick, cross) and the word; the provenance
tags carry a texture (Back-test hatched, Mock dashed, derived dotted) besides the colour. The dataviz checker
(`scripts/validate_palette.js` of the dataviz skill) puts up vs down in the CVD warn band (protan ΔE 6.8), which
is why that rule is a rule.

## Chart colours (dataviz skill)
The M3 roles are deliberately low-chroma (tonal spot caps primary chroma at 36), below the dataviz chroma floor
for series colours, so charts use a separate validated set on the same seed hue:

| Slot | Hex | Note |
|---|---|---|
| series 1 | `#0079d1` | ranges, the model, everything "ours"; bands at alpha .32 (50%) and .14 (80%) |
| series 2 | `#df7d00` | 2.83:1 on the surface: direct labels or the table view required |
| series 3 | `#876cc8` | |
| series 4 | `#009486` | |

Validator runs (light, surface `#f8f9ff`): series 1-4 adjacent pass (worst CVD ΔE 11.1, normal-vision 20.4;
series 2 contrast WARN); slots 1, 2, 4 pass all-pairs (scatter/maps; worst CVD 12.2, normal-vision 15.8);
up/down/series-1 all-pairs pass with up vs down in the warn band. Ink line = on-surface, grid =
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
Breakpoints: shell rail from 600 px (navigation bar below); pages keep their own content breakpoint (the
decision page uses 760 px). Phone gutter 16 px, no horizontal page scroll.
