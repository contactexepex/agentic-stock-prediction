# WS6: results and earnings-call digests

## Scope
When a watchlist company publishes quarterly results, the system detects it deterministically, computes the
release's numbers from stored data as of the release, stores the primary text, and a results-analyst agent writes
at most 5 quoted bullets that a deterministic gate checks before they are stored in a new kind `results_digests`.
Earnings calls get the same treatment where the company filed the text (India: NSE transcript announcements; US:
prepared remarks filed with the SEC, else `transcript_unavailable`). Branch `build/ws6-results`. Research only:
the digest reports what the company stated; it never predicts prices or recommends trades.

## Files
Created (all owned by WS6):
- `scripts/results_digest.py` (entry point) and `scripts/marketbrief/results/`:
  `constants.py` (names, enums, messages), `detection.py` (which releases), `numbers.py` (as-of numbers),
  `surprise.py` (consensus before the release, price reaction), `texts.py` (fetching primary texts),
  `sources.py` (stored texts per release, status, state key), `gate.py` (the agent gate, pure),
  `digest.py` (assembling releases, agent input, stored rows), `cli.py` (prepare | validate | add),
  `payload.py` (cockpit stock-page payload).
- `scripts/marketbrief/core/schema_results.py` (kind `results_digests`).
- `config/results.yaml`.
- `.claude/agents/results-analyst.md` (Sonnet 5.5 in the frontmatter, like the other scoring agents).
- `routine/RESULTS_PROMPT.md` (the step, to be wired into routine/PROMPT.md at consolidation).
- `tests/test_results_gate.py`, `tests/test_results_india.py`, `tests/test_results_us.py`.
- `docs/ws/ws6.md`, `docs/ws/ws6-judgments.jsonl`.

Shared files changed (additive only):
- `scripts/marketbrief/core/schemas.py`, two lines:
  ```python
  from marketbrief.core.schema_results import RESULTS_SCHEMAS  # WS6
          **RESULTS_SCHEMAS,  # WS6
  ```
- `sql/views.sql`: a `-- WS6:` block appended at the end: macro `results_digests_asof(ts)`, views
  `results_digests_latest` and `results_digest_ticker_latest`.
- No constants module changed (WS6 constants live in `marketbrief/results/constants.py`); `requirements.txt`
  unchanged (see Open questions on PDF parsing).

Data written by the step (never by this branch): `data/<market>/primary_texts/` (existing kind; India rows are new:
`source: nse`, `doc_type: attachment`, `primary_id` = the announcement id) and `data/<market>/results_digests/`.

## Contract
**Detection** (deterministic, rows known by `now` only; window = last `detection.lookback_days` = 10 days, or
`--since`; a release is due when no stored digest has its `state_key`, so a missed run is caught up and a release
is digested again only when its inputs change):
- India results: the first NSE Integrated Filing of a quarter (`financials`, min `filed_at` over both bases; a
  revision of an old quarter is no new release). Id `<TICKER>-results-<period_end>`. Its results announcements are
  those in `india_results_categories` whose subject names results, published -1..+2 days around it.
- India call: an announcement in `india_concall_categories` whose subject names a transcript. Id
  `<TICKER>-concall-<announcement id>`.
- US results: an SEC item 2.02 date that `event_history.earnings_events` keeps as a quarter's results release
  (`results_filter`, 10-Q/10-K reports accepted by now; its text must be a filing whose main document states
  "Item 2.02", so a 6-K, which has no item numbers, is not matched: no 6-K filer is on the watchlist). Id
  `<TICKER>-results-<release date>`; `release_at` becomes
  the 2.02 filing's acceptance time once its text is stored (`release_time_basis: sec_accepted_at`), local midnight
  of the date before that (`date_only`).
- US call: `<TICKER>-concall-<release date>` for every US release: EX-99 documents of the ticker's SEC filings from
  the release date to `concall_days` (3) after it whose name or first 3000 characters say "prepared remarks",
  "transcript" or "prepared commentary"; none -> `transcript_unavailable`. No transcript site is ever read.

**Numbers** (`numbers` JSON; growth and margins in %, 2 decimals, growth on |previous|):
- India: the quarter's filings (both bases) filed within `india_release_grace_hours` (24) of the first one;
  `consolidated` first, else `standalone`; YoY = the same-basis quarter ending 350-380 days earlier, QoQ = 80-125
  days earlier, each as filed by that cut. `operating_profit` is null (not in the stored NSE data);
  `profit_before_tax` and `pbt_margin_pct` instead. A later restatement is never used (`numbers_as_of` = the cut).
