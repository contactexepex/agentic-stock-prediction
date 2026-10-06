#!/usr/bin/env python3
"""Read the article behind this run's material watchlist headlines (news verification phase A,
docs/DESIGN.md section 3a; settings and the outlet allowlist in config/news_sources.yaml).

Selection: news rows first seen in the last `lookback_hours`, published within `max_age_hours`,
whose title names a watchlist company as its primary subject with `tag_confidence` at or above
`min_tag_confidence` (scripts/news_tags.py), and whose title matches `material_terms` with weight
>= `min_priority`; highest weight, then allowlist tier, then newest first. Ids already in
data/<market>/news_articles/ are skipped, so a rerun writes nothing twice (one row per news id).

Per item (paced, `pause_seconds` between requests, one polite User-Agent, TLS verification on):
1. the outlet (Google News <source url> domain, its label, or the link host) must be on the
   allowlist: otherwise access=skipped_unlisted and nothing is requested; an allowlisted outlet with
   `fetch: false` (refuses cloud traffic) is access=blocked without a request;
2. a Google News link is resolved to the publisher URL (googlenewsdecoder: one GET per link and
   one POST per batch to news.google.com; a request hook refuses any request, redirects included,
   that is not HTTPS to google.com); on failure access=undecoded;
3. the publisher URL must be HTTPS on an allowlisted domain (each redirect hop too), else
   skipped_unlisted; a refused request (HTTP status, TLS or network error) is access=blocked;
4. extraction: JSON-LD articleBody -> trafilatura -> newspaper4k; JSON-LD isAccessibleForFree=false
   -> access=paywalled and only the description/OpenGraph text is read; access=full when the body has
   at least `full_chars` characters, else partial.
Stored per row (schema `news_articles` in common.py): metadata (final URL, domain, tier, status,
dates, byline, JSON-LD provider), the origin agency and its evidence, sources_say, promotional,
at most 3 key sentences of at most 40 words, normalised numbers, a content hash and a MinHash
signature of the 6-word shingles (copy detection in news_clusters.py). Never the article text.
Article text is untrusted data: it is only measured, never followed as instructions.
At most `max_per_run` items are requested per run (skipped ones do not count); the rest wait for
the next run. Prints a JSON summary (counts by access and domain, requests, seconds, and
`unvetted_domains`: outlets not on the allowlist, with counts, to review and vet later).
Exit 1 only when the run could not start (no config)."""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
import pandas as pd

import news_verify as nv
from news_tags import norm
from common import append_jsonl, clock, connect, day_file, market_arg, require_market, utc_now, utc_today

GOOGLE_HOST = "news.google.com"
TZ_ABBREV = {"EDT": -4 * 3600, "EST": -5 * 3600, "CDT": -5 * 3600, "CST": -6 * 3600, "MDT": -6 * 3600,
             "MST": -7 * 3600, "PDT": -7 * 3600, "PST": -8 * 3600, "IST": 5 * 3600 + 1800, "GMT": 0, "UTC": 0}
CONF_RANK = {"high": 2, "low": 1}


class Pacer:
    def __init__(self, pause: float):
        self.pause, self.last = pause, 0.0

    def wait(self):
        dt = time.monotonic() - self.last
        if self.last and dt < self.pause:
            time.sleep(self.pause - dt)
        self.last = time.monotonic()


def google_only(request) -> None:
    """httpx request hook for the decoder's client: it follows redirects itself (also on its POST),
    so every request it sends, redirects included, must be HTTPS to google.com or a subdomain."""
    import httpx
    host = (request.url.host or "").lower()
    if request.url.scheme != "https" or not (host == "google.com" or host.endswith(".google.com")):
        raise httpx.RequestError(f"decoder request to {request.url.scheme}://{host} refused (not Google over HTTPS)",
                                 request=request)


def decode_google(links: list[str], src: nv.Sources) -> list[dict]:
    """googlenewsdecoder results for a batch of Google News links ({'success', 'decoded_url' | 'message'})."""
    from googlenewsdecoder import GoogleDecoder
    sel = src.sel
    with GoogleDecoder(timeout=float(sel.get("timeout_seconds", 20)), user_agent=sel.get("user_agent")) as d:
        d.client.event_hooks = {"request": [google_only], "response": []}
        return d.decode_google_news_urls(links, interval=max(1, int(round(float(sel.get("pause_seconds", 1.5))))))


