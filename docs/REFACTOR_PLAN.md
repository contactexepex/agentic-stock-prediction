# Refactor plan (feature freeze: no behaviour changes)

Owner's binding rules for the refactor:
- no class longer than 350 lines, and no module longer than 350 lines (target);
- logical, functional, self-explanatory names for every class, function, parameter, argument and variable;
- no long or unnecessary inline comments: a short docstring per class and function states its purpose;
- helper, mapper and utility modules, so code is centralized and reusable;
- one `scripts/` folder with a package of subfolders for shared classes and logic; thin entry-point
  scripts stay at `scripts/<name>.py`, so the routine's commands (`python scripts/collect_prices.py
  --market india` ...) and the tests keep working;
- centralized constants: shared strings (data kinds, column names, source names, statuses, config
  keys, file names) and exception/log messages live in constants modules, not inline.
- Agreed Python note: pure calculations may stay module-level functions grouped by purpose; classes
  where there is state or a role (API clients, data access, mappers, collectors).

Step 0 (this document's commit) adds only the safety net: golden outputs, lint and size enforcement,
this inventory and plan. It moves no code.

## 1. Golden outputs (the proof that a step changed nothing)

`tests/golden/golden.py` runs the deterministic pipeline on fixed inputs and compares every output
byte for byte with a recorded run.

```
python tests/golden/golden.py record  [--dir work/golden]   # once, on the commit before the step
python tests/golden/golden.py compare [--dir work/golden]   # after the step: exit 0 = identical
```

Fixed inputs:
- `data/`, `config/` and `reports/` extracted with `git archive` from commit
  `24749bdc4835bff242b2683f83e85f2a7e3a2ab0` (`INPUT_COMMIT`), never the working tree, so daily-run
  appends do not change the inputs;
- a synthetic overlay built by rules in golden.py: stored calls of ISO week 2026-W39 (the first 3
  tickers of each market, 1d and 5d, every weekday 2026-09-21..25), a forecaster file
  (`work/predictions.jsonl`: one 5d call per ticker with news, citing a real stored news id, plus one
  call that breaks the rules: confidence 0.95 and an unknown evidence id), number-free lessons for
  the reflector's role, and number-free sentences in place of the report's AGENT markers;
- each script runs as a subprocess with `MB_ROOT`/`MB_CONFIG` = the scratch root, `MB_MARKET`, a fixed
  `MB_NOW`, `PYTHONHASHSEED=0`, `TZ=UTC`, no Slack/Neo4j/SEC credentials or proxies, and
  `tests/golden/site/sitecustomize.py` loaded: the test network guard (any non-loopback connection is
  refused and logged; a refusal fails the comparison) and DuckDB on one thread. The one-thread setting
  is needed because several queries have no full `ORDER BY`: with parallel scans, the order of the
  scored outcomes and the context pack's call list changed between two runs of the same code (seen
  2026-10-06; it also changed a float sum, `mean_conf` 0.625 vs 0.6250000000000001). It is a harness
  setting only; the code under test is not changed.

Two phases per market, each with a frozen clock:

| phase | india MB_NOW | us MB_NOW | what it exercises |
|---|---|---|---|
| pre_open | 2026-10-05T02:40Z | 2026-10-05T12:15Z | bars current; US publishes 40 ranges (1d and 5d); India's ranges for as-of 2026-10-01 are already stored (skip path); report, charts, HTML, Slack dry run |
| late | 2026-10-06T02:30Z | 2026-10-06T12:15Z | every stored input visible; bars a session behind (STALE_BARS, MISSING_REGIME failures); scoring of the W39 calls; lessons; news clusters; forecaster gate and append; late ranges; review; spot-check; backtest; replays; ai_replay; Neo4j dry run |

Commands covered (49 script runs per market, 98 per run, plus 5 synthetic-input steps per market;
the step list is `steps()` in golden.py):

| script | invocations (per market) |
|---|---|
| market_status.py | `--now` pre-open clock, mid-session 2026-10-05T15:00Z, late clock |
| validate.py | `--stage collect` (x2), `features` (x2), `context` (x2), `forecast` (absent file; real file), `report` (x2), `all` |
| score_predictions.py | pre_open, late |
| lessons.py | `prepare`, `validate F`, `add F` |
| features.py, calibrate.py | pre_open, late |
| news_clusters.py | late |
| context.py | x4 (before and after ranges, both phases; stdout saved as work/context.md) |
| ranges.py | pre_open, late |
| review.py | `--week 2026-W39`, then `--if-due --week 2026-W39` (not-due path) |
| charts.py, report.py, html_report.py | pre_open, late (`report.py --force` in late) |
| notify_slack.py | `--dry-run` (pre_open) |
| spotcheck.py | `--week 2026-W39` |
| graph.py | `status` |
| backtest.py | `--eval-sessions 40` |
| replay.py | `--start 2026-09-14 --end 2026-10-01`, and the same with `--aci` |
| ai_replay.py | `dates`; `prepare --date 2026-09-25` (scratch root, source = the golden root); `record` with an empty calls file; `score` |
| neo4j_sync.py | `--dry-run --full` (statements written to work/neo4j_dryrun/) |

Library modules run through them: common, events, indicators, regime, rangelib, range_inputs, aci,
scoring, adjust, prediction_rules, narrative_numbers, view_data, relations, smart_money, fundamentals,
macro_context, nse_context, news_tags, news_verify (cluster and validate side). Not run: sec, nse,
sources (imported only by collectors).

Compared per step: exit code, stdout, stderr. Compared files: every file under the run directory
that the run created or changed (data/ appends, reports, charts PNG, HTML, work/ files, ai_replay
roots and results, Neo4j dry-run statements), as sha256 of the normalised bytes; an input file the
run deleted is a difference too. 1508 files per run when recorded on 2026-10-06.

Normalisation (the complete list; nothing else is masked):
- the run directory's absolute path -> `<RUN>`, this checkout's path -> `<CODE>` (outputs print paths);
- JSON keys whose values come from the wall clock, not MB_NOW: `runtime_s` (replay.py),
  `generated_at` (view_data.py, the HTML report's data), `prepared_at` (ai_replay.py prepare),
  `seconds` (news_clusters.py summary);
- the text `runtime N s.` in replay.py's HTML footer.

Not covered, and why:
- the collectors (`collect_*.py`, `check_sec_times.py`, `ai_replay.py backfill`): they read the
  network (Yahoo, SEC, NSE, FINRA, Treasury, FRED, Cboe, NSDL, RSS, article pages); the golden run is
  offline by design. They are covered by the fixture-based tests (test_collectors, test_sources,
  test_nse_india, test_sec_*, test_fundamentals, test_relationships, test_price_fallback,
  test_news_verify). Step 3 below first adds a golden collector mode (local fixture server, see there);
- `notify_slack.py` posting, `neo4j_sync.py` against a server, `collect_articles.py`: network;
- `graph.py add|attempt|hits` and `relations.py main`: covered by test_relations, no stored edges in
  the pinned data.

How each later step proves byte-identical outputs:
1. on the base commit of the step (before any change): `python tests/golden/golden.py record`;
2. make the step's changes;
3. `python tests/golden/golden.py compare` must print `"identical": true` and exit 0 (it reruns the
   whole set; about 5 minutes); its output, the base commit and the step's commit go to the judge;
4. any difference is a blocker, even a float's last digit; the normalisation list above may not grow
   in a refactor step (a new wall-clock field would be a behaviour change).

The recorded set (manifest with hashes and exit codes plus a full copy of every output, used for
diffs) lives in `work/golden/` (git-ignored); only the generator, the comparer and the sitecustomize
are in git.

## 2. Enforcement

- `ruff.toml` (ruff pinned at 0.16.10 in requirements.txt): pycodestyle E/W (line length 120),
  pyflakes F (unused imports/variables), pep8-naming N, unused arguments ARG, commented-out code ERA,
  mccabe C901 (max complexity 12), pylint PLR0911/0912/0913/0915 (max 6 returns, 12 branches,
  6 arguments, 50 statements). Run `python -m ruff check scripts --statistics`.
- Step 0 reports only (no fixes). Counts on 2026-10-06 (commit 24749bd):

  | rule | scripts/ | tests/ (before this step's files) |
  |---|---|---|
  | E501 line-too-long | 279 | 135 |
  | N806 non-lowercase variable | 38 | 1 |
  | PLR0913 too many arguments | 36 | 8 |
  | C901 too complex | 27 | 0 |
  | PLR0912 too many branches | 22 | 0 |
  | ARG001 unused function argument | 17 | 48 |
  | PLR0915 too many statements | 13 | 5 |
  | PLR0911 too many returns | 10 | 1 |
  | E741 ambiguous variable name | 9 | 5 |
  | ARG005 unused lambda argument | 2 | 9 |
  | F401 unused import | 1 | 3 |
  | ARG002 unused method argument | 1 | 10 |
  | F541 f-string without placeholders | 0 | 6 |
  | ERA001 commented-out code | 0 | 1 |
  | N802 invalid function name | 0 | 1 |
  | total | 455 | 233 |

  Most findings per file (scripts/): html_report 115 (mostly E501 in the embedded CSS/JS), replay 68,
  ai_replay 47, validate 37, neo4j_sync 18, collect_prices 18, report 15, review 12, collect_holdings 11.
  The new step-0 files (tests/golden, tests/test_code_structure.py, tools/) are clean.
- `tests/test_code_structure.py`: fails when a module or a class under `scripts/` (recursive, so the
  new package is included) exceeds 350 lines. Today's offenders are allow-listed with their line
  count; a listed module may not grow, and an entry must be removed once its module is within the limit
  or gone, so the list only shrinks. No class exceeds 350 lines today (largest: sec.Edgar 131,
  news_verify.Sources 115, news_tags.Tagger 102).

  Module offenders (16): ai_replay 1215, replay 1143, review 857, neo4j_sync 818, validate 815,
  html_report 772, collect_prices 641, common 625, news_verify 570, collect_events 478, sec 395,
  news_clusters 387, lessons 376, report 369, backtest 354, range_inputs 351.

## 3. Inventory (2026-10-06, commit 24749bd; `python tools/refactor_inventory.py`)

59 modules, 17,408 lines in scripts/. Responsibilities per module (L = lines):

| module | L | responsibility |
|---|---|---|
| ai_replay.py | 1215 | as-of replay harness for the AI agents: sample dates, cutoff rules, copy data as of a cutoff, prepare/record/score, backfill, HTML score page |
| replay.py | 1143 | rule-based historical replay: inputs, per-day ranges/regime/baselines, statistics (binomial, clustered CI), ACI comparison, HTML and JSON report |
| review.py | 857 | weekly review: range and call summaries, confidence bands, ablations, ACI proposals, markdown |
| neo4j_sync.py | 818 | Neo4j projection: HTTP Query API client, dry-run sink, row shapers per kind, Cypher statements, watermarks, sync |
| validate.py | 815 | daily gates: file/schema/bar/fetch/summary/news/article checks, features, context, forecast, report stages |
| html_report.py | 772 | parse the filled report, render narrative HTML, page and index (inline CSS/JS) |
| collect_prices.py | 641 | Yahoo bars, NSE bhavcopy fallback, split/bonus detection, write CSV |
| common.py | 625 | paths, schemas, clock, market config, CLI args, day files, JSONL append, DuckDB connection with frozen clock |
| news_verify.py | 570 | news verification helpers: source allowlist, URL checks, fetch, extractors, sentences, numbers, MinHash |
| collect_events.py | 478 | earnings/dividends from Yahoo, SEC 8-K 2.02 backfill, NSE results filings |
| sec.py | 395 | SEC EDGAR client (Edgar), acceptance-time correction, filing helpers |
| news_clusters.py | 387 | same-event clustering, independent origins, primary-source candidates |
| lessons.py | 376 | reflection log: prepare facts, validate lessons, add, context section |
| report.py | 369 | report skeleton and Slack draft |
| backtest.py | 354 | walk-forward backtest of the range formula |
| range_inputs.py | 351 | earnings moves, dividends, index-cue beta, implied vol for ranges |
| collect_articles.py | 319 | read article pages behind material headlines |
| collect_relations_india.py | 319 | NSE PIT trades, bulk/block deals, shareholding and pledges |
| view_data.py | 318 | presentation view of a day (HTML report and Slack) |
| nse.py | 343 | NSE client (Nse), parsing helpers, scratch-root guard, collector main |
| collect_nse_india.py | 272 | NSE announcements, results, FII/DII flows, delivery |
| news_tags.py | 265 | ticker tagging and news ids |
| graph.py | 263 | connection map: edges, validation, hits, refresh record |
| ranges.py | 262 | publish 50%/80% ranges |
| collect_fundamentals.py | 260 | SEC XBRL company facts |
| narrative_numbers.py | 229 | numbers in narrative vs sources |
| collect_holdings.py | 220 | 13F holdings |
| notify_slack.py | 216 | Slack thread / webhook post |
| context.py | 204 | context pack |
| collect_macro.py | 201 | Treasury, FRED, Cboe |
| collect_flows_india.py | 196 | NSDL FPI, NSE index closes |
| events.py | 179 | trading calendar and scheduled events |
| collect_shorts.py | 177 | FINRA short volume and short interest |
| scoring.py | 176 | proper scores |
| charts.py | 175 | PNG charts |
| sources.py | 169 | HTTP client and storage for free-source collectors |
| rangelib.py | 165 | range math |
| collect_news.py | 162 | RSS headlines |
| indicators.py | 149 | PASDS indicators |
| relations.py | 143 | India relationship risk flags |
| collect_insiders.py, score_predictions.py | 140 | Form 4 insiders; scoring |
| collect_options.py | 138 | option implied vol |
| features.py | 136 | indicator snapshot and regime |
| aci.py, spotcheck.py | 128 | ACI tracker; weekly judge sample |
| collect_stakes.py | 121 | 13D/13G |
| calibrate.py | 108 | range calibration |
| check_sec_times.py | 97 | SEC header times |
| macro_context.py | 96 | macro/flows/short context sections |
| prediction_rules.py | 95 | CLAUDE.md prediction rules |
| adjust.py | 93 | split/bonus adjustments |
| collect_filings.py | 84 | SEC filings |
| smart_money.py | 74 | smart-money section and flags |
| collect_quotes.py | 73 | overnight cues snapshot |
| fundamentals.py | 63 | fundamentals section |
| nse_context.py | 56 | NSE context sections |
| market_status.py | 52 | trading-day status |
| regime.py | 38 | regime classification |

### Duplicated helpers found

Identical bodies in different modules (AST-equal):
- `report.money` = `view_data.money`; `report.table` = `review.table`;
- `replay.major_between` = `review.major_between`;
- `replay._r` = `scoring._r`; `replay.pct` = `ai_replay.pct` = `ai_replay._f`;
- `ai_replay._ts` = `prediction_rules.ts`.

Same purpose, slightly different behaviour (merge with explicit options; golden proves equality):
- number parsing `num`: nse.py (strips `,` and `%`), sec.py (strips `,`), sources.py (also `Rs.` and
  accounting negatives), view_data.py (JSON-safe rounding);
- timestamp/ISO formatting: `_ts`/`_iso`/`iso` in ai_replay, news_clusters, lessons, view_data, nse,
  prediction_rules; `iso_z`/`parse_z` in sec.py;
- `slug`: graph.py, neo4j_sync.py (with "unknown" fallback), collect_flows_india.py;
- `recent_sessions`: collect_prices.py (last n completed sessions) and sources.py (sessions in a
  calendar-day window); `next_session` in events.py and ai_replay.py;
- `clean` (text cleanup): neo4j_sync, notify_slack, review; `_clean`: news_verify, range_inputs;
- markdown tables: `common.md_table`, `report.table`, `review.table`, `lessons.table`;
- `stored` (rows already stored): check_sec_times, collect_fundamentals, collect_holdings;
- `base_row`: collect_articles, collect_holdings, neo4j_sync; `to_rows`: collect_holdings, collect_insiders;
- `range_summary`: replay, review; `summarize`: ai_replay, backtest, replay; `verdict`: backtest, review;
  `svg_calibration`, `tile`, `top_sentences`, `limitations`: ai_replay and replay (HTML pieces).

Repeated infrastructure:
- HTTP clients, each with its own pacing/retry/error type: `sources.Client` + `sources.FetchError`
  (urllib), `nse.Nse` + `nse.FetchError` (urllib opener with cookies), `sec.Edgar` (urllib, SEC pacing),
  `neo4j_sync.Neo4jClient` (urllib), `notify_slack.Slack` (urllib), `collect_articles` (requests
  Session), `collect_news` (feedparser), yfinance in collect_prices/collect_quotes/collect_events/
  collect_options. Each defines its own User-Agent and retry rule.
- JSONL reading by hand (`json.loads(line)` over `read_text().splitlines()`) in 10 modules (adjust,
  ai_replay x4, collect_events, collect_fundamentals, collect_holdings, common, graph, lessons, sources,
  validate x2); appends outside `common.append_jsonl` in ai_replay.py (context file) and
  collect_prices.py (CSV).
- config YAML loads outside common: `settings.yaml` in notify_slack.py, report.py and validate.py;
  `validate.yaml` in validate.py.
- CLI: `common.market_arg`/`require_market` in most scripts; ai_replay.py builds its own parser and
  repeats the "--market is required" message; every script ends with `print(json.dumps(..., indent=2))`.

### Top 50 string literals repeated across modules

Ranked by the number of modules, then total count (docstrings and f-string fragments excluded):

| # | literal | modules | count |
|---|---|---|---|
| 1 | `market` | 44 | 246 |
| 2 | `__main__` | 39 | 39 |
| 3 | `ticker` | 35 | 227 |
| 4 | `id` | 35 | 204 |
| 5 | `tickers` | 32 | 106 |
| 6 | `source` | 26 | 94 |
| 7 | `name` | 25 | 91 |
| 8 | `error` | 24 | 56 |
| 9 | `date` | 21 | 125 |
| 10 | `url` | 19 | 56 |
| 11 | `collector` | 19 | 28 |
| 12 | `step` | 18 | 37 |
| 13 | `first_seen_at` | 17 | 62 |
| 14 | `utf-8` | 17 | 44 |
| 15 | `close` | 16 | 62 |
| 16 | `failed` | 16 | 22 |
| 17 | `, ` | 15 | 34 |
| 18 | `symbol` | 14 | 33 |
| 19 | `warnings` | 14 | 18 |
| 20 | `; ` | 13 | 27 |
| 21 | `filings` | 13 | 27 |
| 22 | `store_true` | 13 | 17 |
| 23 | `regime` | 12 | 51 |
| 24 | `as_of_date` | 12 | 46 |
| 25 | `ranges` | 12 | 32 |
| 26 | `horizon_days` | 11 | 31 |
| 27 | `accepted_at` | 11 | 29 |
| 28 | `skipped` | 11 | 12 |
| 29 | `confidence` | 10 | 37 |
| 30 | `form` | 10 | 31 |
| 31 | `made_at` | 10 | 31 |
| 32 | `target_date` | 10 | 27 |
| 33 | `direction` | 10 | 26 |
| 34 | `session_date` | 10 | 22 |
| 35 | `calibration` | 10 | 18 |
| 36 | `calls` | 9 | 37 |
| 37 | `computed_at` | 9 | 28 |
| 38 | `earnings` | 9 | 26 |
| 39 | `hit80` | 9 | 26 |
| 40 | `symbols` | 9 | 26 |
| 41 | `title` | 9 | 26 |
| 42 | `hit50` | 9 | 25 |
| 43 | `kind` | 9 | 24 |
| 44 | `sector` | 9 | 23 |
| 45 | `quality` | 9 | 21 |
| 46 | `notes` | 9 | 20 |
| 47 | `sec_times` | 9 | 15 |
| 48 | `requests` | 9 | 10 |
| 49 | `_none_\n` | 9 | 9 |
| 50 | `accession` | 8 | 55 |

Just below the cut: `hi80` and `lo80` (8 modules, 28 each). They group into: column names
(`accession`, `ticker`, `id`, `tickers`, `date`, `close`, `as_of_date`, `horizon_days`,
`made_at`, `target_date`, `direction`, `confidence`, `hit50`, `hit80`, `first_seen_at`,
`accepted_at`, `computed_at`, `session_date`, `form`, `title`, `url`, `sector`, `quality`, `symbol`);
data kinds (`filings`, `ranges`, `calibration`, `regime`, `sec_times`, `earnings`); summary keys and
statuses (`step`, `market`, `collector`, `failed`, `skipped`, `warnings`, `error`, `notes`, `requests`,
`calls`); config keys (`symbols`, `name`, `source`, `kind`); formatting (`, `, `; `, `utf-8`, `_none_\n`).

### Exception messages raised more than once

| message | where |
|---|---|
| `unreachable` | nse.py:93, sec.py:133, sources.py:84 |
| `--market is required; available: {}` | ai_replay.py:1190, common.py:492 |
| `no benchmark bars; run collect_prices.py --period 2y first` | backtest.py:280, replay.py:276 |
| `no published ranges; run ranges.py first` | report.py:94, view_data.py:111 |

All other `raise X("...")` messages are used once; they still move to
`marketbrief/constants/messages.py` with the module that raises them.

## 4. Target layout

```
scripts/
  <name>.py                      thin entry points, unchanged commands (e.g. collect_prices.py:
                                 `from marketbrief.collectors.prices import main` + sys.exit(main()))
  marketbrief/
    constants/   kinds.py (data kinds), columns.py (column names), statuses.py (ok/failed/skipped/late,
                 regime codes, quality), sources.py (source names, hosts, user agents), config_keys.py,
                 files.py (file and folder names: work/context.md, settings.yaml ...), messages.py
                 (exception and log messages)
    core/        paths.py (CODE, ROOT, CONFIG, data_dir, day_file), clock.py (clock, utc_now, utc_today,
                 freeze_sql, FrozenClockConnection), schemas.py (SCHEMAS, FEATURE_COLS, RELATION_SCHEMAS),
                 market_config.py (MarketConfig: load_market, symbols_by_role, benchmark_key,
                 sector_etf_map ...), storage.py (JsonlStore: append, read, recent_ids), database.py
                 (connect, views), cli.py (market_arg, require_market, print_summary), calendar.py
                 (events.py calendar half)
    utils/       numbers.py (num variants, pct, rounding), timefmt.py (_ts/_iso/iso, iso_z/parse_z),
                 text.py (slug, clean), markdown.py (md_table, table), money.py
    sources/     http.py (one HttpClient base: pacing, retry, FetchError), sec_client.py (Edgar),
                 nse_client.py (Nse), yahoo.py (yfinance access), rss.py, article_fetch.py
    collectors/  prices.py (+ prices_nse_fallback.py, adjustments.py), quotes.py, events.py (+ events_sec.py,
                 events_nse.py), news.py, filings.py, options.py, insiders.py, stakes.py, holdings.py,
                 fundamentals.py, macro.py, shorts.py, flows_india.py, nse_india.py, relations_india.py,
                 articles.py, sec_times.py
    analytics/   indicators.py, regime.py, rangelib.py, range_inputs.py (+ earnings_inputs.py), aci.py,
                 scoring.py, calibrate.py, features.py, relations.py, smart_money.py, fundamentals.py,
                 news_tags.py, news_clusters.py, news_verify (split: allowlist, extract, similarity),
                 prediction_rules.py, adjust.py
    pipeline/    score_predictions.py, lessons.py (prepare, validate, add), context.py (+ macro/nse
                 sections), ranges.py, validate/ (files, bars, summaries, news, forecast, report),
                 spotcheck.py, review/ (summaries, ablations, proposals, markdown), market_status.py
    replay/      backtest.py, rule_replay/ (inputs, rows, statistics, aci_compare, html), ai_replay/
                 (dates_cutoff, copy_asof, prepare, record, score, html), html_parts.py (shared tiles,
                 svg_calibration, top_sentences)
    presentation/ view_data.py, charts.py, report.py, html_report/ (parse, render, assets: CSS and JS
                 as files read at build time), notify_slack.py, narrative_numbers.py
    graph/       connection_map.py (graph.py), neo4j/ (client, shapes, statements, sync)
