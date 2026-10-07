"""Where onboarding checks a company's identifiers: SEC (US: CIK, name, exchange, SIC description), NSE (India:
the equity list and the quote's industry info) and Yahoo (instrument type, exchange, history). Free sources on the
HTTPS allowlist only; the SEC client sends SEC_USER_AGENT (else a generic research user agent), never an email typed
here. FixtureSources answers the same questions from a JSON file (MB_LIFECYCLE_FIXTURES) for offline tests."""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from marketbrief.constants.environment import ENV_SEC_USER_AGENT
from marketbrief.constants.sources import FREE_SOURCE_USER_AGENT

ENV_FIXTURES = "MB_LIFECYCLE_FIXTURES"
SEC_EXCHANGE_MAP_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
NSE_EQUITY_LIST = "/content/equities/EQUITY_L.csv"
NSE_QUOTE_ENDPOINT = "quote-equity"
SECONDS_PER_YEAR = 365.25 * 86400


class LiveSources:
    """The live answers (network)."""

    offline = False

    def __init__(self, cfg: dict):
        """Clients are made on first use."""
        self.cfg, self._edgar, self._nse, self._sec_map, self._nse_list = cfg, None, None, None, None

    def edgar(self):
        """The SEC client."""
        if self._edgar is None:
            from marketbrief.sources.sec_client import Edgar
            self._edgar = Edgar(os.environ.get(ENV_SEC_USER_AGENT) or FREE_SOURCE_USER_AGENT)
        return self._edgar

    def nse(self):
        """The NSE client of the market config."""
        if self._nse is None:
            from marketbrief.collectors.nse_session import nse_client
            self._nse = nse_client(self.cfg)
        return self._nse

    def sec_company(self, ticker: str) -> dict | None:
        """{cik, name, exchange} from SEC's ticker/exchange file, or None."""
        if self._sec_map is None:
            data = self.edgar().json(SEC_EXCHANGE_MAP_URL)
            fields = data["fields"]
            self._sec_map = {str(row[fields.index("ticker")]).upper(): dict(zip(fields, row)) for row in data["data"]}
        found = self._sec_map.get(ticker.upper())
        return {"cik": int(found["cik"]), "name": found["name"], "exchange": found["exchange"]} if found else None

    def sec_industry(self, cik: int) -> list[str]:
        """SEC's SIC description of the company (one string, or none)."""
        description = self.edgar().json(SEC_SUBMISSIONS.format(cik=int(cik))).get("sicDescription")
        return [description] if description else []

    def nse_equity(self, symbol: str) -> dict | None:
        """{name, series, isin} from NSE's equity list (common stocks; ETFs are not in it), or None."""
        if self._nse_list is None:
            reader = csv.DictReader(io.StringIO(self.nse().text(NSE_EQUITY_LIST)))
            self._nse_list = {row["SYMBOL"].strip().upper(): {key.strip(): (value or "").strip()
                                                              for key, value in row.items() if key}
                              for row in reader}
        found = self._nse_list.get(symbol.upper())
        if not found:
            return None
        return {"name": found.get("NAME OF COMPANY"), "series": found.get("SERIES"), "isin": found.get("ISIN NUMBER")}

    def nse_industry(self, symbol: str) -> dict:
        """{strings: NSE's industry info (basic industry, industry, sector, macro), etf: bool}."""
        quote = self.nse().json(NSE_QUOTE_ENDPOINT, {"symbol": symbol})
        info = quote.get("industryInfo") or {}
        strings = [info.get(key) for key in ("basicIndustry", "industry", "sector", "macro") if info.get(key)]
        return {"strings": strings, "etf": bool((quote.get("info") or {}).get("isETFSec"))}

    def yahoo_meta(self, symbol: str) -> dict | None:
        """{instrument_type, exchange, currency, years}: Yahoo's history metadata and how many years of daily bars
        it serves (None when it serves nothing)."""
        import yfinance

        ticker = yfinance.Ticker(symbol)
        frame = ticker.history(period="max", interval="1d", auto_adjust=False)
        if frame is None or frame.empty:
            return None
        meta = getattr(ticker, "history_metadata", None) or {}
        first = frame.index[0].to_pydatetime().astimezone(timezone.utc)
        years = (datetime.now(timezone.utc) - first).total_seconds() / SECONDS_PER_YEAR
        return {"instrument_type": meta.get("instrumentType"), "exchange": meta.get("exchangeName"),
                "currency": meta.get("currency"), "years": round(years, 1), "first_bar": first.date().isoformat()}

    def yahoo_profile(self, symbol: str) -> list[str]:
        """Yahoo's sector and industry of the company (a second sector source; empty when Yahoo has none)."""
        import yfinance

        info = yfinance.Ticker(symbol).info or {}
        return [info[key] for key in ("industry", "sector") if info.get(key)]

    def yfinance(self):
        """The yfinance module (the price backfill)."""
        import yfinance

        return yfinance


class FixtureSources:
    """The same answers from a JSON file: {"sec": {TICKER: {...}}, "sec_industry": {CIK: [...]}, "nse": {SYM: {...}},
    "nse_industry": {SYM: {...}}, "yahoo": {SYMBOL: {...}}, "bars": {SYMBOL: [[date, o, h, l, c, v], ...]}}.
    Offline: news, filings and announcements are not backfilled."""

    offline = True

    def __init__(self, path: Path):
        """Read the fixture file."""
        self.data = json.loads(Path(path).read_text())

    def sec_company(self, ticker: str) -> dict | None:
        """See LiveSources."""
        return self.data.get("sec", {}).get(ticker.upper())

    def sec_industry(self, cik: int) -> list[str]:
        """See LiveSources."""
        return self.data.get("sec_industry", {}).get(str(int(cik)), [])

    def nse_equity(self, symbol: str) -> dict | None:
        """See LiveSources."""
        return self.data.get("nse", {}).get(symbol.upper())

    def nse_industry(self, symbol: str) -> dict:
        """See LiveSources."""
        return self.data.get("nse_industry", {}).get(symbol.upper(), {"strings": [], "etf": False})

    def yahoo_meta(self, symbol: str) -> dict | None:
        """See LiveSources."""
        return self.data.get("yahoo", {}).get(symbol)

    def yahoo_profile(self, symbol: str) -> list[str]:
        """See LiveSources."""
        return self.data.get("yahoo_profile", {}).get(symbol, [])

    def yfinance(self):
        """A stand-in for the yfinance module that serves the fixture bars."""
        from marketbrief.lifecycle.fixture_prices import FixtureYfinance

        return FixtureYfinance(self.data.get("bars", {}))


def sources_for(cfg: dict):
    """FixtureSources when MB_LIFECYCLE_FIXTURES is set, else LiveSources."""
    fixtures = os.environ.get(ENV_FIXTURES)
    return FixtureSources(Path(fixtures)) if fixtures else LiveSources(cfg)
