# Workstream notes (docs/ws/)

Every workstream (WS1-WS8, and wave0) keeps its notes here, so the orchestrator can merge the
parallel branches without reading every diff first. Architecture and contracts: `docs/ARCHITECTURE.md`
and `api/openapi.yaml`.

## Files per workstream

| File | Content |
|---|---|
| `docs/ws/wsN.md` | The workstream's notes, in the sections below (wave 0 keeps them in this README) |
| `docs/ws/wsN-judgments.jsonl` | One JSON line per judge verdict on the workstream's work, append-only |

### `wsN.md` sections (in this order, headings exactly as written)

1. `## Scope` - the task in two or three lines and the branch name.
2. `## Files` - files created and changed; every shared file (`core/schemas.py`, `constants/*`,
   `sql/views.sql`, `requirements.txt`) listed with the exact lines added.
3. `## Contract` - what other workstreams can rely on: data kinds and their schemas, read-model tables
   and payload fields filled, CLI flags, config keys. Any change to `api/openapi.yaml` (minor version
   bump for additions; a major bump needs the owner).
4. `## Tests` - the commands and their counts, pasted from command output, never retyped.
5. `## Judge verdicts` - one line per round (round, verdict, commit), mirroring the JSONL file.
6. `## Proposed edits to shared docs` - the exact lines for CLAUDE.md, docs/DESIGN.md and the routine
   prompts, each with the file, the place (after which line or heading) and the text in a fenced
   block. The orchestrator applies them at merge; workstreams never edit those files.
7. `## Cosmetic follow-ups` - each cosmetic judge finding, one bullet (file, finding). Not opened
   as issues by the workstream; the orchestrator files them at merge.
8. `## Open questions` - decisions for the owner, each with the default the workstream took.

### `wsN-judgments.jsonl` lines

Same fields as `judgments/log.jsonl`, one object per line, appended (never rewritten):

```json
{"subject": "WS1 warehouse", "work": "<what was judged, one line>", "commit": "<full sha>", "round": 1, "verdict": "PASS", "summary": "<the judge's summary>", "recorded_at": "2026-10-07T12:00:00Z"}
```

`verdict` is `PASS` or `FAIL`; `round` starts at 1 and counts re-checks; `recorded_at` is ISO UTC.
At merge the orchestrator appends these lines to `judgments/log.jsonl` (the commits then exist on main).

## Wave 0 notes

Wave 0 has no `wave0.md` (its file list is this README), so its sections sit here one heading level down,
in the order above.

### Scope
Contracts for waves 1-3 on branch `build/wave0`: `docs/ARCHITECTURE.md`, `api/openapi.yaml`,
`tests/test_openapi.py`, this README. Docs and spec only, no runtime code.

### Files
Created: `docs/ARCHITECTURE.md`, `api/openapi.yaml`, `tests/test_openapi.py`, `docs/ws/README.md`;
`docs/ws/wave0-judgments.jsonl` is added with the first recorded verdict. No shared file changed; no dependency added (pyyaml was present).

### Contract
`api/openapi.yaml` version 1.0.0. Read-model tables `rm.markets|status|overview|watchlist|stock|bars|
track_record|news|runs`, planned `rm.portfolio`, bookkeeping `rm.builds` (ARCHITECTURE.md 4.1).

### Tests
- `python -m pytest tests/test_openapi.py -q` -> `9 passed in 0.25s`
- `python -m ruff check tests/test_openapi.py` -> `All checks passed!`
- Full suite `python -m pytest -n auto -q` (round 1 commit) -> `1 failed, 892 passed, 2 skipped`; the failure is
  `test_every_logged_commit_exists`, which needs full git history (this clone is shallow; CI excludes it).

### Judge verdicts
- Round 1, FAIL, 17eb531: README listed the judgments file as created; the units note was wrong for `atr_pct`.
- Round 2, PASS, 8d1f20d: both blockers fixed; no new blockers.

### Proposed edits to shared docs

**CLAUDE.md**, in `## Layout`, after the `- Neo4j projection (DESIGN.md section 12): ...` bullet:

```markdown
- App architecture (docs/ARCHITECTURE.md; contract `api/openapi.yaml`, checked by `tests/test_openapi.py`):
  `data/` stays the source of truth; MotherDuck `market_brief` (env `MOTHERDUCK_TOKEN`) is a derived copy
  plus per-page read models in schema `rm` (one keyed row per market x page, payload JSON as of the run's
  cut-off, rebuilt idempotently by hash), synced after each daily and news run, non-blocking. The Next.js
  app on Vercel reads only `rm` through MotherDuck's Postgres endpoint under `/api/v1`. Static `reports/`
  and Slack keep working when MotherDuck is down or capped. Workstream notes: `docs/ws/`.
```

**docs/DESIGN.md**, a new section after `### 15.1 ...` (end of file):

```markdown
## 16. The app around the pipeline (contract 2026-10-07)
The app (API, frontend, paper portfolio, governed actions) is specified in `docs/ARCHITECTURE.md` and
`api/openapi.yaml`. It changes no daily-run step: MotherDuck `market_brief` is a derived copy of
`data/` (like Neo4j, section 12) holding small per-page read models built as of the run's clock; the app
does one keyed SELECT per page and Vercel caches it until the next build changes that page. Every signal
stays "Paper only — no proven edge yet" until the weekly review's `model_skill` is true; Strong Buy /
Strong Sell appear only once proven. User records (paper trades, add-company requests) enter `data/`
only through validated CLIs, from Slack or Claude Code now and from an append-only inbox later.
```

**routine/PROMPT.md** and **routine/NEWS_PROMPT.md**: no wave 0 edit. WS1 proposes the exact
`warehouse_sync` step lines (after `dashboard` in the daily run, after the push in the news run;
non-blocking, like step 10b `neo4j_sync`).

### Cosmetic follow-ups
Round 1's cosmetic findings were all fixed in round 2's commit: the x-source check now fails on a missing
module, a new test checks that operations returning planned schemas are planned, the `rm` size and
budget-total wording were corrected, and these wave 0 notes gained Tests and Judge verdicts sections.

Open (round 2):
- `docs/ARCHITECTURE.md` section 5, budget total row: the low case "~9.3" leaves out the 0.25 h of read
  misses (about 9.5 h, under the cap), so "at or over the cap" overstates it; say "near the cap".

### Open questions
1. News-run cadence: answered by the owner: every 4 hours, 5 runs per market per day (ARCHITECTURE.md 5, DESIGN.md section 2).
2. MotherDuck billing (per-query minimum, idle cool-down, Postgres endpoint) decides whether news
   syncs may touch MotherDuck at all; to verify in week 1 from the usage page (ARCHITECTURE.md 5).
3. Dashboard form writes need a MotherDuck token that can write the `inbox` schema in Vercel. If
   MotherDuck cannot scope a token to one schema or database, should the form go through our MCP
   server (WS7) instead of a Vercel-side token? Default taken: decide when the form is built (wave 3);
   until then Vercel holds a read-only token only.
4. Should the market-wide news feed (`rm.news`, page_key `_`) cover only watchlist tickers or every
   stored headline? Default: watchlist tickers, newest 50.
