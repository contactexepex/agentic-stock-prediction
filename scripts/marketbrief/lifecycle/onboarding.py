"""The onboarding pipeline of an add (F8.3; deterministic, no AI): resolve and check the identifiers, set the sector,
backfill prices, news, filings and announcements, run the candidate's collect gate. The add event is appended only by
commands.submit, after this pipeline passed; the event's `onboarding` JSON holds every check's result.

India: the NSE symbol must be in NSE's equity list (common stocks; ETFs are not in it) and not flagged an ETF by NSE's
quote; a symbol missing there that Yahoo serves as <SYM>.BO is refused as BSE-only, otherwise as unknown. US: the
ticker must be in SEC's ticker/exchange file on NYSE or Nasdaq (CIK and name from there). Both: Yahoo must serve daily
bars and must not call the instrument an ETF (or anything but an equity)."""
from __future__ import annotations

import re

from marketbrief.lifecycle import backfill
from marketbrief.lifecycle import constants as text
from marketbrief.lifecycle.constants import (
    CHECK_BACKFILL_ANNOUNCEMENTS,
    CHECK_BACKFILL_FILINGS,
    CHECK_BACKFILL_NEWS,
    CHECK_BACKFILL_PRICES,
    CHECK_COLLECT_GATE,
    CHECK_EXCHANGE,
    CHECK_IDENTIFIERS,
    CHECK_LONG_HISTORY,
    CHECK_NOT_ETF,
    CHECK_SECTOR,
    FAILED,
    OK,
    SKIPPED,
)
from marketbrief.lifecycle.gate import candidate_gate
from marketbrief.lifecycle.store import load_lifecycle_config

EQUITY = "EQUITY"
ETF_TYPES = ("ETF", "MUTUALFUND")


class Refusal(Exception):  # noqa: N818 (a refusal is an expected outcome, not an error)
    """An add the pipeline refuses: a refusal code and plain-language errors."""

    def __init__(self, code: str, errors: list[str]):
        """Keep the code and errors."""
        super().__init__("; ".join(errors))
        self.code, self.errors = code, errors


class SourceUnavailable(Exception):  # noqa: N818 (an expected outcome: the command is retried by the next import)
    """A source did not answer (or answered nothing for a symbol another source confirmed): nothing is decided."""


def yahoo_checks(sources, yahoo: str, symbol: str) -> dict:
    """Yahoo's metadata of a symbol the exchange's own list (NSE) or SEC confirmed; refuses ETFs. Yahoo serving
    nothing for a confirmed symbol is a source that did not answer (blocked, rate-limited), not an unknown symbol."""
    meta = sources.yahoo_meta(yahoo)
    if not meta:
        raise SourceUnavailable(f"Yahoo served no daily bars for {yahoo}, which {symbol}'s listing confirms")
    kind = (meta.get("instrument_type") or "").upper()
    if kind in ETF_TYPES:
        raise Refusal(text.REFUSE_ETF, [f"{symbol} is an ETF or fund ({kind}); only common stocks can be added"])
    if kind and kind != EQUITY:
        raise Refusal(text.REFUSE_UNKNOWN, [f"{symbol} is a {kind} on Yahoo, not a common stock"])
    return meta


def profile(sources, yahoo: str) -> list[str]:
    """Yahoo's industry and sector strings, empty when Yahoo does not answer."""
    try:
        return list(sources.yahoo_profile(yahoo))
    except Exception:  # a second sector source only
        return []


