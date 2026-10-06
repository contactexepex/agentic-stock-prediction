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
A cluster's status is the highest of its base status (the cluster row alone) and the statuses of the
facts its outlet items state. A fact stated only by a primary source (no outlet item affirms it, e.g. a
share allotment filed beside an unconfirmed story) keeps its own row, flagged primary_only, but never
raises the cluster's status or confirmed_at, nor adds its primary ids to the confirming ids."""

from __future__ import annotations

from marketbrief.analytics.claim_numbers import values_match
from marketbrief.constants.verification import (
    ATTRIBUTION_OPINION,
    ATTRIBUTION_SOURCES_SAY,
    CLAIM_TYPE_OPINION,
    CLAIM_TYPE_PROMOTIONAL,
    CLAIM_TYPE_RUMOUR,
    FIELD_TITLE,
    FLAG_MISMATCH_PRIMARY,
    FLAG_OUTLET_VALUES_DISAGREE,
    FLAG_PRIMARY_DENIES,
    FLAG_PRIMARY_ONLY,
    FLAG_PRIMARY_WITHOUT_VALUE,
    FLAG_STANCES_DISAGREE,
    FLAG_UNIT_MISMATCH,
    PRIMARY_SOURCE_KINDS,
    STATUS_CONFIRMED_PRIMARY,
    STATUS_CONTRADICTED,
    STATUS_CORROBORATED,
    STATUS_PRECEDENCE,
    STATUS_PROMOTIONAL,
    STATUS_RUMOUR,
    STATUS_SINGLE_SOURCE,
    STATUS_UNVERIFIED,
    STANCE_AFFIRMS,
    STANCE_DENIES,
)


def highest(statuses) -> str:
    """The status of highest precedence (unverified for none)."""
    return min(statuses, key=STATUS_PRECEDENCE.index, default=STATUS_UNVERIFIED)


def is_primary(statement: dict) -> bool:
    """True when the statement comes from a primary source."""
    return statement["source_kind"] in PRIMARY_SOURCE_KINDS


def is_opinion(statement: dict) -> bool:
    """True for an opinion or an attributed opinion."""
    return statement["claim_type"] == CLAIM_TYPE_OPINION or statement["attribution"] == ATTRIBUTION_OPINION


def is_promotional(statement: dict) -> bool:
    """True for a promotional statement."""
    return statement["claim_type"] == CLAIM_TYPE_PROMOTIONAL


def is_rumour(statement: dict) -> bool:
    """True for a rumour or an attributed rumour."""
    return statement["claim_type"] == CLAIM_TYPE_RUMOUR or statement["attribution"] == ATTRIBUTION_SOURCES_SAY


def has_value(statement: dict) -> bool:
    """A value that takes part in comparisons: stated with a unit, and not quoted from a headline."""
    return (
        statement.get("value_num") is not None
        and statement.get("unit") is not None
        and statement.get("quote_field") != FIELD_TITLE
    )


def same_period(first: str | None, second: str | None) -> bool:
    """Periods agree when either is missing or one contains the other ('Q3' and 'Q3 2026')."""
    first_text, second_text = ("".join((period or "").lower().split()) for period in (first, second))
    return not first_text or not second_text or first_text in second_text or second_text in first_text


def value_groups(statements: list[dict]) -> list[list[dict]]:
    """Numeric statements of one unit grouped by agreeing value (each joins the first group it matches)."""
    groups: list[list[dict]] = []
    for statement in sorted(statements, key=lambda item: (item["value_num"], item["quote_source_id"])):
        for group in groups:
            head = group[0]
            if head["unit"] == statement["unit"] and values_match(
                (head["value_num"], head.get("value_text")), (statement["value_num"], statement.get("value_text"))
            ):
                group.append(statement)
                break
        else:
            groups.append([statement])
    return groups


def conflict_rows(groups: list[list[dict]]) -> list[dict]:
    """The disagreeing values for display: value (a primary source's when one states it), unit, the source
    ids stating it, and whether a primary did."""
    heads = [next((statement for statement in group if is_primary(statement)), group[0]) for group in groups]
    return [
        {
            "value": horizon["value_num"],
            "unit": horizon["unit"],
            "ids": sorted({statement["quote_source_id"] for statement in group}),
            "primary": is_primary(horizon),
        }
        for horizon, group in zip(heads, groups)
    ]


def _primary_checks(primary: list[dict], outlets: list[dict], result: dict) -> bool:
    """Primary statements against each other and the outlets; returns True when the fact is contradicted."""
    affirm = [statement for statement in primary if statement["stance"] == STANCE_AFFIRMS]
    deny = [statement for statement in primary if statement["stance"] == STANCE_DENIES]
    contradicted = bool(affirm and deny)
    if deny:
        affirming_outlets = [statement for statement in outlets if statement["stance"] == STANCE_AFFIRMS]
        if affirming_outlets:
            contradicted = True
            result["flags"].add(FLAG_PRIMARY_DENIES)
            result["mismatch_ids"].update(
                news_id for statement in affirming_outlets for news_id in statement["news_ids"]
            )
    values = [statement for statement in affirm if has_value(statement)]
    if any(
        len(value_groups([statement for statement in values if statement["unit"] == unit])) > 1
        for unit in {statement["unit"] for statement in values}
    ):
        contradicted = True
    for statement in (outlet_statement for outlet_statement in outlets if has_value(outlet_statement) and values):
        same_unit = [
            primary_statement for primary_statement in values if primary_statement["unit"] == statement["unit"]
        ]
        if not same_unit:
            result["flags"].add(FLAG_UNIT_MISMATCH)
        elif not any(
            values_match(
                (primary_statement["value_num"], primary_statement.get("value_text")),
                (statement["value_num"], statement.get("value_text")),
            )
            and same_period(primary_statement.get("period"), statement.get("period"))
            for primary_statement in same_unit
        ):
            result["flags"].add(FLAG_MISMATCH_PRIMARY)
            result["mismatch_ids"].update(statement["news_ids"])
    return contradicted


