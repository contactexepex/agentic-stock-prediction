# market-brief

Personal research project: two scheduled Claude Code routines (India and US) collect free
prices, overnight cues, news, events and SEC filings, compute PASDS indicators and the market
regime, reason over them with subagents, make small, scored predictions, store everything in
this repo and post one Slack digest per market. Research only: never place trades, never
connect to brokerage tools, and nothing here is investment advice. Design: `docs/DESIGN.md`.

## Layout
- `config/markets/<market>.yaml` per market: exchange calendar, timezone, market-level symbols
  (benchmark, vol index, cues, factors), regime thresholds, sectors, `company_meta` (per-company metadata: name,
  Yahoo symbol, news names, aliases, ADR; the company list itself is B1's watchlist events, B18), news feeds
- `config/events.yaml` scheduled market events (rules and fixed dates)
- `scripts/` deterministic Python. Every script takes `--market india|us` (or `MB_MARKET`).
  Collectors: `collect_prices` (India: a watchlist bar Yahoo lacks for a recent session comes
  from NSE's bhavcopy when its price basis checks out, listed in `filled_from_nse` and recorded in
  `data/india/price_sources/`, view `bar_sources`; `price_fallback` in the market config; both markets: bars on days that are no
  session of the market calendar and flat zero-volume stock bars are not stored (summary `dropped_non_session`), stored holiday rows are
  left out on read by the `ohlc_raw` view (`own_closed_days`, built by `connect`); both markets:
  a split or bonus confirmed by a Yahoo `Stock Splits` row, or for India by NSE's bhavcopy, is recorded
  once in `data/<market>/adjustments/` (`marketbrief/analytics/price_adjustments.py`) and applied on read by the `ohlc`/`bars`
  views, raw bars in `ohlc_raw`/`bars_raw`; an unconfirmed re-base is a `warnings` entry and holds
  that symbol's new bars (`held`; 5+ sessions without a new bar: `held_too_long`, gate warning
  `PRICE_HELD_TOO_LONG`); a wrong record is cancelled by a later one with `supersedes`
  (`adjustment_records.py` lists the calls and ranges made while the wrong row was active);
  DESIGN.md section 3; the market calendar counts `special_sessions` of the market config, e.g. India's
  Muhurat days, as sessions with their own hours from `special_session_hours`), `collect_quotes`,
  `collect_events` (also backfills past earnings
  days, India from NSE results filings, US from SEC 8-K item 2.02, every 2.02 stored as filed and kept only when it is a
  quarter's results release when read (`event_history.results_filter`, anchored on stored 10-Q/10-K `periodic_report`
  rows), and dividends; also Yahoo's consensus EPS point in time -> `earnings_estimates`, read with
  `earnings_estimates_asof(ts)`, context only), `collect_news` (catch-up window: Google News `when:` and the oldest item
  kept reach back to the market's last successful news run, +1 h, at most 7 days, never below 1 day / 3 days;
  a query filling Google News' 100-item answer is re-asked per day; one row per run in `data/<market>/news_runs/`;
  `marketbrief/collectors/news_window.py`, DESIGN.md section 3 "News timing"; de-duplication, once per market:
  the same article link or the same normalised title from the same outlet (outlet key: host without www./m./amp.,
  allowlisted domain and its `same_as`, or a configured outlet name) within 9 days is not stored again, a new
  headline at a stored link is a `news_updates` row; different outlets stay separate; stored duplicates are hidden
  on read via `news_id_map` (`news` view: one row per item with its latest headline by now, `news_asof(ts)`,
  `news_aliases`, `news_lookup` for any stored id; `marketbrief/analytics/news_dedup.py`, DESIGN.md section 3
  "News de-duplication")), `collect_filings`, `collect_options` (US option-chain
  implied vol; India skips). Then `score_predictions` (calls and ranges; its summary adds the proper
  scores of `scoring.py`: Brier, log loss, reliability with Wilson intervals, interval and quantile
  scores, also in the context pack, weekly review and HTML track record), `lessons` (reflection log,
  pattern from TauricResearch/TradingAgents: `prepare` writes the deterministic facts of settled calls
  without a lesson, the reflector agent writes one lesson of at most 60 words each, `validate` checks
  each cites an existing settled prediction id and its numbers match the outcome, `add` appends to
  `data/<market>/lessons/`; the context pack shows a lesson only from its `available_from` = scoring
  time, MB_NOW-aware), `features` (indicators +
  regime), `calibrate`, `context`, and after the forecaster `ranges`, `charts` (single-purpose
  PNGs) and `report` (report skeleton + Slack summary draft with every number; agents fill only
  the `AGENT` markers, see `templates/report.md`). After the report gate passes, `html_report` builds
  the reader's HTML report from the filled md plus the data (C2, `marketbrief/presentation/reader/`: a phone-first page on
  B7's tokens with light and dark mode; the 20-second top: market mood, benchmark move, how many companies lean up or
  down, the biggest expected moves, the paper label; one card per active company with B12's published N+1/N+3/N+5
  ranges as a fan on the last 20 closes, B10's model P(up) as "chance of going up", the lean, a plain-language why from
  the score's points per feature group, flags (results soon, BLOCKED, contradicted news) and the change since the
  previous run from B12's forecast_history; paper trades and signal tiers in lean words, SIMULATED, once a strategy is
  live; everything as of the run's clock), then `dashboard` builds
  `reports/<market>/dashboard.html` (decision-support dashboard, stored data only as of the run's clock:
  watchlist, sector heatmap, candlesticks with the published ranges via the vendored TradingView
  Lightweight Charts in `marketbrief/presentation/dashboard/vendor/` (version and SHA-256 in its NOTICE),
  the signal model's P(up) with its points and formula, bull vs bear, news with status, track record;
  "Paper only — no proven edge yet" until the weekly review's `model_skill` is true), and `notify_slack` posts a thread
  (summary, chart images, HTML file, dashboard) with `SLACK_BOT_TOKEN`, or the summary text alone through
  `SLACK_WEBHOOK_URL`. Processing data (data/, context pack, summaries) and presentation (HTML,
  PNGs, Slack) are separate: `view_data.py` only reads the data for both presentation outputs.
  `backtest` evaluates the
  range formula walk-forward. `replay` is the historical replay of everything rule-based (no AI):
  each past day's N+k ranges (every horizon of `config/strategies.yaml`) as `ranges.py` builds
  them, the regime, and direction baselines (always-up, momentum, RSI mean reversion), scored ->
  `reports/<market>/replay-<end>.html|json` and `data/<market>/replays/` (DESIGN.md section 7);
  `replay --aci` compares fixed bands with
  Adaptive Conformal Inference (`adaptive_conformal.py`: per horizon x band x regime miss rate alpha_t updated from
  outcomes scored before `calibrate` runs; `aci:` in `config/ranges.yaml`, off by default; the weekly
  review shows alpha_t and proposes switching it on from a replay with the same settings, marked
  provisional unless its held-out check `--aci-tune-end` agrees). `ai_replay` replays the AI agents as of past
  days (never runs an LLM itself); ForecastBench leakage rule: only as-of dates after
  `model_training_cutoff` in `config/settings.yaml` are a fair test, earlier ones are labelled
  `contaminated` on every row and the score page and scored separately, never pooled. Formulas: `indicators.py` (PASDS file 06), `regime.py` (file 07),
  `core/calendar.py` (exchange calendar and events), `range_math.py` (ranges; settings in `config/ranges.yaml`),
  `event_history.py`, `earnings_reaction.py`, `index_cue.py`, `implied_volatility.py` and `range_switches.py` in
  `marketbrief/analytics/` (past earnings moves, ex-dividend shift, beta split, implied vol; each
  switchable in `config/ranges.yaml`).
  `review` is the weekly review (coverage, calls, input ablations; thresholds in
  `config/review.yaml`): it proposes `config/ranges.yaml` changes, a human applies them; it also
  reruns the signal-model backtest on the inputs dated (or first seen) by the reviewed week's end and says plainly
  whether the model shows skill (`model_skill`).
  Direction calls are scored close-to-close before `call_scoring.from` in `config/settings.yaml` and
  open-to-close from then on (`label_basis` on each outcome; `marketbrief/analytics/call_basis.py`); an open-to-close
  call of horizon k sells at the close of D+k (N+k), a 5-day call made before `call_scoring.n_plus_k_from` at D+4
  (`horizon_label` legacy_5d_d4); every summary shows the two bases apart, never pooled. An open-to-close
  call whose window has a session without a bar stays open (`session_gap_open`), never shifted.
  `validate` is the daily run's deterministic gate (`--stage collect|news_collect|news|features|context|forecast|report|all`,
  settings in `config/validate.yaml`; prediction rules shared with `ai_replay` in `marketbrief/analytics/prediction_rules.py`);
  `spotcheck` picks the weekly judge sample.
  Schemas live in `scripts/marketbrief/core/schemas.py` (`scripts/common.py` is only the `ROOT`/`CONFIG` patch point).
  Where the code of the daily steps lives (each `scripts/<name>.py` is a thin entry point with the same flags): `marketbrief/pipeline/` (validate, review and lessons as packages, `context`, `score_predictions`, `spotcheck`, `market_status`), `marketbrief/replay/` (`backtest/`, `rule_replay/`, `ai_replay/`), `marketbrief/graph/` (`connection_map`, `news_hits`, `neo4j/`) `marketbrief/presentation/report/` (the report skeleton and Slack draft) and `marketbrief/presentation/dashboard/` (the dashboard: read helpers, data assembly, page build; `assets/` and `vendor/` hold its JS, CSS and the charting library). Messages and constants of each live in `marketbrief/constants/`.
