"""Group news items about the same event and count independent origins (news verification phase A, deterministic;
docs/DESIGN.md section 3a; settings under `clusters:` in config/news_sources.yaml). Run after collect_articles.py.

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
   domain; a row without one (older Google News rows) is mapped from its source label
   (news_sources.outlet_of). Items of one outlet share an origin; items of different outlets whose
   texts are copies (6-shingle MinHash containment >= `copy_containment`) share an origin.
   An item is VETTED only by an allowlisted outlet (any tier, also `fetch: false`) or by being the
   agency itself (its source label); an agency named in an unvetted item's title joins that
   agency's group but never makes it count. Promotional items and opinion items (an outlet with
   `opinion_unless_path`, e.g. Seeking Alpha contributors) never count.
   independent_origins counts VERIFIED groups: one with a vetted, non-promotional, non-opinion item
   that was read (article text or description) or carries agency evidence. Vetted groups with
   only unread headlines are counted apart in unread_vetted_origins (flag origins_unverified):
   without text their independence cannot be checked. Items from unvetted outlets are
   informational (`unvetted_ids`); the summary lists their outlets (`unvetted_domains`).
5. Primary candidates: the ticker's SEC filings of `sec_forms` and NSE announcements public from
   `window_hours` before the first report until now (not yet matched to the claims: phase B).
Flags: promotional_provider, sources_say, single_source (exactly 1 verified origin),
no_vetted_origin (none), origins_unverified, opinion,
low_tier_only (no vetted item: no allowlisted outlet and no agency), unread (no article text or
description was read),
duplicates_removed. A cluster is appended (schema `news_clusters`) when it has an item first seen
in the last `window_hours`, holds 2+ items or a fetched article, and is new or changed since its
last stored row. Read the state at a time with the macro news_clusters_asof(ts) (sql/views.sql).
Prints a JSON summary."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict

import pandas as pd

from marketbrief.analytics.cluster_items import (DisjointSets, drop_tokens, iso_seconds, load_items,
                                                 load_primaries)
from marketbrief.analytics.cluster_origins import describe
from marketbrief.analytics.news_sources import Sources, load_sources
from marketbrief.analytics.news_tags import norm
from marketbrief.analytics.text_measures import estimated_containment, title_tokens
from marketbrief.constants.news_clusters import (DEFAULT_COPY_CONTAINMENT, DEFAULT_MIN_SHINGLES, DEFAULT_TITLE_JACCARD,
                                                 DEFAULT_TITLE_MIN_SHARED, DEFAULT_WINDOW_HOURS, MAX_EXAMPLES,
                                                 MAX_SIZE_BUCKET, MAX_UNVETTED_DOMAINS, METHOD_VERSION_CLUSTERS,
                                                 STATE_HASH_KEYS, STATE_HASH_LENGTH, STEP_NEWS_CLUSTERS,
                                                 STORED_CLUSTERS_SQL)
from marketbrief.core import cli, clock, database, storage


def duplicate_sets(items: list[dict]) -> DisjointSets:
    """Items merge when they share a canonical URL, or a normalised title from the same outlet."""
    dup = DisjointSets(len(items))
    first: dict = {}
    for i, it in enumerate(items):
        for key in ((("u", it["canon"]) if it["canon"] else None), ("t", norm(it["title"]), it["outlet_key"])):
            if key is None:
                continue
            if key in first:
                dup.union(first[key], i)
            else:
                first[key] = i
    return dup


def copy_test(items: list[dict], cl: dict):
    """A function telling whether the article texts of two items are copies (MinHash containment)."""
    copy_threshold = float(cl.get("copy_containment", DEFAULT_COPY_CONTAINMENT))
    min_shingles = int(cl.get("min_shingles", DEFAULT_MIN_SHINGLES))

    def copies(i: int, j: int) -> bool:
        """True when the article texts of two items are copies (MinHash containment)."""
        a, b = items[i]["article"] or {}, items[j]["article"] or {}
        if (a.get("shingle_count") or 0) < min_shingles or (b.get("shingle_count") or 0) < min_shingles:
            return False
        c = estimated_containment(a.get("minhash"), a.get("shingle_count"), b.get("minhash"), b.get("shingle_count"))
        return c is not None and c >= copy_threshold
    return copies


def cluster_ticker(items: list[dict], cfg: dict, src: Sources) -> list[dict]:
    """Clusters of one ticker's items (see the module docstring)."""
    cl = src.clusters
    window = pd.Timedelta(hours=float(cl.get("window_hours", DEFAULT_WINDOW_HOURS)))
    jac = float(cl.get("title_jaccard", DEFAULT_TITLE_JACCARD))
    shared = int(cl.get("title_min_shared", DEFAULT_TITLE_MIN_SHARED))
    items = sorted(items, key=lambda x: (x["t"], x["id"]))
    dup = duplicate_sets(items)   # 1. duplicates
    reps = [i for i in range(len(items)) if dup.find(i) == i]
    dups = defaultdict(list)
    for i in range(len(items)):
        if dup.find(i) != i:
            dups[dup.find(i)].append(i)
    drop = drop_tokens(cfg, items[0]["ticker"]) if items else set()
    toks = {i: title_tokens(items[i]["title"], drop) for i in reps}
    copies = copy_test(items, cl)
    events = DisjointSets(len(items))   # 2. event links
    for x, i in enumerate(reps):
        for j in reps[x + 1:]:
            if items[j]["t"] - items[i]["t"] > window:
                break
            ti, tj = toks[i], toks[j]
            inter = len(ti & tj)
            same_title = inter >= shared and inter / len(ti | tj) >= jac
            same_number = inter >= 1 and bool(items[i]["nums"] & items[j]["nums"])   # "$20 billion" alone is common
            if same_title or same_number or copies(i, j):
                events.union(i, j)
    groups = defaultdict(list)
    for i in reps:
        groups[events.find(i)].append(i)
    out = []
    for members in groups.values():
        members.sort(key=lambda i: (items[i]["t"], items[i]["id"]))
        out.append(describe(items, members, dups, copies))
    return out


