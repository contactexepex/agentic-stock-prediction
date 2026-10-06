"""Verification status of a news event and of each fact stated about it (news verification phase B,
docs/DESIGN.md section 3b). Pure: statements (stored claims) and the cluster row come in as dicts.

Precedence, highest first: contradicted > confirmed_primary > corroborated > rumour > promotional >
single_source > unverified. A fact is
- contradicted: primary sources disagree with each other (values or stance), a primary source denies
  what an outlet affirms, or, with no primary confirmation, outlets state values that disagree (each
  pair compared within 1% of the larger or either literal's stated rounding) or opposite stances;
- confirmed_primary: a primary source (SEC filing, NSE announcement) affirms it; when outlets state a
  value, a primary source must state one too (an outlet value that does not match it is flagged
  mismatch_primary: the filing wins);
- corroborated: >= 2 verified independent origins (news_clusters origin groups) among the outlets
  stating it (opinion and promotional statements never count);
- rumour: an outlet statement attributed to unnamed sources or typed rumour (an outlet's own
  unattributed reporting, attribution outlet_reporting, is an ordinary factual statement);
- promotional: a statement typed promotional (marketing claims, vendor content);
- single_source: exactly one verified origin; unverified: none.
A value quoted from a headline (quote_field title) is never compared: headlines are cut and drop hedges,
so such a statement neither needs nor contradicts a primary value. confirmed_at is when the confirming
primary source was public (source_published_at: SEC acceptance, NSE dissemination).
A cluster's status is the highest of its facts' and its base status (the cluster row alone)."""
from __future__ import annotations

from marketbrief.analytics.claim_numbers import values_match
from marketbrief.constants.verification import (ATTRIBUTION_OPINION, ATTRIBUTION_SOURCES_SAY, CLAIM_TYPE_OPINION,
                                                FIELD_TITLE,
                                                CLAIM_TYPE_PROMOTIONAL, CLAIM_TYPE_RUMOUR, FLAG_MISMATCH_PRIMARY,
                                                FLAG_OUTLET_VALUES_DISAGREE, FLAG_PRIMARY_DENIES,
                                                FLAG_PRIMARY_WITHOUT_VALUE, FLAG_STANCES_DISAGREE, FLAG_UNIT_MISMATCH,
                                                PRIMARY_SOURCE_KINDS, STATUS_CONFIRMED_PRIMARY, STATUS_CONTRADICTED,
                                                STATUS_CORROBORATED, STATUS_PRECEDENCE, STATUS_PROMOTIONAL,
                                                STATUS_RUMOUR, STATUS_SINGLE_SOURCE, STATUS_UNVERIFIED,
                                                STANCE_AFFIRMS, STANCE_DENIES)


def highest(statuses) -> str:
    """The status of highest precedence (unverified for none)."""
    return min(statuses, key=STATUS_PRECEDENCE.index, default=STATUS_UNVERIFIED)


def is_primary(statement: dict) -> bool:
    return statement["source_kind"] in PRIMARY_SOURCE_KINDS


def is_opinion(statement: dict) -> bool:
    return statement["claim_type"] == CLAIM_TYPE_OPINION or statement["attribution"] == ATTRIBUTION_OPINION


def is_promotional(statement: dict) -> bool:
    return statement["claim_type"] == CLAIM_TYPE_PROMOTIONAL


def is_rumour(statement: dict) -> bool:
    return statement["claim_type"] == CLAIM_TYPE_RUMOUR or statement["attribution"] == ATTRIBUTION_SOURCES_SAY


def has_value(statement: dict) -> bool:
    """A value that takes part in comparisons: stated with a unit, and not quoted from a headline."""
    return (statement.get("value_num") is not None and statement.get("unit") is not None
            and statement.get("quote_field") != FIELD_TITLE)


def same_period(first: str | None, second: str | None) -> bool:
    """Periods agree when either is missing or one contains the other ('Q3' and 'Q3 2026')."""
    a, b = ("".join((p or "").lower().split()) for p in (first, second))
    return not a or not b or a in b or b in a


def value_groups(statements: list[dict]) -> list[list[dict]]:
    """Numeric statements of one unit grouped by agreeing value (each joins the first group it matches)."""
    groups: list[list[dict]] = []
    for s in sorted(statements, key=lambda x: (x["value_num"], x["quote_source_id"])):
        for group in groups:
            head = group[0]
            if head["unit"] == s["unit"] and values_match((head["value_num"], head.get("value_text")),
                                                          (s["value_num"], s.get("value_text"))):
                group.append(s)
                break
        else:
            groups.append([s])
    return groups