- US: `fundamentals_metrics_asof(numbers_as_of)` where `numbers_as_of` = the first 10-Q/10-K known for the quarter
  (the quarter ended at most `report_window_days` = 75 days before the release, so the previous quarter, ~91 days
  earlier, is never taken for the new one). Before that report is filed: `numbers_status: pending_report` and the
  release is digested again when it arrives. `derived` marks a Q4 computed as FY - 9M; `prev_quarter_gap_days`
  shows when QoQ compares quarters of unequal length (e.g. Costco's 16-week Q4: 112 days).
- Call digests carry no numbers (`numbers_status: unavailable`): their bullets must quote every number.

**Consensus** (`consensus` JSON, `note: "context only"`): the newest Yahoo row of `earnings_estimates_asof(release_at
- 1 s)` whose report date is within `max_report_gap_days` (7) of the release (`status: before_release`), else
`none_before_release`. Reported EPS is Yahoo's (same basis as its consensus) as stored by now, else the filed
diluted EPS (`surprise_basis` says which). **Reaction** (`reaction` JSON): close-to-close over
`earnings_reaction.affected_sessions` from the session before the window, counting only final bars
(`last_complete_session`), with the benchmark's move and the excess.

**Kind `results_digests`** (`core/schema_results.py`): id, release_kind, ticker, release_at, release_date,
release_timing, release_time_basis, period_end, fiscal_label, basis, currency, status (`ok` | `no_bullets` |
`text_unavailable` | `transcript_unavailable`), numbers_status (`ok` | `pending_report` | `unavailable`),
numbers_as_of, numbers, consensus, reaction, bullets (`[{topic, text, quote, source_id, source_kind}]`),
source_ids, sources, state_key, inputs_until (<= created_at), created_at, prompt_version, method_version. The newest
row per id wins (`results_digests_asof(ts)`, no look-ahead).

**CLI**: `python scripts/results_digest.py --market india|us prepare [--out F] [--no-fetch] [--since YYYY-MM-DD]
[--ticker T ...] [--dry-run]`, `validate F [--since D]`, `add F [--valid-only] [--since D]` (validate and add
use the same window as the prepare they follow). `--dry-run` writes fetched texts to
`work/results_texts.jsonl` instead of `data/`.

**Gate** (`gate.py`, modelled on `claim_rules.py`): the release id is a current due release with text; `kind`
matches; at most 5 bullets; fields and topic enum (`headline_numbers`, `guidance`, `one_off`, `commentary`);
`source_id` is one of the release's stored texts; quote <= 40 words and verbatim (after quote/dash/space
normalisation) in that text; every number in the bullet's own text is stated in the quote (same % / bps / currency
marker; a bare number as a digit token) or equals a release number as rounded in the text (a % only a `_pct` value;
trailing zeros are not rounding: "30%" never matches 25.0), or is a digit of the period labels; the text never says
buy / sell / recommend / price target / outperform / "the stock will" etc. `prompt_version` matches `results-v\d+`.

**Payload** for the cockpit stock page: `marketbrief.results.payload.stock_results_payload(con, ticker, as_of=None,
history=8)` -> `{ticker, as_of, disclaimer, latest_results, latest_concall, history}`; each digest with its JSON
columns parsed. Read only, through `results_digests_asof`.

