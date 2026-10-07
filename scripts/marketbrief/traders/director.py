"""The weekly research director's gate and report (docs/SPEC.md F6.2). Its proposals are approvable config diffs and
change nothing by themselves: the gate only checks that each diff applies to the file as it is now (`git apply` on a
copy in a temporary folder, outside any repository); nothing here ever writes a config file.

The director writes work/research_review.json:
`{"findings": [{"text", "cited_ids"}], "proposals": [{"proposal_id", "kind", "file", "diff", "rationale",
"cited_ids"}], "prompt_version": "director-v1"}`. Checks: findings 1-60 words and rationales 1-80 words, each citing
ids of the week's inputs (director_facts.citable), every number in them one of the cited records' numbers, no trade
advice; proposal ids p-<iso_week>-<n> in order; kind new_strategy_version | weight | threshold; file one of
PROPOSAL_FILES; the diff (unified, paths a/<file> b/<file>, with context lines) applies; for config/strategies.yaml
the result still parses and no live strategy (live_from set) changes: a change is a new id (an id's behaviour never
changes)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

from marketbrief.traders import constants as c
from marketbrief.traders import numbers
from marketbrief.traders.director_facts import citable

TRADE_ADVICE = re.compile(r"\b(buy now|sell now|strong buy|strong sell|recommend (?:buying|selling)|"
                          r"investment advice|price target)\b", re.I)
STRATEGIES = "config/strategies.yaml"


def flat_numbers(value, out: list) -> list:
    """Every number inside a record (nested JSON included)."""
    if isinstance(value, str) and value[:1] in "{[":
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return out
    if isinstance(value, dict):
        for inner in value.values():
            flat_numbers(inner, out)
    elif isinstance(value, list):
        for inner in value:
            flat_numbers(inner, out)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out.append((float(value), True, "cited"))
    return out


def text_errors(where: str, text, words: int, cited, known: dict) -> list[str]:
    """Word count, cited ids known, numbers from the cited records, no trade advice."""
    count = len(text.split()) if isinstance(text, str) else 0
    if not 1 <= count <= words:
        return [c.MSG_DIRECTOR_WORDS.format(where=where, words=words, count=count)]
    if not isinstance(cited, list) or not cited:
        return [c.MSG_DIRECTOR_FIELD.format(where=where, field="cited_ids")]
    errors = []
    unknown = [i for i in cited if i not in known]
    if unknown:
        errors.append(c.MSG_DIRECTOR_CITE.format(where=where, ids=unknown))
    facts = []
    for cited_id in cited:
        flat_numbers(known.get(cited_id, {}), facts)
    unmatched = numbers.problems(text, facts, list(cited))
    if unmatched:
        errors.append(f"{where}: " + c.MSG_EOD_NUMBER.format(numbers=unmatched))
    advice = TRADE_ADVICE.search(text)
    if advice:
        errors.append(f"{where}: " + c.MSG_EOD_ADVICE.format(word=advice.group(0)))
    return errors


def applied(file: str, current: str, diff: str) -> tuple[str | None, str]:
    """(the file after the diff, '') or (None, git's message); never touches the repo."""
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(current, encoding="utf-8")
        patch = Path(folder) / "proposal.diff"
        patch.write_text(diff if diff.endswith("\n") else diff + "\n", encoding="utf-8")
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(folder).parent)}   # never find an enclosing repo
        result = subprocess.run(["git", "apply", "--whitespace=nowarn", "proposal.diff"], cwd=folder, env=env,
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None, (result.stderr.strip() or result.stdout.strip())[:300]
        return target.read_text(encoding="utf-8"), ""


def live_changes(before: str, after: str) -> list[str]:
    """Ids of live strategies (live_from set) whose entry differs after the change (or that disappear)."""
    old = {s["id"]: s for s in yaml.safe_load(before)["strategies"]}
    new = {s["id"]: s for s in (yaml.safe_load(after) or {}).get("strategies", [])}
    return sorted(i for i, entry in old.items() if entry.get("live_from") and new.get(i) != entry)


def proposal_errors(number: int, proposal, facts: dict, known: dict) -> list[str]:
    """One proposal: id, kind, file, the diff applies, the rationale."""
    if not isinstance(proposal, dict):
        return [f"proposal {number}: not a JSON object"]
    want = f"p-{facts['iso_week']}-{number}"
    errors = [] if proposal.get("proposal_id") == want else [c.MSG_DIRECTOR_ID.format(got=proposal.get("proposal_id"),
                                                                                     want=want)]
    if proposal.get("kind") not in c.PROPOSAL_KINDS:
        errors.append(c.MSG_EOD_ENUM.format(field="kind", value=proposal.get("kind"), allowed=list(c.PROPOSAL_KINDS)))
    file = proposal.get("file")
    if file not in c.PROPOSAL_FILES:
        return errors + [c.MSG_DIRECTOR_FILE.format(pid=want, file=file, allowed=list(c.PROPOSAL_FILES))]
    diff = proposal.get("diff")
    if not isinstance(diff, str) or f"--- a/{file}" not in diff or f"+++ b/{file}" not in diff:
        errors.append(c.MSG_DIRECTOR_DIFF.format(pid=want, file=file, detail=f"needs --- a/{file} and +++ b/{file}"))
    else:
        after, message = applied(file, facts["config_files"][file], diff)
        if after is None:
            errors.append(c.MSG_DIRECTOR_DIFF.format(pid=want, file=file, detail=message))
        elif file == STRATEGIES:
            try:
                changed = live_changes(facts["config_files"][file], after)
            except (yaml.YAMLError, AttributeError, KeyError, TypeError) as error:
                changed = [f"(does not parse: {error})"]
            if changed:
                errors.append(c.MSG_DIRECTOR_NEW_ID.format(pid=want, ids=changed))
    return errors + text_errors(f"proposal {want}", proposal.get("rationale"), c.RATIONALE_WORDS,
                                proposal.get("cited_ids"), known)


def validate(review, facts: dict) -> list[str]:
    """Every problem of the director's file (empty = it passes)."""
    if not isinstance(review, dict):
        return ["not a JSON object"]
    errors = [c.MSG_UNKNOWN_FIELD.format(field=k) for k in review if k not in ("findings", "proposals",
                                                                              "prompt_version")]
    if review.get("prompt_version") != c.DIRECTOR_PROMPT_VERSION:
        errors.append(c.MSG_EOD_PROMPT.format(want=c.DIRECTOR_PROMPT_VERSION))
    known = citable(facts)
    findings, proposals = review.get("findings"), review.get("proposals")
    if not isinstance(findings, list) or not isinstance(proposals, list):
        return errors + ["findings and proposals must be lists (empty is allowed)"]
    for number, finding in enumerate(findings, 1):
        finding = finding if isinstance(finding, dict) else {}
        errors += text_errors(f"finding {number}", finding.get("text"), c.FINDING_WORDS, finding.get("cited_ids"),
                              known)
    for number, proposal in enumerate(proposals, 1):
        errors += proposal_errors(number, proposal, facts, known)
    return errors
