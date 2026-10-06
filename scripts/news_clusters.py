#!/usr/bin/env python3
"""Group news items about the same event and count independent origins (news verification
phase A, deterministic; docs/DESIGN.md section 3a; settings under `clusters:` in
config/news_sources.yaml). Run after collect_articles.py.

As of now (MB_NOW in a replay), only inputs known by then are used: news rows first seen in the
last `lookback_hours`, article rows fetched by then, SEC filings accepted by then (the `filings`
view, acceptance times corrected by sec_times), NSE announcements disseminated by then.
1. Items: news rows whose title names a watchlist ticker as primary subject (news_tags.py).
2. Duplicates: one article stored under two ids (the same canonical publisher URL after Google
   News decoding, or the same normalised title from the same outlet, e.g. the labels "Business
   Today" and "businesstoday.in") is kept once; the others are listed in `duplicate_ids`.
3. Clusters, per ticker, items at most `window_hours` apart, linked (single linkage) when their
   informative title tokens (stopwords and the company's own name removed) have Jaccard >=
   `title_jaccard` with >= `title_min_shared` shared tokens, or their titles share a distinctive
   normalised number (a currency amount, a percent with decimals, or a number >= 1000 that is not
   a year) and at least one informative token, or their article texts are copies (MinHash
   containment >= `copy_containment`).
4. Origins: an agency copy (byline, JSON-LD provider, dateline, "By Reuters" title, "Reuters
   reported"-style attribution in the lede, a wire's own domain or label) is that agency's origin;
   else the JSON-LD provider (vendor content on Yahoo/AOL); else the outlet. The outlet is its
   domain; a row without one (older Google News rows) is mapped from its source label (configured
   names, a label that is a host, or the domain other rows of this run give that label). Items of
   one outlet share an origin; items of different outlets whose texts are copies (6-shingle
   MinHash containment >= `copy_containment`) share an origin. Only VETTED origins count: a group
   with an item from an allowlisted outlet (any tier, also `fetch: false` ones) or attributed to
   an agency, and with a non-promotional item. Items from unvetted outlets are informational
   (`unvetted_ids`), and the summary lists their domains (`unvetted_domains`) for review.
   independent_origins = the number of vetted, non-promotional origin groups.
5. Primary candidates: the ticker's SEC filings of `sec_forms` and NSE announcements public from
   `window_hours` before the first report until now (not yet matched to the claims: phase B).
Flags: promotional_provider, sources_say, single_source (<= 1 vetted independent origin),
low_tier_only (no vetted item: no allowlisted outlet and no agency), unread (no article text or
description was read),
duplicates_removed. A cluster is appended (schema `news_clusters`) when it has an item first seen
in the last `window_hours`, holds 2+ items or a fetched article, and is new or changed since its
last stored row. Read the state at a time with the macro news_clusters_asof(ts) (sql/views.sql).
Prints a JSON summary."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict

import pandas as pd

import news_verify as nv
from common import append_jsonl, clock, connect, day_file, market_arg, require_market, utc_today
from news_tags import norm

READ = ("full", "partial", "paywalled")


class DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def _ts(v) -> pd.Timestamp | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _iso(t: pd.Timestamp | None) -> str | None:
    return None if t is None else t.floor("s").isoformat()


def label_domains(rows) -> dict[str, str]:
    """Source label -> the domain other rows with that label give (Google News <source url>), so a
    label-only row and a domain row of one outlet are one outlet ("The CSR Universe" /
    thecsruniverse.com). A label used with several domains is left out."""
    seen: dict[str, set] = defaultdict(set)
    for r in rows:
        if r[3] and r[4]:
            seen[norm(r[3])].add(r[4])
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def outlet_of(source: str | None, src: nv.Sources, learned: dict[str, str]) -> str | None:
    if not source:
        return None
    d = src.domain_of_label(source) or learned.get(norm(source))
    if d is None and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", source.strip()):
        d = source.strip().lower().removeprefix("www.")
    return d


def load_items(con, cfg: dict, src: nv.Sources, as_of: pd.Timestamp) -> list[dict]:
    cl = src.clusters
    since = as_of - pd.Timedelta(hours=float(cl.get("lookback_hours", 144)))
    rows = con.execute(
        "SELECT id, title, url, source, source_domain, published_at, first_seen_at, primary_tickers "
        "FROM news WHERE first_seen_at <= ? AND first_seen_at >= ? ORDER BY first_seen_at, id",
        [as_of.to_pydatetime(), since.to_pydatetime()]).fetchall()
    arts = {r["id"]: r for r in con.execute(
        "SELECT DISTINCT ON (id) * FROM news_articles WHERE fetched_at <= ? ORDER BY id, fetched_at DESC",
        [as_of.to_pydatetime()]).df().to_dict("records")}
    learned = label_domains(rows)
    items = []
    for nid, title, url, source, sdom, pub, seen, prim in rows:
        tickers = [t for t in (prim or []) if t in cfg["tickers"]]
        if not tickers:
            continue
        a = arts.get(nid)
        a = {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in a.items()} if a else None
        host = nv.host_of(url)
        domain = ((a or {}).get("domain") if a and a.get("final_url") else None) or sdom \
            or (host if host and host != "news.google.com" and src.lookup(host)[0] else None) \
            or outlet_of(source, src, learned) or (host if host and host != "news.google.com" else None)
        dom_l = src.lookup(domain)[0]
        domain = dom_l or domain
        seen_t, pub_t = _ts(seen), _ts(pub)
        wire, ev = (a.get("origin_wire"), a.get("origin_evidence")) if a and a.get("origin_wire") else \
            src.detect_wire(title=title, source=source, domain=domain)
        provider = (a or {}).get("provider")
        promo = ((a or {}).get("promotional") or src.is_promotional(name=source, domain=domain)
                 or src.is_promotional(name=provider) or src.is_promotional(text=title))
        canon = nv.canonical_url((a or {}).get("final_url") or (url if host != "news.google.com" else None))
        for t in tickers:
            items.append({
                "id": nid, "ticker": t, "title": title or "", "source": source, "domain": domain,
                "tier": src.tier(domain), "vetted": bool(dom_l) or bool(wire), "t": pub_t if pub_t is not None and pub_t <= seen_t else seen_t,
                "seen": seen_t, "wire": wire, "wire_ev": ev, "provider": provider if not src.wire_of_name(provider) else None,
                "promo": promo, "canon": canon, "outlet_key": domain or f"label:{norm(source)}",
                "article": a, "fetched": _ts((a or {}).get("fetched_at")),
                "say": bool((a or {}).get("sources_say")) or nv.sources_say(title),
                "nums": nv.distinctive(nv.numbers(title)),
            })
    return items


def load_primaries(con, cfg: dict, src: nv.Sources, as_of: pd.Timestamp) -> dict[str, list[tuple]]:
    cl = src.clusters
    since = as_of - pd.Timedelta(hours=float(cl.get("lookback_hours", 144)) + float(cl.get("window_hours", 72)))
    out: dict[str, list[tuple]] = defaultdict(list)
    forms = list(cl.get("sec_forms") or [])
    for tid, ticker, t in con.execute(
            "SELECT id, ticker, coalesce(accepted_at, CAST(filing_date AS TIMESTAMPTZ) + INTERVAL 1 DAY) AS t "
            "FROM filings WHERE list_contains(?, form) ORDER BY t, id", [forms]).fetchall():
        tt = _ts(t)
        if tt is not None and since <= tt <= as_of:
            out[ticker].append((tt, tid))
    for tid, ticker, t in con.execute("SELECT id, ticker, published_at FROM announcements "
                                      "WHERE published_at IS NOT NULL ORDER BY published_at, id").fetchall():
        tt = _ts(t)
        if tt is not None and since <= tt <= as_of:
            out[ticker].append((tt, tid))
    return out


def drop_tokens(cfg: dict, ticker: str) -> set[str]:
    m = cfg["tickers"][ticker]
    names = [m["name"], *m.get("aliases", []), *(m.get("news_names") or []), ticker]
    return {w for n in names for w in nv.title_tokens(n)} | {ticker.lower()}


def cluster_ticker(items: list[dict], cfg: dict, src: nv.Sources) -> list[dict]:
    """Clusters of one ticker's items (see the module docstring)."""
    cl = src.clusters
    window = pd.Timedelta(hours=float(cl.get("window_hours", 72)))
    jac, shared = float(cl.get("title_jaccard", 0.5)), int(cl.get("title_min_shared", 2))
    copy_thr, min_sh = float(cl.get("copy_containment", 0.5)), int(cl.get("min_shingles", 30))
    items = sorted(items, key=lambda x: (x["t"], x["id"]))
    # 1. duplicates: same canonical URL, or same normalised title from the same outlet
    dup = DSU(len(items))
    first: dict = {}
    for i, it in enumerate(items):
        for key in ((("u", it["canon"]) if it["canon"] else None), ("t", norm(it["title"]), it["outlet_key"])):
            if key is None:
                continue
            if key in first:
                dup.union(first[key], i)
            else:
                first[key] = i
    reps = [i for i in range(len(items)) if dup.find(i) == i]
    dups = defaultdict(list)
    for i in range(len(items)):
        if dup.find(i) != i:
            dups[dup.find(i)].append(i)
    drop = drop_tokens(cfg, items[0]["ticker"]) if items else set()
    toks = {i: nv.title_tokens(items[i]["title"], drop) for i in reps}

    def copies(i: int, j: int) -> bool:
        a, b = items[i]["article"] or {}, items[j]["article"] or {}
        if (a.get("shingle_count") or 0) < min_sh or (b.get("shingle_count") or 0) < min_sh:
            return False
        c = nv.containment_est(a.get("minhash"), a.get("shingle_count"), b.get("minhash"), b.get("shingle_count"))
        return c is not None and c >= copy_thr

    # 2. event links
    ev = DSU(len(items))
    for x, i in enumerate(reps):
        for j in reps[x + 1:]:
            if items[j]["t"] - items[i]["t"] > window:
                break
            ti, tj = toks[i], toks[j]
            inter = len(ti & tj)
            same_title = inter >= shared and inter / len(ti | tj) >= jac
            same_number = inter >= 1 and bool(items[i]["nums"] & items[j]["nums"])   # "$20 billion" alone is common
            if same_title or same_number or copies(i, j):
                ev.union(i, j)
    groups = defaultdict(list)
    for i in reps:
        groups[ev.find(i)].append(i)
    out = []
    for members in groups.values():
        members.sort(key=lambda i: (items[i]["t"], items[i]["id"]))
        out.append(describe(items, members, dups, copies))
    return out


