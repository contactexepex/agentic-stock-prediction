# WS4: paper portfolio and signal tiers

## Scope
On branch `build/ws4-portfolio`, the owner records paper trades and holdings and requests new companies,
through Claude Code now and Slack later. They see positions and P&L before and after costs. Each watchlist
stock gets a plain signal tier that never overstates proof: Strong tiers appear only in a proven cell.
Otherwise every tier says "Paper only — no proven edge yet".
Research only. A paper trade is a record, never an order. Nothing here connects to a broker. Paper-follow
(optional item 4) is built and labelled SIMULATED.

## Files
Created:
- `scripts/portfolio.py`: thin entry point.
- `scripts/marketbrief/portfolio/`:
  - `__init__`, `constants`, `settings`;
  - `context`: `Context`, `TradeInput`, `context()`;
  - `reads`: as-of reads;
  - `costs`: per-side cost in currency;
  - `trades`: validation, stored row, append;
  - `ledger`: FIFO positions and P&L;
  - `service`: importable functions;
  - `proof`: proof status;
  - `signal_inputs`;
  - `signals`: tiers and `cockpit_payload`;
  - `paper_follow`: the simulation;
  - `api_shapes`: the openapi shapes;
  - `tables`;
  - `cli`.
- `scripts/marketbrief/core/schema_portfolio.py`
- `config/portfolio.yaml`
- `tests/test_portfolio.py`, `tests/test_portfolio_signals.py`
- `docs/ws/ws4.md`, `docs/ws/ws4-judgments.jsonl` (one line per judge verdict)

Shared files changed (additive only):
- `scripts/marketbrief/core/schemas.py`: one import and one spread line:
  ```python
  from marketbrief.core.schema_portfolio import PORTFOLIO_SCHEMAS  # WS4
          **PORTFOLIO_SCHEMAS,  # WS4
  ```
- `scripts/marketbrief/constants/kinds.py`: a block at the end:
  ```python
  # ---------- WS4: paper portfolio (scripts/portfolio.py; marketbrief/portfolio/) ----------
  KIND_PORTFOLIO_TRADES = "portfolio_trades"
  KIND_WATCHLIST_REQUESTS = "watchlist_requests"
  ```

Not changed: `sql/views.sql`, `requirements.txt`, every existing daily-run step. Being in `SCHEMAS`, the new kinds
add two empty tables to `connect()` when no file exists, and `validate --stage collect` schema-checks their files
and counts them in `rows_today` like every kind.

## Contract
**Data kinds.** Both are append-only JSONL. A row goes in the day file of its UTC write time
(`data/<market>/<kind>/YYYY/MM/YYYY-MM-DD.jsonl`), and it is written via a temp file in `work/portfolio/`
before the append.

`portfolio_trades` has these columns:
- `id` = `pt-<market>-<sha256(market|key)[:16]>`
- `market`, `ticker`
- `side`: `buy`, `sell` or `cancel`
- `quantity`
- `price`: as traded, on the stored bar's basis of that day
- `price_basis`: `open`, `close` or `manual`
- `trade_date`
- `source`: `claude_code`, `slack` or `form`
- `idempotency_key`
- `entered_at`, `note`
- `supersedes`

Corrections never edit a row:
- **Replace a trade:** `add-trade --supersedes <id>` writes a new buy/sell row with the same ticker. The old row
  stops counting.
- **Cancel a trade:** `cancel-trade --id <id>` writes a `cancel` row with quantity 0 and price null.
- **Limits:** a superseded row cannot be superseded again. To correct a correction, supersede the newest row.

`watchlist_requests` has these columns:
- `id` = `wr-<market>-<hash>`
- `market`, `ticker`, `name`, `reason`
- `requested_at`, `source`
- `status`: `requested`
- `idempotency_key`

A request never changes config. Adding the company to `config/markets/<market>.yaml` stays a human or reviewed
change.