**api/openapi.yaml (Wave 0, branch build/wave0, commit 17eb531)**: fetched and compared. The spec (1.0.0) has no
results field or table: `StockDetail` carries only the next earnings date (`earnings`) and `events`. ARCHITECTURE.md
section 12 says WS6 "adds a read model later (spec bump)". Proposed additive change for WS2 (minor bump to 1.1.0),
field names exactly those of the payload above:
```yaml
# under components/schemas/StockDetail/properties
        results:
          x-status: planned
          x-source: marketbrief/results/payload.stock_results_payload (results_digests_asof(cutoff))
          oneOf: [{$ref: '#/components/schemas/ResultsSection'}, {type: 'null'}]
# new components/schemas
    ResultsSection:
      type: object
      x-status: planned
      required: [ticker, as_of, disclaimer, latest_results, latest_concall, history]
      properties:
        ticker: {$ref: '#/components/schemas/Ticker'}
        as_of: {type: ['string', 'null'], format: date-time}
        disclaimer: {type: string}
        latest_results: {oneOf: [{$ref: '#/components/schemas/ResultsDigest'}, {type: 'null'}]}
        latest_concall: {oneOf: [{$ref: '#/components/schemas/ResultsDigest'}, {type: 'null'}]}
        history:
          type: array
          items:
            type: object
            properties:
              id: {type: string}
              release_kind: {type: string, enum: [results, concall]}
              release_at: {type: string, format: date-time}
              period_end: {type: ['string', 'null'], format: date}
              fiscal_label: {type: ['string', 'null']}
              status: {type: string, enum: [ok, no_bullets, text_unavailable, transcript_unavailable]}
              numbers_status: {type: string, enum: [ok, pending_report, unavailable]}
    ResultsDigest:
      type: object
      x-status: planned
      x-source: results_digests (core/schema_results.py)
      description: Numbers are as stored; growth and margins are percentages (names end in _pct). Consensus is
        context only.
      required: [id, release_kind, ticker, release_at, status, numbers_status, numbers, bullets, sources]
      properties:
        id: {type: string}
        release_kind: {type: string, enum: [results, concall]}
        ticker: {$ref: '#/components/schemas/Ticker'}
        release_at: {type: string, format: date-time}
        release_date: {type: string, format: date}
        release_timing: {type: ['string', 'null']}
        release_time_basis: {type: string, enum: [nse_filed_at, sec_accepted_at, date_only]}
        period_end: {type: ['string', 'null'], format: date}
        fiscal_label: {type: ['string', 'null']}
        basis: {type: ['string', 'null']}
        currency: {type: ['string', 'null']}
        status: {type: string, enum: [ok, no_bullets, text_unavailable, transcript_unavailable]}
        numbers_status: {type: string, enum: [ok, pending_report, unavailable]}
        numbers_as_of: {type: ['string', 'null'], format: date-time}
        numbers: {type: object, additionalProperties: true}
        consensus: {type: object, additionalProperties: true}
        reaction: {type: object, additionalProperties: true}
        bullets:
          type: array
          maxItems: 5
          items:
            type: object
            required: [topic, text, quote, source_id, source_kind]
            properties:
              topic: {type: string, enum: [headline_numbers, guidance, one_off, commentary]}
              text: {type: string}
              quote: {type: string}
              source_id: {type: string}
              source_kind: {type: string, enum: [filing, announcement, attachment]}
        source_ids: {type: array, items: {type: string}}
        sources: {type: array, items: {type: object}}
        created_at: {type: string, format: date-time}
```
Differences to note for WS1/WS2: the spec's convention is "fractions unless the name ends in `_pct`"; every WS6
percentage field ends in `_pct`, so it is consistent. `as_of` here is a timestamp (the spec's `StockDetail.as_of` is
a date): WS1 passes the read model's cut-off timestamp.

## Tests
Fast tier with this branch (`python -m pytest -m "not slow" -n auto -q`; the one failure also fails on main in this
clone, the shallow history lacks old commits, and CI excludes that test):
```
FAILED tests/test_judgments.py::test_every_logged_commit_exists - AssertionEr...
1 failed, 813 passed, 2 skipped, 6193 warnings in 88.27s (0:01:28)
```
WS6 tests (`python -m pytest tests/test_results_gate.py tests/test_results_india.py tests/test_results_us.py -q`):
```
12 passed in 11.59s
```
They cover: detection (India first filing vs revision, transcript announcements; US 2.02 kept by results_filter,
a future yfinance date ignored), as-of numbers (India: a revision of the previous quarter and a restatement of the
released quarter filed later are not used; US: numbers from the first 10-Q, a 10-Q a year later restating the
quarter is not used; the previous quarter is never taken for the new one), consensus before the release only (a
revised estimate collected after the release is ignored; only an after-release row -> `none_before_release`), the
reaction, the gate (non-verbatim quote, invented release and source ids, wrong number incl. "30%" vs 25.0 and a % taken
from a date, advice words, topic enum, bullet limit, kind mismatch), `add` all-or-nothing and auto rows, the
`transcript_unavailable` path, prepared remarks filed with the SEC, the SEC submissions fallback (real Tesla
fixtures), NSE attachments read from the archive host only (an off-host URL and a PDF without a parser are never
requested), the PDF branch (skipped where `pypdf` is not installed), the payload, and that the stored rows pass the
daily `validate` row checks.