def resolve_india(symbol: str, sources) -> tuple[dict, dict, list[str]]:
    """(identity, yahoo meta, industry strings) of an NSE common stock."""
    equity = sources.nse_equity(symbol)
    if not equity:
        bse = sources.yahoo_meta(f"{symbol}.BO")
        if bse and (bse.get("instrument_type") or "").upper() in ETF_TYPES:
            raise Refusal(text.REFUSE_ETF, [f"{symbol} is an ETF or fund; only NSE common stocks can be added"])
        if bse:
            raise Refusal(text.REFUSE_BSE_ONLY, [f"{symbol} is not listed on NSE (BSE only); only NSE stocks"])
        raise Refusal(text.REFUSE_UNKNOWN, [f"{symbol} is not an NSE equity symbol"])
    try:
        industry = sources.nse_industry(symbol)
    except Exception as exc:  # NSE's API refuses some networks (cloud egress): Yahoo's type and profile still check
        industry = {"strings": [], "etf": False, "error": str(exc)[:200]}
    if industry.get("etf"):
        raise Refusal(text.REFUSE_ETF, [f"{symbol} is an ETF on NSE; only common stocks can be added"])
    yahoo = f"{symbol}.NS"
    meta = yahoo_checks(sources, yahoo, symbol)
    identity = {"name": equity.get("name") or symbol, "exchange": "NSE", "yahoo": yahoo, "nse_symbol": symbol,
                "cik": None}
    return identity, meta, list(industry.get("strings") or []) + profile(sources, yahoo)


def resolve_us(symbol: str, sources, exchanges: dict) -> tuple[dict, dict, list[str]]:
    """(identity, yahoo meta, industry strings) of a NYSE or Nasdaq common stock."""
    yahoo = symbol.replace(".", "-")
    found = sources.sec_company(symbol)
    if not found:
        meta = sources.yahoo_meta(yahoo)
        if meta and (meta.get("instrument_type") or "").upper() in ETF_TYPES:
            raise Refusal(text.REFUSE_ETF, [f"{symbol} is an ETF or fund; only common stocks can be added"])
        raise Refusal(text.REFUSE_UNKNOWN, [f"{symbol} is not a ticker in SEC's company list"])
    exchange = exchanges.get(found.get("exchange"))
    if not exchange:
        raise Refusal(text.REFUSE_VALIDATION,
                      [f"{symbol} trades on {found.get('exchange') or 'no exchange'}; only NYSE and Nasdaq stocks"])
    meta = yahoo_checks(sources, yahoo, symbol)
    identity = {"name": found["name"], "exchange": exchange, "yahoo": yahoo, "nse_symbol": None,
                "cik": f"{int(found['cik']):010d}"}
    return identity, meta, list(sources.sec_industry(int(found["cik"]))) + profile(sources, yahoo)


def pick_sector(market: str, given: str | None, hints: list[str], lifecycle_cfg: dict) -> str:
    """The owner's sector, else the first rule matching a source's industry string."""
    if given and given.strip():
        return given.strip()
    for rule in (lifecycle_cfg.get("sector_rules") or {}).get(market, []):
        if any(re.search(rule["pattern"], hint, re.I) for hint in hints):
            return rule["sector"]
    raise Refusal(text.REFUSE_VALIDATION,
                  [f"no sector rule matches the industry {hints or 'information (none found)'}; pass --sector"])


def resolve(market: str, symbol: str, sources, sector: str | None = None, name: str | None = None) -> dict:
    """The candidate company (identity, sector, Yahoo history) or a Refusal."""
    lifecycle_cfg = load_lifecycle_config()
    if market == "india":
        identity, meta, hints = resolve_india(symbol, sources)
    else:
        identity, meta, hints = resolve_us(symbol, sources, (lifecycle_cfg.get("exchanges") or {}).get(market, {}))
    company = {"market": market, "ticker": symbol, **identity, "sector": pick_sector(market, sector, hints,
                                                                                     lifecycle_cfg)}
    if name:
        company["name"] = name
    return {"company": company, "yahoo": meta, "industry": hints}