def state_hash(c: dict) -> str:
    """A short hash of the cluster's stored state (a new row is written only when it changes)."""
    return hashlib.sha1(json.dumps({k: c[k] for k in STATE_HASH_KEYS}, sort_keys=True,
                                   default=str).encode()).hexdigest()[:STATE_HASH_LENGTH]


def stored_row(c: dict, as_of: pd.Timestamp, digest: str) -> dict:
    """The `news_clusters` record of a cluster."""
    return {
        "id": f"{c['cluster_id']}@{as_of:%Y%m%dT%H%M%SZ}", "as_of": iso_seconds(as_of), "cluster_id": c["cluster_id"],
        "ticker": c["ticker"], "news_ids": c["news_ids"], "duplicate_ids": c["duplicate_ids"],
        "n_items": c["n_items"], "outlets": c["outlets"], "tiers": c["tiers"],
        "independent_origins": c["independent_origins"], "unread_vetted_origins": c["unread_vetted_origins"],
        "unvetted_ids": c["unvetted_ids"],
        "origins": c["origins"], "origin_groups": c["origin_groups"], "primary_ids": c["primary_ids"],
        "first_reported_at": iso_seconds(c["first_reported_at"]),
        "last_reported_at": iso_seconds(c["last_reported_at"]),
        "inputs_until": iso_seconds(c["inputs_until"]), "flags": c["flags"], "state_hash": digest,
        "method_version": METHOD_VERSION_CLUSTERS,
    }


def attach_primaries(c: dict, prim: dict, window: pd.Timedelta) -> None:
    """Add the ticker's filings and announcements public from `window` before the first report."""
    lo = c["first_reported_at"] - window
    p = [(t, i) for t, i in prim.get(c["ticker"], []) if lo <= t]   # load_primaries: <= as_of
    c["primary_ids"] = [i for _t, i in p]
    if p:
        c["inputs_until"] = max(c["inputs_until"], max(t for t, _i in p))


def run_summary(market: str, as_of: pd.Timestamp, counts: dict, current: list[dict]) -> dict:
    """The JSON summary of a run."""
    examples = sorted(current, key=lambda c: (-c["n_items"], c["cluster_id"]))[:MAX_EXAMPLES]
    return {
        "step": STEP_NEWS_CLUSTERS, "market": market, "as_of": iso_seconds(as_of), **counts,
        "size_distribution": dict(sorted(Counter(min(c["n_items"], MAX_SIZE_BUCKET) for c in current).items())),
        "independent_origins_distribution": dict(sorted(Counter(c["independent_origins"] for c in current).items())),
        "unread_vetted_distribution": dict(sorted(Counter(c["unread_vetted_origins"] for c in current).items())),
        "clusters_with_unvetted_items": sum(1 for c in current if c["unvetted_ids"]),
        # outlets not on the allowlist (config/news_sources.yaml), for review: vet and add, or ignore
        "unvetted_domains": dict(Counter(o for c in current for o in c["unvetted_outlets"])
                                 .most_common(MAX_UNVETTED_DOMAINS)),
        "flags": dict(Counter(f for c in current for f in c["flags"]).most_common()),
        "with_primary": sum(1 for c in current if c["primary_ids"]),
        "examples": [{"cluster_id": c["cluster_id"], "n_items": c["n_items"], "titles": c["titles"][:4],
                      "origins": c["origins"], "independent_origins": c["independent_origins"],
                      "unvetted_ids": c["unvetted_ids"], "primary_ids": c["primary_ids"][:5],
                      "flags": c["flags"]} for c in examples],
    }


def main() -> int:
    """Entry point of scripts/news_clusters.py."""
    cfg = cli.require_market(cli.market_arg(__doc__).parse_args())
    market, src = cfg["market"], load_sources()
    t0, as_of = time.monotonic(), pd.Timestamp(clock.clock()).floor("s")
    window = pd.Timedelta(hours=float(src.clusters.get("window_hours", DEFAULT_WINDOW_HOURS)))
    con = database.connect(market)
    items = load_items(con, cfg, src, as_of)
    prim = load_primaries(con, src, as_of)
    stored = dict(con.execute(STORED_CLUSTERS_SQL, [as_of.to_pydatetime()]).fetchall())
    by_ticker = defaultdict(list)
    for it in items:
        by_ticker[it["ticker"]].append(it)
    clusters = [c for t in sorted(by_ticker) for c in cluster_ticker(by_ticker[t], cfg, src)]
    rows, unchanged, skipped, current = [], 0, 0, []
    for c in clusters:
        attach_primaries(c, prim, window)
        if c["newest_seen"] < as_of - window or (c["n_items"] < 2 and not c["n_articles"]):
            skipped += 1
            continue
        current.append(c)
        digest = state_hash(c)
        if stored.get(c["cluster_id"]) == digest:
            unchanged += 1
            continue
        rows.append(stored_row(c, as_of, digest))
    written = storage.append_jsonl(storage.day_file(market, "news_clusters", clock.utc_today()), rows) if rows else 0
    counts = {"items": len(items), "clusters": len(clusters), "current": len(current), "written": written,
              "unchanged": unchanged, "not_written_single_or_old": skipped}
    summary = run_summary(market, as_of, counts, current)
    summary["seconds"] = round(time.monotonic() - t0, 1)
    print(json.dumps(summary, indent=2, default=str))
    return 0