**Validation in `add-trade`.** Every check runs against data stored by the run's clock. Nothing is stored
unless all of them pass:
- the ticker is in the market's watchlist;
- `trade_date` is a session of the market calendar, and not after the clock's date;
- `price_basis` open/close takes the stored bar's open or close;
- `manual` needs a price inside that bar's low-high (`trades.manual_price_tolerance`, 0 by default);
- a price given with open/close is rejected;
- a bar must be stored for that day. Today's bar exists only after its close plus 120 minutes, so a same-day
  trade is recorded after the next price collection;
- the idempotency key must be unused by any stored trade or request. The default key is derived from the
  fields, so the same command twice counts as one trade (a retried message);
- a `supersedes` target must exist, be active and have the same ticker;
- a sell may not exceed the quantity held after the change (`trades.allow_short: false`). The same applies to
  a cancel that would leave a later sell uncovered.

**P&L (`ledger.py`).** Lots are matched FIFO. Trades are ordered by trade_date, then within a day by
open < manual < close, then by entered_at and id.
- **Split basis:** every trade is put on today's split/bonus basis (price × factor, quantity / factor). The
  factor comes from the `adjustments` detected by the clock, minus superseded ones. A later split therefore
  never shows as a loss.
- **Mark:** the latest stored close by the clock.
- **Realised** is booked on each sell:
  - net = gross − the closed lots' share of their buy cost − the sell's cost.
- **Unrealised** is booked on each open lot:
  - net = gross − the open share of the buy cost − the estimated cost of selling at the mark (`est_exit_cost`).
- **Costs:**
  - rates come from `config/costs.yaml`, the signal model's own;
  - India: per side (brokerage + exchange + SEBI) × (1 + GST) + STT + slippage, with stamp duty on the buy;
  - US: commission + slippage, plus the SEC fee and the FINRA TAF on the sell (per share, capped);
  - a buy plus a sell of the same value equals `model/settings.round_trip_cost` (tested).

**Proof status (`proof.py`, `config/portfolio.yaml` `proof`).** A (horizon, confidence band) cell is
*proven* only when all of these hold, each as of the clock:
- the newest weekly review has `model_skill: true`;
- the forecaster's calls in that horizon and band were scored on `open_to_close` only, never pooled with
  close_to_close, and made and scored by the clock;
- there are at least `min_count` of them (50);
- their Wilson 95% lower bound is at least `min_wilson_low` (0.55).

The bands are `[0.5, 0.6)`, `[0.6, 0.7)`, `[0.7, 0.8)` and `[0.8, 0.9]`, the same bins as `scoring.py`. The market
is proven when any cell is.

**Tiers (`signals.py`, `config/portfolio.yaml` `tiers`).**
- **Inputs:**
  - `final p` = model_prob + the call's agent_adjustment, or model_prob alone when there is no call;
  - the direction is the call's own, or else the side of 0.5;
  - confidence = max(p, 1 − p), rounded to 4 decimals.
- **The tiers:**
  - **Strong Buy / Strong Sell:** the cell is proven, a forecaster call exists (`strong_requires_call`), and
    confidence ≥ 0.65;
  - **Buy / Sell:** confidence ≥ 0.55;
  - **Hold/No call:** everything else, plus quality `BLOCKED`, or earnings within 1 calendar day
    (`features.days_to_earnings`). Every watchlist ticker and horizon without a model score on the as-of date
    also gets a Hold/No call row, with the reason "no model score".
- **Labels:** a row has `paper_only: false` and the proven label only when it has a forecaster call in a
  proven cell. Every other row, including model-only rows in a proven cell, has `paper_only: true` and the
  label "Paper only — no proven edge yet". The payload-level `label` says proven when any cell is proven.
- **No strong tier:** the payload says "No proven strong signals today". It lists up to 5 Paper candidates by
  |model_prob − 0.5|, ties broken by ticker and horizon. Each carries the score's own top 3 drivers on its
  side, from `contributions.up|down`.

**Importable functions.** These are for WS1's read models and WS7's governed tools. Each takes a `Context` and
returns a JSON-ready dict. Rejected writes return `{"ok": false, "errors": [...]}` and store nothing.
- `marketbrief.portfolio.service`:
  - `context(market)`
  - `add_trade(ctx, TradeInput(...))`
  - `cancel_trade(ctx, id, source, note=, idempotency_key=)`
  - `request_company(ctx, source, reason, ticker=, name=, idempotency_key=)`
  - `positions_report(ctx)`, `pnl_report(ctx)`, `list_report(ctx)`