```

Moving rules: the old module names (`common`, `events`, `sec`, `nse`, `sources`, `rangelib`, ...) stay
importable as re-export shims until every caller (scripts and tests) is moved, then the shim is
deleted in the step that empties it. Tests patch module globals today (`monkeypatch.setattr(common,
"ROOT", ...)` in 10 test files; `collect_prices.utc_today`, `collect_events.data_dir`, `sec.Edgar`,
`collect_articles.SESSION_FACTORY` ...): a patch on a shim does not reach moved code, so each step
moves the patched names behind one lookup point (e.g. `core.paths.root()` reading a module variable)
and updates those tests in the same step, keeping their assertions unchanged. Docs (CLAUDE.md,
README, DESIGN.md, routine/PROMPT.md) keep naming the entry points, which do not change.

## 5. Steps (each one small enough to judge)

| step | content | removes from the size allow-list |
|---|---|---|
| 0 | this commit: golden harness, ruff, size test, inventory and plan | none |
| 1 | `marketbrief/core`, `constants`, `utils`; common.py becomes a shim; identical helpers merged (money, table, major_between, _r, pct/_f, _ts); settings/validate YAML loads through core | common.py |
| 2 | `sources/`: one HttpClient base; Edgar, Nse, Client, Slack and Neo4j HTTP on it; FetchError unified with the same messages | sec.py, (nse.py stays < 350) |
| 3 | `collectors/` (first: golden collector mode, a local HTTP fixture server built from tests/fixtures plus recorded Yahoo frames, so collectors get byte-identical proof too; then one collector family per sub-step: prices, events, SEC, NSE, free sources, news/articles) | collect_prices.py, collect_events.py |
| 4 | `analytics/` | range_inputs.py, news_verify.py, news_clusters.py |
| 5 | `pipeline/` (validate, review, lessons, context, ranges, scoring, spotcheck) | validate.py, review.py, lessons.py |
| 6 | `replay/` (backtest, rule replay, ai_replay; shared HTML parts) | replay.py, ai_replay.py, backtest.py |
| 7 | `presentation/` (report, html_report with CSS/JS as asset files, view_data, charts, Slack) | report.py, html_report.py |
| 8 | `graph/` (connection map, Neo4j) | neo4j_sync.py |

Proof required for every step 1-8 (all four, given to the judge with the commands' output):
1. golden: `record` on the step's base commit, `compare` on the step's commit -> `"identical": true`;
2. full suite `python -m pytest -q -n auto` and the fast tier `python -m pytest -q -n auto -m "not slow"`
   pass with the same counts as the base (tests only move imports or monkeypatch targets, never assertions);
3. `python -m ruff check <every file the step created or moved>` is clean (all rules above);
4. `tests/test_code_structure.py` passes with the step's entries removed from `MODULE_ALLOWLIST`
   (and no new entry added).
Each step also moves its strings into `constants/` and its exception/log messages into
`constants/messages.py`, renames to self-explanatory names, and replaces long inline comments with
docstrings, only within the code it moves.
