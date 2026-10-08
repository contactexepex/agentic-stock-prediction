# WS1: MotherDuck warehouse adapter, sync and read models

## Scope
A derived copy of each market's data in MotherDuck database `market_brief`, plus precomputed per-page
read models the app (wave 2) reads with one keyed SELECT. It can be rebuilt from the repo at any time and
is cheap enough for the Lite plan (10 compute-hours a month). Branch `build/ws1-warehouse`.
Optional and non-blocking: static `reports/` and Slack never depend on it.

## Files
Created:
- `config/warehouse.yaml`: provider, database name, Postgres endpoint (`pg_host`, `pg_port`, `pg_user`,
  `sslmode`, `sslrootcert`), `local_path` under `work/`, kill switch (`enabled`, `monthly_hours_ceiling`).
  No secret: the token is only ever the environment variable `MOTHERDUCK_TOKEN`.
- `scripts/warehouse_sync.py`: thin entry point.
- `scripts/marketbrief/warehouse/`:
  - `connection.py`: target selection, `connect_warehouse(read_only=...)`.
  - `errors.py`: the token from the environment, `redact`, `WarehouseError`.
  - `extension.py`: the MotherDuck extension installed over HTTPS only (follow-up below).
  - `postgres.py`: `PostgresEndpoint` (URL with the token URL-encoded, libpq params; repr/str redacted).
  - `tables.py`: the mirrored tables and their cut-off-aware queries, Parquet staging.
  - `read_models.py`: the page payloads, sliced from `gather_dashboard`, plus the required-key check.
  - `rm_writer.py`: hash-based upsert of `rm.*` and the `rm.builds` row.
  - `sql_statements.py`: shared SQL text (quoted literals, column definitions, one-row inserts).
  - `sync.py`: one market's sync (`SyncRun`: stage, connect, kill switch, one transaction, record).
  - `sync_records.py`: the run's `meta.sync_runs` and `rm.builds` rows, page facts, summary file.
  - `cli.py`: `--market india|us [--full] [--dry-run] [--local] [--kind daily|news]`.
- `scripts/marketbrief/constants/warehouse.py`: names, required payload keys and messages. This is a new
  module in the shared `constants/` folder; no existing constants module was changed apart from
  `environment.py`, below.
- `tests/test_warehouse_connection.py` and `tests/test_warehouse_extension.py` (offline, no MotherDuck), and
  `tests/test_warehouse_sync.py` (offline, local fallback DuckDB file on a copy of the US data).
- `docs/ws/ws1.md`, `docs/ws/ws1-judgments.jsonl`.

Shared files changed (additive only):
- `scripts/marketbrief/constants/environment.py`, appended:
  ```python
  # WS1 warehouse sync: the MotherDuck token, read from the environment only
  ENV_MOTHERDUCK_TOKEN = "MOTHERDUCK_TOKEN"
  ```
- `tests/conftest.py`: a `# WS1: ...` block in `SLOW` lists the 11 tests of `tests/test_warehouse_sync.py`.
  They share one module fixture that runs several local syncs (about 30 s together).

- `requirements.txt` (follow-up): `duckdb>=1.1` became `duckdb==1.5.6`, because the MotherDuck extension
  is built per DuckDB version and `config/warehouse.yaml` pins the matching build.
- `scripts/marketbrief/presentation/dashboard/reads.py` (follow-up): the company-events rule inside
  `EARNINGS_SQL` became its own constant, `COMPANY_EVENTS_ASOF_SQL`, which the warehouse's `company_events`
  table and the stock page's events now reuse. The golden harness shows the dashboard's outputs unchanged.

Not changed: `core/schemas.py` and `sql/views.sql`. No dependency was added: pyarrow is absent, so staging
goes through DuckDB's own Parquet writer. No data kind was added and nothing under `data/`
was written.

## Contract

### Target and secrets
- With `provider: motherduck` and `MOTHERDUCK_TOKEN` set, the target is `md:market_brief`. Otherwise it is
  the local file `work/warehouse/market_brief.duckdb`. `--local` forces the local file.
- Without the token and without `--local`, the sync fails with a message that names the variable and
  `--local`. It never echoes a value.
- The extension is installed by `extension.py` over HTTPS only (see the follow-up section below). DuckDB
  checks both files' signatures; `allow_unsigned_extensions` is never touched (it stays `false`). The
  extension reads `MOTHERDUCK_TOKEN` from the environment itself, so the token is never put into SQL, a
  connection string or a config dict.