- `marketbrief.portfolio.signals.cockpit_payload(con, clock, market, settings)` returns these fields:
  - `market`, `as_of_date`, `computed_at`;
  - `proof` (status, model_skill, review, basis, rule, cells);
  - `paper_only`, `label`, `strong_count`, `headline`;
  - `tiers[]`: id, ticker, horizon_days, tier, direction, model_prob, agent_adjustment, final_prob,
    confidence, has_call, range, band, proven, paper_only, label, blocked, reasons, drivers;
  - `candidates[]`.
- `marketbrief.portfolio.paper_follow.simulate(con, cfg, clock, market, settings, costs)`
- `marketbrief.portfolio.api_shapes.signal_tiers(payload, cfg)` gives openapi `SignalTiers`.
  `paper_portfolio(ctx)` gives `PaperPortfolio`.

**CLI.** `python scripts/portfolio.py --market india|us <command>`:
- `add-trade --ticker --side --quantity --date --basis [--price] [--supersedes] [--note] --source [--key]`
- `cancel-trade --id --source [--note] [--key]`
- `request-company (--ticker | --name) --reason --source [--key]`
- `positions`, `pnl`, `list`, `signals`, `paper-follow`, `api-signals`, `api-portfolio`

stdout carries one JSON object; a short table goes to stderr. A rejected write exits with code 2. Every read
is MB_NOW-aware: rows are filtered by `collected_at`, `entered_at`, `requested_at`, `computed_at`, `made_at`,
`scored_at` or `detected_at` ≤ clock. Paper-follow's feature rows also have to be computed before the open of D.

**Paper-follow.** It is a deterministic simulation on stored bars, labelled
"SIMULATED — paper-follow on stored bars, not real trades".
- It covers the last `paper_follow.lookback_sessions` as-of dates.
- An id's score counts only when computed before the open of D; ids scored later are counted in `late_scores`.
- Candidates are picked as `signals` picks them, with the feature block as of that time.
- The trade is open-to-close: entry at the open of D, exit at the close of D+1 (1d) or D+4 (5d).
- Returns are after the round trip of `costs.yaml`.
- Up candidates are simulated long. Down candidates are "sell if held", reported apart and never pooled.

**Alignment with api/openapi.yaml.** `build/wave0` was first read at 17eb531 on 2026-10-07, and rechecked at
7f448e2, whose later commits change only units notes, not these fields. `api-signals` emits
`SignalTiers` exactly:
- `headline`, `rule`, `strong[]` and `paper_candidates[]` of `SignalCandidate`;
- each candidate has ticker, name, h, tier (`strong_buy|strong_sell|paper_up|paper_down`), model_prob,
  prediction_id, direction, confidence, entry, exit and label.

`api-portfolio` emits `PaperPortfolio`: market, as_of, label, positions, trades and pending. Remaining
differences, for the orchestrator or owner to settle:
1. **Trade side:** the contract has `buy|sell`; the stored kind also has `cancel` rows, which are not listed in
   `trades`.
2. **Trade source:** the contract has `slack|claude_code|dashboard`; the brief says `form`. A one-word change in
   `config/portfolio.yaml` `trades.sources`.
3. **`PaperTradeRequest`:** it has `horizon_days` and no trade_date, price_basis or price. The stored kind keeps
   the trade's date and basis and has no horizon. When the inbox import is built, the request needs
   trade_date and price_basis, or the import assumes today and the open.
4. **`PaperPortfolio.positions`:** there is one entry per open lot. `entry_price` is the trade's price (open,
   close or manual) on today's split basis, not always "the open". `h` and `exit_date` are absent, because
   trades carry no horizon. Extra fields: price_basis, mark_date, trade_id. There is also an extra `totals`
   object.