- India primary sources (NSE; shared session and replay guard in `marketbrief/collectors/nse_runner.py`, `nse_session.py` and `nse_replay_guard.py`): `collect_nse_india`
  -> `data/india/announcements|financials|flows|delivery/` (exchange announcements, Integrated
  Filing results per period and basis, FII/DII provisional flows, delivery %); context sections
  from `nse_sections.py`.
- Relationships (DESIGN.md phase 5): `collect_relations_india` (NSE: SEBI PIT insider/promoter
  trades, bulk and block deals, shareholding and promoter pledges -> `data/india/insiders|deals|holdings/`),
  `marketbrief/analytics/relation_flags.py` (risk flags: big deals, pledge rises, insider sales; optional range widening in
  `config/ranges.yaml`, off by default) and `graph.py` (connection map in `data/<market>/graph/`:
  `status`, `edges`, `hits` = second-order news, `add` = validate and append the graph-builder's edges,
  `attempt` = record the monthly refresh in `data/<market>/graph_runs/`)
- SEC CIKs: every SEC collector reads a ticker's filings from its mapped CIK plus the CIKs under
  `fundamentals.predecessor_ciks` in `config/markets/us.yaml` (XOM: 2115436 and 34088), each
  accession once (`sec_filings.ticker_submissions`).
- SEC acceptance times: the submissions JSON `acceptanceDateTime` can be shifted later by the New
  York UTC offset (+4h EDT, +5h EST) for a whole CIK's file (seen from 2026-10-05). `Edgar.recent`
  checks each file against the SGML header `<ACCEPTANCE-DATETIME>` (Eastern) of its newest and
  oldest filing (cached requests, `work/sec_acceptance.json`) and corrects it only when both are
  shifted; otherwise (mixed, unreadable) it keeps the served times and the collector lists the CIK
  in `warnings` (summary key `sec_times`: ok / shifted / unverified). Stored rows are fixed on
  read: `check_sec_times.py` (run by the routine after the SEC collectors) appends header times to
  `data/<market>/sec_times/`; `core.database.connect` reads `accepted_at` of filings, insiders, stakes,
  holdings and fundamentals through them, and `ai_replay` filters those kinds by the same times.
- Relationships, US (SEC EDGAR, helpers in `marketbrief/sources/sec_filings.py`): `collect_insiders` (Form 4),
  `collect_stakes` (13D/13G) and `collect_holdings` (13F for the filers and CUSIPs under
  `relationships:` in `config/markets/us.yaml`) write `data/us/insiders|stakes|holdings/`.
  Views `insider_flow`, `insider_cluster_buys`, `activist_stakes`, `holdings_filings`, `holdings_change` and
  `holdings_quarter` feed the context pack's "Smart money" section and a range risk note
  (`marketbrief/analytics/smart_money.py`; the widen `activist_13d_factor` in `config/ranges.yaml` stays off).
- Fundamentals, US (SEC XBRL company facts): `collect_fundamentals` writes 10-Q/10-K values
  (revenue, gross profit, operating and net income, diluted EPS, operating cash flow, capex, cash,
  debt parts, shares; quarter, H1/9M year-to-date and FY) to `data/us/fundamentals/`, one row per
  tag x period x filing that first reported or changed the value (`fundamentals:` in
  `config/markets/us.yaml`). Views `fundamentals_latest` (newest filing wins), `fundamentals_quarterly`
  (Q4 = FY - 9M and quarterly cash flows derived, marked), `fundamentals_metrics` (YoY growth,
  margins, FCF), `fundamentals_balance` and `fundamentals_latest_report` feed the context pack's
  "Fundamentals" section (`marketbrief/analytics/fundamentals.py`; no consensus estimates, so no "surprise").
  These views show today's knowledge (restatements replace originals); for anything as of a past
  time use the macros `fundamentals_latest_asof|quarterly_asof|metrics_asof(<timestamp>)`
- Neo4j projection (DESIGN.md section 12): `neo4j_sync.py` copies each market's data and results
  (companies, sectors, news with sentiment, filings, events, insider trades, deals, stakes and
  holdings, the connection map, predictions, ranges, outcomes, regime, features, judgments,
  fundamentals, flows) into Neo4j through the HTTPS Query API v2 (`NEO4J_URI`, `NEO4J_USER`,
  `NEO4J_PASSWORD`; database = first host label unless `NEO4J_DATABASE`). It only reads `data/`
  through DuckDB; Neo4j is a derived copy that `--full` rebuilds from the repo. Idempotent MERGE
  batches, incremental by per-kind watermarks stored in Neo4j, `--dry-run` writes the statements to
  `work/neo4j_dryrun/`. Optional and non-blocking in the routine.
