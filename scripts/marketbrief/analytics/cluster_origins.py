"""The independent origins, flags and summary row of one cluster of news items (news verification phase A)."""

from __future__ import annotations

from collections import defaultdict

from marketbrief.analytics.cluster_items import DisjointSets
from marketbrief.constants.news_clusters import (
    FLAG_DUPLICATES_REMOVED,
    FLAG_LOW_TIER_ONLY,
    FLAG_NO_VETTED_ORIGIN,
    FLAG_OPINION,
    FLAG_ORIGINS_UNVERIFIED,
    FLAG_PROMOTIONAL,
    FLAG_SINGLE_SOURCE,
    FLAG_SOURCES_SAY,
    FLAG_UNREAD,
    LABEL_OUTLET,
    LABEL_PROVIDER,
    LABEL_WIRE,
    READ_ACCESS,
)


def item_label(item: dict) -> str:
    """The origin label of an item: its agency, else its content provider, else its outlet."""
    if item["wire"]:
        return f"{LABEL_WIRE}{item['wire']}"
    if item["provider"]:
        return f"{LABEL_PROVIDER}{item['provider']}"
    return f"{LABEL_OUTLET}{item['outlet_key']}"


def countable(item: dict) -> bool:
    """Can the item count as an origin: vetted, not promotional, not opinion."""
    return item["vetted"] and not item["promo"] and not item["opinion"]


def merge_origins(items: list[dict], members: list[int], labels: list[str], copies) -> DisjointSets:
    """Items merge by the same label, or by copied text across different outlets."""
    origin_sets = DisjointSets(len(members))
    seen: dict[str, int] = {}
    for position, lab in enumerate(labels):
        if lab in seen:
            origin_sets.union(seen[lab], position)
        else:
            seen[lab] = position
    for first_position in range(len(members)):
        for second_position in range(first_position + 1, len(members)):
            # copied text joins origins of different outlets only: two stories of one outlet share
            # boilerplate or reuse its own paragraphs, which says nothing about an agency origin
            first_item, second_item = items[members[first_position]], items[members[second_position]]
            if (
                first_item["outlet_key"] != second_item["outlet_key"]
                and origin_sets.find(first_position) != origin_sets.find(second_position)
                and copies(members[first_position], members[second_position])
            ):
                origin_sets.union(first_position, second_position)
    return origin_sets


def origin_group(group: list[dict], labels: list[str]) -> dict:
    """One origin: its name (agency, else provider, else first label) and what its items allow it to count."""
    name = (
        next((label for label in labels if label.startswith(LABEL_WIRE)), None)
        or next((label for label in labels if label.startswith(LABEL_PROVIDER)), None)
        or labels[0]
    )
    return {
        "origin": name,
        "news_ids": [item["id"] for item in group],
        "promotional": all(item["promo"] for item in group),
        "vetted": any(item["vetted"] for item in group),
        "opinion": any(item["opinion"] for item in group),
        # verified: a vetted, non-promotional, non-opinion item whose text was read
        # or that carries agency evidence (byline, provider, dateline, title, label)
        "verified": any(countable(item) and (item["read"] or item["wire"]) for item in group),
        "unread_vetted": any(countable(item) for item in group),
    }


def origin_groups(items: list[dict], members: list[int], copies) -> list[dict]:
    """The origins of a cluster, sorted by name."""
    labels = [item_label(items[member]) for member in members]
    origin_sets = merge_origins(items, members, labels, copies)
    by_root = defaultdict(list)
    for position in range(len(members)):
        by_root[origin_sets.find(position)].append(position)
    groups = [
        origin_group([items[members[position]] for position in positions], [labels[position] for position in positions])
        for positions in by_root.values()
    ]
    groups.sort(key=lambda group: group["origin"])
    return groups


def cluster_flags(
    its: list[dict], arts: list[dict], independent: int, unread_vetted: int, has_duplicates: bool
) -> list:
    """The flags of a cluster (see the news_clusters module docstring)."""
    checks = [
        (any(item["promo"] for item in its), FLAG_PROMOTIONAL),
        (any(item["say"] for item in its), FLAG_SOURCES_SAY),
        (independent == 1, FLAG_SINGLE_SOURCE),
        (independent == 0, FLAG_NO_VETTED_ORIGIN),
        (bool(unread_vetted), FLAG_ORIGINS_UNVERIFIED),
        (any(item["opinion"] for item in its), FLAG_OPINION),
        (not any(item["vetted"] for item in its), FLAG_LOW_TIER_ONLY),
        (not any(article.get("access") in READ_ACCESS for article in arts), FLAG_UNREAD),
        (has_duplicates, FLAG_DUPLICATES_REMOVED),
    ]
    return [flag for hit, flag in checks if hit]


def describe(items: list[dict], members: list[int], dups: dict, copies) -> dict:
    """The summary of one cluster: its items, duplicates, outlets, independent origins and flags."""
    groups = origin_groups(items, members, copies)
    all_idx = members + [duplicate_index for member_index in members for duplicate_index in dups.get(member_index, [])]
    its = [items[member_index] for member_index in all_idx]
    rep = items[members[0]]
    outlets = sorted({item["outlet_key"] for item in its})
    tier_of = {item["outlet_key"]: item["tier"] for item in its}
    counted = [group for group in groups if group["verified"]]
    independent = len(counted)
    unread_vetted = sum(1 for group in groups if group["unread_vetted"] and not group["verified"])
    for group in groups:
        group["unread_vetted"] = group["unread_vetted"] and not group["verified"]
    arts = [item["article"] for item in its if item["article"]]
    return {
        "ticker": rep["ticker"],
        "cluster_id": f"{rep['ticker']}-{rep['id']}",
        "news_ids": [items[member_index]["id"] for member_index in members],
        "duplicate_ids": sorted(
            items[duplicate_index]["id"] for member_index in members for duplicate_index in dups.get(member_index, [])
        ),
        "n_items": len(members),
        "outlets": outlets,
        "tiers": [tier_of[outlet] for outlet in outlets],
        "independent_origins": independent,
        "unread_vetted_origins": unread_vetted,
        "unvetted_ids": sorted(
            items[member_item_index]["id"] for member_item_index in members if not items[member_item_index]["vetted"]
        ),  # also in a vetted group
        "origins": [group["origin"] for group in counted],
        "origin_groups": groups,
        "first_reported_at": min(item["t"] for item in its),
        "last_reported_at": max(item["t"] for item in its),
        "inputs_until": max(
            [item["seen"] for item in its] + [item["fetched"] for item in its if item["fetched"] is not None]
        ),
        "newest_seen": max(item["seen"] for item in its),
        "flags": cluster_flags(its, arts, independent, unread_vetted, len(all_idx) > len(members)),
        "n_articles": len(arts),
        "titles": [items[member_index]["title"] for member_index in members],
        "unvetted_outlets": [item["outlet_key"] for item in its if not item["vetted"]],
    }