5. **`CompanyRequest`:** the contract requires `ticker`; `request-company` accepts a ticker or a name.
6. **Inbox import (ARCHITECTURE.md §9):** `add_trade(..., idempotency_key=<inbox_id>)` already gives the
   idempotent import. A repeated key is rejected with the earlier row id. `inbox_imports` rows are not
   built: they belong with the inbox.

### Slack and Claude Code entry
A message like "bought 10 HDFCBANK at open today" becomes a validated `add-trade` call, run by a Claude Code
session. There is no Slack bot: the governed MCP tool comes in wave 2 (WS7), and it wraps
`service.add_trade` and `service.request_company` directly.

1. **Parse** the message into fields:
   - ticker `HDFCBANK`, checked against `config/markets/india.yaml` `tickers` and their `aliases`. "HDFC"
     alone is ambiguous: ask;
   - side `buy`, quantity `10`, price_basis `open` ("at open"; "at close" → `close`; "at 1612.5" → `manual`
     with `--price 1612.5`);
   - trade_date = "today" in the market's timezone (Asia/Kolkata for India, America/New_York for the US), as
     an ISO date;
   - source `slack` if the message came from Slack, `claude_code` if typed in a session.
2. **Pick an idempotency key** from the message itself, e.g. `slack-<channel>-<message ts>`, so a retried or
   re-read message can never record the trade twice.
3. **Run** it:
   ```bash
   python scripts/portfolio.py --market india add-trade --ticker HDFCBANK --side buy --quantity 10 \
     --date 2026-10-07 --basis open --source slack --key slack-C0123-1759800000.000100
   ```
4. **On `"ok": true`:** reply with the stored id, price and file. Then commit only the new
   `data/india/portfolio_trades/` file and push.
5. **On exit code 2:** reply with the `errors` list verbatim and store nothing. A common case is "no stored bar
   for HDFCBANK on 2026-10-07": today's bar is stored after the close plus 120 minutes. Say so and run the same
   command, with the same key, after the next price collection.
6. **Corrections:**
   - "it was 12, not 10": `add-trade ... --quantity 12 --supersedes <id>`;
   - "cancel that": `cancel-trade --id <id> --source slack`.
7. **"Add Zomato to the watchlist":** `request-company --name Zomato --reason "..." --source slack`. Tell the
   owner that adding it to config is a reviewed change.
8. **Never** place, route or suggest an order, and never touch a brokerage tool. A paper trade is a record only.

## Tests
Offline, on synthetic data roots (fixtures in the test files). Pasted from command output:

```
$ python -m pytest -q tests/test_portfolio.py tests/test_portfolio_signals.py tests/test_code_structure.py tests/test_judgments.py --deselect tests/test_judgments.py::test_every_logged_commit_exists
47 passed, 1 deselected in 30.88s

$ python -m pytest -n auto -q
1 failed, 923 passed, 2 skipped, 6453 warnings in 215.14s (0:03:35)
```

The one failure is `tests/test_judgments.py::test_every_logged_commit_exists`. It fails the same way on a
clean checkout of main in this session (the clone is shallow, so older logged commits are missing), and CI
excludes it (CLAUDE.md).

```
$ ruff check scripts/marketbrief/portfolio scripts/portfolio.py scripts/marketbrief/core/schema_portfolio.py scripts/marketbrief/core/schemas.py scripts/marketbrief/constants/kinds.py tests/test_portfolio.py tests/test_portfolio_signals.py
All checks passed!
```

These are round 2's runs, after the blocker fixes. Round 1's were "42 passed, 1 deselected" and
"1 failed, 918 passed, 2 skipped", with the same single failure.

What is covered:
- validation failures: non-watchlist ticker, Saturday, future date, manual price outside low-high, a missing
  or infinite price, a price with open/close, zero, infinite, NaN or bool quantity, bad side, basis or
  source, no stored bar, a duplicate
  idempotency key (explicit and derived), selling more than held, the same-day open before close;
- corrections: supersedes, a double correction, ticker change, an unknown target, cancel, a cancel that
  would uncover a sell;