def conflict_rows(groups: list[list[dict]]) -> list[dict]:
    """The disagreeing values for display: value (a primary source's when one states it), unit, the source
    ids stating it, and whether a primary did."""
    heads = [next((s for s in g if is_primary(s)), g[0]) for g in groups]
    return [{"value": h["value_num"], "unit": h["unit"], "ids": sorted({s["quote_source_id"] for s in g}),
             "primary": is_primary(h)} for h, g in zip(heads, groups)]


def _primary_checks(primary: list[dict], outlets: list[dict], result: dict) -> bool:
    """Primary statements against each other and the outlets; returns True when the fact is contradicted."""
    affirm = [s for s in primary if s["stance"] == STANCE_AFFIRMS]
    deny = [s for s in primary if s["stance"] == STANCE_DENIES]
    contradicted = bool(affirm and deny)
    if deny:
        affirming_outlets = [s for s in outlets if s["stance"] == STANCE_AFFIRMS]
        if affirming_outlets:
            contradicted = True
            result["flags"].add(FLAG_PRIMARY_DENIES)
            result["mismatch_ids"].update(n for s in affirming_outlets for n in s["news_ids"])
    values = [s for s in affirm if has_value(s)]
    if any(len(value_groups([s for s in values if s["unit"] == unit])) > 1 for unit in {s["unit"] for s in values}):
        contradicted = True
    for s in (x for x in outlets if has_value(x) and values):
        same_unit = [p for p in values if p["unit"] == s["unit"]]
        if not same_unit:
            result["flags"].add(FLAG_UNIT_MISMATCH)
        elif not any(values_match((p["value_num"], p.get("value_text")), (s["value_num"], s.get("value_text")))
                     and same_period(p.get("period"), s.get("period")) for p in same_unit):
            result["flags"].add(FLAG_MISMATCH_PRIMARY)
            result["mismatch_ids"].update(s["news_ids"])
    return contradicted


def _outlets_disagree(factual: list[dict], result: dict) -> bool:
    """Without primary confirmation: outlet values or stances that disagree."""
    affirming = [s for s in factual if s["stance"] == STANCE_AFFIRMS and has_value(s)]
    disagree = False
    for unit in sorted({s["unit"] for s in affirming}):
        if len(value_groups([s for s in affirming if s["unit"] == unit])) > 1:
            disagree = True
            result["flags"].add(FLAG_OUTLET_VALUES_DISAGREE)
    if {s["stance"] for s in factual} == {STANCE_AFFIRMS, STANCE_DENIES}:
        disagree = True
        result["flags"].add(FLAG_STANCES_DISAGREE)
    return disagree


def fact_status(statements: list[dict], verified_origin: dict[str, str]) -> dict:
    """Status of one fact from its statements. verified_origin: news id -> its verified origin group."""
    primary = [s for s in statements if is_primary(s)]
    outlets = [s for s in statements if not is_primary(s)]
    factual = [s for s in outlets if not is_opinion(s) and not is_promotional(s)]
    result = {"flags": set(), "mismatch_ids": set()}
    contradicted = _primary_checks(primary, outlets, result)
    affirm = [s for s in primary if s["stance"] == STANCE_AFFIRMS]
    primary_values = [s for s in affirm if has_value(s)]
    outlet_values = any(has_value(s) for s in factual)
    if affirm and not primary_values and outlet_values:
        result["flags"].add(FLAG_PRIMARY_WITHOUT_VALUE)
    confirmed = bool(affirm) and not contradicted and (bool(primary_values) or not outlet_values)
    if not contradicted and not confirmed:
        contradicted = _outlets_disagree(factual, result)
    origins = {verified_origin[n] for s in factual for n in s["news_ids"] if n in verified_origin}
    if contradicted:
        status = STATUS_CONTRADICTED
    elif confirmed:
        status = STATUS_CONFIRMED_PRIMARY
    elif len(origins) >= 2:
        status = STATUS_CORROBORATED
    elif any(is_rumour(s) for s in outlets):
        status = STATUS_RUMOUR
    elif any(is_promotional(s) for s in outlets):
        status = STATUS_PROMOTIONAL
    else:
        status = STATUS_SINGLE_SOURCE if origins else STATUS_UNVERIFIED
    numeric = [s for s in statements if has_value(s) and s["stance"] == STANCE_AFFIRMS]
    groups = [g for unit in sorted({s["unit"] for s in numeric})
              for g in value_groups([s for s in numeric if s["unit"] == unit])]
    return {"status": status, "flags": sorted(result["flags"]), "mismatch_ids": sorted(result["mismatch_ids"]),
            "primary_ids": sorted({s["quote_source_id"] for s in affirm}),
            "outlet_ids": sorted({n for s in outlets for n in s["news_ids"]}),
            "origins": sorted(origins), "conflicts": conflict_rows(groups) if len(groups) > 1 else [],
            "confirmed_at": min((s.get("source_published_at") or s["source_available_at"] for s in affirm),
                                default=None) if confirmed else None}


