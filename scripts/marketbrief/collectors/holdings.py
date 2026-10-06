"""Collect quarterly 13F holdings of watchlist tickers from a short list of large institutional
filers (relationships.holdings in config/markets/<market>.yaml: filers by CIK, ticker CUSIPs)
into data/<market>/holdings/YYYY/MM/<today>.jsonl.

Rows per processed filing:
- one filing row (ticker null): report type, table lines, `complete`, and in `note` why the
  filing is incomplete or, for a 13F notice, which manager reports the holdings instead;
- one row per watched (ticker[, put/call]) held: shares, value (USD), table lines summed;
- only for a complete filing, a zero row for each watchlist ticker the filer does not hold,
  so a real exit shows up as a change.
A filing is complete only if it is a 13F HOLDINGS REPORT (not a COMBINATION report, where other
managers report part of the holdings), omits nothing as confidential, has as many table lines
as the cover page's tableEntryTotal, and is not a placeholder table (CUSIP 000000000).
A 13F-NT (notice: "reported by another manager") gets only the filing row and counts as filed.

The first time a filer is seen its latest `quarters` periods are loaded, so a quarter-on-quarter
change exists from day one. Cheap to run daily: it uses the network only in the ~50 days after
a quarter end while some filer has not yet filed that quarter (or a filer is new to the
config), and then downloads only filings it has not stored yet; on other days it exits at once.
Original 13F-HR/13F-NT only; amendments (13F-HR/A) are ignored. Information tables (up to
~25 MB) are stream-parsed. `--force` checks the filers even when up to date.
Only for markets with `filings: sec`. Requires SEC_USER_AGENT."""
from __future__ import annotations

import json

from marketbrief.collectors.holdings_parsing import (FilingRef, filing_row, incomplete_reason, info_table_url,
                                                     parse_cover, parse_info_table, quarter_end, to_rows)
from marketbrief.constants.columns import COL_ACCESSION
from marketbrief.constants.config_keys import CFG_MARKET
from marketbrief.constants.kinds import KIND_HOLDINGS
from marketbrief.constants.sec_collection import (CFG_RELATIONSHIPS, COLLECTOR_HOLDINGS, DEFAULT_QUARTERS,
                                                  ERROR_TEXT_LIMIT, FILING_WINDOW_DAYS, FORM_13F_HR, FORM_13F_NT,
                                                  MSG_NO_FILERS, MSG_NO_NEW_QUARTER, MSG_UNNAMED_MANAGER,
                                                  MSG_UP_TO_DATE, REPORT_TYPE_NOTICE)
from marketbrief.core.cli import market_arg, require_market
from marketbrief.core.clock import utc_now, utc_today
from marketbrief.core.paths import data_dir
from marketbrief.core.storage import append_jsonl, day_file
from marketbrief.sources.sec_acceptance import time_summary, time_warnings
from marketbrief.sources.sec_client import Edgar, archive_url
from marketbrief.sources.sec_filings import filings_of_forms, require_sec


def stored(market: str) -> tuple[set[str], dict[str, str]]:
    """Accessions already stored, and the latest stored period per filer CIK."""
    accessions, latest = set(), {}
    for file in (data_dir(market) / KIND_HOLDINGS).glob("**/*.jsonl"):
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                accessions.add(row[COL_ACCESSION])
                latest[row["filer_cik"]] = max(latest.get(row["filer_cik"], ""), row["period"])
    return accessions, latest


def configured(cfg: dict) -> tuple[dict[int, str], dict[str, str], int]:
    """(filers {CIK: name}, watched CUSIPs {CUSIP: ticker}, quarters to load) of relationships.holdings."""
    settings = cfg.get(CFG_RELATIONSHIPS, {}).get(COLLECTOR_HOLDINGS, {})
    filers = {int(k): v for k, v in (settings.get("filers") or {}).items()}
    cusips = {}
    for ticker, listed in (settings.get("cusips") or {}).items():
        for cusip in [listed] if isinstance(listed, str) else listed:
            cusips[str(cusip).upper()] = ticker
    return filers, cusips, int(settings.get("quarters", DEFAULT_QUARTERS))


def newest_per_period(found: list[dict]) -> dict[str, dict]:
    """The latest original filing per period; a report beats a notice."""
    newest: dict[str, dict] = {}
    for filing in found:
        period = filing["report_date"]
        replaces_notice = period in newest and newest[period]["form"] == FORM_13F_NT and filing["form"] == FORM_13F_HR
        if period and (period not in newest or replaces_notice):
            newest[period] = filing
    return newest