- App and warehouse (WS1, docs/ws/ws1.md, docs/ARCHITECTURE.md; code `marketbrief/warehouse/`, settings `config/warehouse.yaml`):
  `data/` stays the source of truth. `warehouse_sync.py --market india|us [--full] [--dry-run] [--local] [--kind daily|news]`
  copies the market's stored data as of the run's clock (MB_NOW-aware) into MotherDuck `market_brief` (env
  `MOTHERDUCK_TOKEN`, never printed; without it the local file of the config under `work/`): one schema per market
  with the cockpit's tables (bars, quotes, features, regime, predictions, track record per label basis, ranges, model
  scores and versions, news with status, events, agent reasoning, lessons, reviews), replaced in one transaction, plus
  per-page read models in `rm` (`overview`, `watchlist`, `stock`, `bars`, `track_record`, `status`; key `(market, page_key)`,
  payload sliced from `gather_dashboard`, upserted by `payload_sha256`), `rm.builds` and `meta.sync_runs`. Kill switch
  `enabled` and `monthly_hours_ceiling` in the config. The MotherDuck extension is installed by
  `marketbrief/warehouse/extension.py` over HTTPS only (both signed files downloaded through the proxy, DuckDB checks
  the signatures; never `INSTALL motherduck`, whose downloads are plain HTTP); `duckdb` is pinned in requirements.txt
  and the matching extension build under `extension:` in `config/warehouse.yaml`. Optional, non-blocking, rebuildable with `--full`; static
  `reports/` and Slack never depend on it. Read-model framework (B4, docs/ws/b4.md): each `rm.<table>` is a
  `PageBuilder` declared in a `warehouse/rm_<page>.py` module (found by name; shared page blocks in `rm_common.py`,
  as of the clock, collected companies only via B1's `watchlist(market, cutoff, "collected")`), checked against its
  schema before writing; a MotherDuck sync then revalidates the app's cache of the changed keys (`app_url`,
  `REVALIDATE_SECRET`). The API under `/api/v1` (Next.js route handlers in `web/app/api/v1/`, shared helpers in
  `web/lib/data/`) reads only `rm`; contract `api/openapi.yaml` 2.0 plus `api/paths/*.yaml` and `api/schemas/*.yaml`
  (one file per page session; bundled by `warehouse/openapi_spec.py`), checked by `tests/test_openapi.py` and
  against the approved mockups by `tests/test_api_contract.py` (`scripts/api_contract.py` for the live warehouse).
