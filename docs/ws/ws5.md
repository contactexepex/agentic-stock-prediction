# WS5: intraday checks and the deviation explainer

## Scope
A few times per session, check each market's watchlist against the session's published 1d/5d ranges and the
open calls and model scores as of the check time, flag deviations, list deterministic attribution candidates,
and let the `deviation-explainer` agent write a gated note per flagged ticker. Everything is stored for the
reflector, the weekly review and the cockpit. Branch `build/ws5-intraday`. Research only: a check never
predicts and never trades; every signal stays "Paper only — no proven edge yet".

## Files
Created:
- `scripts/intraday_check.py` (thin entry point) and `scripts/marketbrief/intraday/`: `cli.py` (run, prepare,
  validate, add), `check.py` (one check: market status, fetch, inputs, rows, run row), `quotes.py` (Yahoo
  5-minute bars through yfinance, the quotes collector's `priced` and `snapshot`, bars cut at the check time),
  `inputs.py` (stored inputs as of check_at), `rows.py` (one ticker's row), `measures.py` (pure deviation
  math and flags), `attribution.py` (candidates), `explain.py` + `explain_gate.py` (the explainer's gate),
  `outcomes.py` (learning loop), `payload.py` (cockpit read model), `settings.py`, `store.py`, `constants.py`
- `scripts/marketbrief/core/schema_intraday.py` (kinds `intraday_checks`, `intraday_runs`,
  `intraday_explanations`)
- `config/intraday.yaml`, `.claude/agents/deviation-explainer.md`, `routine/INTRADAY_PROMPT.md`,
  `tests/test_intraday.py`, `docs/ws/ws5.md`, `docs/ws/ws5-judgments.jsonl`

Shared files changed (additive only):
- `scripts/marketbrief/core/schemas.py`, one import and one spread line:
  ```python
  from marketbrief.core.schema_intraday import INTRADAY_SCHEMAS  # WS5
          **INTRADAY_SCHEMAS,  # WS5
  ```
- `sql/views.sql`, a `-- WS5:` block appended at the end: views `intraday_checks_latest`,
  `intraday_deviations`, `intraday_today`, `intraday_explanation_close`.
- No constants module changed (WS5's constants live in `marketbrief/intraday/constants.py`), no
  requirements change (yfinance, duckdb, pandas, pyyaml were present).

## Contract
**Data kinds** (append-only, files dated by the UTC date of `check_at` / `created_at`; columns in
`core/schema_intraday.py`):
- `intraday_checks`: one row per ticker per check. `id` = `<check_id>-<ticker>`, `check_id` =
  `ic-<market>-<YYYY-MM-DDTHH:MM>Z` (the clock truncated to the minute). `quality` ok | stale_quote |
  no_quote (no measures or flags unless ok). Prices: the first bar's open and the newest 5-minute bar complete
  by check_at (bar start + 5 min <= check_at). Measures (fractions): `gap` (open vs the stored previous close),
  `ret_since_open`, `elapsed_fraction`, `sigma_1d` (the 1d range's `sigma_h`; else the 5d range's / sqrt 5;
  else EWMA vol / sqrt 252; the fallback is in `notes`), `move_z` = ret_since_open / (sigma_1d x
  sqrt(elapsed)), the 1d bands and `band_1d`, the 5d 80% band and `band_5d` (below80 | below50 | inside50 |
  above50 | above80; a price on an edge is inside), `bench_ret`, `beta` (features `beta_1y`, clipped; default
  1.0 noted), `residual` = ret - beta x bench_ret and `residual_z`, `sector_ret` (`sector_source` sector_etf, or
  peers = mean of the sector's other watchlist tickers) and `sector_residual`. `calls` JSON: open predictions
  and model scores whose holding window (entry at the open of the session after as-of, to the close of its last
  session) contains the session, each with `entry_open`, `ret`, `z` (sigma_1d x sqrt(sessions held)) and
  `against`. `flags`: outside_1d_80, outside_1d_50, outside_5d_80, large_move, large_residual,
  against_call, against_model; `flagged` = any flag in `flag_on` of the config. `candidates` JSON and
  `candidate_ids` only on flagged rows.
- `intraday_runs`: one row per check time (id = check_id): status ok | market_closed | stale, counts,
  `stale` tickers, `failed` fetches.
- `intraday_explanations`: id = `ix-<check row id>`, `check_row_id`, `check_id`, `check_at`, `session_date`,
  `ticker`, `flags` (copied from the stored row), `attribution`, `text`, `cited_ids`, `prompt_version`,
  `created_at`.

**No look-ahead** (all as of check_at): ranges `made_at` <= check_at (first published per id, as
`ranges_latest`); predictions `made_at`, model scores `computed_at` (newest per id), features
`computed_at`, news `first_seen_at` in [session open, check_at] and `published_at` <= check_at,
news status `news_status_ids_asof(check_at)`, enrichment `analyzed_at` <= check_at, announcements and
events `first_seen_at` <= check_at, bars complete by check_at, the cue's quote time <= check_at.

**Attribution candidates** (ids the explainer may cite): `bench:<benchmark>` (ret, beta, residual),
`sector:<ETF or sector name>` (ret, source, residual), `cue:<index_cue symbol>` (`ret` = change vs the previous
regular-session close from the quotes collector's `snapshot`, plus the 1d range's cue notes), news ids
(title, source, first_seen_at, status, materiality, sentiment), announcement ids (India, NSE), event ids
(earnings, ex_dividend dated this session).

**CLI** (`--market india|us` or `MB_MARKET`; MB_NOW-aware):
`python scripts/intraday_check.py [run] [--out DIR]`, `prepare [--check ID] [--out F]`, `validate F`,
`add F`. `--out DIR` writes the kinds under DIR instead of `data/<market>/` (live tests).

**Config** `config/intraday.yaml`: `quotes` (bar_minutes, stale_minutes, stale_run_share), `measures`
(min_elapsed_fraction, default_beta, beta_clip), `thresholds` (move_z, residual_z, against_call_z,
model_min_edge), `flag_on`, `attribution` (news_window open | prev_close, max_news), `explainer`
(max_words, prompt_version), `outcome` (hold_fraction).

**Learning loop**: `marketbrief.intraday.outcomes.explanation_outcomes(con, settings, start, end, as_of)` pairs
each explained deviation with the session's stored close (view `intraday_explanation_close`, raw basis):
`held` (same sign, at least `hold_fraction` of the move since the open kept), `reversed` (sign flipped),
`faded`, or `pending` (no close stored by as_of); plus `closed_outside_1d_80`. `outcome_summary(rows)` counts
them overall and per attribution, for the weekly review.

**Cockpit payload**: `marketbrief.intraday.payload.intraday_payload(con, market, settings, as_of=None,
session_date=None)` returns `{market, cutoff, session_date, label, runs, tickers, deviations, history}` as of
`as_of` (default the clock); notes written after `as_of` are blanked, closes collected after it are pending.

**api/openapi.yaml (build/wave0, fetched at 17eb531)**: it has no intraday operation; the WS table in
ARCHITECTURE.md says WS5 "adds a read model later (spec bump)". Alignment done: payload fields are the kind's
column names; fractions throughout (the cue's change is `ret`, not the collector's fraction-valued
`change_pct`); the time is `cutoff` (ReadModelMeta's `as_of` is a date, so the payload does not reuse that
name); runs newest first like `RunList`; news status values are the spec's `NewsStatus` enum; the label is the
spec's "Paper only — no proven edge yet". Differences left for WS1/WS2 to decide: no `rm.intraday` table or
`/intraday` path exists yet, and `ReadModelMeta` fields are added by the warehouse, not by this function.
Proposed minor bump (1.1.0), for WS2 to apply:

```yaml
  /api/v1/markets/{market}/intraday:
    get:
      tags: [markets]
      x-read-model: rm.intraday
      x-status: planned
      summary: The session's intraday checks, deviations with notes, and the learning loop's outcomes
      parameters: [{$ref: '#/components/parameters/Market'}]
      responses:
        '200': {content: {application/json: {schema: {$ref: '#/components/schemas/IntradayResponse'}}}}
# components/schemas:
    Intraday:
      type: object
      x-source: intraday/payload.intraday_payload (intraday_runs, intraday_checks, intraday_deviations,
        intraday_explanation_close as of the cut-off)
      required: [market, cutoff, session_date, label, runs, tickers, deviations, history]
      properties:
        market: {$ref: '#/components/schemas/Market'}
        cutoff: {$ref: '#/components/schemas/IsoTime'}
        session_date: {type: ['string', 'null'], format: date}
        label: {type: string}
        runs: {type: array, items: {type: object}}        # id, check_at, status, tickers, written, flagged, stale
        tickers: {type: array, items: {type: object}}     # payload.TICKER_FIELDS
        deviations: {type: array, items: {type: object}}  # payload.DEVIATION_FIELDS
        history: {type: object}                           # n, outcomes, by_attribution, rows
```

## Tests
All pasted from command output.

`python -m pytest tests/test_intraday.py tests/test_doc_commands.py tests/test_code_structure.py -q -n auto`:
```
50 passed in 9.90s
```

Full suite `python -m pytest -n auto -q` (before the last word-list edit, which the run above covers):
```
FAILED tests/test_judgments.py::test_every_logged_commit_exists - AssertionEr...
1 failed, 901 passed, 2 skipped, 6453 warnings in 195.41s (0:03:15)
```
The one failure is `test_every_logged_commit_exists`, which fails the same way on main in this shallow clone
(`git rev-parse --is-shallow-repository` = true; CI excludes it). `ruff check` on every touched Python file:
`All checks passed!`

Live check, one real run per market (2026-10-07, `date -u` 15:12:48 UTC) with output under
`work/intraday_live/` only (`--out`); `git status --short data` printed nothing afterwards:
```
{"market": "us", "check_id": "ic-us-2026-10-07T15:12Z", "check_at": "2026-10-07T15:12:00+00:00", "status": "ok", "tickers": 20, "written": 20, "flagged": 7, "stale": [], "failed": [], "flagged_tickers": {"JPM": ["outside_1d_80", "outside_1d_50"], "BAC": ["outside_1d_80", "outside_1d_50"], "UAL": ["outside_1d_80", "outside_1d_50"], "CVX": ["outside_1d_50", "large_move", "large_residual", "against_model"], "LLY": ["outside_1d_80", "outside_1d_50", "large_move", "large_residual"], "CAT": ["outside_1d_80", "outside_1d_50", "outside_5d_80", "large_move", "large_residual"], "DE": ["outside_1d_80", "outside_1d_50", "large_move", "large_residual", "against_model"]}, "benchmark_ret": -0.001753156673340528, "cue": {"symbol": "ES", "ret": -0.006953, "ts": "2026-10-07T15:00:00+00:00"}, "to": "../work/intraday_live/us"}
{"market": "india", "check_id": "ic-india-2026-10-07T08:45Z", "check_at": "2026-10-07T08:45:00+00:00", "status": "ok", "tickers": 20, "written": 20, "flagged": 0, "stale": [], "failed": [], "flagged_tickers": {}, "benchmark_ret": -0.005777744112120398, "cue": null, "to": "../work/intraday_live/india"}
{"market": "india", "check_id": "ic-india-2026-10-07T15:13Z", "check_at": "2026-10-07T15:13:00+00:00", "status": "market_closed", "written": 0, "note": "market closed at 2026-10-07T15:13:00+00:00 (session 2026-10-07)", "to": "../work/intraday_live/india"}
```
The US run is live. India was closed at the time, so its second line used `MB_NOW=2026-10-07T08:45:00+00:00`
(today's session; Yahoo bars after that time are cut). Its cue is null because the S&P 500 snapshot was
quoted after 08:45 UTC (the look-ahead guard). India published no 1-day range on 2026-10-07 (its daily run was
mid-session), so its rows note `no_range_1d` and scale moves with the 5-day sigma / sqrt 5. The third line is
the same India command without MB_NOW: only a `market_closed` run row.

## Judge verdicts
(see `docs/ws/ws5-judgments.jsonl`)

## Proposed edits to shared docs

**CLAUDE.md**, in `## Layout`, after the `- routine/PROMPT.md ...` bullet (the routines' prompts):

```markdown
- Intraday checks (WS5; `scripts/intraday_check.py`, code in `marketbrief/intraday/`, settings `config/intraday.yaml`,
  `routine/INTRADAY_PROMPT.md`): a few times per session, Yahoo 5-minute bars of the watchlist, benchmark and
  sector indices (bars complete by the check time) are compared with the session's published 1d/5d ranges and the
  open calls and model scores as of the check (MB_NOW-aware): band position, move since the open scaled by the
  1-day sigma, beta-adjusted residual, direction against an open call -> `data/<market>/intraday_checks/` (one row
  per ticker, with deterministic attribution candidates: benchmark, sector, cue, news/announcements first seen
  since the open with their status, today's events) and `intraday_runs/` (one row per check; market closed: that
  row only; a repeated check time writes nothing). The `deviation-explainer` agent (Sonnet 5.5) writes <= 60 words
  per flagged row citing only those candidates; `intraday_check.py validate|add` is its gate (ids, numbers, enums,
  no prediction words) -> `intraday_explanations/`. Views `intraday_checks_latest`, `intraday_deviations`,
  `intraday_today`, `intraday_explanation_close`; `intraday/outcomes.py` pairs each note with the close (held /
  reversed / faded) for the weekly review; `intraday/payload.py` is the cockpit's read model.
```

**CLAUDE.md**, in the `.claude/agents/` bullet, after "graph-builder (monthly connection map; every edge cites a
public source),": `deviation-explainer (one note per flagged intraday deviation, citing only the check's
candidates),` and in the model sentence "Sonnet 5.5 for news scoring, claim checking, the reflector, the
deviation explainer and the researchers".

**docs/DESIGN.md**, in section 2 after the news light-run table:

```markdown
Intraday light runs (`routine/INTRADAY_PROMPT.md`, WS5): two checks per session, in exchange time so daylight
saving never shifts them, away from the news light runs; on holidays the check writes only a `market_closed` row.

| Intraday run | Cron | UTC |
|---|---|---|
| India | `CRON_TZ=Asia/Kolkata 13 11 * * 1-5` and `CRON_TZ=Asia/Kolkata 13 14 * * 1-5` | 05:43 and 08:43 (session 03:45-10:00) |
| US | `CRON_TZ=America/New_York 27 12 * * 1-5` and `CRON_TZ=America/New_York 57 14 * * 1-5` | 16:27 and 18:57 in EDT, 17:27 and 19:57 in EST (session 13:30-20:00 EDT, 14:30-21:00 EST) |
```

**docs/DESIGN.md**, section 13 (model table): a row `deviation-explainer | Sonnet 5.5 | medium | one gated
60-word note per flagged intraday deviation`.

**Weekly review** (`marketbrief/pipeline/review/`, not changed by WS5): add a section from
`outcome_summary(explanation_outcomes(con, load_intraday_config(), week_start, week_end, as_of=clock()))`:
counts of held / reversed / faded per attribution.

**Reflector** (`.claude/agents/reflector.md`, not changed): optional later input, the intraday notes of a
settled call's session (`intraday_deviations` where session_date in the call's window), so a lesson can say
whether an intraday deviation foreshadowed the outcome.

## Schedules (for the orchestrator's triggers)
- India: `CRON_TZ=Asia/Kolkata 13 11 * * 1-5` (11:13 IST = 05:43 UTC) and `CRON_TZ=Asia/Kolkata 13 14 * * 1-5`
  (14:13 IST = 08:43 UTC). NSE session 09:15-15:30 IST = 03:45-10:00 UTC. India news light runs are at 05:17
  and 11:17 UTC, so the 05:43 check pushes 26 minutes after one; their folders differ (no same-file rebase).
- US: `CRON_TZ=America/New_York 27 12 * * 1-5` (12:27 ET = 16:27 UTC in EDT, 17:27 UTC in EST) and
  `CRON_TZ=America/New_York 57 14 * * 1-5` (14:57 ET = 18:57 / 19:57 UTC). Session 09:30-16:00 ET. The US news
  light runs are at 15:47 and 21:47 UTC.
- Holidays and early closes come from the market calendar (`core/calendar.py`): a check outside the session
  (open + one bar to close + one bar) writes only its `market_closed` run row. Each trigger runs
  `routine/INTRADAY_PROMPT.md` with `MARKET=<india|us>` in a fresh session.

## Cosmetic follow-ups
(none yet; filled from judge verdicts)

## Open questions
1. News window for attribution: the spec says items first seen since the open (default `news_window: open`).
   The 1-day band also counts the opening gap, so overnight items can explain an `outside_1d_80` flag;
   `news_window: prev_close` lists them too. Default taken: `open`, as specified.
2. Which flags send a row to the explainer: default `flag_on: [outside_1d_80, outside_5d_80, large_move,
   against_call]`; `outside_1d_50`, `large_residual` and `against_model` are stored as information only
   (model scores exist for every ticker every day, so `against_model` would flag most of the watchlist).
3. Mid-session ("late") 5-day ranges, published for the record and never scored, are still used as the
   session's 5-day band. Default: used (the check compares, it does not score).
4. The newest 5-minute bar is used only once complete, so a check lags the live price by up to 5 minutes
   plus Yahoo's own delay. Default: kept (a rerun as of the same time sees the same bars).
