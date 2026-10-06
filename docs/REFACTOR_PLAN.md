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

Both run the parallel schedule by default (`tests/golden/parallel.py`): the two markets at once, each
on its own copy of the seeded root (a sibling directory whose path has the run directory's length),
and within a market up to `--jobs` (default 3) steps at a time where they do not conflict. A step
waits for every earlier step of its phase that writes what it reads or reads or writes what it
writes; the reads and writes of each step are declared in `ACCESS` (data kinds, checked against the
step's SQL, and named work/report files), and a step without a declaration waits for every earlier
step. The late phase starts after the pre_open phase. Each market's copy is then merged back into the
run directory in market order (its path rewritten to the run directory's). `--serial` runs every
step in list order in one root, as the harness did before. Both give the same bytes, so a record of
either compares with the other. The `ACCESS` declarations are checked by that equality only
(`tests/test_golden_schedule.py` checks that every step has one and that the writers keep their
order): after changing a step, its script's queries or `ACCESS`, and at least once per refactor
step, run `record --serial` and a parallel `compare` against it.

Fixed inputs:
- `data/`, `config/` and `reports/` extracted with `git archive` from commit
  `24749bdc4835bff242b2683f83e85f2a7e3a2ab0` (`INPUT_COMMIT`), never the working tree, so daily-run
  appends do not change the inputs;
- a synthetic overlay built by rules in `tests/golden/overlay.py`: stored calls of ISO week 2026-W39
  (the first 3 tickers of each market, 1d and 5d, every weekday 2026-09-21..25), a forecaster file
  (`work/predictions.jsonl`: one 5d call per ticker with news, citing a real stored news id, preceded
  by the primary id that confirms one of the ticker's events in news_verified when there is one, plus one
  call that breaks the rules: confidence 0.95 and an unknown evidence id), number-free lessons for
  the reflector's role, and number-free sentences in place of the report's AGENT markers;
- seeded kinds (`tests/golden/seed.py`, `tests/golden/seed_sources.py`). The pinned data has no rows
  of the relationship, fundamentals, macro, short-selling, NSE, graph, options, price-source and
  SEC-time kinds, so the real collectors fill a separate scratch root from the test fixtures and their
  data files are copied into the golden root (never over a file):
  - India: `collect_relations_india.py` and `collect_nse_india.py --replay tests/fixtures/nse/real
    --today 2026-10-05 --full` (insiders, holdings, announcements, financials, flows, delivery), then
    `collect_relations_india.py --replay` on `tests/fixtures/nse/synthetic` with its `__Dn__` dates set
    relative to 2026-10-05 (deals and insider trades of watchlist tickers; the real snapshot has none),
    `graph.py add tests/fixtures/graph_edges.jsonl` (3 edges; the fixture's 4th edge is invalid on
    purpose, so that step exits 1) and `graph.py attempt`, and `collect_flows_india` on
    `tests/fixtures/sources` (fpi, indices);
  - US: `collect_insiders`, `collect_stakes`, `collect_holdings` and `collect_fundamentals` with
    `MB_SEC_FIXTURES` (a urls.json built as in tests/test_relationships.py and
    tests/test_fundamentals.py; the seed config tracks the fixture 13F filer 9999200 in place of the
    real filers), and `collect_macro` and `collect_shorts` on `tests/fixtures/sources`;
  - rule-built rows for the kinds whose collectors need Yahoo or SEC header pages: options (AAPL,
    JPM, NVDA), sec_times (one Form 4 accession), price_sources (one INFY bar); and India financials
    of the quarter a year before the fixtures' latest (2025-04-01..06-30 for INFY consolidated,
    HDFCBANK and SBILIFE standalone), so the y/y columns of "Latest quarterly results" have values;
  - the fixture 13F tables are served with the AAPL common-share values times 1,000,164 (copies in
    `run/seed/sec/`; tests/fixtures unchanged), so the 13F `value_bn` is 37.51 instead of 0.0.
    Checked: `round(value_usd / 1e9, 1)` in smart_money.py fails `compare` (5 files, the US context
    packs) and `round(revenue_yoy * 100, 0)` in nse_context.py fails it (7 files: the India context
    packs and the ai_replay context with its sha256); with the earlier seed both printed the same
    (0.0, empty);
  - the seed root lives in a temporary directory outside the checkout (the NSE `--replay` guard
    refuses any write target inside a repository) and is copied to `run/seed/root`; its paths appear
    as `<SEED>` in the seed logs;
- each script runs as a subprocess with `MB_ROOT`/`MB_CONFIG` = the scratch root, `MB_MARKET`, a fixed
  `MB_NOW`, `PYTHONHASHSEED=0`, `TZ=UTC`, no Slack/Neo4j/SEC credentials or proxies (the seed sets a
  dummy `SEC_USER_AGENT`), and `tests/golden/site/sitecustomize.py` loaded: the test network guard
  (any non-loopback connection is refused and logged; a refusal fails the comparison). DuckDB runs
  with its default threads, as in production (the one-thread setting was removed when "Known
  nondeterminism" below was fixed); `GOLDEN_DUCKDB_THREADS=N` sets N threads to stress it.

Phases (seed first, then two per market, each with a frozen clock):

| phase | india MB_NOW | us MB_NOW | what it exercises |
|---|---|---|---|
| seed | 2026-10-05T02:00Z | 2026-10-05T12:00Z | the collectors above, into the seed root |
| pre_open | 2026-10-05T02:40Z | 2026-10-05T12:15Z | bars current; rows collected later that day are flagged by validate (SCHEMA: time in the future); scoring of the W39 calls (27 India and 30 US outcomes); US publishes 40 ranges (1d and 5d, using the seeded option IV); India's ranges for as-of 2026-10-01 are already stored (skip path); report, charts, HTML, Slack dry run |
| late | 2026-10-06T02:30Z | 2026-10-06T12:15Z | every stored input visible; bars a session behind (STALE_BARS, MISSING_REGIME failures); scoring again (nothing new to score); lessons (27 and 30 added); news clusters (15 and 20 written); claims prepare (7 and 10 clusters selected; no filing text without an SEC user agent); synthetic claims for events with a stored primary text (India 12 written and added, quoting NSE announcement subjects and item titles; US none); news status (15 and 20 rows: India 6 confirmed_primary, 1 single_source, 8 unverified; US 13 promotional, 1 single_source, 6 unverified); forecaster gate (the rule-breaking call dropped; the calls whose main evidence is an unverified news id dropped by NEWS_STATUS_MAIN; India appends 1 call citing its event's confirming announcement first, US none); ranges.py on the late path (as-of bars a session behind: target session closed, nothing published); review; spot-check; backtest; replays; ai_replay; Neo4j dry run |

Commands covered: 11 seed runs, then 53 script runs per market (106), plus 6 synthetic-input steps per
market; the lists are `seed_steps()` in seed.py and `steps()` in golden.py:

| script | invocations (per market unless noted) |
|---|---|
| market_status.py | `--now` pre-open clock, mid-session 2026-10-05T15:00Z, late clock |
| validate.py | `--stage collect` (x2), `features` (x2), `context` (x2), `forecast` (absent file; real file), `report` (x2), `all` |
| score_predictions.py | pre_open, late |
| lessons.py | `prepare`, `validate F`, `add F` |
| features.py, calibrate.py | pre_open, late |
| news_clusters.py | late |
| claims.py | `prepare`, `validate`, `add` (late; the claims file is written by the overlay) |
| news_status.py | late |
| context.py | x4 (before and after ranges, both phases; stdout saved as work/context.md) |
| ranges.py | pre_open, late |
| review.py | `--week 2026-W39`, then `--if-due --week 2026-W39` (not-due path) |
| charts.py, report.py, html_report.py | pre_open, late (`report.py --force` in late) |
| notify_slack.py | `--dry-run` (pre_open) |
| spotcheck.py | `--week 2026-W39` |
| graph.py | `status`; seed (India): `add`, `attempt` |
| backtest.py | `--eval-sessions 40` |
| replay.py | `--start 2026-09-14 --end 2026-10-01`, and the same with `--aci` |
| ai_replay.py | `dates`; `prepare --date 2026-09-25` (scratch root, source = the golden root); `record` with an empty calls file; `score` |
| neo4j_sync.py | `--dry-run --full` (statements written to work/neo4j_dryrun/) |
| seed (fixtures) | India: collect_relations_india (x2), collect_nse_india, collect_flows_india; US: collect_insiders, collect_stakes, collect_holdings, collect_fundamentals, collect_macro, collect_shorts |

What runs on rows (checked in the recorded set, late-phase context packs): every seeded context
section is non-empty. US: "Macro & flows" (15 rows), "Short selling" (20), "Smart money" (insider
flow 1, largest trades 2, 13D/13G 2, 13F 20) and "Fundamentals" (last quarter 2, balance sheet 1).
India: insider trades 4, bulk/block deals 2, promoter holding and pledge 4, relationship risk flags 3,
connections 12, FII/DII flows 1, NSE announcements 6, quarterly results 3, delivery 20, FPI 9, NSE
indices 14. The Neo4j dry run reads rows of insiders, stakes, holdings_13f, fundamentals (US) and
announcements, insiders, deals, shareholding, graph, financials, flows (India). So these run on real
rows: common, events, indicators, regime, rangelib, range_inputs (incl. option IV), aci, scoring,
adjust, prediction_rules, narrative_numbers, view_data, relations, smart_money, fundamentals,
macro_context, nse_context, graph, news_tags, news_verify (cluster and validate side), and, through
the seed, sec, nse, sources and the collectors named above. Their SQL views (insider_flow,
insider_trades, stake_filings, activist_stakes, holdings_quarter/change/filings, fundamentals_*,
macro_series/latest, shorts_*, short_interest_*, fpi_*, indices_*, deals_scored, holdings_quarterly,
pledge_changes, graph_edges, announcements_*, financials_*, flows_daily, delivery_stats,
options_latest) run on those rows.

Still running on empty or no data (explicitly uncovered):
- kinds with no rows: news_articles (collect_articles needs article pages), primary_texts (no SEC
  text in the harness; tests/test_news_claims.py covers it on fixtures), US news_claims, adjustments (no split in
  the window), judgments, range_outcomes (the stored ranges' targets have no bars yet), US graph and
  India stakes/fundamentals (not applicable to that market);
- context sections that stay empty: in the late phase "Overnight cues" (the stored quotes are of
  2026-10-05, the late clocks' day is 2026-10-06; the pre-open packs show 28 US and 15 India rows);
  India "Sector ETFs and indices" (no such bars in the pinned data); "Ranges scored on the latest
  target date", "Range scorecard", "Judge FAILs" and US "Connections" in both phases;
- not run at all: collect_prices, collect_quotes, collect_events, collect_news, collect_filings,
  collect_options, collect_articles and check_sec_times (Yahoo, RSS, article pages, SEC header pages;
  covered by the fixture tests test_collectors, test_price_fallback, test_split_adjust,
  test_range_inputs, test_news_verify, test_sec_times), `ai_replay.py backfill`, `notify_slack.py`
  posting, `neo4j_sync.py` against a server, `relations.py` main and `graph.py hits|edges|check`.

Compared per step: exit code, stdout, stderr. Compared files: every file under the run directory
that the run created or changed (seed root and its copies into data/, data/ appends, reports, chart
PNGs, HTML, work/ files, ai_replay roots and results, Neo4j dry-run statements), as sha256 of the
normalised bytes; an input file the run deleted is a difference too. 1621 files per run when recorded
at bef503b.

Normalisation (the complete list; nothing else is masked; `NORMALISED` in golden.py):
- the run directory's absolute path -> `<RUN>`, this checkout's path -> `<CODE>` (outputs print paths);
- wall-clock values that do not follow MB_NOW, each masked only in the outputs where it appears:
  `runtime_s` (replay.py) in `root/data/*/replays/`, `root/reports/*/replay-*.json` and the replay
  steps' stdout; the text `runtime N s.` in `root/reports/*/replay-*.html`; `generated_at`
  (view_data.py) in `root/reports/*/<date>.html` and `root/work/slack_*_plan/<date>.html`;
  `prepared_at` (ai_replay.py prepare) in `ai_replay_*/ai_replay.json` and its step stdout;
  `seconds` (news_clusters.py) in its step stdout.

How each later step proves byte-identical outputs:
1. on the base commit of the step (before any change): `python tests/golden/golden.py record`;
2. make the step's changes;
3. `python tests/golden/golden.py compare` must print `"identical": true` and exit 0 (it reruns the
   whole set; about 2 minutes, `--serial` about 5.5); its output, the base commit and the step's
   commit go to the judge;
4. any difference is a blocker, even a float's last digit; the normalisation list above may not grow
   in a refactor step (a new wall-clock field would be a behaviour change).

The recorded set (manifest with hashes and exit codes plus a full copy of every output, used for
diffs) lives in `work/golden/` (git-ignored). Committed are only `tests/golden/golden.py` (steps,
runner, hashing, record/compare), `tests/golden/parallel.py` (the parallel schedule and the merge),
`tests/golden/overlay.py` (synthetic inputs), `tests/golden/seed.py` and
`tests/golden/seed_sources.py` (seeded kinds) and `tests/golden/site/sitecustomize.py`.
Evidence (2026-10-06, harness at bef503b): `record` then two `compare` runs, both
`"identical": true` over 1621 files with a clean network log; a deliberate change in a seeded module
(`macro_context`: basis-point changes printed with one decimal) made `compare` fail on the US context
packs (5 files: 4 context steps' stdout and work/context.md); earlier (before the seed) a change in
`rangelib.naive_range` (factor 1.0001) failed with 22 differing outputs.
Parallel schedule (2026-10-06, 4 cores): `record --serial` at 2695ad7 took 310 s; the parallel
`compare` against it printed `"identical": true` over 1621 files in 115 s. The parallel run also
compared identical with a record made by the previous harness (one root, serial) at 2d90f32, so the
per-market roots and the merge reproduce the shared-root run byte for byte.

### Known nondeterminism (fixed)

Production `common.connect` runs DuckDB with its default threads. Several queries had no full
ORDER BY, or aggregated floats in scan order, so their row order, or a float's last digit, could
differ between two runs on the same data. One observation (2026-10-06): a compare with default
threads against the then one-thread record differed in 25 of 1621 files.

Fixed (commits f548309 and e2e499b): every query below now has a full ORDER BY (a unique key, or
every output column), and float averages and sums that reach an output are order-independent:
SQL sums over `TRY_CAST(x AS DECIMAL(38,10))` (integer arithmetic; `avg` of it is the exact sum
divided by n), `scoring._mean` (exact rational sum, rounded once), split-factor products over a
sorted list. Limits of the decimal cast: each value is rounded to 10 decimals before the sum; NaN,
infinities and values of 1e28 or more become NULL and are left out of `avg`/`sum` (before, they
made the result NaN or inf), while `count(*)` beside them still counts their rows
(`tests/test_determinism.py::test_exact_decimal_sum_limits`).

Rounding convention for printed whole percents: half up on the value's decimal form, everywhere
(1- and 2-decimal percents keep Python formatting, e.g. in backtest tables, range/validate notes, review.py's
`rel_score` and ablation `:+.1%` columns and collect_prices.py's split-gap message).
`scoring.percent` (whole percent, `decimal` ROUND_HALF_UP) prints every share in the md report,
the Slack text, the context pack's proper-score tables and view_data's call and record texts; the
HTML report's JavaScript uses `pct0` (same rule). The weekly review, chart labels and range/regime
notes use `scoring.percent` too; no `:.0%` format is left in `scripts/` (a test checks this). DuckDB's
`round()` rounds half up on the double's binary value, so a 2-decimal SQL rounding can differ from
`percent` on values like 1.005 (not used for printed whole percents). So an
exact 0.625 (a band average, or 5 of 8 hits) prints 63% in the md report and the HTML alike
(before: 62% from Python's half-to-even `:.0%` beside 63% from JavaScript's `Math.round`).

| place | change |
|---|---|
| `score_predictions.py` `SQL`, `RANGE_SQL` | `ORDER BY base.id, base.made_at` / `ORDER BY r.id`: outcomes and range_outcomes appended in id order |
| `scoring.summary` | calls `ORDER BY id, scored_at`, ranges `ORDER BY id`; Brier, log loss, `mean_conf` and the range means use `_mean` |
| `view_data.py` | `SCORED_CALLS_SQL` ordered; `BANDS_SQL` exact average; per-ticker range/call records `ORDER BY ticker, h`; news `ORDER BY id` (ties in the item ranking and the same-title dedupe); announcements `ORDER BY id` (sources map); company events `ORDER BY date, ticker, type, name` |
| `context.py` | "Open predictions" `ORDER BY as_of_date, ticker, horizon_days, id, direction, confidence`; news sentiment, "Range scorecard" and "Track record by horizon" averages exact; SEC filings and scored ranges full keys; upcoming company events `ORDER BY ALL`; judge FAILs `+ agent, round` |
| `report.py` | `CONF_BANDS_SQL` (in view_data.py) exact; scorecard over `RANGE_RECORD_EXACT`; yesterday's calls `ORDER BY ticker, horizon_days, id`; quotes `ORDER BY symbol`; features `ORDER BY ticker`; scored ranges `+ id` |
| `relations.py`, `smart_money.py`, `nse_context.py` | `+ id` after value/date keys (ties under `LIMIT`); FII/DII sums exact |
| `macro_context.py` | NSDL 5-report net sum exact (printed rounded to whole crore) |
| `calibrate.py`, `aci.py` | live pools `ORDER BY id` (weighted quantile with tied z values) |
| `ai_replay.py` evidence, `lessons.evidence`, `spotcheck.evidence_rows`, `validate.evidence_times` | ordered, so the row kept per id and the output order are fixed (lessons: in the call's `evidence_ids` order) |
| `validate.py` BAD_CLOSE, `ranges.py` options, `review.latest_aci_replay` | `ORDER BY 1`; `ORDER BY ticker, expiry, day`; `+ id DESC` |
| `sql/views.sql` | `bar_factors` and `deals_scored` factor product `list_product(list_sort(list(...)))`; `insider_flow` dollar sums exact |

Not changed, judged deterministic: plain scans and filters (DuckDB keeps insertion order);
`holdings_quarter` sums of share counts and 13F dollar values (integer-valued doubles, exact below
2^53); window averages in views, whose frames are ordered by a date unique per partition. Not
covered: a `DISTINCT ON` whose ORDER BY ties on two different rows keeps either.

Proof (2026-10-06): golden `record` with default threads at e2e499b, then two `compare` runs, both
`"identical": true` over 1626 files. Against the one-thread record at 29fde83, 41 files differ,
all row orderings or float last digits of the queries above: outcome rows (same lines, id order),
"Open predictions" and SEC-filing row order in the context packs (and so the ai_replay context
sha256), `mean_conf` and `calibration[].stated` (0.5499999999999999 -> 0.55, 0.7000000000000001 ->
0.7, 0.6250000000000001 -> 0.625) in score summaries, review records and the HTML data (and so
its byte counts), yesterday's-calls row order, one INDIGO sentiment 0.15 -> 0.16 (exact mean 0.155, half up), and the copied
`sql/views.sql` in the ai_replay roots. `tests/test_determinism.py` runs each fixed query 12 times
with 8 threads on data built to expose ties and summation order. With the half-up convention
(golden record, then `compare` `"identical": true` over 1626 files) the 25 files that differ from
the e2e499b record are the "0.60-0.69" / "0.60-0.70" rows (62% -> 63%) in the md reports, their
skeleton and previous copies and the context packs' reliability table, and the HTML reports (the
`pct0` script lines) with their Slack-plan copies and byte counts.

## 2. Enforcement

- `ruff.toml` (ruff pinned at 0.16.10 in `requirements-dev.txt`, which CI installs with requirements.txt;
  the routine installs requirements.txt only): pycodestyle E/W (line length 120),
  pyflakes F (unused imports/variables), pep8-naming N, unused arguments ARG, commented-out code ERA,
  mccabe C901 (max complexity 12), pylint PLR0911/0912/0913/0915 (max 6 returns, 12 branches,
  6 arguments, 50 statements). Run `python -m ruff check scripts --statistics`.
- Step 0 reports only (no fixes). Counts on 2026-10-06 (commit 24749bd):

  | rule | scripts/ | tests/ (pre-existing files; the step-0 files are clean) |
  |---|---|---|
  | E501 line-too-long | 279 | 133 |
  | N806 non-lowercase variable | 38 | 1 |
  | PLR0913 too many arguments | 36 | 8 |
  | C901 too complex | 27 | 0 |
  | PLR0912 too many branches | 22 | 0 |
  | ARG001 unused function argument | 17 | 45 |
  | PLR0915 too many statements | 13 | 5 |
  | PLR0911 too many returns | 10 | 1 |
  | E741 ambiguous variable name | 9 | 5 |
  | ARG005 unused lambda argument | 2 | 9 |
  | F401 unused import | 1 | 3 |
  | ARG002 unused method argument | 1 | 10 |
  | F541 f-string without placeholders | 0 | 6 |
  | ERA001 commented-out code | 0 | 1 |
  | N802 invalid function name | 0 | 1 |
  | total | 455 | 228 |

  Most findings per file (scripts/): html_report 115 (mostly E501 in the embedded CSS/JS), replay 68,
  ai_replay 47, validate 37, neo4j_sync 18, collect_prices 18, report 15, review 12, collect_holdings 11.
  The new step-0 files (tests/golden, tests/test_code_structure.py, tools/) are clean.
- `tests/test_code_structure.py`: fails when a module or a class under `scripts/` (recursive, so the
  new package is included) exceeds 350 lines. Today's offenders are allow-listed with their line
  count; a listed module may not grow, and an entry must be removed once its module is within the limit
  or gone, so the list only shrinks. A further test checks every entry against the module's line
  count at commit 24749bd (via git; skipped when that commit is not available): an entry may not
  name a module that did not exist then or list more lines than it had, so the list cannot be raised
  by hand. No class exceeds 350 lines today (largest: sec.Edgar 131,
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
- `replay._r` = `scoring._r`; `replay.pct` = `ai_replay.pct` = `ai_replay._f` in body only: the
  default differs (`replay.pct(x, k=0)`, `ai_replay.pct(x, k=1)`, `ai_replay._f(x, k=1)`), so a merged
  helper must keep each caller's default (pass `k` explicitly). `tools/refactor_inventory.py` prints
  every same-name and same-body group with its signatures and flags differing ones;
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
"ROOT", ...)` in 11 test files: test_collectors, test_fundamentals, test_guard, test_judge_fails, test_news_tags,
test_news_verify, test_price_fallback, test_relationships, test_sources, test_split_adjust,
test_validate; 15 of the 16 test files that call `monkeypatch.setattr` patch an attribute of a scripts
module, the 16th, test_nse_india, only a client instance; `collect_prices.utc_today`, `collect_events.data_dir`, `sec.Edgar`,
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
| 3 | `collectors/` (the golden seed already runs the NSE, SEC-relationship, fundamentals and free-source collectors on fixtures; first extend it to collect_prices, collect_quotes, collect_events, collect_news, collect_filings, collect_options, collect_articles and check_sec_times with fixture clients and recorded Yahoo frames, so every collector gets byte-identical proof; then one collector family per sub-step: prices, events, SEC, NSE, free sources, news/articles) | collect_prices.py, collect_events.py |
| 4 | `analytics/` | range_inputs.py, news_verify.py, news_clusters.py |
| 5 | `pipeline/` (validate, review, lessons, context, ranges, scoring, spotcheck) | validate.py, review.py, lessons.py |
| 6 | `replay/` (backtest, rule replay, ai_replay; shared HTML parts) | replay.py, ai_replay.py, backtest.py |
| 7 | `presentation/` (report, html_report with CSS/JS as asset files, view_data, charts, Slack) | report.py, html_report.py |
| 8 | `graph/` (connection map, Neo4j) | neo4j_sync.py |

Status: steps 1 and 2 were built as one batch (build/refactor-batch2). Not in it: the calendar half of
`events.py` (`core/calendar.py`), `utils/text.clean` and the other "same purpose" helpers, and the top-50 string
literals and the other exception messages outside the code those steps moved (they move with their modules; the
four messages raised in more than one module are already constants).

Status of steps 3 and 4: built as one batch (build/refactor-batch4). Step 3 moved every collector into
`marketbrief/collectors/` (the `scripts/collect_*.py` and `check_sec_times.py` are thin entry points) and `sources`,
`nse` and `sec` into `marketbrief/sources/` and `collectors/`; the golden seed first gained offline collector seeds
(`tests/golden/seed_collectors.py`: faked Yahoo, feeds, article pages, NSE replay) whose outputs stay out of the
golden root. Step 4 moved the formulas and the range and news analytics into `marketbrief/analytics/`
(`range_math`, the range-input modules, `news_sources`/`article_*`/`text_measures`, `adaptive_conformal`,
`calibration`, `range_publication`, ...); `scripts/features.py`, `calibrate.py`, `ranges.py`, `relations.py`
and `news_clusters.py` are thin entry points. Removed from the allow-list: collect_prices.py,
collect_events.py, news_verify.py, news_clusters.py, range_inputs.py.

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
