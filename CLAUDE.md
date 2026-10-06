# market-brief

Personal research project: two scheduled Claude Code routines (India and US) collect free
prices, overnight cues, news, events and SEC filings, compute PASDS indicators and the market
regime, reason over them with subagents, make small, scored predictions, store everything in
this repo and post one Slack digest per market. Research only: never place trades, never
connect to brokerage tools, and nothing here is investment advice. Design: `docs/DESIGN.md`.

## Layout
- `config/markets/<market>.yaml` per market: exchange calendar, timezone, market-level symbols
  (benchmark, vol index, cues, factors), regime thresholds, sectors, tickers, news feeds
- `config/events.yaml` scheduled market events (rules and fixed dates)
- `scripts/` deterministic Python. Every script takes `--market india|us` (or `MB_MARKET`).
  Collectors: `collect_prices` (India: a watchlist bar Yahoo lacks for a recent session comes
  from NSE's bhavcopy when its price basis checks out, listed in `filled_from_nse` and recorded in
  `data/india/price_sources/`, view `bar_sources`; `price_fallback` in the market config; both markets:
  a split or bonus confirmed by a Yahoo `Stock Splits` row, or for India by NSE's bhavcopy, is recorded
  once in `data/<market>/adjustments/` (`scripts/adjust.py`) and applied on read by the `ohlc`/`bars`
  views, raw bars in `ohlc_raw`/`bars_raw`; an unconfirmed re-base is a `warnings` entry and holds
  that symbol's new bars (`held`); a wrong record is cancelled by a later one with `supersedes`;
  DESIGN.md section 3), `collect_quotes`, `collect_events` (also backfills past earnings
  days, India from NSE results filings, US from SEC 8-K item 2.02 kept only when it is a quarter's
  results release, anchored on stored 10-Q/10-K `periodic_report` rows, and dividends), `collect_news`, `collect_filings`, `collect_options` (US option-chain
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
  the reader's HTML report from the filled md plus the data, and `notify_slack` posts a thread
  (summary, chart images, HTML file) with `SLACK_BOT_TOKEN`, or the summary text alone through
  `SLACK_WEBHOOK_URL`. Processing data (data/, context pack, summaries) and presentation (HTML,
  PNGs, Slack) are separate: `view_data.py` only reads the data for both presentation outputs.
  `backtest` evaluates the
  range formula walk-forward. `replay` is the historical replay of everything rule-based (no AI):
  each past day's 1d/5d ranges as `ranges.py` builds them, the regime, and direction baselines
  (always-up, momentum, RSI mean reversion), scored -> `reports/<market>/replay-<end>.html|json`
  and `data/<market>/replays/` (DESIGN.md section 7); `replay --aci` compares fixed bands with
  Adaptive Conformal Inference (`aci.py`: per horizon x band x regime miss rate alpha_t updated from
  outcomes scored before `calibrate` runs; `aci:` in `config/ranges.yaml`, off by default; the weekly
  review shows alpha_t and proposes switching it on from a replay with the same settings, marked
  provisional unless its held-out check `--aci-tune-end` agrees). `ai_replay` replays the AI agents as of past
  days (never runs an LLM itself); ForecastBench leakage rule: only as-of dates after
  `model_training_cutoff` in `config/settings.yaml` are a fair test, earlier ones are labelled
  `contaminated` on every row and the score page and scored separately, never pooled. Formulas: `indicators.py` (PASDS file 06), `regime.py` (file 07),
  `events.py` (calendar), `rangelib.py` (ranges; settings in `config/ranges.yaml`),
  `range_inputs.py` (past earnings moves, ex-dividend shift, beta split, implied vol; each
  switchable in `config/ranges.yaml`).
  `review` is the weekly review (coverage, calls, input ablations; thresholds in
  `config/review.yaml`): it proposes `config/ranges.yaml` changes, a human applies them.
  `validate` is the daily run's deterministic gate (`--stage collect|news|features|context|forecast|report|all`,
  settings in `config/validate.yaml`; prediction rules shared with `ai_replay` in `prediction_rules.py`);
  `spotcheck` picks the weekly judge sample.
  Schemas live in `scripts/common.py`.
- India primary sources (NSE; shared session and replay guard in `nse.py`): `collect_nse_india`
  -> `data/india/announcements|financials|flows|delivery/` (exchange announcements, Integrated
  Filing results per period and basis, FII/DII provisional flows, delivery %); context sections
  from `nse_context.py`.