ruff (`ruff check` and `ruff format --check` on every WS6 file and `core/schemas.py`):
```
All checks passed!
16 files already formatted
```
Full suite (`python -m pytest -n auto -q`, same pre-existing failure):
```
FAILED tests/test_judgments.py::test_every_logged_commit_exists - AssertionEr...
1 failed, 897 passed, 2 skipped, 6453 warnings in 227.08s (0:03:47)
```

**Live check** (`prepare --dry-run`, texts to `work/results_texts.jsonl`, input to `work/ws6_live/`, nothing under
`data/` changed; 2026-10-07):

US, Costco's FY2026 Q4 release (`python scripts/results_digest.py --market us prepare --dry-run --since 2026-09-20
--ticker COST --out work/ws6_live/us_inputs.jsonl`):
```
  "detected": 2,
  "already_stored": 0,
  "due": 2,
  "deferred": 0,
  "for_agent": 1,
      "release_id": "COST-concall-2026-09-24",
      "status": "transcript_unavailable",
      "release_id": "COST-results-2026-09-24",
      "status": "ok",
      "numbers_status": "ok",
      "release_at": "2026-09-24T20:17:37+00:00",
      "sources": 3,
  "texts": {
    "filings": 1,
    "documents": 3,
    "failed": [],
    "skipped": null,
    "requests": 10,
```
The input's numbers (from the 10-K accepted 2026-10-07T01:13:15Z): `{"fiscal_label": "FY2026 Q4", "revenue":
95723000000.0, "net_profit": 2998000000.0, "eps_diluted": 6.75, "revenue_yoy_pct": 11.1, "eps_yoy_pct": 14.99,
"revenue_qoq_pct": 35.73, "prev_quarter_gap_days": 112, "derived": true}`; consensus `none_before_release` (Yahoo
estimates are stored from 2026-10-07 only); reaction `{"window": ["2026-09-25"], "move_pct": 2.93,
"benchmark_move_pct": 0.54, "excess_pct": 2.39}`; sources: the 8-K main document, EX-99.1 press release ("COSTCO
WHOLESALE CORPORATION REPORTS FOURTH QUARTER AND FISCAL YEAR 2026 OPERATING RESULTS") and EX-99.2 supplemental.

India (`python scripts/results_digest.py --market india prepare --dry-run --since 2026-08-01 --out
work/ws6_live/india_inputs.jsonl`):
```
  "detected": 2,
  "due": 2,
  "for_agent": 0,
      "release_id": "HINDALCO-results-2026-06-30",
      "status": "text_unavailable",
      "numbers_status": "ok",
      "release_at": "2026-08-07T11:54:34+00:00",
      "release_id": "ONGC-results-2026-06-30",
      "status": "text_unavailable",
      "numbers_status": "ok",
      "release_at": "2026-08-04T14:49:03+00:00",
```
No text because the stored NSE announcements start on 2026-10-04 (the August results announcements were never
collected). One-off check of the attachment path on a stored NSE archive PDF (Dr. Reddy's "Intimation of Earnings
call", parser enabled only for this check, output in `work/ws6_live/`): `status with config default:
pdf_not_parsed`, then `362355 bytes; 2504 chars`.

## Judge verdicts
See `docs/ws/ws6-judgments.jsonl`.

## Proposed edits to shared docs
**CLAUDE.md**, `## Layout`, after the `- News verification, phase B ...` bullet:
```markdown
- Results digests (WS6, docs/ws/ws6.md; logic in `scripts/marketbrief/results/`, settings `config/results.yaml`):
  `results_digest.py prepare` detects the watchlist's quarterly results releases (India: first NSE Integrated
  Filing of a quarter; US: SEC 2.02 kept by `results_filter`) and earnings-call texts (India: NSE transcript
  announcements; US: prepared remarks filed with the SEC, else `transcript_unavailable`) of the last 10 days,
  stores their primary texts in `primary_texts` (NSE attachments from the archive host only), computes the numbers
  as of the release (no later restatement: India filings within 24 h of the first, US `fundamentals_metrics_asof`
  at the quarter's first 10-Q/10-K, `pending_report` until then), the consensus collected before the release
  (context only) and the reaction, and writes the results-analyst's input; `validate|add` is the gate (ids,
  verbatim quotes, numbers from the quote or the release, enums, no advice) and appends to `results_digests`
  (views `results_digests_asof(ts)`, `results_digests_latest`, `results_digest_ticker_latest`).
```
**CLAUDE.md**, `## Layout`, the `.claude/agents/` bullet: add "results-analyst (at most 5 quoted bullets per results
release or earnings-call text, never a forecast or advice)" to the list, and "the results-analyst" to the Sonnet 5.5
group.

