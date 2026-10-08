# Help mockup: catalogue entities and fields used

The Help page is static content (SPEC section 6, page 12). Its text is written for the page; only the strategy list,
the go-live checklist, the default amount and one company's agreement count (the example) come from the catalogue,
so they never drift from the registry.

Source files: `design/catalogue/<entity>.json` (W1); five files. Payload per market, `data.json` key `markets.<market>`. Top
level: `page`, `spec`, `endpoint` ("(static content; no endpoint)"), `read_model` ("(none)"), `sources`, `as_of`,
`cutoff`, `built_at`, `markets`, `_example`, `_note`. Per market: `market`, `name`, `currency`, `as_of` (Market
status `market`, `name`, `currency`, `as_of`), `cutoff` (the catalogue files' shared `as_of`), `built_at` (Market
status `freshness.built_at`), `horizons`, `default_horizon`, then the keys below. `build.py` copies only the listed
fields of every record (`pick`), except `status`, which is the market's record whole.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole (the shell's chips) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons (the shell) |
| `go_live_detail` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline, best_baseline_net_pnl, drawdown_limit, drawdown_within_limit, holds_in_calm_and_volatile, cost_view}` | the same row (the go-live checklist example) |
| `default_amount` | Owner's paper portfolio | `default_amounts.<market>` | the market's default money per paper trade |
| `strategies` | Strategy | `id`, `family`, `name`, `description`, `compared_to`, `differs_in`, `threshold`, `horizons`, `live` | all 15, keyed by id (the strategy lists; the description in each name's tooltip; the reference = the rule strategy without `compared_to`; the AI horizons = the union of the AI traders' `horizons`) |
| `agreement_example` | Company | `ticker`, `name`, `agreement_n1.{buy, of}` | the market's first active company by ticker (the "Agreement" example) |

Shown but static (written for the page, not data): every explanatory sentence; the sample odds meter (57%), the
sample range bar (96-104 around 100) and the sample sentiment arrows are labelled "sample". The count of go-live
checks is the length of the page's list of them; the horizon the pages open on is `default_horizon`; the rule
strategies' bar in the horizons section is the reference strategy's `threshold`.

Spec constants in the shared shell (`design/mockups/_shared/shell.js`) used here, with their sources: the go-live
bar's 2 months and about 300 trades (SPEC F7.2), two intraday checks per session (SPEC section 7), 20 settled trades
to rank (SPEC section 6), the luck test's 95% interval (lab/luck.py), and the 60-word limit of an AI trader's reason
(SPEC F4.2), a deviation note (SPEC section 7) and an EOD reason (SPEC F6). The back-test's 15 years is not
mentioned on this page. The statuses, bands and flags come from the shell's STATUS, BAND and FLAG tables, which the
other pages use.

Build: `python design/mockups/12-help/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/12-help/page.html design/mockups/12-help shot` and `node design/system/check_text.js
design/mockups/12-help/page.html`.
