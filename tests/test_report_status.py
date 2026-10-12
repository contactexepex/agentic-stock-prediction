"""Issue #460: a news status word in the report's agent-written text must be a stored status of the news ids it
describes as of the run (validate.py --stage report, REPORT_STATUS; marketbrief/pipeline/validate/report_status.py)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.core.database import connect  # noqa: E402
from marketbrief.pipeline.validate import report_checks  # noqa: E402
from marketbrief.pipeline.validate.gate_result import Result  # noqa: E402
from marketbrief.pipeline.validate.report_status import status_claims, wrong_statuses  # noqa: E402
import test_validate  # noqa: E402
from test_news_status_rules import status_row  # noqa: E402
from test_validate import MARKET, write_jsonl  # noqa: E402

TSLA_ID = "cced5d4b933d5106"
NVDA_ID = "ab389b7d388dcec8"
EVENT_ID = "7083623705480959"
NOW = pd.Timestamp("2026-10-07T12:30:00+00:00")


@pytest.fixture
def root(tmp_path, monkeypatch):
    """test_validate's synthetic US tree with status rows: TSLA_ID unverified, NVDA_ID single_source; EVENT_ID is
    promotional itself in an event (cluster) whose status is rumour."""
    tree = test_validate.root.__wrapped__(tmp_path, monkeypatch)
    write_jsonl(tree, "news_verified", date(2026, 10, 7), [
        status_row([TSLA_ID], ["unverified"], as_of="2026-10-07T04:40:00+00:00", cluster_id="TSLA-x", ticker="TSLA"),
        status_row([NVDA_ID], ["single_source"], as_of="2026-10-07T04:40:00+00:00", cluster_id="NVDA-x",
                   ticker="NVDA"),
        {**status_row([EVENT_ID], ["promotional"], as_of="2026-10-07T04:40:00+00:00", cluster_id="AAPL-r"),
         "status": "rumour"},
    ])
    write_jsonl(tree, "news_clusters", date(2026, 10, 7), [{
        "id": "AAPL-r@1", "as_of": "2026-10-07T04:30:00+00:00", "cluster_id": "AAPL-r", "ticker": "AAPL",
        "news_ids": [EVENT_ID], "duplicate_ids": [], "n_items": 1, "inputs_until": "2026-10-07T04:30:00+00:00"}])
    return tree


def checked(lines: list[str], now=NOW) -> tuple[list[dict], list[dict]]:
    return wrong_statuses(connect(MARKET), lines, now)


@pytest.mark.usefixtures("root")
def test_issue_460_wrong_words_are_found():
    wrong, _ = checked([
        f"Tesla's deliveries are confirmed by its 8-K (0001628280-26-064366); the merger talk is only a rumour "
        f"({TSLA_ID}).",
        f"Bear: NVDA is stretched, and the chip-financing story is unverified ({NVDA_ID}).",
    ])
    assert [(item["id"], item["word"], item["stored"]) for item in wrong] == [
        (TSLA_ID, "rumour", ["unverified"]), (NVDA_ID, "unverified", ["single_source"])]


@pytest.mark.usefixtures("root")
@pytest.mark.parametrize("line", [
    f"The merger talk is unverified ({TSLA_ID}).",
    f"The merger talk ({TSLA_ID}, unverified) cannot support a call.",
    f"The chip story is single-source ({NVDA_ID}).",
    f"The news is single_source or unverified ({NVDA_ID}, {TSLA_ID}).",
    f"The merger talk is not a rumour yet but unverified ({TSLA_ID}).",
    f"AAPL fell on an order-cut report that is only a rumour ({EVENT_ID}).",     # the event's status
    f"AAPL fell on an order-cut report ({EVENT_ID}, promotional).",              # the id's own status
    f"Its deliveries are confirmed by the 8-K (0001628280-26-064366, confirmed by the company) ({TSLA_ID}).",
])
def test_true_words_pass(line):
    assert checked([line])[0] == []


@pytest.mark.usefixtures("root")
def test_word_pairs_with_its_own_parentheses_not_the_next_id():
    """'(<id>, promotional)' describes that id, never the id cited later in the sentence."""
    wrong, _ = checked([f"Bull: a target was raised ({EVENT_ID}, promotional); TSLA named a CEO ({TSLA_ID})."])
    assert wrong == []
    wrong, _ = checked([f"Bull: a target was raised ({TSLA_ID}, promotional); AAPL named a CEO ({EVENT_ID})."])
    assert [(item["id"], item["stored"]) for item in wrong] == [(TSLA_ID, ["unverified"])]


def test_status_word_without_an_id_is_uncited():
    claims, uncited = status_claims(["Bear: the delivery beat looks priced, and its merger talk is rumour only.",
                                     f"Background ({TSLA_ID}) moved; the talk is a rumour."])
    assert claims == [] and [item["word"] for item in uncited] == ["rumour", "rumour"]


@pytest.mark.usefixtures("root")
def test_unknown_id_is_unverified_and_nothing_is_checked_before_the_feature():
    other = "0123456789abcdef"
    assert checked([f"A rumour ({other})."])[0][0]["stored"] == ["unverified"]
    assert checked([f"A story that is unverified ({other})."])[0] == []
    assert checked([f"A rumour ({TSLA_ID})."], now=pd.Timestamp("2026-10-07T04:00:00+00:00")) == ([], [])


def test_report_stage_blocks_a_wrong_word_and_warns_on_an_uncited_one(root):
    res = Result()
    report = root / "reports" / MARKET / "2026-10-07.md"
    lines = [f"The merger talk is only a rumour ({TSLA_ID}).", "Its merger talk is rumour only."]
    report_checks.check_statuses(res, connect(MARKET), NOW, report, lines, True)
    assert [item["code"] for item in res.failures] == ["REPORT_STATUS"]
    assert TSLA_ID in res.failures[0]["detail"] and "unverified" in res.failures[0]["detail"]
    assert [item["code"] for item in res.warnings] == ["REPORT_STATUS_UNCITED"]
    slack = Result()
    report_checks.check_statuses(slack, connect(MARKET), NOW, report, lines[1:], False)   # Slack draft: no warning
    assert slack.failures == [] and slack.warnings == []