def run_backfill(company: dict, sources, full_cfg: dict, lifecycle_cfg: dict) -> tuple[dict, dict]:
    """(checks, details) of the backfill and the gate."""
    checks, details = {}, {}
    with backfill.candidate_mode(company) as cand_cfg:
        try:   # a yfinance error (rate limit, network) leaves the command undecided: failed, retried later
            checks[CHECK_BACKFILL_PRICES], details["prices"] = backfill.backfill_prices(cand_cfg, sources.yfinance())
            checks[CHECK_LONG_HISTORY], details["long_history"] = backfill.backfill_long_history(
                cand_cfg, sources.yfinance(), int(lifecycle_cfg["backfill"]["long_history_years"]))
        except Exception as exc:
            raise SourceUnavailable(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        steps = {CHECK_BACKFILL_NEWS: ("news", lambda: backfill.backfill_news(
            backfill.with_candidate(full_cfg, company), company["ticker"]))}
        if company["market"] == "us":
            steps[CHECK_BACKFILL_FILINGS] = ("filings", lambda: backfill.backfill_filings(cand_cfg, company,
                                                                                         sources.edgar()))
        else:
            steps[CHECK_BACKFILL_ANNOUNCEMENTS] = ("announcements", lambda: backfill.backfill_announcements(
                cand_cfg, sources.nse(), int(lifecycle_cfg["backfill"]["announcement_days"])))
        for check, (label, step) in steps.items():
            if getattr(sources, "offline", False):
                checks[check], details[label] = SKIPPED, {"reason": "offline fixture sources (no news, filings or "
                                                          "announcement source)"}
                continue
            try:
                checks[check], details[label] = step()
            except Exception as exc:  # a source failure is recorded; the gate decides
                checks[check], details[label] = FAILED, {"error": str(exc)[:300]}
        gate = candidate_gate(cand_cfg, int(lifecycle_cfg["backfill"]["min_bars"]))
    checks[CHECK_COLLECT_GATE], details["collect_gate"] = (OK if gate["ok"] else FAILED), gate
    return checks, details


def failed_result(what: str, exc: BaseException) -> dict:
    """The result of an onboarding a source left undecided (logged `failed`, retried by the next import)."""
    return {"ok": False, "refusal_code": None, "failed": True,
            "errors": [f"{what}: {type(exc).__name__}: {str(exc)[:200]}"]}


def onboard(market: str, symbol: str, sources, full_cfg: dict, sector: str | None = None,  # noqa: PLR0913
            name: str | None = None, skip_backfill: bool = False) -> dict:
    """The whole pipeline: {"ok", "company", "onboarding", "details"} or {"ok": False, "refusal_code", "errors"}."""
    lifecycle_cfg = load_lifecycle_config()
    try:
        resolved = resolve(market, symbol, sources, sector, name)
    except Refusal as refusal:
        return {"ok": False, "refusal_code": refusal.code, "errors": refusal.errors}
    except Exception as exc:  # a source that did not answer: nothing is decided, the command can be retried
        return failed_result("identifier sources did not answer", exc)
    company, yahoo = resolved["company"], resolved["yahoo"]
    checks = {CHECK_IDENTIFIERS: OK, CHECK_NOT_ETF: OK, CHECK_EXCHANGE: OK, CHECK_SECTOR: OK}
    details = {"yahoo": yahoo, "industry": resolved["industry"]}
    if skip_backfill:
        checks.update({CHECK_BACKFILL_PRICES: SKIPPED, CHECK_LONG_HISTORY: SKIPPED, CHECK_COLLECT_GATE: SKIPPED})
    else:
        try:
            backfill_checks, backfill_details = run_backfill(company, sources, full_cfg, lifecycle_cfg)
        except SourceUnavailable as exc:   # Yahoo failed during the price backfill: retried by the next import
            return failed_result("the price backfill's source did not answer", exc)
        checks.update(backfill_checks)
        details.update(backfill_details)
        if checks[CHECK_COLLECT_GATE] != OK:
            return {"ok": False, "refusal_code": text.REFUSE_VALIDATION, "company": company, "onboarding": checks,
                    "details": details, "errors": [f"collect gate failed: {details['collect_gate']['failures']}"]}
    return {"ok": True, "company": company, "onboarding": checks, "details": details}
