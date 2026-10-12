"""Report stage, issue #460: a news verification status word in agent-written text must be a stored status of
the news ids it describes, as of the run.

A status word (rumour, unverified, single-source, corroborated, promotional, contradicted, confirmed_primary) is
paired with the news ids (16-hex) of the parentheses it is written in ("(<id>, unverified)"), else with the first
parenthesised group of news ids after it in the same sentence ("only a rumour (<id>)"); every news id of that
group must have that status as of now, either its own (news_status_ids_asof, any ticker) or that of an event
(cluster status row of news_verified_asof) listing it, the status the context pack's events table shows. An id
with neither is unverified. A word after a
negation ("not a rumour", "no longer unverified") is not checked; alternatives ("single_source or unverified")
pass when the id has one of them. Plain "confirmed" is not checked (everyday
English: "the company confirmed"); templates/report.md keeps it for confirmed_primary. A status word with no news id
after it in its sentence cannot be checked: a warning for the report (the Slack draft may leave ids out)."""

from __future__ import annotations

import re

import pandas as pd

from marketbrief.constants.verification import (
    STATUS_CONFIRMED_PRIMARY,
    STATUS_CONTRADICTED,
    STATUS_CORROBORATED,
    STATUS_PROMOTIONAL,
    STATUS_RUMOUR,
    STATUS_SINGLE_SOURCE,
    STATUS_UNVERIFIED,
)

ACTIVE_SQL = "SELECT count(*) FROM news_verified WHERE as_of <= ?::TIMESTAMPTZ"
STORED_SQL = """
SELECT news_id, status FROM news_status_ids_asof(?::TIMESTAMPTZ)
UNION
SELECT unnest(list_concat(c.news_ids, coalesce(c.duplicate_ids, []))) AS news_id, v.status
FROM news_clusters_asof(?::TIMESTAMPTZ) c JOIN news_verified_asof(?::TIMESTAMPTZ) v USING (cluster_id)
WHERE v.level = 'cluster'"""

STATUS_WORDS = (
    (re.compile(r"\brumou?r(?:s|ed)?\b", re.IGNORECASE), STATUS_RUMOUR),
    (re.compile(r"\bunverified\b", re.IGNORECASE), STATUS_UNVERIFIED),
    (re.compile(r"\bsingle[ _-]sourced?\b", re.IGNORECASE), STATUS_SINGLE_SOURCE),
    (re.compile(r"\bcorroborated\b", re.IGNORECASE), STATUS_CORROBORATED),
    (re.compile(r"\bpromotional\b", re.IGNORECASE), STATUS_PROMOTIONAL),
    (re.compile(r"\bcontradicted\b", re.IGNORECASE), STATUS_CONTRADICTED),
    (re.compile(r"\bconfirmed[ _-]primary\b", re.IGNORECASE), STATUS_CONFIRMED_PRIMARY),
)
NEWS_ID = re.compile(r"\b[0-9a-f]{16}\b")
GROUP = re.compile(r"\(([^()]*)\)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
NEGATIONS = {"not", "no", "never", "nor", "isn't", "wasn't", "aren't", "weren't", "isn’t", "wasn’t"}
NEGATION_WINDOW = 3   # words before the status word
ALTERNATIVE = re.compile(r"\s*(?:or|/)\s*", re.IGNORECASE)


def negated(sentence: str, start: int) -> bool:
    """True when one of the NEGATION_WINDOW words before the status word negates it."""
    before = re.findall(r"[\w'’]+", sentence[:start].lower())[-NEGATION_WINDOW:]
    return any(word in NEGATIONS for word in before)


def word_runs(sentence: str) -> list[tuple[int, int, list[str], list[str]]]:
    """(start, end, words, statuses) of the sentence's status words in order; alternatives joined by "or" or "/"
    ("single_source or unverified") form one run, which any of its statuses satisfies."""
    found = sorted(
        (word.start(), word.end(), word.group(0), status)
        for pattern, status in STATUS_WORDS
        for word in pattern.finditer(sentence)
    )
    runs: list[tuple[int, int, list[str], list[str]]] = []
    for start, end, word, status in found:
        if runs and ALTERNATIVE.fullmatch(sentence[runs[-1][1]:start]):
            first, _end, words, statuses = runs[-1]
            runs[-1] = (first, end, [*words, word], [*statuses, status])
        else:
            runs.append((start, end, [word], [status]))
    return runs


def status_claims(lines: list[str]) -> tuple[list[dict], list[dict]]:
    """(claims, uncited): each status word (or run of alternatives) with the news ids it describes and its sentence;
    the status words with no news id to pair with."""
    claims, uncited = [], []
    for line in lines:
        for sentence in SENTENCE_END.split(line.strip()):
            groups = [
                (match.start(), match.end(), NEWS_ID.findall(match.group(1))) for match in GROUP.finditer(sentence)
            ]
            for start, end, words, statuses in word_runs(sentence):
                if negated(sentence, start):
                    continue
                inside = next((found for first, last, found in groups if first < start < last), None)
                ids = inside if inside is not None else next(
                    (found for first, _last, found in groups if first >= end and found), None
                )
                entry = {"word": " or ".join(words), "statuses": statuses, "sentence": sentence}
                if ids:
                    claims.append({**entry, "ids": ids})
                else:
                    uncited.append(entry)
    return claims, uncited


def wrong_statuses(con, lines: list[str], now) -> tuple[list[dict], list[dict]]:
    """(mismatches, uncited): each (id, word) whose stored statuses as of now (own or event) lack the word's status;
    nothing is checked before the first status row (the feature was not running)."""
    claims, uncited = status_claims(lines)
    stamp = pd.Timestamp(now).isoformat()
    if not claims or not con.execute(ACTIVE_SQL, [stamp]).fetchone()[0]:
        return [], uncited
    table: dict[str, set[str]] = {}
    for news_id, status in con.execute(STORED_SQL, [stamp, stamp, stamp]).fetchall():
        table.setdefault(news_id, set()).add(status)
    mismatches = []
    for claim in claims:
        for news_id in claim["ids"]:
            stored = table.get(news_id) or {STATUS_UNVERIFIED}
            if not stored & set(claim["statuses"]):
                mismatches.append({**claim, "id": news_id, "stored": sorted(stored)})
    return mismatches, uncited
