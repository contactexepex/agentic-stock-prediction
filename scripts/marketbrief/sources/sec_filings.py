"""SEC EDGAR helpers for the SEC collectors (filings, events, insiders, stakes, holdings,
fundamentals). Free endpoints only. SEC requires a descriptive
User-Agent with contact info (SEC_USER_AGENT="your-name your@email.com") and at most 10 requests/second;
every request goes through one throttle (the Edgar client in marketbrief/sources/sec_client.py, interval
SEC_MIN_INTERVAL_SECONDS) and backs off on 429/5xx. The throttle is per
process, so the SEC collectors must run one after another, never in parallel.

A ticker's filings can sit under more than one CIK: SEC's ticker map names the current
registrant, while an earlier (or related) registrant may still file (XOM: the holding company
2115436 since 2026-07-01, while Exxon Mobil Corp 34088 still lists filings and holds the
earlier history). `related_ciks`
reads those CIKs from the market config (`fundamentals.predecessor_ciks`) and `ticker_submissions`
fetches and merges the submission lists of all of a ticker's CIKs; every per-ticker collector
uses it (collect_holdings follows 13F filers, not tickers).

Acceptance times. The submissions JSON's `acceptanceDateTime` (labelled UTC, "Z") is not always
true: since 2026-10-05 some CIKs' submission files are served with every acceptance time shifted
later by the New York UTC offset of that moment (+4h in EDT, +5h in EST; the ET wall-clock time
converted to UTC twice), while other CIKs' files are right (by 2026-10-06 the shifted files were
exactly those regenerated after a new filing on 2026-10-05). The shift is uniform over a whole
file, so `Edgar.recent` checks each file against the authoritative time, the SGML header
`<ACCEPTANCE-DATETIME>` (YYYYMMDDHHMMSS, US Eastern; `<acc>.hdr.sgml`, the same time as the index
page's "Accepted") of its newest and its oldest listed filing. Both right: the column is kept
("ok"). Both shifted: every value is corrected ("shifted": true = JSON minus the ET offset; the
JSON value is kept in `acceptanceDateTimeJson`). Anything else (a header that cannot be read, a
difference that is not that offset, or a mixed file with one right and one shifted) keeps the
column as served and says so ("unverified: ..."): never unshift a value that may be right, which
would make it 4-5h too early (look-ahead). Statuses are in `Edgar.time_checks` (CIK -> status);
`time_summary` goes into the collectors' summaries as `sec_times`, and `time_warnings` puts each
unverified CIK into their `warnings` (the routine lists them in data_quality). Header times are
immutable, so they are cached per accession in work/sec_acceptance.json (under MB_ROOT): a second
collector in the same run, or a later run whose newest filing is unchanged, costs no extra
request. Stored rows (including those stored from an unverified file) are corrected on read
through `sec_times`: scripts/check_sec_times.py, run by the routine after the SEC collectors,
appends each new accession's header time, and core.database.connect applies them.

Tests run offline: with MB_SEC_FIXTURES=<dir>, URLs are served from <dir>/urls.json
({url: file path, absolute or relative to <dir>}) instead of the network (a header missing from
the fixtures leaves the file "unverified" without counting a request; the disk cache is not used)."""

from __future__ import annotations

import json
import os
from datetime import date

from marketbrief.constants.config_keys import (
    CFG_FILINGS,
    CFG_FUNDAMENTALS,
    CFG_MARKET,
    CFG_PREDECESSOR_CIKS,
    CFG_TICKERS,
    FILINGS_SOURCE_SEC,
)
from marketbrief.constants.environment import ENV_SEC_USER_AGENT
from marketbrief.constants.messages import MSG_SEC_NOT_APPLICABLE, MSG_SEC_USER_AGENT_MISSING
from marketbrief.constants.statuses import SUMMARY_COLLECTOR, SUMMARY_ERROR, SUMMARY_MARKET, SUMMARY_SKIPPED
from marketbrief.sources.sec_client import Edgar


def related_ciks(cfg: dict) -> dict[str, list[int]]:
    """Ticker -> CIKs of earlier or related registrants whose filings also belong to the ticker
    (`fundamentals.predecessor_ciks` in config/markets/<market>.yaml: the one list every SEC
    collector reads)."""
    found = (cfg.get(CFG_FUNDAMENTALS) or {}).get(CFG_PREDECESSOR_CIKS) or {}
    return {
        str(ticker).upper(): [int(c) for c in (cs if isinstance(cs, list) else [cs])] for ticker, cs in found.items()
    }