- append-only writes with no temp files left;
- P&L with costs, India FIFO and US sell fees, computed by hand in the test;
- per-side costs adding up to `round_trip_cost` with the real `config/costs.yaml`;
- the split basis;
- no look-ahead for trades, bars, reviews and scores;
- tiers: the pure rule; strong never without proof (skill false, close_to_close record, too few calls,
  low Wilson); strong emitted when proven; a model-only row in a proven cell stays paper only; every
  watchlist ticker and horizon gets a row ("no model score"); blocks;
- paper-follow, scored by hand; feature rows after the clock are ignored;
- the openapi shapes;
- the CLI's JSON, exit codes and table.

## Judge verdicts
- Round 1, FAIL, 6acd8e9. Blockers:
  - look-ahead in paper-follow's feature blocks;
  - no tier row for watchlist tickers without a score;
  - quantity and price accepted infinity;
  - ws4.md: the judgments file was listed before it existed, "sessions" was written for calendar-day
    earnings, and the label rule did not match the code.
  
  All were fixed in round 2's commit, each with a test.
- Round 2, PASS, fed8f55: all six blockers verified fixed with tests; no new blockers.
- Round 3, PASS, a1d432f: the merge of main (WS1, WS5, wave 0). Its one conflict was in `core/schemas.py`,
  where the WS4 and WS5 spread lines were both kept. After the merge, the full suite gave "1 failed, 972 passed,
  2 skipped" (the same shallow-clone failure).

## Proposed edits to shared docs

**CLAUDE.md**, in `## Layout`, after the `- Signal model (DESIGN.md section 15; ...` bullet:

```markdown
- Paper portfolio and signal tiers (WS4; `scripts/portfolio.py --market india|us`, logic in `marketbrief/portfolio/`,
  settings `config/portfolio.yaml`, notes `docs/ws/ws4.md`): research only, a paper trade is a record, never an order.
  `add-trade` validates (watchlist ticker, a session, price = the stored bar's open/close or a manual price inside its
  low-high, unused idempotency key, no selling more than held) and appends to `data/<market>/portfolio_trades/`
  (corrections: a new row with `supersedes`, `cancel-trade`); `request-company` appends to
  `data/<market>/watchlist_requests/` (config stays a human change); `positions` / `pnl` (FIFO, marked to the latest
  stored close, before and after `config/costs.yaml` costs, split basis of `adjustments`); `signals` (tiers Strong Buy
  .. Strong Sell; Strong only in a proven horizon x confidence band: review `model_skill` true and >= 50 open_to_close
  calls with Wilson low >= 0.55; else "No proven strong signals today" + Paper candidates); `paper-follow` (SIMULATED).
  Every read is as of the clock (MB_NOW-aware).
```