def describe(items: list[dict], members: list[int], dups: dict, copies) -> dict:
    # origins: label per item, merged by same label or copied text
    def label(it: dict) -> str:
        if it["wire"]:
            return f"wire:{it['wire']}"
        if it["provider"]:
            return f"provider:{it['provider']}"
        return f"outlet:{it['outlet_key']}"

    o = DSU(len(members))
    labels = [label(items[i]) for i in members]
    seen: dict[str, int] = {}
    for k, lab in enumerate(labels):
        if lab in seen:
            o.union(seen[lab], k)
        else:
            seen[lab] = k
    for a in range(len(members)):
        for b in range(a + 1, len(members)):
            # copied text joins origins of different outlets only: two stories of one outlet share
            # boilerplate or reuse its own paragraphs, which says nothing about an agency origin
            ia, ib = items[members[a]], items[members[b]]
            if ia["outlet_key"] != ib["outlet_key"] and o.find(a) != o.find(b) and copies(members[a], members[b]):
                o.union(a, b)
    og = defaultdict(list)
    for k in range(len(members)):
        og[o.find(k)].append(k)
    origin_groups = []
    for ks in og.values():
        labs = [labels[k] for k in ks]
        name = next((x for x in labs if x.startswith("wire:")), None) or \
            next((x for x in labs if x.startswith("provider:")), None) or labs[0]
        origin_groups.append({"origin": name, "news_ids": [items[members[k]]["id"] for k in ks],
                              "promotional": all(items[members[k]]["promo"] for k in ks),
                              "vetted": any(items[members[k]]["vetted"] for k in ks)})
    origin_groups.sort(key=lambda g: g["origin"])
    all_idx = members + [d for i in members for d in dups.get(i, [])]
    its = [items[i] for i in all_idx]
    rep = items[members[0]]
    outlets = sorted({it["outlet_key"] for it in its})
    tier_of = {it["outlet_key"]: it["tier"] for it in its}
    counted = [g for g in origin_groups if g["vetted"] and not g["promotional"]]
    independent = len(counted)
    unvetted = sorted(i for g in origin_groups if not g["vetted"] for i in g["news_ids"])
    arts = [it["article"] for it in its if it["article"]]
    flags = []
    if any(it["promo"] for it in its):
        flags.append("promotional_provider")
    if any(it["say"] for it in its):
        flags.append("sources_say")
    if independent <= 1:
        flags.append("single_source")
    if not any(it["vetted"] for it in its):
        flags.append("low_tier_only")
    if not any(a.get("access") in READ for a in arts):
        flags.append("unread")
    if len(all_idx) > len(members):
        flags.append("duplicates_removed")
    return {
        "ticker": rep["ticker"], "cluster_id": f"{rep['ticker']}-{rep['id']}",
        "news_ids": [items[i]["id"] for i in members],
        "duplicate_ids": sorted(items[d]["id"] for i in members for d in dups.get(i, [])),
        "n_items": len(members), "outlets": outlets, "tiers": [tier_of[x] for x in outlets],
        "independent_origins": independent, "unvetted_ids": unvetted,
        "origins": [g["origin"] for g in counted], "origin_groups": origin_groups,
        "first_reported_at": min(it["t"] for it in its), "last_reported_at": max(it["t"] for it in its),
        "inputs_until": max([it["seen"] for it in its] + [it["fetched"] for it in its if it["fetched"] is not None]),
        "newest_seen": max(it["seen"] for it in its), "flags": flags, "n_articles": len(arts),
        "titles": [items[i]["title"] for i in members],
        "unvetted_outlets": [it["outlet_key"] for it in its if not it["vetted"]],
    }