class HoldingsRun:
    """One holdings run over the configured filers."""

    def __init__(self, edgar: Edgar, accessions: set[str], cusips: dict[str, str], quarters: int, now: str):
        """The 13F collector's client, accessions, CUSIPs, quarters and clock."""
        self.edgar, self.accessions, self.cusips, self.quarters, self.now = edgar, accessions, cusips, quarters, now
        self.tickers = sorted(set(cusips.values()))
        self.rows: list[dict] = []
        self.loaded: list[str] = []
        self.notices: list[str] = []
        self.failed: list[dict] = []

    def load_notice(self, ref: FilingRef, cover: dict, period: str) -> None:
        """A 13F-NT (notice: reported by another manager) gets only the filing row and counts as filed."""
        by = "; ".join(cover["other_managers"]) or MSG_UNNAMED_MANAGER
        self.rows.append(filing_row(ref, REPORT_TYPE_NOTICE, None, False, f"reported by {by}"))
        self.notices.append(f"{ref.filer} {period}: reported by {by}")

    def load_holdings(self, ref: FilingRef, cover: dict, period: str, table: tuple) -> None:
        """The filing row and the watched rows of a holdings report (zero rows only when it is complete)."""
        aggregates, n_lines, placeholder = table
        why = incomplete_reason(cover, n_lines, placeholder)
        self.rows.append(filing_row(ref, cover["report_type"], n_lines, why is None, why))
        self.rows += to_rows(ref, aggregates, self.tickers if why is None else [], cover["report_type"], why is None)
        held = sum(1 for (_, put_call), a in aggregates.items() if put_call is None and a["shares"] > 0)
        self.loaded.append(f"{ref.filer} {period}: {held} held" + (f" (incomplete: {why})" if why else ""))

    def load_period(self, cik: int, name: str, filing: dict, period: str) -> None:
        """Read one filing (its cover page, then its information table) and add its rows."""
        try:
            cover_url = archive_url(cik, filing[COL_ACCESSION], "primary_doc.xml")
            cover = parse_cover(self.edgar.get(cover_url))
            if filing["form"] == FORM_13F_NT:
                self.load_notice(FilingRef(filing, cik, name, cover_url, self.now), cover, period)
                return
            url = info_table_url(self.edgar, cik, filing[COL_ACCESSION])
            with self.edgar.open(url) as stream:
                table = parse_info_table(stream, self.cusips)
        except Exception as exc:
            self.failed.append({"filer": name, COL_ACCESSION: filing[COL_ACCESSION],
                                "error": str(exc)[:ERROR_TEXT_LIMIT]})
            return
        self.load_holdings(FilingRef(filing, cik, name, url, self.now), cover, period, table)

    def load_filer(self, cik: int, name: str) -> None:
        """Load the filer's latest `quarters` periods that are not stored yet."""
        try:
            found = filings_of_forms(self.edgar.recent(cik), {FORM_13F_HR, FORM_13F_NT})
        except Exception as exc:
            self.failed.append({"filer": name, "error": str(exc)[:ERROR_TEXT_LIMIT]})
            return
        newest = newest_per_period(found)
        for period in sorted(newest, reverse=True)[:self.quarters]:
            if newest[period][COL_ACCESSION] not in self.accessions:
                self.load_period(cik, name, newest[period], period)


def skip_reason(args, filers: dict[int, str], latest: dict[str, str], due: str, in_window: bool
                ) -> tuple[str, list[str]] | None:
    """(why the run exits at once, filers waiting for the quarter) or None to go on: nothing to do when every
    filer is up to date, or when the filing window of the quarter is closed (unless --force or a filer is new)."""
    waiting = [name for cik, name in filers.items() if latest.get(str(cik), "") < due]
    new_filers = [name for cik, name in filers.items() if str(cik) not in latest]
    if not args.force and not new_filers and (not waiting or not in_window):
        reason = MSG_UP_TO_DATE.format(quarter=due) if not waiting else MSG_NO_NEW_QUARTER.format(quarter=due)
        return reason, waiting
    return None


def main() -> int:
    """Entry point of scripts/collect_holdings.py."""
    parser = market_arg(__doc__)
    parser.add_argument("--force", action="store_true", help="check the filers even if up to date")
    args = parser.parse_args()
    cfg = require_market(args)
    market = cfg[CFG_MARKET]
    user_agent = require_sec(cfg, COLLECTOR_HOLDINGS)
    if user_agent is None:
        return 0
    filers, cusips, quarters = configured(cfg)
    if not filers or not cusips:
        print(json.dumps({"collector": COLLECTOR_HOLDINGS, "market": market, "skipped": MSG_NO_FILERS}))
        return 0

    accessions, latest = stored(market)
    quarter_end_day = quarter_end(utc_today())
    due = str(quarter_end_day)
    # 13F is due 45 days after quarter end: poll only inside that window (plus a few days' slack)
    in_window = (utc_today() - quarter_end_day).days <= FILING_WINDOW_DAYS
    skipped = skip_reason(args, filers, latest, due, in_window)
    if skipped:
        print(json.dumps({"collector": COLLECTOR_HOLDINGS, "market": market, "skipped": skipped[0],
                          "not_filed": skipped[1]}))
        return 0

    edgar = Edgar(user_agent)
    run = HoldingsRun(edgar, accessions, cusips, quarters, utc_now())
    for cik, name in filers.items():
        run.load_filer(cik, name)

    written = append_jsonl(day_file(market, KIND_HOLDINGS, utc_today()), run.rows)
    _, latest = stored(market)
    print(json.dumps({
        "collector": COLLECTOR_HOLDINGS, "market": market, "quarter_due": due, "filings_loaded": run.loaded,
        "reported_by_other_manager": run.notices, "new_rows": written, "requests": edgar.requests,
        "sec_times": time_summary(edgar), "warnings": time_warnings(edgar),
        "waiting_on": [n for c, n in filers.items() if latest.get(str(c), "") < due], "failed": run.failed},
        indent=2))
    return 0
