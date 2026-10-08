# Assistant mockup: catalogue entities and fields used

Source files: `design/catalogue/<entity>.json` (W1); three files. Payload per market, `data.json` key
`markets.<market>`. Top level: `page`, `spec`, `endpoint` (`POST /api/assistant`, the `explain` tool of
`mcp/tools.yaml`), `read_model` (none: conversations are an operational log), `sources`, `as_of`, `cutoff`,
`built_at`, `markets`, `_example`, `_note`, `_data_requests`. Per market: `market`, `name`, `currency`, `as_of`
(Market status `market`, `name`, `currency`, `as_of`), `cutoff` (the catalogue files' shared `as_of`), `built_at`
(Market status `freshness.built_at`), `horizons`, `default_horizon`, then the keys below. `build.py` copies only the
listed fields of every record (`pick`), except `status`, which is the market's record whole; nested objects listed
with `{...}` are copied with the keys named.

| Payload key | Catalogue entity | Fields used | Selection |
|---|---|---|---|
| `status` | Market status | `market`, `name`, `as_of`, `currency`, `session.{local_time, trading_day, session_date, previous_session, calendar_covered, session_open_utc, session_close_utc, in_session, late_run}`, `regime`, `runs.{pre_open, intraday[], post_close, news}.{at, ok, next_at, new_items}`, `freshness.{state, built_at, age_minutes}`, `paper_label`, `benchmark.{symbol, name, close, close_date, change_pct, change_5d_pct}`, `vol_index.{the same}` (ride along; not shown) | the market's record, whole (the shell's chips and footer) |
| `go_live` | Scoreboard row | `go_live.{proven, months_forward, trades_needed, beats_best_baseline}` (these four keys only) | of the reference strategy's accuracy row, all horizons (carried for the shared shell; this page shows no signal band) |
| `answers` | Assistant answer | `id`, `market`, `channel`, `asked_at`, `question`, `text`, `cited_ids`, `cited[].{id, kind, as_of}`, `as_of`, `not_in_data`, `declined` | the market's answers whose `as_of` (the data they read up to) is at or before `cutoff`, oldest `asked_at` first; each cited record's `as_of` is checked to be at or before the answer's. The example questions are asked 10-25 minutes after the noon cut-off about data up to it, which a conversation log shows (no look-ahead on data) |

Shown but computed by the page (presentation only): the state of each answer (answered from the data / not in the
data / declined, from `not_in_data` and `declined`), the kind words and page links of the cited records
(`paper_trades_settled` = "settled paper trade" -> Paper portfolios, `news` = "news item" -> Home, `eod_analyses` =
"end-of-day analysis" -> Rule vs AI; other kinds fall back to the kind's words and the Help page), the channel words
(`dashboard`, `slack` = "Slack /ask"), the list of distinct cited records, the example-question chips (the market's
questions), the question length counter, and the pending questions typed on this page (mockup state, never sent).

Spec constants in the shared shell (`design/mockups/_shared/shell.js`), used here with their sources: the question's
500 characters (`mcp/tools.yaml` explain `question.max_length`), the budget's $0.65 a day and $20 a month hard cap
(SPEC F11; `mcp/tools.yaml` explain `budget`), the 90 days conversations are kept (SPEC F11). The go-live and
intraday constants are not used on this page.

Data request (`_data_requests` in data.json): the budget state (today's and the month's spend against the daily
budget and the cap), so the panel can say "over budget" as F11 requires; the page shows the caps and says the spend
is not in the example data.

Build: `python design/mockups/11-assistant/build.py` (deterministic). Checks: `node design/system/check_page.js
design/mockups/11-assistant/page.html design/mockups/11-assistant shot` and `node design/system/check_text.js
design/mockups/11-assistant/page.html`.