**CLAUDE.md**, `## Judging every change`, the "Daily runs are gated by" bullet: after "`scripts/lessons.py validate`"
add ", for the results-analyst's bullets by `scripts/results_digest.py validate`".

**docs/DESIGN.md** section 13 (agent table): a row `results-analyst | Sonnet 5.5 | medium | results digests
(WS6)`. A new short section (after 3b) can reuse this file's `## Contract` text.

**routine/PROMPT.md**, step 3, after item `d.` (news_status) and before the `Gate:` paragraph:
```markdown
   e. Results digests (non-blocking; docs/ws/ws6.md): follow routine/RESULTS_PROMPT.md (results_digest.py
      prepare, the results-analyst subagent, validate, add). List every failure, skip and dropped line in
      `data_quality`.
```
and in the preamble's list of per-agent gates:
```markdown
- results-analyst: `scripts/results_digest.py validate` (step 3e: release and source ids, verbatim quotes, numbers
  from the quote or the release's deterministic numbers, enums, no forecast or advice);
```

**Context pack** (`scripts/context.py` / `pipeline/context.py`, not edited here): a section after "Fundamentals":
```markdown
## Results digests (last 10 days)
Deterministic numbers as of each release; quotes verbatim from the filed text; consensus is context only.
| ticker | release | quarter | revenue YoY % | net profit YoY % | EPS | surprise % | reaction % | status |
- <ticker> <topic>: <text> [<source_id>]
```
from
```sql
SELECT * FROM results_digests_asof(now()) WHERE release_at >= now() - INTERVAL 10 DAY
ORDER BY release_at DESC, id
```
(`numbers->>'revenue_yoy_pct'`, `numbers->>'net_profit_yoy_pct'`, `numbers->>'eps_diluted'`,
`consensus->>'surprise_pct'`, `reaction->>'move_pct'`). The forecast gate need not change: digests cite filing and
announcement ids, not news ids.

**scripts/marketbrief/constants/ai_replay.py** `PUBLIC_AT` (so an as-of replay can copy digests):
`"results_digests": ["created_at"],  # WS6: a digest once stored (every input <= inputs_until <= created_at)`.
Until then `ai_replay` lists the kind as "no known publication-time rule" and leaves it out (safe).

**scripts/marketbrief/constants/neo4j.py** `NOT_PROJECTED`:
`"results_digests": "per-release results digests (WS6), DuckDB only for now",`.

## Cosmetic follow-ups
None yet (filled from the judge's findings).

## Open questions
1. **PDF parsing (India).** NSE attachments (results press releases, transcripts) are PDFs. The safety rules allow
   parsing PDFs only with libraries already in `requirements.txt`, and none parses PDF. Default taken:
   `texts.pdf_parser: null`, so PDF attachments are recorded as `pdf_not_parsed`, never requested, and India
   digests hold numbers only (`text_unavailable`). To enable: add `pypdf` (pure Python, no dependencies) to
   `requirements.txt` and set `pdf_parser: pypdf`; the code path exists and is tested where the library is installed.
2. **India announcement history.** Stored announcements start 2026-10-04, so earlier results releases have no text.
   Default: no backfill (the next quarter's releases from mid-October are covered). A one-off
   `collect_nse_india.py` announcements backfill would add texts for July-August releases.
3. **US numbers arrive twice.** The 2.02 press release comes weeks before the 10-Q, so a US release is first
   digested with `pending_report` and again when the 10-Q is filed (the agent sees its earlier bullets). Default:
   both rows kept (append-only), the newest wins.
4. **Consensus history.** Yahoo estimates are stored from 2026-10-07; releases before then show
   `none_before_release`. Default: no backfill (a past estimate collected after the release is never used).