- Relationships (DESIGN.md phase 5): `collect_relations_india` (NSE: SEBI PIT insider/promoter
  trades, bulk and block deals, shareholding and promoter pledges -> `data/india/insiders|deals|holdings/`),
  `relations.py` (risk flags: big deals, pledge rises, insider sales; optional range widening in
  `config/ranges.yaml`, off by default) and `graph.py` (connection map in `data/<market>/graph/`:
  `status`, `edges`, `hits` = second-order news, `add` = validate and append the graph-builder's edges,
  `attempt` = record the monthly refresh in `data/<market>/graph_runs/`)
- SEC CIKs: every SEC collector reads a ticker's filings from its mapped CIK plus the CIKs under
  `fundamentals.predecessor_ciks` in `config/markets/us.yaml` (XOM: 2115436 and 34088), each
  accession once (`sec.ticker_submissions`).
- SEC acceptance times: the submissions JSON `acceptanceDateTime` can be shifted later by the New
  York UTC offset (+4h EDT, +5h EST) for a whole CIK's file (seen from 2026-10-05). `Edgar.recent`
  checks each file against the SGML header `<ACCEPTANCE-DATETIME>` (Eastern) of its newest and
  oldest filing (cached requests, `work/sec_acceptance.json`) and corrects it only when both are
  shifted; otherwise (mixed, unreadable) it keeps the served times and the collector lists the CIK
  in `warnings` (summary key `sec_times`: ok / shifted / unverified). Stored rows are fixed on
  read: `check_sec_times.py` (run by the routine after the SEC collectors) appends header times to
  `data/<market>/sec_times/`; `common.connect` reads `accepted_at` of filings, insiders, stakes,
  holdings and fundamentals through them, and `ai_replay` filters those kinds by the same times.
- Relationships, US (SEC EDGAR, helpers in `scripts/sec.py`): `collect_insiders` (Form 4),
  `collect_stakes` (13D/13G) and `collect_holdings` (13F for the filers and CUSIPs under
  `relationships:` in `config/markets/us.yaml`) write `data/us/insiders|stakes|holdings/`.
  Views `insider_flow`, `insider_cluster_buys`, `activist_stakes`, `holdings_filings`, `holdings_change` and
  `holdings_quarter` feed the context pack's "Smart money" section and a range risk note
  (`scripts/smart_money.py`; the widen `activist_13d_factor` in `config/ranges.yaml` stays off).
- Fundamentals, US (SEC XBRL company facts): `collect_fundamentals` writes 10-Q/10-K values
  (revenue, gross profit, operating and net income, diluted EPS, operating cash flow, capex, cash,
  debt parts, shares; quarter, H1/9M year-to-date and FY) to `data/us/fundamentals/`, one row per
  tag x period x filing that first reported or changed the value (`fundamentals:` in
  `config/markets/us.yaml`). Views `fundamentals_latest` (newest filing wins), `fundamentals_quarterly`
  (Q4 = FY - 9M and quarterly cash flows derived, marked), `fundamentals_metrics` (YoY growth,
  margins, FCF), `fundamentals_balance` and `fundamentals_latest_report` feed the context pack's
  "Fundamentals" section (`scripts/fundamentals.py`; no consensus estimates, so no "surprise").
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
- Macro, flows and short selling (issue #9; HTTP client and append helper in `scripts/sources.py`,
  context sections in `scripts/macro_context.py`): `collect_macro` (US `macro:` config: Treasury
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
  `scripts/news_verify.py`):
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
- `sql/views.sql` derived DuckDB views (bars, returns, latest features/regime/quotes, events,
  news by ticker/day, track record)
- `data/<market>/<kind>/YYYY/MM/YYYY-MM-DD.<ext>` raw, append-only records (UTC dates, except
  prices/price_sources/features/regime which use the trading date, and adjustments: the ex-date)
- `summaries/<market>/daily|weekly|monthly/` layered narrative memory written by Claude
- `reports/<market>/<session_date>.md` the daily report (agent-editable source);
  `reports/<market>/<session_date>.html` the self-contained reader's report linked from Slack
  (filters by sector and company; no network needed) and `reports/<market>/index.html` (all days);
  chart images in `reports/<market>/charts/<session_date>/` (`ranges`, `sectors`, `track_record`);
  `config/settings.yaml` holds the repo URL, optional `pages_url`, the Slack channel id and the AI
  model's `model_training_cutoff` (ai_replay's fair vs contaminated split)
