"""Shared HTTP access and storage for the free-source collectors (issue #9): collect_macro.py
(US Treasury yields, FRED series, Cboe put/call ratios), collect_shorts.py (FINRA short-sale
volume and short interest) and collect_flows_india.py (NSDL FPI flows, NSE index closes).

One polite client per run: an identifying User-Agent, a pause between requests, up to two
retries on a transient network error and none on an HTTP error. Errors are classified so a summary can say
what happened: an HTTP status from the site, the egress proxy refusing the host (the host to
allowlist), or the site closing the connection without an answer (a site-side refusal; the
proxy accepted the connection). After a host refuses or drops a connection, later calls to the
same host in that run fail at once instead of waiting for the same answer again.

Tests pass a fake client with the same `get` method, so nothing here touches the network."""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from common import append_jsonl, data_dir, day_file

UA = "Mozilla/5.0 (compatible; market-brief/1.0; personal research, low volume)"


class FetchError(Exception):
    """A failed request. status: the HTTP status, or None when there was no HTTP answer;
    host: set when the egress proxy refused the host (it must be allowlisted)."""

    def __init__(self, url: str, error: str, status: int | None = None, host: str | None = None):
        super().__init__(error)
        self.url, self.error, self.status, self.host = url, error, status, host

    def entry(self, source: str, **extra) -> dict:
        e = {"source": source, "url": self.url, "error": self.error[:200], **extra}
        if self.status is not None:
            e["status"] = self.status
        if self.host:
            e["allowlist"] = self.host
        return e


class Client:
    def __init__(self, pause: float = 1.0, user_agent: str = UA, timeout: float = 45, attempts: int = 3,
                 backoff: float = 3.0):
        # 3 attempts: fred.stlouisfed.org sometimes closes a connection without answering and
        # serves the same URL on the next try (seen 2026-10-05)
        self.pause, self.ua, self.timeout, self.attempts, self.backoff = pause, user_agent, timeout, attempts, backoff
        self.requests = 0
        self.dead: dict[str, str] = {}   # host -> why later calls to it are skipped this run

    def get(self, url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
        host = urllib.parse.urlsplit(url).hostname or ""
        if host in self.dead:
            raise FetchError(url, f"not requested: {host} {self.dead[host]} earlier in this run")
        hdrs = {"User-Agent": self.ua, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", **(headers or {})}
        for attempt in range(1, self.attempts + 1):
            self.requests += 1
            try:
                req = urllib.request.Request(url, data=data, headers=hdrs)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                raise FetchError(url, f"HTTP {exc.code} from {host}", status=exc.code) from exc
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                reason = str(getattr(exc, "reason", exc))
                if "Tunnel connection failed" in reason:
                    self.dead[host] = "was refused by the egress proxy"
                    raise FetchError(url, f"egress proxy denied {host}: {reason}", host=host) from exc
                closed = any(s in repr(exc) for s in ("RemoteDisconnected", "closed connection", "Connection reset",
                                                      "EOF occurred", "UNEXPECTED_EOF"))
                if attempt == self.attempts:
                    if closed:
                        self.dead[host] = "closed the connection without an answer"
                        raise FetchError(url, f"{host} closed the connection without an HTTP answer "
                                              f"{attempt} times (site-side refusal; the proxy connected): "
                                              f"{reason}") from exc
                    raise FetchError(url, f"{host} unreachable after {attempt} attempts: {reason}") from exc
                time.sleep(self.backoff)
            finally:
                time.sleep(self.pause)
        raise AssertionError("unreachable")

    def json(self, url: str, **kw):
        body = self.get(url, **kw)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(url, f"not JSON: {body[:80]!r}") from exc


def not_published(exc: FetchError) -> bool:
    """Per-day files on S3/CDN buckets answer 403 or 404 for a day that has no file (yet)."""
    return exc.status in (403, 404)


def recent_sessions(cfg: dict, today: date, lookback_days: int) -> list[date]:
    """The market's sessions in the last `lookback_days` calendar days up to today, oldest first."""
    import events as ev
    days = [today - timedelta(days=n) for n in range(lookback_days, -1, -1)]
    return [d for d in days if ev.is_session(cfg, d)]


def stale_cutoff(cfg: dict, today: date) -> date:
    """A per-day file missing for a session before this date is a failure, not a publishing lag:
    the latest completed session (before today) may still be in the publisher's queue."""
    import events as ev
    return ev.prev_session(cfg, today, include=False)


def stored_rows(market: str, kind: str, files: int = 400) -> dict[str, dict]:
    """Latest stored row per id across the newest `files` daily files of a kind."""
    out: dict[str, dict] = {}
    for f in sorted((data_dir(market) / kind).glob("**/*.jsonl"))[-files:]:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["id"]] = row
    return out


def store_changed(market: str, kind: str, rows: list[dict], today: date, value_cols: list[str]) -> int:
    """Append rows whose id is new, or whose values differ from the latest stored row with that id
    (a revision is a new record, never an edit). Duplicates within `rows` keep the last one."""
    stored = stored_rows(market, kind)
    fresh: dict[str, dict] = {}
    for r in rows:
        old = stored.get(r["id"])
        if old is None or any(old.get(c) != r.get(c) for c in value_cols):
            fresh[r["id"]] = r
    return append_jsonl(day_file(market, kind, today), fresh.values()) if fresh else 0


def num(x) -> float | None:
    """'1,234.5' -> 1234.5; '(12.5)' -> -12.5 (accounting negative); '.', '-', '' -> None."""
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x).replace(",", "").replace("Rs.", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def summary(collector: str, market: str, new: dict, failed: list, notes: list, warnings: list,
            client) -> dict:
    out = {"collector": collector, "market": market, "new": new, "failed": failed, "warnings": warnings,
           "notes": notes, "requests": getattr(client, "requests", None)}
    hosts = sorted({f["allowlist"] for f in failed if f.get("allowlist")})
    if hosts:
        out["allowlist_needed"] = hosts
    return out