- Market pages (B11, docs/ws/b11.md; contract 2.0): `scripts/marketbrief/warehouse/rm_home.py`, `rm_watchlist.py`,
  `rm_news.py` and `rm_companies.py` build rm.home, rm.watchlist (replacing the 1.0 dashboard slice), rm.news and
  rm.companies as of the run's clock, served by `/api/v1/markets/{market}/home|watchlist|news|companies`
  (`api/paths|schemas/<page>.yaml`, routes in `web/app/api/v1/markets/[market]/`). Shared reads B12 reuses:
  `news_items.news_items` (decision 12: a company deleted by the cut-off is never in an item's tags) and
  `news_window` (3 days, at most 50: up to 25 company and 25 market-wide, a share one scope leaves unused going to the
  other, each kept by market movers, high materiality, then newest; owner, 2026-10-08), `calendar_events.calendar_events`,
  `company_records` (lifecycle events, commands with deleted companies masked). The Companies page's commands:
  `POST .../companies/preview` (summary, add_company's resolved identifiers; nothing written) and
  `.../companies/commands` (written through B5's tool layer only when `confirmed_summary` equals the server's own
  preview; delete typed; `web/lib/data/company-commands.ts`).
- Public brief (C2, docs/ws/c2.md; owner decision 2026-10-10): the reader's daily page, read-only and without
  login, at the gateway's `GET /brief/<market>/<session>-<token>` (`web/app/brief/[market]/[slug]/route.ts`,
  `web/lib/brief/brief.ts`; B5's gateway allowlist). token = HMAC-SHA256(`BRIEF_LINK_SECRET`, market and session)
  cut to 128 bits (`presentation/reader/links.py`), never stored: `warehouse/rm_brief.py` writes rm.brief
  (page_key = session; the committed `reports/<market>/<session>.html` and the token's SHA-256, newest 30 reader
  pages), the route checks the slug before reading and compares the SHA-256 in constant time; anything else is a
  404. Without the secret no link and no rm.brief row. The HTML file stays attached in Slack as the offline backup.
- Company pages (B12, docs/ws/b12.md; contract 2.0): `scripts/marketbrief/warehouse/rm_company.py` (builders),
  `company_payloads.py` (per-company slicing in the mockups' fields) and `company_sources.py` (the stored records read
  once per build as of the cut-off, collected companies only) build rm.stock (the whole 03-company page: the shared
  blocks, lifecycle events, agreement, picks, predictions, open trades, latest trade checks, settled trades, AI
  reasons, news of 30 days / newest 50, results, events of the next 60 days, the last 250 bars; owner, 2026-10-08;
  ranges.py's `published_ranges` whatever a strategy's live_from and the `forecast_history` of every stored range and
  score run of the last 10 as-of dates (B10's N+k labels) with each run's change, `company_history.py`; owner,
  2026-10-10),
  rm.bars, rm.stock_strategies (04 page), rm.trades (`_`: every open trade, the latest check, the last 5 sessions'
  settlements; per ticker: the last 60 sessions) and rm.lifecycle (`<ticker>:<date>`, the last 30 sessions: the
  predictions and picks made for that session followed to their checks, settlements and AI reasons), served by
  `/api/v1/markets/{market}/stocks/{ticker}[/bars|/strategies|/lifecycle/{date}]` and `/trades[?ticker=]`
  (`api/paths|schemas/company.yaml`). `rm_company.trade_checks(ctx)` / `market_trade_checks(ctx)` give the latest
  check's rows to the market and portfolio pages.
- Strategy lab and lifecycle formats (W1, docs/SPEC.md sections 3-4 and 10; field guide `docs/DATA_CATALOGUE.md`,
  example data `design/catalogue/*.json`, rebuilt by `design/catalogue/make_examples.py` with B2's engine code; notes
  `docs/ws/w1.md`): `config/strategies.yaml` is the strategy registry. It holds the horizon list
  `horizons: [1, 2, 3, 4, 5]` (N+k = sell at the close of the k-th session after the entry session D), `ai_horizons`
  and the 8 rule strategies, 3 baselines and 4 AI traders, each differing from its `compared_to` in one parameter.
  The new append-only kinds are in `core/schema_lab.py` (`strategy_predictions`, `strategy_abstentions`,
  `paper_trades_settled`, `head_to_head_picks`, `trade_reasons_ai`, `trade_checks`, `eod_analyses`,
  `research_reviews`, `news_impact`) and `core/schema_lifecycle.py` (`watchlist_events`, `command_log`); B2's
  `cost_views` (`core/schema_b2.py`) is documented in the catalogue. Interfaces in `marketbrief/contracts/`:
  `protocol` (F1, delegates to `marketbrief/lab/protocol.py`), `watchlist` (delegates to `marketbrief/lifecycle/`),
  `horizons` (per-horizon score and range records, B10) and `strategies` (the registry's allowed values). Governed
  tools per channel: `mcp/tools.yaml`. A field the pages need and the catalogue lacks is a data request to W1.
- Company lifecycle (F8, B1; docs/ws/b1.md; code `marketbrief/lifecycle/`, settings `config/lifecycle.yaml`): the
  watchlist is data.
  `scripts/company.py --market M add|deactivate|reactivate|set-amount|delete|list|seed|import-inbox` validates and
  appends `data/<market>/watchlist_events/` (each add, deactivate, reactivate, set-amount, delete and imported inbox
  command also gets a `command_log` row; delete needs `--confirm <ticker>` and is never allowed from Slack).
  `load_market` rebuilds the company lists from the events as of the run's clock (MB_NOW-aware): `cfg["tickers"]` =
  every collected company (active and inactive, never deleted; collectors keep reading it), `cfg["sectors"]` rebuilt,
  `cfg["active_tickers"]` = active only; code that predicts or displays uses `lifecycle.loader.active_tickers(cfg)` /
  `active_sectors(cfg)`; replays and new code use `contracts.watchlist.watchlist(market, as_of, state)`. An event
  counts once both effective_from and recorded_at have passed, except the seed's add events (channel `seed`, the 20
  config companies per market, effective from the start of stored history), which restate the config list and count
  from effective_from. The config's `company_meta:` (legacy `tickers:`) holds per-company metadata; its entries act
  as adds only while a market has no stored seed event (test roots, unseeded markets). Add runs the deterministic onboarding
  (identifiers from NSE's equity list or SEC's ticker/exchange file plus Yahoo; no ETFs, BSE-only or unknown symbols;
  sector from `sector_rules`; backfill of prices from the first stored day, daily history into the long-history cache
  `work/model_history/` from its start, else 15 years back, news, filings or announcements; the candidate's collect
  gate) before its event is appended. `.github/workflows/onboard.yml` imports the MotherDuck inbox
  (`market_brief_inbox`, `MOTHERDUCK_INBOX_TOKEN`).
- AI traders, EOD analyst, research director (B3, docs/SPEC.md F4 and F6, notes `docs/ws/b3.md`; code
  `marketbrief/traders/`, run as `PYTHONPATH=scripts python -m marketbrief.traders <command>`). Four traders
  (`.claude/agents/trader-news-results.md`, `trader-pattern-mood.md`, `trader-combined.md`, and `forecaster.md` as
  `ai.combined.opus.v1`) each read only `work/traders/<id>.md` (`prepare`) and predict N+1, N+3 and N+5 or abstain.
  Each agent file's `yaml trader` block holds its prompt_version, kill switch (`enabled`) and budget. `add` is the gate
  (shared with prediction_rules and the forecast-v11 anchor, which binds only the combined traders; made_at of a
  clockless trader = its file's write time, capped at the gate's clock). It allows one retry, then
  `strategy_abstentions` (gate_failed, timeout 15 minutes before the open, killed, blocked_quality, earnings_window,
  abstained). Post-close (`routine/POSTCLOSE_PROMPT.md`): B2's `scripts/lab.py settle`, the `eod-analyst` agent and
  its gate `eod-validate|add` -> `trade_reasons_ai`, `eod_analyses` (market-cost view), B6's close alerts. Weekly
  (`routine/WEEKLY_PROMPT.md`, Saturday 09:51 local): the `research-director` agent and its gate
  `director-validate|add` (config diffs that apply to a copy, never applied) -> `research_reviews`,
  `reports/<market>/research-<week>.md`.
- Tools and channels (B5, SPEC F10; docs/ws/b5.md): the `web/` Next.js project (App Router; `package.json`, lockfile,
  `tsconfig.json`, `next.config.ts` owned by B5; later sessions only add dependency lines). The governed tool layer
  `web/lib/tools/` implements `mcp/tools.yaml`; `mcp/build_registry.py` generates `registry.generated.ts` from it and
  `mcp/agents/*.yaml` (allowed tools, day budgets, kill switch per agent; `assistant` has read tools only), checked by
  `tests/test_b5_tools.py`. Identity comes only from the channel's auth, never from arguments. Every write needs an
  idempotency key; company commands are confirmed (summary; typed for delete, dashboard only), paper trades come from
  the `/trade` form (or a tool call) without a summary step. Writes are appended to the inbox
  (`mcp/inbox.sql`, database `market_brief_inbox`, `MOTHERDUCK_INBOX_TOKEN`): company commands to
  `inbox.company_commands` (read by `company.py import-inbox`), paper trades to `inbox.requests` (read by
  `portfolio.py import-inbox`); each write dispatches `onboard.yml`; pending until imported. Every call is logged in `inbox.command_log`
  (operational, not imported); refusals are posted to #market-brief for the owner. Gateway mode (`MB_GATEWAY=1`,
  the Vercel project at `omenix-gateway.vercel.app`, `web/middleware.ts`) serves only `/slack/*` (signed, at most 5 minutes old),
  `/mcp` (GitHub OAuth, the owner's login and numeric id only) and `/oauth/*` plus `/.well-known/oauth-*` (POST only on
  `/slack/commands` and `/slack/interactions`). Slack:
  `/company`, `/trade`, `/ask india|us QUESTION` (the `explain` tool, answered by B8's assistant through the tool
  layer's explain hook; "coming soon" until it is wired), in #market-brief only; Confirm posts a visible request message whose
  `slack_channel`/`slack_ts` go into the inbox row for B6's onboarding reply. Web tests: `npm test` in `web/` (node test
  runner, offline, with the prompt-injection suite), CI `.github/workflows/web-tests.yml`.
- Assistant (B8, SPEC F11; docs/ws/b8.md; code `web/lib/assistant/`, route `web/app/api/assistant/`, page 11 and the
  chat panel in `web/app/(cockpit)/[market]/assistant/_parts/` and `@chat/`): the `explain` tool answers a question
  (at most 500 characters) from the stored data only, through B5's read tools (gated, logged, read-budgeted), with
  `claude-sonnet-5-5` and a pinned refusal fallback to `claude-sonnet-5`; every cited id must be in what the tools
  returned, an answer that reads as advice is replaced by the decline, "not in the data" when it is not. A
  conversation carries its last 4 turns (`conversation_id`; Slack /ask continues the asker's last 30 minutes). No
  money budget in code (owner decision 2026-10-08): each answer's cost is logged per attempt and the spend shown;
  the Anthropic console's limit is the cap. Conversation log `market_brief_inbox.app` (`web/lib/assistant/app.sql`,
  90 days, operational, never imported). Kill switch: `inbox.controls` agent `assistant`.
- Macro, flows and short selling (issue #9; HTTP client in `marketbrief/sources/free_source_client.py`, storage helpers in `marketbrief/collectors/collector_store.py`,
  context sections in `marketbrief/pipeline/macro_sections.py`): `collect_macro` (US `macro:` config: Treasury
  par yield curve, FRED series via fredgraph.csv, Cboe daily put/call ratios -> `data/us/macro/`),
  `collect_shorts` (US `shorts:`: FINRA Reg SHO daily short-sale volume and short interest ->
  `data/us/shorts|short_interest/`), `collect_flows_india` (India `india_flows:`: NSDL daily FPI
  investment and NSE index closes with P/E, P/B, dividend yield -> `data/india/fpi|indices/`).
  Views `macro_series` (adds 10y-2y and 10y-3m spreads), `macro_latest`, `shorts_latest`,
  `short_interest_latest`, `fpi_latest`, `indices_latest`; context sections "Macro & flows" and
  "Short selling". A per-session file stored incomplete (`complete` false) is fetched again next run.
  Press-release wire feeds (`watchlist_only: true`) match tickers on `wire_names` minus
  `news.wire_exclude`. BSE (api.bseindia.com) refuses cloud traffic, so India announcements stay NSE-only
- News verification, phase A (DESIGN.md section 3a; deterministic, no LLM; helpers in
  `marketbrief/analytics/news_sources.py`, `article_pages.py`, `article_extraction.py`, `text_measures.py`):
  - `collect_articles` reads the article pages behind this run's material watchlist headlines.
    It reads only from the HTTPS outlets allowlisted (vetted) in `config/news_sources.yaml`: a broad
    list of established media, trade press, data sites and primary sources, with tiers, agency names
    and promotional providers. An unlisted outlet is recorded as `skipped_unlisted`, never requested,
    and listed in the summary's `unvetted_domains` for review. Outlets that answer 401/403/a bot
    challenge are `fetch: false`: never requested, still vetted. Output goes to `data/<market>/news_articles/`, one row per news id: access
    full|partial|paywalled|blocked|undecoded|skipped_unlisted, metadata, agency origin, at most 3
    key sentences of <= 40 words, normalised numbers, and a MinHash. The full text is never stored.
  - `news_clusters` groups same-event items per ticker and counts independent verified origins.
    A verified origin is a vetted outlet whose item was read, or that carries agency evidence.
    Copies of one agency story, or of one text, count once. Unread vetted headlines are counted
    apart (`unread_vetted_origins`). Unvetted outlets, promotional items and opinion never count. It attaches SEC filing and NSE announcement
    candidates. Output goes to `data/<market>/news_clusters/` as per-run snapshots. Read them as
    of a time with the `news_clusters_asof(ts)` macro, which does not look ahead.
- News verification, phase B (DESIGN.md section 3b; logic in `scripts/marketbrief/`): `claims.py
  prepare` picks the run's high-materiality watchlist clusters (`claims:` in `config/news_sources.yaml`),
  stores the text of their SEC 8-K/6-K primary sources (`data/<market>/primary_texts/`) and writes the
  claim-checker agent's input; `claims.py validate|add` is the gate (ids exist, quotes verbatim in the
  stored extract or primary text, numbers stated in the quote, enums) and appends to `news_claims`;
  `news_status.py` computes each event's and fact's status deterministically (contradicted >
  confirmed_primary > corroborated > rumour > promotional > single_source > unverified) into
  `news_verified`, read with `news_verified_asof(ts)` / `news_status_ids_asof(ts)` (no look-ahead). The
  context pack shows events with their status; the forecast gate checks each cited id's status as of
  `made_at` (`prediction_rules.check_news_status`).
- Results digests (WS6, docs/ws/ws6.md; code `marketbrief/results/`, settings `config/results.yaml`,
  `routine/RESULTS_PROMPT.md`): `results_digest.py prepare` detects the watchlist's quarterly results releases (India:
  first NSE Integrated Filing of a quarter; US: SEC 2.02 kept by `results_filter`) and earnings-call texts (India: NSE
  transcript announcements; US: prepared remarks filed with the SEC, else `transcript_unavailable`) of the last 10
  days, stores their primary texts in `primary_texts` (NSE attachments from the archive host only; no PDF parser, so
  India digests hold numbers only until `pypdf` is added), computes the numbers as of the release (no later
  restatement: India filings within 24 h of the first, US `fundamentals_metrics_asof` at the quarter's first
  10-Q/10-K, `pending_report` until then), the consensus collected before the release (context only) and the
  reaction, and writes the results-analyst's input; `validate|add` is the gate (ids, verbatim quotes, numbers from
  the quote or the release, enums, no advice) and appends to `results_digests` (views `results_digests_asof(ts)`,
  `results_digests_latest`, `results_digest_ticker_latest`). The context pack shows the active companies' digests of
  the last 10 days after "Fundamentals" (`results/context_section.py`, as of now; omitted when there is none).