- `reports/<market>/review-YYYY-Www.md` the weekly review (record in `data/<market>/reviews/`)
- `judgments/log.jsonl` every judge verdict on build work (append-only); daily-run verdicts are in
  `data/<market>/judgments/`
- `.claude/agents/` subagents: reflector (one lesson per settled call, after scoring), news-analyst,
  bull-researcher, bear-researcher, forecaster (reads the lessons; never overriding the prediction rules),
  graph-builder (monthly connection map; every edge cites a public source), and judge
  (independent verifier of code, config, agent-instruction and process changes, the monthly
  graph-builder edges and the weekly spot-check sample).
  Each agent's model and effort are set in its frontmatter (Sonnet 5.5 for news scoring, the
  reflector and the researchers, Opus 5.5 for the forecaster, graph-builder and judge; table in DESIGN.md section 13).
- `routine/PROMPT.md` the routines' saved prompt (one per market)
- Refactor (feature freeze, `docs/REFACTOR_PLAN.md`): every step proves byte-identical outputs with
  `tests/golden/golden.py record|compare` (recorded set in `work/golden/`), keeps `ruff.toml` clean
  for the files it moves and shrinks the size allow-list in `tests/test_code_structure.py`

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
- Scope of a review follows the change: an end-to-end run of the routine is needed only when
  executable behaviour changes (scripts, SQL views, schemas, config). Docs, wording and
  agent-instruction changes get a judge review of the diff only, never an end-to-end run. Nothing is
  merged or pushed to main before its PASS.
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
  in `config/validate.yaml`), not by the judge: one retry (the run is time-boxed), then the failed
  output is dropped or withheld as `routine/PROMPT.md` says and listed in the report's
  `data_quality`. The judge still checks the monthly graph-builder edges, and once a week
  (`scripts/spotcheck.py --if-due`) a deterministic sample of the past week's output (2 forecasts
  with their evidence, 1 filled report) for what scripts cannot see.
- Every verdict, PASS or FAIL, is appended as one line: build work to `judgments/log.jsonl`
  (subject, work, commit, round, verdict, summary, recorded_at as ISO UTC); daily-run verdicts
  (graph-builder, spot-check) to `data/<market>/judgments/` (schema `judgments` in
  `scripts/common.py`). Both are append-only, and `tests/test_judgments.py` checks the build log's
  format and that every commit exists.

## Data rules
1. Files under `data/` are append-only. Never edit, reorder or delete existing lines or files.
   Corrections are new records (e.g. a newer `news_enriched` row for the same id).
2. Agents append via a temp file in `work/` then `cat work/x.jsonl >> data/...`. Never use a
   tool that overwrites an existing data file.
3. All timestamps are ISO 8601 UTC. Never use information published after a prediction's `made_at`.
4. Numbers come from `scripts/context.py` or DuckDB (run from `scripts/`:
   `python -c "from common import connect; print(connect('us').execute('...').df())"`),
   never from memory or estimation.
5. Don't read raw data files in bulk. Use the context pack, DuckDB queries and the summaries.
6. A market's agents only read and write that market's `data/<market>/`, `summaries/<market>/`
   and `reports/<market>/`.

## Prediction rules
- One record per call: `id` = `<as_of_date>-<ticker>-<horizon>d`; skip if the id already exists.
- `direction` is `up` or `down`; `horizon_days` is 1 or 5 (trading days); `confidence` 0.50-0.90.
- `as_of_date` = the latest price date in the context pack for that ticker.
- `evidence_ids` must reference news/filing ids. Abstaining is always allowed and often right.
- No new call for a ticker with indicator quality `BLOCKED`, or with earnings within 1 day
  (`days_to_earnings` <= 1). Lower confidence in `EVENT_HEAVY` and `UNSTABLE` regimes.
- Price ranges are computed by `scripts/ranges.py`, never by hand. The forecaster may only
  widen a range (`range_widen` 0-0.5), never narrow it.
- Calibrate against the track record: if a confidence band hits less often than its stated
  confidence, use lower confidence or abstain.
- `prompt_version` identifies the agent instructions used (bump it when agent files change).