def merge_recent(parts: list[tuple[int | str, dict]]) -> dict:
    """Merge the `filings.recent` blocks of several CIKs (the mapped CIK first) into one, column
    by column, with an added `cik` column (the CIK whose submission list holds the filing, i.e.
    the archive folder it is served from). A filing listed under several CIKs (a joint filing) is
    kept once, under the first CIK that lists it. One CIK: its block unchanged plus the `cik`
    column. Several: newest first (by filing date, then acceptance time); a column missing from
    one CIK's block is None for its filings."""
    if len(parts) == 1:
        cik, rec = parts[0]
        return {**rec, "cik": [cik] * len(rec["form"])}
    cols = [c for c in dict.fromkeys(k for _, rec in parts for k in rec) if c not in ("name", "cik")]
    rows, seen = [], set()
    for cik, rec in parts:
        n = len(rec["form"])
        accs = rec.get("accessionNumber") or [None] * n
        for i in range(n):
            if accs[i] is not None:
                if accs[i] in seen:
                    continue
                seen.add(accs[i])
            row = {c: (rec[c][i] if isinstance(rec.get(c), list) else None) for c in cols}
            row["cik"] = cik
            rows.append(row)
    rows.sort(key=lambda r: (r.get("filingDate") or "", r.get("acceptanceDateTime") or ""), reverse=True)
    out = {c: [r[c] for r in rows] for c in [*cols, "cik"]}
    out["name"] = parts[0][1].get("name")
    return out


def ticker_submissions(
    edgar: Edgar, ticker: str, cik, related: dict[str, list[int]] | None = None
) -> tuple[dict | None, list[dict]]:
    """The submissions (`filings.recent`) of a ticker's mapped CIK plus its related CIKs (see
    related_ciks), merged and de-duplicated by accession number (merge_recent). One request per
    CIK, each through the Edgar throttle. Returns (merged block, failures): each CIK whose request
    fails is one failure {"ticker", "cik", "error"}, and the CIKs that answered are still merged;
    the block is None only when every CIK failed."""
    ciks = [cik, *[c for c in (related or {}).get(str(ticker).upper(), []) if int(c) != int(cik)]]
    parts, failed = [], []
    for c in ciks:
        try:
            parts.append((c, edgar.recent(c)))
        except Exception as exc:
            failed.append({"ticker": ticker, "cik": c, "error": str(exc)[:200]})
    return (merge_recent(parts) if parts else None), failed


def filings_of_forms(recent: dict, forms: set[str], since: date | None = None) -> list[dict]:
    """Filings of the given forms filed on/after `since`, in list order (newest first). `cik` is
    the CIK whose submission list holds the filing (merge_recent's column), else None."""
    n, out = len(recent["form"]), []
    accepted = recent.get("acceptanceDateTime") or [None] * n
    reported = recent.get("reportDate") or [None] * n
    ciks = recent.get("cik") or [None] * n
    for i, form in enumerate(recent["form"]):
        filed = recent["filingDate"][i]
        if form not in forms or (since and date.fromisoformat(filed) < since):
            continue
        out.append(
            {
                "accession": recent["accessionNumber"][i],
                "form": form,
                "filing_date": filed,
                "accepted_at": accepted[i] or None,
                "primary_doc": recent["primaryDocument"][i],
                "report_date": reported[i] or None,
                "cik": ciks[i],
            }
        )
    return out


def require_sec(cfg: dict, collector: str) -> str | None:
    """User-Agent for SEC markets; prints a JSON summary and returns None when not applicable."""
    if cfg.get(CFG_FILINGS) != FILINGS_SOURCE_SEC:
        print(
            json.dumps(
                {SUMMARY_COLLECTOR: collector, SUMMARY_MARKET: cfg[CFG_MARKET], SUMMARY_SKIPPED: MSG_SEC_NOT_APPLICABLE}
            )
        )
        return None
    user_agent = os.environ.get(ENV_SEC_USER_AGENT)
    if not user_agent:
        print(
            json.dumps(
                {
                    SUMMARY_COLLECTOR: collector,
                    SUMMARY_MARKET: cfg[CFG_MARKET],
                    SUMMARY_ERROR: MSG_SEC_USER_AGENT_MISSING,
                }
            )
        )
        raise SystemExit(1)
    return user_agent


def watch_ciks(cfg: dict, edgar: Edgar) -> tuple[dict[str, int], list[str]]:
    """Watchlist ticker -> CIK (via SEC's ticker map); tickers not registered with the SEC are skipped."""
    cmap = edgar.cik_map()
    found, skipped = {}, []
    for ticker, meta in cfg[CFG_TICKERS].items():
        cik = cmap.get(str(meta.get("sec_ticker", ticker)).upper())
        if cik is None:
            skipped.append(ticker)
        else:
            found[ticker] = cik
    return found, skipped