- Every error raised from the package goes through `redact()`, which hides the token both as is and
  URL-encoded. `PostgresEndpoint` keeps the password out of `repr`/`str`. Only `url()` and `params()`
  return it, for handing straight to a client.
- `connect_warehouse(read_only=True)` attaches MotherDuck with `(READ_ONLY)`. A write through that
  connection is refused (seen live).

### Mirrored tables: one schema per market (`india`, `us`)
Each table is rebuilt as of the run's clock (MB_NOW-aware). Every query filters on the column that says when
a row was stored, with the view's own pick rule (`DISTINCT ON ... ORDER BY`) and the cut-off added:

| Table | Built from (cut-off column) |
|---|---|
| `tickers` | market config: ticker, name, sector, market, currency, position |
| `bars` | the dashboard's ohlc query `reads.BARS_SQL` (`collected_at`, adjustments by `detected_at`, closed days out), all history |
| `quotes_latest` | newest quote per symbol (`collected_at`) |
| `features`, `regime` | `features_latest` / `regime_latest` rule (`computed_at`) |
| `predictions` | first row per id (`made_at`) |
| `track_record` | predictions joined with the first outcome per id (`scored_at`), `label_basis` coalesced as in the view |
| `track_summary` | calls, hits, hit rate and mean confidence per `label_basis` x horizon (the two bases never pooled) |
| `ranges`, `range_record` | `ranges_latest` rule (`made_at`), first `range_outcomes` row per range (`scored_at`) |
| `model_scores_latest`, `model_versions` | the views' rules (`computed_at`, `fitted_at`) |
| `news` | one row per (id, ticker); a headline without tickers gets ticker NULL. It carries the enrichment newest by `analyzed_at` and the status from `news_status_ids_asof(cutoff)` (no row: `unverified`). The url is kept only when plain http(s) (`view_data.safe_url` rule) |
| `news_verified` | `news_verified_asof(cutoff)` |
| `events`, `company_events` | first row per id / the `company_events` rule (`first_seen_at`) |
| `agent_reasoning` | newest per (as_of_date, ticker) (`written_at`) |
| `lessons` | `written_at` and `available_from` <= cut-off |
| `reviews` | `computed_at` (carries `model_skill`) |

### Read models: schema `rm` (docs/ARCHITECTURE.md section 4, api/openapi.yaml 2.0.0)
Updated 2026-10-08 for contract 2.0. WS1 built the 1.0 pages, the sync (`sync.py`) and the writer (`rm_writer.py`).
B4's framework batch (8aaad43, 7d1e8bf; docs/ws/b4.md "Framework") extended both and added the builder registry;
each page type now belongs to the session named below, and WS1 keeps two builders.
- Columns as in ARCHITECTURE.md 4.1: `market, page_key, as_of, cutoff, built_at, schema_version,
  source_commit, payload_sha256, payload`, primary key `(market, page_key)`, one current row per key.
- `schema_version` is the `info.version` of `api/openapi.yaml` (2.0.0 today). `source_commit` is
  `git rev-parse HEAD` of the repo root, or `unknown` outside a checkout. `payload_sha256` is the SHA-256 of
  the canonical payload JSON (sorted keys, no whitespace, strict). The text is stored verbatim, so
  `sha256(payload) == payload_sha256` (tested).