def state_hash(c: dict) -> str:
    keys = ("news_ids", "duplicate_ids", "primary_ids", "origins", "origin_groups", "independent_origins",
            "unvetted_ids", "flags", "outlets")
    return hashlib.sha1(json.dumps({k: c[k] for k in keys}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def main() -> int:
    cfg = require_market(market_arg(__doc__).parse_args())
    market, src = cfg["market"], nv.load_sources()
    t0, as_of = time.monotonic(), pd.Timestamp(clock()).floor("s")
    cl = src.clusters
    window = pd.Timedelta(hours=float(cl.get("window_hours", 72)))
    con = connect(market)
    items = load_items(con, cfg, src, as_of)
    prim = load_primaries(con, cfg, src, as_of)
    stored = dict(con.execute("SELECT DISTINCT ON (cluster_id) cluster_id, state_hash FROM news_clusters "
                              "WHERE as_of <= ? ORDER BY cluster_id, as_of DESC", [as_of.to_pydatetime()]).fetchall())
    by_ticker = defaultdict(list)
    for it in items:
        by_ticker[it["ticker"]].append(it)
    clusters = [c for t in sorted(by_ticker) for c in cluster_ticker(by_ticker[t], cfg, src)]
    rows, unchanged, skipped = [], 0, 0
    current = []
    for c in clusters:
        lo = c["first_reported_at"] - window
        p = [(t, i) for t, i in prim.get(c["ticker"], []) if lo <= t]   # load_primaries: <= as_of
        c["primary_ids"] = [i for _t, i in p]
        if p:
            c["inputs_until"] = max(c["inputs_until"], max(t for t, _i in p))
        if c["newest_seen"] < as_of - window or (c["n_items"] < 2 and not c["n_articles"]):
            skipped += 1
            continue
        current.append(c)
        h = state_hash(c)
        if stored.get(c["cluster_id"]) == h:
            unchanged += 1
            continue
        rows.append({
            "id": f"{c['cluster_id']}@{as_of:%Y%m%dT%H%M%SZ}", "as_of": _iso(as_of), "cluster_id": c["cluster_id"],
            "ticker": c["ticker"], "news_ids": c["news_ids"], "duplicate_ids": c["duplicate_ids"],
            "n_items": c["n_items"], "outlets": c["outlets"], "tiers": c["tiers"],
            "independent_origins": c["independent_origins"], "unvetted_ids": c["unvetted_ids"],
            "origins": c["origins"], "origin_groups": c["origin_groups"], "primary_ids": c["primary_ids"],
            "first_reported_at": _iso(c["first_reported_at"]), "last_reported_at": _iso(c["last_reported_at"]),
            "inputs_until": _iso(c["inputs_until"]), "flags": c["flags"], "state_hash": h,
            "method_version": nv.METHOD_VERSION,
        })
    written = append_jsonl(day_file(market, "news_clusters", utc_today()), rows) if rows else 0
    examples = sorted(current, key=lambda c: (-c["n_items"], c["cluster_id"]))[:3]
    print(json.dumps({
        "step": "news_clusters", "market": market, "as_of": _iso(as_of), "items": len(items),
        "clusters": len(clusters), "current": len(current), "written": written, "unchanged": unchanged,
        "not_written_single_or_old": skipped,
        "size_distribution": dict(sorted(Counter(min(c["n_items"], 10) for c in current).items())),
        "independent_origins_distribution": dict(sorted(Counter(c["independent_origins"] for c in current).items())),
        "clusters_with_unvetted_items": sum(1 for c in current if c["unvetted_ids"]),
        # outlets not on the allowlist (config/news_sources.yaml), for review: vet and add, or ignore
        "unvetted_domains": dict(Counter(o for c in current for o in c["unvetted_outlets"]).most_common(40)),
        "flags": dict(Counter(f for c in current for f in c["flags"]).most_common()),
        "with_primary": sum(1 for c in current if c["primary_ids"]),
        "examples": [{"cluster_id": c["cluster_id"], "n_items": c["n_items"], "titles": c["titles"][:4],
                      "origins": c["origins"], "independent_origins": c["independent_origins"],
                      "unvetted_ids": c["unvetted_ids"], "primary_ids": c["primary_ids"][:5],
                      "flags": c["flags"]} for c in examples],
        "seconds": round(time.monotonic() - t0, 1),
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