- Signal model (DESIGN.md section 15; `scripts/marketbrief/model/`, settings `config/model.yaml`, costs
  `config/costs.yaml`): `model_scores` (routine step 5a, again after the news append) appends per ticker and
  horizon P(up) of the open-to-close label (N+k, decision 37: buy at the open of D, the first session after the
  as-of close; sell at the close of the k-th session after D, k in `config/strategies.yaml` `horizons`;
  `core/horizons.py`) with its explanation (points per feature group, top 3 drivers each
  way) to `data/<market>/model_scores/` (view `model_scores_latest`), plus a `cross_market` variant (every
  cross-market group on, for strategies with `cross_market: true`) in `model_variant_scores|versions`;
  the month's model (L2 logistic, monthly expanding-window refit on labels resolved by the refit date,
  Platt calibration on past out-of-sample rows, JSON coefficients) to `data/<market>/model_versions/`.
  News enters as a fixed prior (not trainable yet; no
  news archive); `model_news_update` reports the re-estimation and the rows it needs. `model_backtest --out DIR`
  is the walk-forward test (both markets and horizons, open-to-close and close-to-close, baselines after costs;
  writes only to DIR; `--history` adds the long-history cache, `--cross-groups`/`--ablate` the cross-market
  variants, `--no-gbm`). Cross-market features (`model/cross_market.py`: other markets' last sessions, FX, rates,
  commodities, India's ADR premium; each symbol's `close_time` in the market config; a bar counts only when
  final before the open of D) are switched per market and group under `cross_market:` in `config/model.yaml` (all off: no tradable skill
  in the 15-year test, DESIGN.md section 15.1).
  `model_history` fetches Yahoo daily bars from 2011 (`--start`) into `work/model_history/<market>/` (gitignored, manifest;
  never data/; a symbol whose fetch fails keeps its previous rows, `kept_previous_rows` in `failed`).
  Symbols of role `adr` (`adr_of: <ticker>`) are collected as bars only. The forecaster anchors on the score:
  `model_prob`, `agent_adjustment` (|x| <= 0.10) and
  `adjustment_reason`, checked by `validate --stage forecast` (MODEL_ADJUSTMENT); `agent_reasoning validate|add`
  stores the day's bull case, bear case and verdict per ticker (`data/<market>/agent_reasoning/`).
- Horizons N+1..N+5 (B10, docs/SPEC.md F2.7, decision 37; docs/ws/b10.md; `core/horizons.py`): horizon k means buy
  at the open of D, sell at the close of the k-th market session after D (weekends and holidays skipped). The list is
  `config/strategies.yaml` `horizons` (`config/ranges.yaml` follows it). Model labels, ranges (target = the exit
  session, width over k + 1 sessions), calibration, call scoring and the prediction rules use it. New
  `model_scores`, `ranges`, `calibration` and `model_versions` rows carry `horizon_label` (`n_plus_k`), ranges and
  scores also `entry_date` and `exit_date`; a new `outcomes` row carries the label of the window its call is scored
  on (a close-to-close call: `legacy_cc`; an open-to-close 5-day call made before `call_scoring.n_plus_k_from`:
  `legacy_5d_d4`; else `n_plus_k`). Older rows are labelled on read (B10 block of `sql/views.sql`): `legacy_cc`
  (old ranges, close-to-close calls), `legacy_5d_d4` (open-to-close 5-day rows sold at D+4), open-to-close 1-day =
  N+1. Legacy rows are never pooled with N+k; the context pack's signal-model section shows N+k scores only, and
  `ai_replay score` scores calls recorded before `n_plus_k_from` on their old window apart (`legacy_cc`).
  `contracts/horizons.py` `scores_asof` (`variant=base|cross_market`) and `ranges_asof` give the N+k records as of
  a time (no look-ahead).