def _outlets_disagree(factual: list[dict], result: dict) -> bool:
    """Without primary confirmation: outlet values or stances that disagree."""
    affirming = [statement for statement in factual if statement["stance"] == STANCE_AFFIRMS and has_value(statement)]
    disagree = False
    for unit in sorted({statement["unit"] for statement in affirming}):
        if len(value_groups([statement for statement in affirming if statement["unit"] == unit])) > 1:
            disagree = True
            result["flags"].add(FLAG_OUTLET_VALUES_DISAGREE)
    if {statement["stance"] for statement in factual} == {STANCE_AFFIRMS, STANCE_DENIES}:
        disagree = True
        result["flags"].add(FLAG_STANCES_DISAGREE)
    return disagree


def fact_status(statements: list[dict], verified_origin: dict[str, str]) -> dict:
    """Status of one fact from its statements. verified_origin: news id -> its verified origin group."""
    primary = [statement for statement in statements if is_primary(statement)]
    outlets = [statement for statement in statements if not is_primary(statement)]
    factual = [statement for statement in outlets if not is_opinion(statement) and not is_promotional(statement)]
    result = {"flags": set(), "mismatch_ids": set()}
    contradicted = _primary_checks(primary, outlets, result)
    affirm = [statement for statement in primary if statement["stance"] == STANCE_AFFIRMS]
    primary_values = [statement for statement in affirm if has_value(statement)]
    outlet_values = any(has_value(statement) for statement in factual)
    if affirm and not primary_values and outlet_values:
        result["flags"].add(FLAG_PRIMARY_WITHOUT_VALUE)
    confirmed = bool(affirm) and not contradicted and (bool(primary_values) or not outlet_values)
    if not contradicted and not confirmed:
        contradicted = _outlets_disagree(factual, result)
    origins = {
        verified_origin[news_id]
        for statement in factual
        for news_id in statement["news_ids"]
        if news_id in verified_origin
    }
    if contradicted:
        status = STATUS_CONTRADICTED
    elif confirmed:
        status = STATUS_CONFIRMED_PRIMARY
    elif len(origins) >= 2:
        status = STATUS_CORROBORATED
    elif any(is_rumour(statement) for statement in outlets):
        status = STATUS_RUMOUR
    elif any(is_promotional(statement) for statement in outlets):
        status = STATUS_PROMOTIONAL
    else:
        status = STATUS_SINGLE_SOURCE if origins else STATUS_UNVERIFIED
    numeric = [statement for statement in statements if has_value(statement) and statement["stance"] == STANCE_AFFIRMS]
    groups = [
        group
        for unit in sorted({statement["unit"] for statement in numeric})
        for group in value_groups([statement for statement in numeric if statement["unit"] == unit])
    ]
    return {
        "status": status,
        "flags": sorted(result["flags"]),
        "mismatch_ids": sorted(result["mismatch_ids"]),
        "primary_ids": sorted({statement["quote_source_id"] for statement in affirm}),
        "outlet_ids": sorted({news_id for statement in outlets for news_id in statement["news_ids"]}),
        "origins": sorted(origins),
        "conflicts": conflict_rows(groups) if len(groups) > 1 else [],
        "confirmed_at": min(
            (statement.get("source_published_at") or statement["source_available_at"] for statement in affirm),
            default=None,
        )
        if confirmed
        else None,
    }


def verified_origins(cluster: dict) -> dict[str, str]:
    """News id -> origin label, for the cluster's verified origin groups (phase A)."""
    return {
        news_id: group["origin"]
        for group in cluster.get("origin_groups") or []
        if group.get("verified")
        for news_id in group["news_ids"]
    }


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
    promo = {news_id for group in groups if group.get("promotional") for news_id in group["news_ids"]}
    opinion = {
        news_id
        for group in groups
        if group.get("opinion") and not group.get("verified")
        for news_id in group["news_ids"]
    }
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
    for statement in statements:
        by_fact.setdefault(statement["fact_key"], []).append(statement)
    facts = {key: fact_status(rows, origins) for key, rows in sorted(by_fact.items())}
    for key, fact in facts.items():
        if not any(not is_primary(statement) and statement["stance"] == STANCE_AFFIRMS for statement in by_fact[key]):
            fact["flags"] = sorted({*fact["flags"], FLAG_PRIMARY_ONLY})
    event = [
        fact_result for fact_result in facts.values() if FLAG_PRIMARY_ONLY not in fact_result["flags"]
    ]  # facts the outlets state
    status = highest([base_status(cluster), *(fact_result["status"] for fact_result in event)])
    mismatch = {news_id for fact_result in event for news_id in fact_result["mismatch_ids"]}
    confirmed = [fact_result["confirmed_at"] for fact_result in event if fact_result["confirmed_at"] is not None]
    result = {
        "status": status,
        "flags": sorted({flag for fact_result in event for flag in fact_result["flags"]}),
        "mismatch_ids": sorted(mismatch),
        "primary_ids": sorted({primary_id for fact_result in event for primary_id in fact_result["primary_ids"]}),
        "outlet_ids": sorted({outlet_id for fact_result in event for outlet_id in fact_result["outlet_ids"]}),
        "conflicts": [conflict for fact_result in event for conflict in fact_result["conflicts"]],
        "confirmed_at": min(confirmed) if status == STATUS_CONFIRMED_PRIMARY and confirmed else None,
        "ids": id_statuses(cluster, status, mismatch),
    }
    return result, facts