def verified_origins(cluster: dict) -> dict[str, str]:
    """News id -> origin label, for the cluster's verified origin groups (phase A)."""
    return {n: g["origin"] for g in cluster.get("origin_groups") or [] if g.get("verified") for n in g["news_ids"]}


def base_status(cluster: dict) -> str:
    """The status of a cluster row alone (no claims): its verified origins and flags."""
    flags, independent = set(cluster.get("flags") or []), int(cluster.get("independent_origins") or 0)
    if independent >= 2:
        return STATUS_CORROBORATED
    if "sources_say" in flags:
        return STATUS_RUMOUR
    if "promotional_provider" in flags and independent == 0:
        return STATUS_PROMOTIONAL
    return STATUS_SINGLE_SOURCE if independent == 1 else STATUS_UNVERIFIED


def id_statuses(cluster: dict, status: str, mismatch_ids: set[str]) -> dict[str, str]:
    """Each news id of the cluster with its own status: contradicted when it disagrees with a filing,
    promotional when its origin group is vendor content, unverified when its outlet is unvetted or it
    is opinion, else the cluster's status. An id never gets a status weaker than a blocking cluster
    status (rumour, promotional, contradicted): an unvetted copy of a rumour stays a rumour."""
    blocking = status in (STATUS_RUMOUR, STATUS_PROMOTIONAL, STATUS_CONTRADICTED)
    groups = cluster.get("origin_groups") or []
    promo = {n for g in groups if g.get("promotional") for n in g["news_ids"]}
    opinion = {n for g in groups if g.get("opinion") and not g.get("verified") for n in g["news_ids"]}
    unvetted = set(cluster.get("unvetted_ids") or [])
    out = {}
    for nid in [*(cluster.get("news_ids") or []), *(cluster.get("duplicate_ids") or [])]:
        if nid in mismatch_ids:
            out[nid] = STATUS_CONTRADICTED
        elif nid in promo:
            out[nid] = STATUS_PROMOTIONAL
        elif (nid in unvetted or nid in opinion) and not blocking:
            out[nid] = STATUS_UNVERIFIED
        else:
            out[nid] = status
    return out


def cluster_status(cluster: dict, statements: list[dict]) -> tuple[dict, dict[str, dict]]:
    """(cluster result, {fact_key: fact result}) for one cluster row and its claims."""
    origins = verified_origins(cluster)
    by_fact: dict[str, list[dict]] = {}
    for s in statements:
        by_fact.setdefault(s["fact_key"], []).append(s)
    facts = {key: fact_status(rows, origins) for key, rows in sorted(by_fact.items())}
    status = highest([base_status(cluster), *(f["status"] for f in facts.values())])
    mismatch = {n for f in facts.values() for n in f["mismatch_ids"]}
    confirmed = [f["confirmed_at"] for f in facts.values() if f["confirmed_at"] is not None]
    result = {"status": status, "flags": sorted({x for f in facts.values() for x in f["flags"]}),
              "mismatch_ids": sorted(mismatch),
              "primary_ids": sorted({p for f in facts.values() for p in f["primary_ids"]}),
              "outlet_ids": sorted({o for f in facts.values() for o in f["outlet_ids"]}),
              "conflicts": [c for f in facts.values() for c in f["conflicts"]],
              "confirmed_at": min(confirmed) if status == STATUS_CONFIRMED_PRIMARY and confirmed else None,
              "ids": id_statuses(cluster, status, mismatch)}
    return result, facts