- Builders: each page type is a `PageBuilder` in a module `warehouse/rm_<page>.py`; `rm_registry.py` finds them
  (no list to edit), and `rm_registry.tables()` is the list of rm tables the sync writes and prunes. On main
  at 27f6eaf (table: payload schema, owner):
  - `overview`: `Overview` (WS1); `watchlist`: `Watchlist` (WS1), registered in `rm_dashboard.py` and sliced
    from `presentation/dashboard/assemble.gather_dashboard` in `read_models.page_payloads`.
  - `stock`: `CompanyPage`, `bars`: `CompanyBars`, `stock_strategies`: `StockStrategiesPage`, `trades`:
    `TradesPage` (B12, all in `rm_company.py`; they replaced WS1's 1.0 StockDetail and Bars at 27f6eaf).
  - `track_record`: `TrackRecordPage`, `strategies`: `StrategyLabTable`, `compare`: `RuleVsAiTable`,
    `review`: `ResearchReviewPage` (B13, `rm_track_record.py`, `rm_strategies.py`, `rm_compare.py`;
    `track_record` moved from WS1 at 64ccd56).
  - `companies`: `CompaniesPayload` (`rm_companies.py`), `news`: `NewsPayload` (`rm_news.py`) (B11); `status`:
    `MarketStatus` (B4, `rm_platform.py`).
  `read_models.upcoming_events` / `EVENTS_SQL` stay because W1's catalogue code imports them.
- One writer: the sync is the only writer of every rm table. It builds all pages of a market from one
  `BuildContext` as of the run's clock and writes them in the sync's one transaction. A builder reads only
  rows stored by the cut-off and puts no build time into its payload, so a rebuild of the same data keeps
  the same hash.
- Upsert by hash (4.4): an unchanged page is left alone (`built_at` and `cutoff` unchanged). A changed or
  new page replaces its row. A stored key the build no longer produces (a ticker that left the watchlist)
  is deleted, which is why a page may only be written through a registered builder.
- Validation: every payload is checked against its schema in `api/openapi.yaml` (`schema_check.py`, the
  JSON Schema subset the contract uses) before it is written. A page that fails is not written and its old
  row stays; the build row records the problems, and the CLI exits 1. (In 1.0 this was a required-key check
  in `constants.warehouse.REQUIRED_KEYS`.)
- `rm.builds` (append-only): `build_id, market, kind (daily|news|full), cutoff, source_commit,
  started_at, finished_at, ok, pages_written, pages_unchanged, error`.

### Bookkeeping
- `meta.sync_runs` (as specified for WS1): `run_id, market, started_at, finished_at` (wall clock),
  `cutoff` (data clock), `target, tables, table_rows (JSON), rows, read_models, mode
  (replace|full), ok, error`. A failed run is recorded with its redacted error. A kill-switch skip is
  recorded with `ok` false and `error` `skipped: ...`.
- The summary goes to `work/warehouse/<market>-sync.json`. It lists the tables with row counts, the
  pages, the payload bytes, `pages_written|unchanged|deleted`, the timings (`stage_s`, `connect_s`,
  `write_s`, `elapsed_s`), `ok` and `build_ok`.

### CLI
- `python scripts/warehouse_sync.py --market india|us`: replace every mirrored table and upsert the pages,
  in one transaction (`BEGIN ... COMMIT`, `ROLLBACK` on any error).
- `--full`: also drop the market's schema and its `rm` rows first (`kind` full).
- `--dry-run`: count the rows and build and validate every page. It writes nothing: no warehouse file, no
  stage folder, no summary.
- `--local`: use the local file even when the token is set.
- `--kind daily|news`: the label in `rm.builds`; the work is the same.
- Exit codes: 1 when the sync failed or a page failed validation. 0 otherwise, a kill-switch skip
  included.
- Kill switch: `enabled: false` skips before connecting. A sync also skips when this UTC month's recorded
  sync wall time in `meta.sync_runs` (both markets) reaches `monthly_hours_ceiling` (7). This guard is
  self-measured, because Lite offers no usage query (see below).

### Design decisions
- Full replace, not incremental by watermark. Each market is about 20-23 thousand rows (bars 16,875 /
  19,048; news 2,861 / 2,983). Staging all of it locally takes about 1.1 s. Measured live: one
  `CREATE OR REPLACE TABLE ... AS SELECT * FROM read_parquet(...)` of the 19,048 US bars took 1.82,
  1.37 and 1.04 s, and a 2-row table took 0.60, 0.48 and 0.50 s. Incremental bars would save under about
  1 s per run, but add watermark state and a correctness risk: re-collected bars and new split records
  change past rows, which the ohlc rule picks up only with a full rebuild. The cost is dominated by the
  number of statements (about 0.4-0.5 s each), not by rows.
- Staging through Parquet files written by DuckDB keeps every column type (lists, JSON, TIMESTAMPTZ) without
  pyarrow. The warehouse then loads each file with one CTAS (MotherDuck's hybrid execution uploads the local file).
- Per-market base schemas (`india.*`, `us.*`) rather than ARCHITECTURE.md 4.5's `base.<kind>` with a
  `market` column, as the WS1 task specified; the app never reads them (see open question 1).

## Measured costs (live, 2026-10-07; pasted from the run summaries)

Dry run, then two real syncs per market against `md:market_brief`:

```
india DRY {'mode': 'dry_run', 'rows': 20373, 'as_of': '2026-10-06', 'read_model_pages': {'overview': 1, 'watchlist': 1, 'stock': 20, 'bars': 20, 'track_record': 1}, 'invalid_pages': [], 'written': False, 'elapsed_s': 2.44}
india RUN1 {'mode': 'replace', 'kind': 'daily', 'target': 'md:market_brief', 'ok': True, 'build_ok': True, 'error': None, 'rows': 20373, 'read_models': 43, 'pages_written': 43, 'pages_unchanged': 0, 'pages_deleted': 0, 'stage_s': 1.15, 'connect_s': 2.11, 'write_s': 11.76, 'elapsed_s': 19.59}
india RUN2 {'mode': 'replace', 'kind': 'daily', 'target': 'md:market_brief', 'ok': True, 'build_ok': True, 'error': None, 'rows': 20373, 'read_models': 43, 'pages_written': 0, 'pages_unchanged': 43, 'pages_deleted': 0, 'stage_s': 1.09, 'connect_s': 2.25, 'write_s': 9.89, 'elapsed_s': 16.43}
india tables {'tickers': 20, 'bars': 16875, 'quotes_latest': 15, 'features': 40, 'regime': 2, 'predictions': 0, 'track_record': 0, 'track_summary': 0, 'ranges': 60, 'range_record': 0, 'model_scores_latest': 40, 'model_versions': 2, 'news': 2861, 'news_verified': 70, 'events': 347, 'company_events': 20, 'agent_reasoning': 20, 'lessons': 0, 'reviews': 1} dry==sync True
india bytes {'overview': 8014, 'watchlist': 19583, 'stock': 226101, 'bars': 278109, 'track_record': 4987}
us DRY {'mode': 'dry_run', 'rows': 23264, 'as_of': '2026-10-06', 'read_model_pages': {'overview': 1, 'watchlist': 1, 'stock': 20, 'bars': 20, 'track_record': 1}, 'invalid_pages': [], 'written': False, 'elapsed_s': 2.46}
us RUN1 {'mode': 'replace', 'kind': 'daily', 'target': 'md:market_brief', 'ok': True, 'build_ok': True, 'error': None, 'rows': 23264, 'read_models': 43, 'pages_written': 43, 'pages_unchanged': 0, 'pages_deleted': 0, 'stage_s': 1.09, 'connect_s': 2.12, 'write_s': 11.89, 'elapsed_s': 18.24}
us RUN2 {'mode': 'replace', 'kind': 'daily', 'target': 'md:market_brief', 'ok': True, 'build_ok': True, 'error': None, 'rows': 23264, 'read_models': 43, 'pages_written': 0, 'pages_unchanged': 43, 'pages_deleted': 0, 'stage_s': 1.45, 'connect_s': 2.39, 'write_s': 9.37, 'elapsed_s': 16.87}
us tables {'tickers': 20, 'bars': 19048, 'quotes_latest': 28, 'features': 40, 'regime': 2, 'predictions': 0, 'track_record': 0, 'track_summary': 0, 'ranges': 40, 'range_record': 0, 'model_scores_latest': 40, 'model_versions': 2, 'news': 2983, 'news_verified': 294, 'events': 723, 'company_events': 23, 'agent_reasoning': 20, 'lessons': 0, 'reviews': 1} dry==sync True
us bytes {'overview': 7387, 'watchlist': 23575, 'stock': 239205, 'bars': 281427, 'track_record': 4956}
```

The warehouse's own records after these runs (read-only connection):

```
[('india-20261007T151212Z-5f62ad', 'daily', True, 43, 0), ('us-20261007T151232Z-3290c6', 'daily', True, 43, 0), ('india-20261007T151251Z-b8c34a', 'daily', True, 0, 43), ('us-20261007T151308Z-f91aea', 'daily', True, 0, 43)]
[('india', 'replace', True, 20373, 43, 19.2), ('us', 'replace', True, 23264, 43, 17.8), ('india', 'replace', True, 20373, 43, 16.0), ('us', 'replace', True, 23264, 43, 16.4)]
```

The app's read, the contract's keyed SELECT on `rm.stock` (`us`, `AAPL`), through a read-only DuckDB connection:

```
connect read-only s 2.42
keyed select s 0.395 ('us', 'AAPL') 1.0.0 11470
keyed select s 0.14 ('us', 'AAPL') 1.0.0 11470
keyed select s 0.137 ('us', 'AAPL') 1.0.0 11470
```

What could and could not be observed:
- `md_information_schema.query_history` is refused on this plan: `MDExternalException: Query History is
  not available on your plan. Consider upgrading to the Business Plan.` So MotherDuck's billed compute
  could not be read from here. All figures below are client-side wall times, used as an upper bound of
  active time. The plan's usage page is the place to check (ARCHITECTURE.md U1).
- Postgres endpoint: psql 16.15 is installed. A read-only query (`SET default_transaction_read_only = on`,
  then the keyed SELECT) timed out on TCP connect to `pg.eu-central-1-aws.motherduck.com:5432` (both
  resolved addresses, `timeout expired` after 40 s). This container allows outbound HTTPS only, so the
  endpoint is unverified from here; nothing was added to work around it.
- A sync to MotherDuck issues about 50 statements when every page changes, and about 40 when none does
  (counted by the judge with an instrumented local sync, plus the connect statements):
  - 5 to connect (INSTALL, LOAD, ATTACH, CREATE DATABASE, USE);
  - 9 to ensure the schemas and tables;
  - 1 ceiling check;
  - 22 in the transaction (BEGIN, CREATE SCHEMA, 19 CTAS, COMMIT);
  - 1 hash read;
  - up to 10 page deletes and inserts;
  - 2 bookkeeping inserts.

### Monthly compute estimate
Counts follow ARCHITECTURE.md section 5: 44 daily syncs, and news syncs every 6 h (240) or every 4 h (360).
Owner decision (2026-10-07): every 4 h with 5 runs per market per day, so 300 news syncs and 344 syncs a month in all.

| Scenario | Per sync | 6-hourly news (284 syncs) | 4-hourly news (404 syncs) |
|---|---|---|---|
| A: billed time = measured connect + write wall time | ~12-14 s | ~1.0-1.1 h | ~1.4-1.6 h |
| B: assumed 1 s minimum per statement, no cool-down | ~50 s | ~3.9 h | ~5.6 h |
| Reads: ~900 cache misses a month (ARCHITECTURE.md A4) | 0.14 s measured, or 1 s minimum | +0.04-0.25 h | +0.04-0.25 h |

Both scenarios fit the 10 h cap; scenario B is not comfortable at 4-hourly. Cheap reductions if week 1
shows B-like billing:
- let `--kind news` rebuild only the news tables and news-dependent pages;
- fold the 9 schema and table `CREATE ... IF NOT EXISTS` statements of the ensure step into a once-per-schema-version check;
- sync both markets on one connection.
The kill switch's ceiling (7 h of recorded wall time) stops syncs before the cap in either case.

## Tests
Pasted from command output.

Full suite, `python -m pytest -n auto -q` (run once at the end):
```
FAILED tests/test_judgments.py::test_every_logged_commit_exists - AssertionEr...
1 failed, 904 passed, 3 skipped, 6453 warnings in 184.35s (0:03:04)
```
`test_every_logged_commit_exists` also fails on the untouched tree in this clone: 27 commits named in `judgments/log.jsonl`
are not in this clone. CI excludes this test (CLAUDE.md).

Fast tier, `python -m pytest -m "not slow" -n auto -q`, before the contract alignment:
```
FAILED tests/test_judgments.py::test_every_logged_commit_exists - AssertionEr...
1 failed, 809 passed, 2 skipped, 6193 warnings in 74.83s (0:01:14)
```

The WS1 tests and the size limits after the last edit (a formatting change), with
`python -m pytest tests/test_warehouse_connection.py tests/test_warehouse_sync.py tests/test_code_structure.py -n auto -q`:
```
24 passed, 1 skipped in 28.17s
```
The skipped test, `test_required_keys_and_version_match_the_spec`, needs `api/openapi.yaml`, which is not on
this branch. With wave 0's spec copied in temporarily from `origin/build/wave0`, then removed:
```
1 passed, 11 deselected in 0.55s
```

Lint: `ruff check` on every WS1 file prints `All checks passed!`. `ruff check tests/conftest.py` reports
2 `ARG001` findings in `pytest_configure` and `pytest_collection_modifyitems`; they are the same on the
untouched tree.

## Judge verdicts
- Round 1: FAIL, commit 4883deff0d24aae821b49f06f94189dafc57703a. The code was verified; there were two
  false doc statements: `ws1-judgments.jsonl` listed as created but missing, and wrong statement counts.
- Round 2: PASS, commit 5bf0ae3f4799f7d00e9b22b18e03386156bb7e35 (re-check of the two blockers and the fix
  diff; no new findings).
- Follow-up (HTTPS extension install, clean-code pass), round 1: FAIL, commit b23f94f (the run's start time
  moved after the local connect; summary key order and failure keys changed).
- Follow-up, round 2: PASS, commit da70e29.

## Follow-up 2026-10-07: HTTPS-only extension install and clean-code pass
Owner decisions (this session): fix the extension install only (no new tokens, no inbox database), tidy the
code to the clean-code rules, leave the shared docs to the owner's final documentation session.

**Cause of the broken sync.** In the routine environment `LOAD motherduck` failed with "MotherDuck extension
is not available for this DuckDB version". Both downloads behind it are plain HTTP:
- DuckDB's `INSTALL motherduck` first fetches `httpfs` from `http://extensions.duckdb.org` (seen in the
  installed file's `.info`).
- On LOAD, the loader fetches its implementation from
  `http://ext.motherduck.com/${REVISION}/${PLATFORM}/${NAME}.duckdb_extension.gz` (from the loader's
  strings). Pointed at a local logging server, the request it makes is
  `GET /v1.5.6/linux_amd64/motherduck_impl.v1.5.6-2026-10-3.duckdb_extension.gz`. A failed fetch
  (blocked or 403) gives exactly that error message.

This container also allows direct plain HTTP, so it never failed here.

**Fix (`extension.py`).**
- Both signed files are downloaded over HTTPS with the repo's `HttpClient`, which takes HTTPS_PROXY and
  the CA bundle from the environment:
  - the loader from `https://extensions.duckdb.org/...`;
  - the implementation from `https://ext.motherduck.com/...` (200, 24,762,380 bytes).
- Only HTTPS on those two hosts is accepted. A generic User-Agent is sent, because extensions.duckdb.org
  answers Python's default one with 403.
- The loader is installed with `INSTALL '<local file>'`.
- The implementation is written where the loader looks for it, and `MOTHERDUCK_EXT_VERSION` is set, so
  the loader downloads nothing.
- Versions are pinned:
  - `duckdb==1.5.6` in requirements.txt;
  - `extension:` in `config/warehouse.yaml`. `https://api.motherduck.com/extension_version` answered
    `{"extensionVersion": "v1.5.6-2026-10-3", "duckdbVersion": "v1.5.6", ...}`.

**Safety checks.**
- Tampered files are refused:
  - a flipped byte in the loader gives "Attempting to install an extension file that doesn't have a valid
    signature";
  - a flipped byte in the implementation gives "... could not be loaded because its signature is either
    missing or invalid and unsigned extensions are disabled by configuration (allow_unsigned_extensions)".
- Under `strace`, the real sync of each market with an empty extension folder connected only to the
  local proxy port:
  ```
  india exit 0 process wall 29.065075242s
    connect ports:       4 sin_port=htons(41179)
  us exit 0 process wall 25.490259345s
    connect ports:       2 sin_port=htons(41179)
  ```
- Live sync summaries from that run:
  ```
  india {'mode': 'replace', 'target': 'md:market_brief', 'ok': True, 'build_ok': True, 'error': None, 'rows': 20558, 'read_models': 43, 'pages_written': 9, 'pages_unchanged': 34, 'pages_deleted': 0, 'stage_s': 2.95, 'connect_s': 5.48, 'write_s': 10.59, 'elapsed_s': 27.31}
  us {'mode': 'replace', 'target': 'md:market_brief', 'ok': True, 'build_ok': True, 'error': None, 'rows': 24788, 'read_models': 43, 'pages_written': 0, 'pages_unchanged': 43, 'pages_deleted': 0, 'stage_s': 3.22, 'connect_s': 2.5, 'write_s': 9.95, 'elapsed_s': 23.86}
  ```

**Clean-code pass.**
- Defined once now:
  - the scored-calls and scored-ranges subqueries in `tables.py`;
  - the company-events rule, `reads.COMPANY_EVENTS_ASOF_SQL`, used by the dashboard, the
    `company_events` table and the stock page;
  - the SQL helpers in `sql_statements.py` (with `core.database.column_spec` for read_json columns).
- `SyncRun` (with `PhaseTimer`) replaces the `state` dict and the four-job function. The run records
  moved to `sync_records.py`.
- Short names are replaced by descriptive ones (`warehouse`, `warehouse_cfg`, ...).
- A failed ROLLBACK no longer hides the original error (tested).

**Judge round 1 of this follow-up (FAIL) and its fix.** The first version took the run's start time after
the ~3 s local `database.connect`, not before it as main does. That shifted `started_at`, the run id and
`built_at`, and shortened the run time recorded in `meta.sync_runs`, which the kill switch adds up. The
summary file also changed: `write_s` came before the page counts, and a failed run listed phases that had
not completed. Fixed: `sync_market` takes the start time before the connect and passes it into `SyncRun`,
`PhaseTimer` records only completed phases, and the summary keeps main's key order. The same `us` local
sync, with main's code (7dbac3b) and with this code, plus a forced write failure:
```
success summary keys identical (order): True
failure summary keys identical (order): True
recorded run time  base: 4.39 new: 4.64
sync_market wall   base: 4.62 new: 4.87
```

**No output change in the stored tables.**
- Both markets synced locally with `--full` and `MB_NOW=2026-10-07T05:00:00+00:00`, once with main's code
  (7dbac3b) and once with this code. Every table was compared, `built_at` (wall clock) excluded:
  ```
  tables base/new: 43 43 same names: True
  differing tables: []
  rows compared: 40779
  ```
- Golden harness, `tests/golden/golden.py compare` (recorded from main 7dbac3b):
  ```
   "identical": true,
   "compared_files": 2850,
   "differing": [],
   "deleted_mismatch": [],
   "network_clean": true,
  ```

## Proposed edits to shared docs

**routine/PROMPT.md**, a new step after step 12 (Save), before step 13 (Notify). It comes after the save
rather than inside step 11 so that `source_commit` is the pushed commit holding the data the pages were
built from:

```markdown
12a. Warehouse (optional, never blocks the run): `python scripts/warehouse_sync.py`. It copies the
    market's stored data as of the run's clock into MotherDuck `market_brief` (schema `<market>`) and
    rebuilds the app's read models (`rm.*`, upserted by hash: unchanged pages are left alone), recording
    the run in `meta.sync_runs` and `rm.builds`. It reads `data/` only and writes nothing to the repo
    (summary in `work/warehouse/<market>-sync.json`). Needs `MOTHERDUCK_TOKEN`; without it, or on any
    failure or a kill-switch skip (`config/warehouse.yaml`), note it on the Slack draft's failures line
    and go on. Static reports and Slack never depend on it.
```

**routine/NEWS_PROMPT.md**, a new step after step 3 (Save), before step 4 (Final message):

```markdown
3a. Warehouse (optional, non-blocking): only when step 3 pushed a commit, run
    `python scripts/warehouse_sync.py --kind news`. It refreshes the market's copy in MotherDuck and
    rebuilds the read models whose payload changed. Name any failure or skip in the final message;
    never retry.
```

**CLAUDE.md**, in `## Layout`, after the `- Neo4j projection (DESIGN.md section 12): ...` bullet:

```markdown
- Warehouse (WS1, docs/ws/ws1.md, docs/ARCHITECTURE.md section 4): `warehouse_sync.py --market india|us
  [--full] [--dry-run] [--local] [--kind daily|news]` copies the market's stored data as of the run's clock
  (MB_NOW-aware) into MotherDuck `market_brief` (env `MOTHERDUCK_TOKEN`, never printed; without it the
  local file of `config/warehouse.yaml` under `work/`): one schema per market with the cockpit's tables
  (bars, quotes, features, regime, predictions, track record per label basis, ranges, model scores and
  versions, news with verification status, events, agent reasoning, lessons, reviews), fully replaced in
  one transaction, plus the read models in `rm` (`overview`, `watchlist`, `stock`, `bars`, `track_record`;
  key `(market, page_key)`, payload sliced from `gather_dashboard`, upserted by `payload_sha256`) and
  `rm.builds` / `meta.sync_runs`. Code in `marketbrief/warehouse/`; kill switch `enabled` and
  `monthly_hours_ceiling` in `config/warehouse.yaml`. Optional and non-blocking; rebuildable with `--full`.
  The MotherDuck extension is installed by `marketbrief/warehouse/extension.py` over HTTPS only (both signed
  files downloaded through the proxy, DuckDB checks the signatures; never `INSTALL motherduck`, whose
  downloads are plain HTTP); `duckdb` is pinned in requirements.txt and the matching extension build under
  `extension:` in `config/warehouse.yaml`.
```

**docs/DESIGN.md**, in wave 0's proposed section 16, after its first paragraph:

```markdown
The warehouse copy is written by `scripts/warehouse_sync.py` (docs/ws/ws1.md): every table is rebuilt as
of the run's clock with each view's own pick rule plus `<stored_at> <= cutoff`, so a replay with MB_NOW
builds exactly what was known then; read models are the dashboard's own data sliced per page, so the app
and `reports/<market>/dashboard.html` can never disagree.
```

## Cosmetic follow-ups
From judge round 1. The stale test docstring and the `config/warehouse.yaml` skip comment were fixed in the
round 2 diff. The duplicated company-events rule, the f-string paths in `tables.py` and the ROLLBACK that
could hide the original error were fixed in the follow-up below.
- `read_models.py` (`missing_keys`): contract 4.1 asks for required keys and types; only keys are checked.
  Today's payloads pass a full jsonschema check against wave 0's spec (judge).
- CLI flag naming: contract 4.4 calls the rebuild `--rebuild-rm`; WS1's `--full` covers it.
- `tests/test_warehouse_sync.py`: the look-ahead test covers features, news, reviews and bars, not ranges,
  predictions or lessons.
- `extension.py`: an implementation file already in the extension folder that fails its signature check is
  not downloaded again; it has to be deleted by hand (DuckDB refuses to load it, so this is safe).
- `extension.py`: `MOTHERDUCK_EXT_VERSION` is set in the process environment, because that is where the
  loader reads it; the variable stays set for the rest of the process.
- Fixed in the follow-up's round 2: a redirect is followed only to HTTPS on the two official hosts; a
  failed decompression leaves no partial file; `cli.py` and `postgres.py` import from `errors.py`; the
  test environment no longer leaks `MOTHERDUCK_EXT_VERSION`; the `SLOW` comment in conftest.
- From the follow-up's round 2: no committed test fixes the summary's key order (checked by a one-off
  script against main's code); no test checks that the downloader's opener uses `AllowedRedirects` (checked
  by hand); `tests/conftest.py` has 2 ruff ARG001 findings and needs a reformat, both from before WS1.
- A changed page (delete and re-insert of the same key in one transaction) is not exercised live on
  MotherDuck; locally it is covered by the `--full` and invalid-page paths.

## Open questions
1. **Base schema shape.** The WS1 task asks for one schema per market (`india.*`, `us.*`) holding the
   cockpit's derived tables. ARCHITECTURE.md 4.5 describes `base.<kind>` with a `market` column,
   mirroring raw kinds incrementally. The default taken is per-market schemas: the app never reads them,
   and they hold the as-of view rules the MCP needs for ad-hoc questions. Switching to `base.<kind>`
   would be a change of `tables.py` only.
2. **Remaining read models.** `rm.markets`, `rm.status`, `rm.news` and `rm.runs` are not built yet. The
   default taken is to build them in WS2's batch, or in a WS1 follow-up once `api/openapi.yaml` is on
   main; the payloads need `news_runs` and `market_status`.
3. **News-run sync.** The default taken is that it does the same full work as the daily sync
   (`--kind news` is only a label), because measured cost is dominated by statement count. Should it be
   narrowed to the news tables and pages now, or only if week 1 shows per-statement billing?
4. **Routine environment.** The routines need `MOTHERDUCK_TOKEN` and HTTPS access (through the proxy) to
   `extensions.duckdb.org`, `ext.motherduck.com` (the two signed extension downloads) and `*.motherduck.com`. The default taken is
   that the owner adds them to the routine environment before consolidation wires the step.
5. **Postgres endpoint.** It is unverified from this container (port 5432 is not reachable). WS2 should
   check it from Vercel; the URL builder (`warehouse.postgres.endpoint()`) is ready for that.
