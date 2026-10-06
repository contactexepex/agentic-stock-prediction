"""The independent origins, flags and summary row of one cluster of news items (news verification phase A)."""
from __future__ import annotations

from collections import defaultdict

from marketbrief.analytics.cluster_items import DisjointSets
from marketbrief.constants.news_clusters import (FLAG_DUPLICATES_REMOVED, FLAG_LOW_TIER_ONLY, FLAG_NO_VETTED_ORIGIN,
                                                 FLAG_OPINION, FLAG_ORIGINS_UNVERIFIED, FLAG_PROMOTIONAL,
                                                 FLAG_SINGLE_SOURCE, FLAG_SOURCES_SAY, FLAG_UNREAD, LABEL_OUTLET,
                                                 LABEL_PROVIDER, LABEL_WIRE, READ_ACCESS)


def item_label(it: dict) -> str:
    """The origin label of an item: its agency, else its content provider, else its outlet."""
    if it["wire"]:
        return f"{LABEL_WIRE}{it['wire']}"
    if it["provider"]:
        return f"{LABEL_PROVIDER}{it['provider']}"
    return f"{LABEL_OUTLET}{it['outlet_key']}"


def countable(it: dict) -> bool:
    """Can the item count as an origin: vetted, not promotional, not opinion."""
    return it["vetted"] and not it["promo"] and not it["opinion"]


def merge_origins(items: list[dict], members: list[int], labels: list[str], copies) -> DisjointSets:
    """Items merge by the same label, or by copied text across different outlets."""
    o = DisjointSets(len(members))
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
    return o


def origin_group(group: list[dict], labels: list[str]) -> dict:
    """One origin: its name (agency, else provider, else first label) and what its items allow it to count."""
    name = next((x for x in labels if x.startswith(LABEL_WIRE)), None) or \
        next((x for x in labels if x.startswith(LABEL_PROVIDER)), None) or labels[0]
    return {"origin": name, "news_ids": [it["id"] for it in group],
            "promotional": all(it["promo"] for it in group),
            "vetted": any(it["vetted"] for it in group),
            "opinion": any(it["opinion"] for it in group),
            # verified: a vetted, non-promotional, non-opinion item whose text was read
            # or that carries agency evidence (byline, provider, dateline, title, label)
            "verified": any(countable(it) and (it["read"] or it["wire"]) for it in group),
            "unread_vetted": any(countable(it) for it in group)}


def origin_groups(items: list[dict], members: list[int], copies) -> list[dict]:
    """The origins of a cluster, sorted by name."""
    labels = [item_label(items[i]) for i in members]
    o = merge_origins(items, members, labels, copies)
    by_root = defaultdict(list)
    for k in range(len(members)):
        by_root[o.find(k)].append(k)
    groups = [origin_group([items[members[k]] for k in ks], [labels[k] for k in ks]) for ks in by_root.values()]
    groups.sort(key=lambda g: g["origin"])
    return groups


def cluster_flags(its: list[dict], arts: list[dict], independent: int, unread_vetted: int,
                  has_duplicates: bool) -> list:
    """The flags of a cluster (see the news_clusters module docstring)."""
    checks = [(any(it["promo"] for it in its), FLAG_PROMOTIONAL), (any(it["say"] for it in its), FLAG_SOURCES_SAY),
              (independent == 1, FLAG_SINGLE_SOURCE), (independent == 0, FLAG_NO_VETTED_ORIGIN),
              (bool(unread_vetted), FLAG_ORIGINS_UNVERIFIED), (any(it["opinion"] for it in its), FLAG_OPINION),
              (not any(it["vetted"] for it in its), FLAG_LOW_TIER_ONLY),
              (not any(a.get("access") in READ_ACCESS for a in arts), FLAG_UNREAD),
              (has_duplicates, FLAG_DUPLICATES_REMOVED)]
    return [flag for hit, flag in checks if hit]


def describe(items: list[dict], members: list[int], dups: dict, copies) -> dict:
    """The summary of one cluster: its items, duplicates, outlets, independent origins and flags."""
    groups = origin_groups(items, members, copies)
    all_idx = members + [d for i in members for d in dups.get(i, [])]
    its = [items[i] for i in all_idx]
    rep = items[members[0]]
    outlets = sorted({it["outlet_key"] for it in its})
    tier_of = {it["outlet_key"]: it["tier"] for it in its}
    counted = [g for g in groups if g["verified"]]
    independent = len(counted)
    unread_vetted = sum(1 for g in groups if g["unread_vetted"] and not g["verified"])
    for g in groups:
        g["unread_vetted"] = g["unread_vetted"] and not g["verified"]
    arts = [it["article"] for it in its if it["article"]]
    return {
        "ticker": rep["ticker"], "cluster_id": f"{rep['ticker']}-{rep['id']}",
        "news_ids": [items[i]["id"] for i in members],
        "duplicate_ids": sorted(items[d]["id"] for i in members for d in dups.get(i, [])),
        "n_items": len(members), "outlets": outlets, "tiers": [tier_of[x] for x in outlets],
        "independent_origins": independent, "unread_vetted_origins": unread_vetted,
        "unvetted_ids": sorted(items[m]["id"] for m in members if not items[m]["vetted"]),  # also in a vetted group
        "origins": [g["origin"] for g in counted], "origin_groups": groups,
        "first_reported_at": min(it["t"] for it in its), "last_reported_at": max(it["t"] for it in its),
        "inputs_until": max([it["seen"] for it in its] + [it["fetched"] for it in its if it["fetched"] is not None]),
        "newest_seen": max(it["seen"] for it in its),
        "flags": cluster_flags(its, arts, independent, unread_vetted, len(all_idx) > len(members)),
        "n_articles": len(arts), "titles": [items[i]["title"] for i in members],
        "unvetted_outlets": [it["outlet_key"] for it in its if not it["vetted"]],
    }