- Paper portfolio and signal tiers (WS4; `scripts/portfolio.py --market india|us`, logic in `marketbrief/portfolio/`,
  settings `config/portfolio.yaml`, notes `docs/ws/ws4.md`): research only, a paper trade is a record, never an order.
  `add-trade` validates (watchlist ticker, a session, price = the stored bar's open/close or a manual price inside its
  low-high, unused idempotency key, no selling more than held) and appends to `data/<market>/portfolio_trades/`
  (corrections: a new row with `supersedes`, `cancel-trade`); `request-company` appends to
  `data/<market>/watchlist_requests/` (config stays a human change); `positions` / `pnl` (FIFO, marked to the latest
  stored close, before and after `config/costs.yaml` costs, split basis of `adjustments`); `signals` (tiers Strong Buy
  .. Strong Sell; Strong only in a proven horizon x confidence band: review `model_skill` true and >= 50 open_to_close
  calls with Wilson low >= 0.55; else "No proven strong signals today" + Paper candidates); `paper-follow` (SIMULATED);
  `import-inbox [--inbox FILE]` (issue #112, `marketbrief/portfolio/inbox_import.py`, docs/ws/ws4.md) imports the
  web tier's `add_paper_trade` requests from `market_brief_inbox.inbox.requests` (`MOTHERDUCK_INBOX_TOKEN`, read
  only) through the same checks as `add-trade`; identity and channel come from the inbox row (stored in the
  `portfolio_trades` columns `submitted_by` and `command_id`, null for CLI trades; sources `dashboard` and
  `claude_app` only through the import), the key is its `inbox_id`, and each row gets one `command_log` row (a
  request not decidable yet is logged `failed` and tried again).
  Every read is as of the clock (MB_NOW-aware).
- Strategy lab and paper-trading engine (B2; docs/SPEC.md F1-F3, F7; DESIGN.md section 17; notes `docs/ws/b2.md`;
  code `marketbrief/lab/`, entry `scripts/lab.py`; a strategy trades only from its `live_from` in
  `config/strategies.yaml` (`registry.is_live`: settle, pick and the forward summary skip pre-live rows, predict
  rehearses)): `predict` (pre-open, rule strategies and baselines from B10's
  per-horizon scores and ranges -> `strategy_predictions`, blocks as `strategy_abstentions`, the cost-viable rows
  of decision 51 of the new qualifying ones -> `cost_views`), `pick` (pre-open,
  refused at or after D's open: the head-to-head picks per company, family and pick rule -> `head_to_head_picks`,
  and the cost-viable rows of every pick and of each qualifying prediction without one yet -> `cost_views`; "best expected gain" = the horizon with the highest
  expected gain per session held), `settle` (post-close: every due trade of both views -> `paper_trades_settled` in
  the market-cost view and its your-cost view -> `cost_views`; F1.9 measures, F1.10 automatic reason; a prediction
  or pick made or first committed at or after D's open is refused; a split correction re-settles as a new row),
  `news-impact` (weekly -> `news_impact`), `summary` (scoreboard ranked on market cost with the bootstrap luck test
  and Bonferroni correction, the go-live bar on your cost, paired comparisons, heatmap data), `backtest` (always-up,
  momentum and, on B10's walk-forward probabilities as of the clock, the model strategies without news; stored bars,
  `--history` adds the cache; basis backtest; `backtest --store` -> `lab_backtests`, once per run_id), `pick-study`. Costs (`lab/costs.py`): the statutory
  rates of `config/costs.yaml` plus its `broker:` section (Axis Direct NRI Normal tier Non-PIS, BUX Basic;
  owner-provided, confirmed final for paper trading by the owner on 2026-10-08, SPEC decision 53); market cost =
  brokerage, statutory taxes and exchange or regulatory fees; your cost adds India's NRI
  reporting charge (₹200 on the buy date and on the sell date) and DP charge, BUX's FX markup each way and the
  pro-rated portfolio fee; the BUX euro fee is converted at the stored `EURUSD=X` close. `cost_viable` = expected
  gain after your cost > 0 (`expected_gain_your_pct` = p x move - (1 - p) x loss - your cost, with the picks'
  conditional move and loss of `lab/gain.py`; null without a probability or 80% range, or when the amount buys no
  whole share); the flag never blocks a
  prediction or pick. The owner's paper portfolio uses the your-cost charges (the US portfolio fee pro-rated per lot over
  the calendar days held, owner decision of 2026-10-08) and shows a EUR view of US positions.
- `scripts/marketbrief/` package of the refactor (docs/REFACTOR_PLAN.md): `constants/` (kinds, columns,
  statuses, sources, config keys, files, messages), `core/` (paths, clock, schemas, market config, storage,
  database, cli, settings), `utils/` (numbers, timestamps, text, markdown, money), `sources/` (one
  `HttpClient` base under the Edgar, NSE, free-source, Neo4j and Slack clients; RSS and article-page access sit beside it). Callers import from
  it directly; `scripts/common.py` is only the patch point (`common.ROOT` and `common.CONFIG` read and write
  `core.paths`; tests assign them), and the collectors' own helpers live beside them: `collectors/` (the code of every `scripts/collect_*.py`, which are thin entry points), `analytics/` (formulas and range/news analytics; `scripts/features.py`, `calibrate.py`, `ranges.py`, `relations.py` and `news_clusters.py` are thin entry points), `pipeline/` and `presentation/`.
- `sql/views.sql` derived DuckDB views (bars, returns, latest features/regime/quotes, events,
  news by ticker/day, track record)
- `data/<market>/<kind>/YYYY/MM/YYYY-MM-DD.<ext>` raw, append-only records (UTC dates, except
  prices/price_sources/features/regime which use the trading date, and adjustments: the ex-date)