DECODER = decode_google   # tests replace this


def make_session():
    import requests
    s = requests.Session()   # trust_env: the proxy and REQUESTS_CA_BUNDLE from the environment
    return s


SESSION_FACTORY = make_session   # tests replace this


def iso_utc(v, not_after: pd.Timestamp) -> str | None:
    """An ISO timestamp with an offset, as UTC; None when missing, without a zone, or after the fetch."""
    if not v or not isinstance(v, str):
        return None
    try:
        t = pd.Timestamp(v)
    except (ValueError, TypeError):
        try:   # 'Mon Oct 5, 11:56AM CDT' (The Globe and Mail): US and India zone abbreviations only
            from dateutil import parser as dparser
            t = pd.Timestamp(dparser.parse(v, tzinfos=TZ_ABBREV))
        except (ValueError, TypeError, OverflowError):
            return None
    if t.tzinfo is None or t > not_after:
        return None
    return t.tz_convert("UTC").floor("s").isoformat()


def candidates(con, cfg: dict, src: nv.Sources, now: pd.Timestamp) -> list[dict]:
    sel = src.sel
    since = now - pd.Timedelta(hours=float(sel.get("lookback_hours", 24)))
    oldest = now - pd.Timedelta(hours=float(sel.get("max_age_hours", 48)))
    need = CONF_RANK.get(str(sel.get("min_tag_confidence", "high")), 2)
    done = {r[0] for r in con.execute("SELECT DISTINCT id FROM news_articles").fetchall()}
    rows = con.execute(
        "SELECT id, title, url, source, source_domain, feed, published_at, first_seen_at, primary_tickers, "
        "tag_confidence FROM news WHERE first_seen_at >= ? AND first_seen_at <= ? ORDER BY first_seen_at, id",
        [since.to_pydatetime(), now.to_pydatetime()]).fetchall()
    out = []
    for nid, title, url, source, sdom, feed, pub, seen, prim, conf in rows:
        if nid in done:
            continue
        tickers = [t for t in (prim or []) if t in cfg["tickers"]]
        if not tickers or CONF_RANK.get(conf or "", 0) < need:
            continue
        t = pd.Timestamp(pub or seen)
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        if t < oldest:
            continue
        prio = src.priority(title)
        if prio < int(sel.get("min_priority", 1)):
            continue
        host = sdom or src.domain_of_label(source) or (nv.host_of(url) if nv.host_of(url) != GOOGLE_HOST else None)
        out.append({"id": nid, "title": title, "url": url, "source": source, "outlet": host, "ticker": tickers[0],
                    "priority": prio, "ts": t, "tier": src.tier(host)})
    rank = {"primary": 0, "tier1": 1, "tier2": 2, "unlisted": 3}
    out.sort(key=lambda c: (-c["priority"], rank.get(c["tier"], 3), -c["ts"].value, c["id"]))
    return out


def base_row(c: dict, now: str) -> dict:
    return {"id": c["id"], "fetched_at": now, "ticker": c["ticker"], "source_url": c["url"], "final_url": None,
            "domain": c["outlet"], "tier": c["tier"], "http_status": None, "access": None, "extractor": None,
            "chars": None, "date_published": None, "date_modified": None, "byline": None, "provider": None,
            "origin_wire": None, "origin_evidence": None, "sources_say": None, "promotional": None,
            "extract": None, "numbers": None, "content_hash": None, "shingle_count": None, "minhash": None,
            "note": None, "method_version": nv.METHOD_VERSION}