**docs/DESIGN.md**, at the end of section 16 (wave 0's new section), a new paragraph:

```markdown
**Paper portfolio and tiers (WS4, built 2026-10-07).** Paper trades (`portfolio_trades`) and add-company requests
(`watchlist_requests`) are append-only kinds written only by `scripts/portfolio.py` after validation against stored
bars and the market calendar; a correction is a new row with `supersedes`. Positions and P&L are FIFO on today's
split basis, marked to the latest stored close, before and after the costs of `config/costs.yaml`. A signal tier is
Strong only in a proven (horizon, confidence band) cell: the latest weekly review has `model_skill` true and the
forecaster's open-to-close calls in that cell number >= `proof.min_count` with a Wilson 95% lower bound >=
`proof.min_wilson_low` (`config/portfolio.yaml`); a row is labelled proven only when it carries a forecaster call in
such a cell, and every other row is labelled "Paper only — no proven edge yet".
```

**routine/PROMPT.md**: none needed. The tiers are computed on read. A later wave may add `portfolio.py signals` to the
digest; that is WS2/WS3's call.

## Cosmetic follow-ups
From round 1. Fixed in round 2's commit:
- `trades.py`: a stored bar with a NaN or missing open/close is now rejected (`bar_price`).
- The duplicate-key error now hints `--key`, for re-entering an identical trade after a cancel.
- `service.request_company`: the ticker is uppercased before the "already listed" check.
- `ws4.md`: the `validate --stage collect` wording and the wave 0 commit (7f448e2).

Open:
- `signals.py` `signal_row`: a pre-forecast-v11 call without `model_prob` combines the call's direction with
  the model's probability (no stored calls exist today).
- `signals.py` `candidates`: a Paper candidate's `tier` can be of the opposite side when the forecaster's
  adjustment flips the side. Its `direction` is the model's side.
- `signals.py` `unscored_rows` (round 2): when no score exists at all, the rows have `id` None, and
  `api_shapes` keys a dict by id. Harmless today, because candidates exclude these rows.

## Open questions
1. **Proof thresholds** (`min_count` 50, `min_wilson_low` 0.55, strong at confidence ≥ 0.65 with a forecaster call
   required). Default: as listed. All of them sit in `config/portfolio.yaml`.
2. **Same-day trades** need the session's stored bar, which is final at close + 120 min, for both open/close and
   manual prices. Default: reject with a clear message and record after the next collection, which fails safe.
   The alternative is accepting an unchecked manual price, marked unchecked.
3. **Paper short selling.** Default: off (`trades.allow_short: false`). The owner holds none of the 40, so a sell
   needs a recorded buy first. An existing holding is recorded as a buy with its date and a manual price.
4. **`cancel` side and `form` source** versus the openapi enums (Alignment items 1-2). Default: kept as the
   brief says.
5. **Horizon on trades.** Default: not stored. Positions have no planned exit; the paper-follow simulation uses
   the D+1 / D+4 convention.

## Issue #112: the paper-trade inbox import (2026-10-07, built in session B2 as the WS4 owner)
The web tier (B5) writes the owner's paper trades from Slack `/trade`, the Claude app and the dashboard to
`market_brief_inbox.inbox.requests` (`tool = add_paper_trade`; schema `mcp/inbox.sql`). The importer stores them.

- **Command:** `python scripts/portfolio.py --market india|us import-inbox [--inbox FILE]`. Without `--inbox`, it
  reads MotherDuck with `MOTHERDUCK_INBOX_TOKEN` only, through B1's `lifecycle/inbox.open_inbox`, read-only. The
  code is in `marketbrief/portfolio/inbox_import.py`.
- **Validation:** each pending row runs through `service.add_trade`, the same checks as `add-trade`:
  - the ticker is an active watchlist company;
  - the trade date is a session and not in the future;
  - the price basis matches a stored bar, or a manual price lies inside the bar's low-high;
  - the idempotency key is unused (the key is the row's `inbox_id`);
  - the sell is no larger than the quantity held.
- **Identity:** `source` is the row's `channel`; `config/portfolio.yaml` `trades.sources` gains `dashboard` and
  `claude_app`. `submitted_by` is the row's identity and `command_id` is the web tier's command id; both are new
  columns of `portfolio_trades`, null for CLI trades. Nothing is taken from the arguments.
- **Refusals:**
  - a channel other than dashboard, slack, claude_code or claude_app: `not_allowed_in_channel`;
  - missing fields or a failed check: `validation_failed`;
  - a key already used by a stored trade: `duplicate`.
- **Logging:** every imported row gets one `command_log` row (B1's format and helper): accepted, refused or
  duplicate.
- **Idempotent:** an `inbox_id` that a `command_log` row already settled is skipped, so a rerun imports nothing
  twice. The inbox is never written.
- **Tests:** `tests/test_portfolio_inbox.py`, on an inbox built from `mcp/inbox.sql`.

Handed over to the owners (not built here):
- **B1:** a step in `.github/workflows/onboard.yml` running
  `python scripts/portfolio.py --market "$market" import-inbox`, beside `company.py import-inbox`.
- **Orchestrator / Wave 5:** the same command in the routines (pre-open and post-close), after
  `company.py import-inbox`.
- **B5:**
  - switch on the paper-trade dispatch in `web/lib/tools/executor.ts`;
  - update the "NO IMPORTER YET" comment in `mcp/inbox.sql`;
  - update the caller's "pending until the paper-trade import is built" text.