- `summaries/<market>/daily|weekly|monthly/` layered narrative memory written by Claude
- `reports/<market>/<session_date>.md` the daily report (agent-editable source);
  `reports/<market>/<session_date>.html` the self-contained reader's report linked from Slack
  (filters by sector and company; no network needed) and `reports/<market>/index.html` (all days);
  chart images in `reports/<market>/charts/<session_date>/` (`ranges`, `sectors`, `track_record`);
  `config/settings.yaml` holds the repo URL, the Slack channel id and the AI model's `model_training_cutoff`
  (ai_replay's fair vs contaminated split) and `slack_link_url`: Slack links open `<slack_link_url>/<market>`, the
  market's page in the app (`core.settings.slack_link_url`); the daily HTML report is attached in the day's thread
  and the weekly report links to its repo file. The static reports site (`pages_url`) is retired from Slack links
  (it deploys only by hand; owner, 2026-10-10); `reports/index.html` and `reports/vercel.json` are left for the later
  static cleanup (the only files under `reports/` that build work may change; no script writes them)
- `reports/<market>/review-YYYY-Www.md` the weekly review (record in `data/<market>/reviews/`)
- `judgments/log.jsonl` every judge verdict on build work (append-only); daily-run verdicts are in
  `data/<market>/judgments/`
- `.claude/agents/` subagents: reflector (one lesson per settled call, after scoring), claim-checker
  (claims of material news events quoted from stored extracts and filing texts), news-analyst,
  bull-researcher, bear-researcher, forecaster (reads the lessons; never overriding the prediction rules),
  graph-builder (monthly connection map; every edge cites a public source),
  deviation-explainer (one note per flagged intraday deviation, citing only the check's candidates),
  results-analyst (at most 5 quoted bullets per results release or earnings-call text, never a forecast or
  advice), the AI traders trader-news-results, trader-pattern-mood and trader-combined (Sonnet; the forecaster is
  also the Opus combined trader), eod-analyst (Sonnet: at most 60 words per settled head-to-head trade and per
  biggest win or miss), research-director (Opus: weekly findings and config-diff proposals), and judge
  (independent verifier of code, config, agent-instruction and process changes, the monthly
  graph-builder edges and the weekly spot-check sample).
  Each agent's model and effort are set in its frontmatter (Sonnet 5.5 for news scoring, claim
  checking, the reflector, the deviation explainer, the results-analyst, the researchers, the three Sonnet traders and
  the eod-analyst, Opus 5.5 for the forecaster (also the Opus trader), graph-builder, research-director and judge;
  table in DESIGN.md section 13).
- `routine/PROMPT.md` the routines' saved prompt (one per market). `routine/NEWS_PROMPT.md` the news-only light
  run (one per market, every 4 hours, weekends and holidays included): `collect_news_only.py` runs `collect_news`,
  India's NSE announcements, `collect_articles`, `news_clusters` and `validate --stage news_collect`, then the
  session commits and pushes the news data folders only; no agents, no Slack. The pre-open run's news analyst
  scores `news_pending.py`'s output: every news/announcement id first seen since the last enrichment
  (`marketbrief/pipeline/news_pending.py`; the news gate and `claims.py` use the same window; each line has a
  `priority`, watchlist lines first; the news gate warns `ENRICH_TEMPLATED` on templated watchlist summaries)
- Intraday checks (WS5; `scripts/intraday_check.py`, code `marketbrief/intraday/`, settings `config/intraday.yaml`,
  `routine/INTRADAY_PROMPT.md`; schedules in DESIGN.md section 2): a few times per session, Yahoo 5-minute bars of
  the watchlist, benchmark and sector indices (bars complete by the check time) are compared with the session's
  published 1d/5d ranges and the open calls and model scores as of the check (MB_NOW-aware): band position, move
  since the open scaled by the 1-day sigma, beta-adjusted residual, direction against an open call ->
  `data/<market>/intraday_checks/` (one row per ticker, with deterministic attribution candidates: benchmark, sector,
  cue, news/announcements first seen since the open with their status, today's events) and `intraday_runs/` (one row
  per check; market closed: that row only; a repeated check time writes nothing). The `deviation-explainer` agent
  writes <= 60 words per flagged row citing only those candidates; `intraday_check.py validate|add` is its gate (ids,
  numbers, enums, no prediction words) -> `intraday_explanations/`. Views `intraday_checks_latest`,
  `intraday_deviations`, `intraday_today`, `intraday_explanation_close`; `intraday/outcomes.py` pairs each note with
  the close (held / reversed / faded); `intraday/payload.py` is the cockpit's read model.
  B9 (docs/ws/b9.md): every open paper trade (a qualifying `strategy_predictions` row or a picked
  `head_to_head_picks` row whose window D..exit_date contains the session, made before D's open; every
  strategy live on D (B2's `live_from`; others counted as `skipped_trades.not_live`), horizon N+1..N+5
  and view; past exit_date while it has no `paper_trades_settled` row, at most
  `trades.max_sessions_past_exit` sessions, note `unsettled_past_exit`) gets a `trade_checks` row per check (W1's format:
  price vs entry, target and its own range, band, target_z; flags outside_range | far_from_target |
  against_prediction; with its detail columns: quality, today's price basis, target reached so far, issue #78;
  rows written before #78 keep those in `trade_check_details`);
  views `trade_check_rows`, `trade_checks_latest`; a ticker with a flagged open trade is flagged
  `open_trade_flagged`, and the explainer's input carries its flagged trades. Band flags exist for every published
  horizon (`outside_<k>d_80`; `bands` JSON on each check row). The intraday alerts feed (`intraday_alerts`, view
  `intraday_alerts_feed`, `intraday_check.py alerts`): one row per ticker with flagged open trades per check (`repeat`
  when already alerted with the same flags that session) and material news on a company with an open trade, once
  per session and item; read by B6's `alerts.py intraday`. Monitoring only, nothing is traded.
- Slack notifications (B6, SPEC F9; `scripts/alerts.py`, code `marketbrief/alerts/`, notes `docs/ws/b6.md`): one
  thread per market per day in #market-brief: `morning` (top 5 by agreement at N+1 with the strongest other horizon,
  the day's head-to-head picks and whether each is viable at the owner's cost: expected gain after your cost > 0),
  `intraday` (B9's `intraday_alerts_feed`: new flagged open trades and material news), `close` (rule vs AI, every
  head-to-head trade, the 10 biggest wins and losses, net after market and your costs from B2's `cost_views`) and
  `corrections` (a reply per trade re-settled after its close post, 30 days); `weekly` (the research review as its
  own post) and `onboarding` (a reply to the command that asked; `post_onboarding_confirmation`); `post_brief`
  puts `notify_slack.py`'s brief into the day's thread (a reply when `alerts.py morning` posted first). Every read as of the clock (MB_NOW-aware),
  every signal labelled Paper, never advice. Each posted part is recorded in `data/<market>/slack_posts/` (kind
  `slack_posts`), so reruns never double-post and later posts find the day's thread; `--dry-run` writes to
  `work/alerts_dryrun/<market>/` and never posts. Token only from `SLACK_BOT_TOKEN` (without it, unthreaded
  messages through `SLACK_WEBHOOK_URL`); neither is ever printed.
- Refactor (feature freeze, `docs/REFACTOR_PLAN.md`): every step proves byte-identical outputs with
  `tests/golden/golden.py record|compare` (recorded set in `work/golden/`), keeps `ruff.toml` clean
  for the files it moves (ruff in `requirements-dev.txt`, dev and CI only) and shrinks the size
  allow-list in `tests/test_code_structure.py`. Queries whose row order or float sums reach an output
  have a full ORDER BY and order-independent sums (plan, "Known nondeterminism", fixed); the golden
  harness runs DuckDB with its default threads, and refactor steps keep those orderings

## Code rules
- Self-explanatory names (docs/REFACTOR_PLAN.md); the conventional short names `cfg`, `con`, `ctx`, `res`,
  `rec`, `src`, `reg`, `feats`, `preds` and `cal` are allowed (user decision).

## Judging every change
Every change to code, config, agent instructions or process is reviewed by the `judge` subagent
before it is merged or pushed to main, whoever made it: a subagent, a build agent, or the
orchestrating session itself (its own edits and merge-conflict resolutions included).
- Give the judge the exact instructions, the claimed result and where the work lives. Never
  merge or push on an agent's word: only a judge PASS counts. (Daily-run appends to `data/` pass
  on the `validate.py` gates instead; see below.)
- Any FALSE claim makes the verdict FAIL, even if the code is right (the report must be true too).
- Severity: every finding is a BLOCKER or COSMETIC. Blockers: broken or wrong functionality, wrong
  numbers, look-ahead, data loss or corruption, false claims or invented sources/data, broken rules,
  untested core logic. Cosmetic: doc wording, naming, formatting, nice-to-have tests for code that
  works. Only blockers fail a verdict and trigger another round; each cosmetic finding becomes a
  GitHub issue labelled `cosmetic` to fix later, and the work can merge.
- Build work: on FAIL (any blocker), send the blocker list back and judge again, repeating until PASS.
  A re-check covers only the listed blockers and the diff that fixed them, not the whole batch again.
  Nothing is merged or pushed to main before its PASS.
- Batches: plan work as a few batches (a feature, a refactor chunk, or a group of related fixes with
  the cosmetic issues that touch the same files), build the whole batch, then one review per batch;
  never a review cycle per small item. The reviewer lists every finding in one pass.
- Build workflow (keep it fast): the builder runs the fast tier while iterating and the full suite
  once at the end; live network checks only when a collector or fetcher changed (otherwise saved
  fixtures); the golden harness (`tests/golden/golden.py`) once at the end for refactors. Every number
  in a build report (test counts, row counts, timings) is pasted from command output, never retyped.
  Mechanical work (moves, renames, refactor steps proven by the golden harness) runs on Sonnet with
  medium effort; new logic and the judge run on Opus. At most one heavy job (full suite, golden run,
  live collection) at a time on the session's machine.
- Scope of a review follows the change: an end-to-end run of the routine is needed only when
  executable behaviour changes (scripts, SQL views, schemas, config). Docs, wording and
  agent-instruction changes get a judge review of the diff only, never an end-to-end run.
- Merging: a batch is merged to main as soon as its review passes; the working branch is only where a
  batch is built. The end-to-end run of both markets is required before the routines are re-enabled,
  not before code reaches main.
- Tests (offline; a guard in `tests/conftest.py` fails any test whose Python code reaches the network;
  it sees Python sockets only, not C libraries or node): the fast tier
  `python -m pytest -m "not slow" -n auto` on each edit, the full suite `python -m pytest -n auto`
  before review or merge. GitHub Actions (`.github/workflows/tests.yml`) runs the full suite on every
  push and PR, except `test_every_logged_commit_exists` (CI cannot see local, unpushed build branches).
  A reviewer may cite the passing CI run for the reviewed commit as evidence of the full suite instead
  of rerunning it, but still runs the tests specific to the change and `tests/test_judgments.py`
  locally. A merge review reruns tests when a conflict touched code, and the orchestrator always runs
  the full suite after any merge that brings in code changes (CI also runs on push). New end-to-end
  tests go in `SLOW` in `tests/conftest.py`.
- Daily runs are gated by `scripts/validate.py` (deterministic checks after each stage, settings
  in `config/validate.yaml`) and, for the reflector's lessons, by `scripts/lessons.py validate`, for the results-analyst's bullets by `scripts/results_digest.py validate`,
  for the deviation-explainer's notes by `scripts/intraday_check.py validate`, for the AI traders by
  `python -m marketbrief.traders add`, for the EOD analyst by `eod-validate`, for the research director by
  `director-validate`, not by the judge: one retry (the run is time-boxed), then the failed
  output is dropped or withheld as `routine/PROMPT.md` says and listed in the report's
  `data_quality`. The judge still checks the monthly graph-builder edges, and once a week
  (`scripts/spotcheck.py --if-due`) a deterministic sample of the past week's output (2 forecasts
  with their evidence, 1 filled report, 1 lesson, 2 claims with their status) for what scripts cannot see.
- Every verdict, PASS or FAIL, is appended as one line: build work to `judgments/log.jsonl`
  (subject, work, commit, round, verdict, summary, recorded_at as ISO UTC); daily-run verdicts
  (graph-builder, spot-check) to `data/<market>/judgments/` (schema `judgments` in
  `scripts/marketbrief/core/schemas.py`). Both are append-only, and `tests/test_judgments.py` checks the build log's
  format and that every commit exists.

## Data rules
1. Files under `data/` are append-only. Never edit, reorder or delete existing lines or files.
   Corrections are new records (e.g. a newer `news_enriched` row for the same id).
2. Agents append via a temp file in `work/` then `cat work/x.jsonl >> data/...`. Never use a
   tool that overwrites an existing data file.
3. All timestamps are ISO 8601 UTC. Never use information published after a prediction's `made_at`.
4. Numbers come from `scripts/context.py` or DuckDB (run from `scripts/`:
   `python -c "from marketbrief.core.database import connect; print(connect('us').execute('...').df())"`),
   never from memory or estimation.
5. Don't read raw data files in bulk. Use the context pack, DuckDB queries and the summaries.
6. A market's agents only read and write that market's `data/<market>/`, `summaries/<market>/`
   and `reports/<market>/`.
7. Stored CSVs keep CRLF line endings (`csv.writer`); the collect gate blocks on a bare LF
   (`CSV_LINE_ENDINGS`, issue #47) because DuckDB's glob read silently drops such a file.

## Prediction rules
- One record per call: `id` = `<as_of_date>-<ticker>-<horizon>d`; skip if the id already exists.
- `direction` is `up` or `down`; `horizon_days` is one of `config/strategies.yaml` `horizons` (1-5; N+k = sell at
  the close of the k-th session after D); `confidence` 0.50-0.90.
- Strategy predictions (`strategy_predictions`) follow docs/SPEC.md F2.6: horizons N+1..N+5 (the k-th session
  after D); rule strategies cite their model score and feature snapshot ids, baselines their feature snapshot id; a
  prediction made at or after D's open is refused by the settlement (F1.8).
- `as_of_date` = the latest price date in the context pack for that ticker.
- `evidence_ids` must reference news/filing ids. Abstaining is always allowed and often right.
- News verification (DESIGN.md 3b): the first evidence id (the main evidence) must be
  `confirmed_primary` or `corroborated` as of `made_at`; `rumour` and `promotional` ids never support a
  call; a `contradicted` id only with `range_widen`; a `single_source` or `unverified` id lowers
  confidence by at least 0.05 (at most 0.85).
- No new call for a ticker with indicator quality `BLOCKED`, or with earnings within 1 day
  (`days_to_earnings` <= 1). Lower confidence in `EVENT_HEAVY` and `UNSTABLE` regimes.
  No call for a company that is not active (`cfg["active_tickers"]`: inactive or deleted companies are never
  predicted or traded; their open paper trades still settle).
- Price ranges are computed by `scripts/ranges.py`, never by hand. The forecaster may only
  widen a range (`range_widen` 0-0.5), never narrow it.
- Calibrate against the track record: if a confidence band hits less often than its stated
  confidence, use lower confidence or abstain.
- Signal model anchor (forecast-v11): when a model score exists for the call's id, `model_prob` = that
  score, `agent_adjustment` within +-0.10 (with `adjustment_reason` when not 0), `direction` = the side of
  0.5 of model_prob + adjustment, `confidence` = max(final, 1 - final).
- `prompt_version` identifies the agent instructions used (bump it when agent files change).