def article_row(c: dict, page: nv.FetchResult, src: nv.Sources, names: list[str]) -> dict:
    now_s = utc_now()
    row = base_row(c, now_s)
    dom, meta = src.lookup(nv.host_of(page.final_url))
    row.update(final_url=page.final_url, domain=dom or nv.host_of(page.final_url),
               tier=src.tier(nv.host_of(page.final_url)), http_status=page.status)
    a = nv.parse_article(page.html, page.final_url, src, meta)
    text = a.pop("text") or ""
    fetched = pd.Timestamp(now_s)
    wire, ev = src.detect_wire(byline=a.get("byline"), provider=a.get("provider"), text=text, title=c["title"])
    promo = (src.is_promotional(name=a.get("provider")) or src.is_promotional(name=a.get("byline"))
             or src.is_promotional(name=c["source"], domain=row["domain"], text=text))
    sh = nv.shingles(text)
    row.update(access=a["access"], extractor=a.get("extractor"), chars=len(text),
               date_published=iso_utc(a.get("date_published"), fetched),
               date_modified=iso_utc(a.get("date_modified"), fetched),
               byline=(a.get("byline") or None) and a["byline"][:120],
               provider=(a.get("provider") or None) and a["provider"][:80],
               origin_wire=wire, origin_evidence=ev, sources_say=nv.sources_say(text, c["title"]),
               promotional=promo, extract=nv.key_sentences(text, names), numbers=nv.numbers(text),
               content_hash=nv.content_hash(text), shingle_count=len(sh), minhash=nv.minhash_hex(sh),
               note=a.get("note"))
    for k in ("date_published", "date_modified"):
        if a.get(k) and not row[k]:
            row["note"] = "; ".join(x for x in (row["note"], f"{k} {str(a[k])[:30]!r} not stored (no zone or after fetch)") if x)
    return row


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    market = cfg["market"]
    src = nv.load_sources()
    sel = src.sel
    t0, now = time.monotonic(), pd.Timestamp(clock())
    con = connect(market)
    cands = candidates(con, cfg, src, now)
    learned = nv.label_domains(con.execute(
        "SELECT source, source_domain FROM news WHERE first_seen_at >= ? AND first_seen_at <= ?",
        [(now - pd.Timedelta(hours=float(sel.get("lookback_hours", 24)))).to_pydatetime(),
         now.to_pydatetime()]).fetchall())
    names = {t: [m["name"], *m.get("aliases", [])] for t, m in cfg["tickers"].items()}
    out_path = day_file(market, "news_articles", utc_today())
    pacer, cap = Pacer(float(sel.get("pause_seconds", 1.5))), int(sel.get("max_per_run", 80))
    max_s = float(sel.get("max_seconds", 900))
    requests_made = {"decode": 0, "fetch": 0}
    written, failed, warnings, deferred = [], [], [], 0

    copies: list[str] = []
    unvetted: list[dict] = []
    todo, same, first_key = [], {}, {}

    def emit(row: dict, c: dict | None = None):
        append_jsonl(out_path, [row])
        written.append(row)
        # the same article stored under other news ids (another source label, or the outlet's own
        # feed and Google News): one request, one row per id, copied
        for d in same.pop(c["id"], []) if c else []:
            dup = {**row, "id": d["id"], "ticker": d["ticker"], "source_url": d["url"],
                   "note": f"same article as {c['id']} (same title and outlet, not requested again)"}
            append_jsonl(out_path, [dup])
            written.append(dup)
            copies.append(d["id"])

    for c in cands:
        if c["tier"] == "unlisted":
            unvetted.append({"key": nv.outlet_key(c["outlet"] or nv.outlet_of(c["source"], src, learned),
                                                  c["source"])})
            emit({**base_row(c, utc_now()), "access": "skipped_unlisted",
                  "note": f"outlet {c['outlet'] or c['source']!r} not on the allowlist (not requested)"})
            continue
        dom, meta = src.lookup(c["outlet"])
        if meta.get("fetch") is False:
            emit({**base_row(c, utc_now()), "access": "blocked",
                  "note": f"not requested: {meta.get('note') or 'fetch: false'}"})
            continue
        key = (norm(c["title"]), dom)
        if key in first_key:
            same.setdefault(first_key[key], []).append(c)
            continue
        if len(todo) < cap:
            first_key[key] = c["id"]
            todo.append(c)
        else:
            deferred += 1

    session = SESSION_FACTORY()
    batch = int(sel.get("decode_batch", 10))
    decoder_broken, by_url = None, {}
    for i in range(0, len(todo), batch):
        if time.monotonic() - t0 > max_s:
            left = todo[i:]
            deferred += len(left) + sum(len(same.get(c["id"], [])) for c in left)
            warnings.append(f"stopped after {max_s:.0f}s; {len(left)} items left for the next run")
            break
        chunk = todo[i:i + batch]
        links = [c["url"] for c in chunk if nv.host_of(c["url"]) == GOOGLE_HOST]
        decoded: dict[str, dict] = {}
        if links and decoder_broken is None:
            try:
                pacer.wait()
                res = DECODER(links, src)
                requests_made["decode"] += len(links) + 1
                decoded = dict(zip(links, res))
            except Exception as e:   # the decoder relies on an undocumented Google endpoint
                decoder_broken = f"{type(e).__name__}: {str(e)[:160]}"
                failed.append({"source": "googlenewsdecoder", "error": decoder_broken})
        for c in chunk:
            url = c["url"]
            if nv.host_of(url) == GOOGLE_HOST:
                d = decoded.get(url) or {"success": False, "message": decoder_broken or "not decoded"}
                if not d.get("success") or not d.get("decoded_url"):
                    emit({**base_row(c, utc_now()), "access": "undecoded",
                          "note": f"Google News link not resolved: {str(d.get('message'))[:160]}"}, c)
                    continue
                url = d["decoded_url"]
            canon = nv.canonical_url(url)
            if canon in by_url:   # decoded to an article already read in this run
                prev = by_url[canon]
                emit({**prev, "id": c["id"], "ticker": c["ticker"], "source_url": c["url"],
                      "note": f"same article as {prev['id']} (same URL, not requested again)"}, c)
                continue
            ok, why, dom = nv.url_check(url, src)
            if not ok:
                emit({**base_row(c, utc_now()), "final_url": url if url.startswith("https://") else None,
                      "domain": dom or nv.host_of(url) or c["outlet"], "tier": src.tier(nv.host_of(url)),
                      "access": "blocked" if dom else "skipped_unlisted", "note": f"not requested: {why}"}, c)
                continue
            pacer.wait()
            page = nv.fetch_page(session, url, src)
            requests_made["fetch"] += page.requests
            if page.html is None:
                listed = src.lookup(nv.host_of(page.final_url))[0]
                emit({**base_row(c, utc_now()),
                      "final_url": page.final_url if (page.final_url or "").startswith("https://") else None,
                      "domain": listed or nv.host_of(page.final_url) or c["outlet"],
                      "tier": src.tier(nv.host_of(page.final_url)), "http_status": page.status,
                      "access": "skipped_unlisted" if page.skipped and not listed else "blocked",
                      "note": page.error}, c)
                continue
            try:
                row = article_row(c, page, src, names.get(c["ticker"], []))
            except Exception as e:   # one bad page never stops the run
                row = {**base_row(c, utc_now()), "final_url": page.final_url, "http_status": page.status,
                       "access": "partial", "note": f"extraction failed: {type(e).__name__}: {str(e)[:120]}"}
            by_url[canon] = row
            emit(row, c)
    try:
        session.close()
    except Exception:
        pass
    n_dec = sum(1 for r in written if r["access"] == "undecoded")
    tried = sum(1 for c in todo if nv.host_of(c["url"]) == GOOGLE_HOST)
    if tried and n_dec / tried > 0.5:
        warnings.append(f"{n_dec} of {tried} Google News links not decoded")
    print(json.dumps({
        "collector": "articles", "market": market, "candidates": len(cands), "written": len(written),
        "deferred": deferred, "copied_same_article": len(copies),
        # outlets not on the allowlist (never requested), for review: vet and add, or ignore
        "unvetted_domains": dict(Counter(r["key"] for r in unvetted).most_common(40)),
        "by_access": dict(Counter(r["access"] for r in written).most_common()),
        "by_domain": dict(Counter(f"{r['domain']}:{r['access']}" for r in written).most_common()),
        "requests": {**requests_made, "total": sum(requests_made.values()),
                     "note": "decode = one GET per Google News link + one POST per batch"},
        "seconds": round(time.monotonic() - t0, 1), "failed": failed, "warnings": warnings,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
