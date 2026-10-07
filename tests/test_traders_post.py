"""Post-close and weekly parts of B3 (docs/SPEC.md F6; settling is B2's `lab.py settle`): the EOD analyst's facts and
gate (ids, numbers, enums, no advice), the research director's gate (diffs that apply, nothing applied), the track
record by band and the per-horizon inputs. Data are W1's example records written to a scratch root. Offline."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from traders_fixtures import REPO, catalogue

from marketbrief.core import paths
from marketbrief.core.database import connect
from marketbrief.traders import director, director_facts, director_report, eod, eod_facts, eod_gate, track_record
from marketbrief.traders.inputs import InputsUnavailableError, per_horizon

INDIA_DAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc)


def put(root: Path, market: str, kind: str, day: str, rows: list[dict]) -> None:
    path = root / "data" / market / kind / day[:4] / day[5:7] / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A scratch root holding W1's example settled trades (both markets)."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    for row in catalogue("paper_trade"):
        put(tmp_path, row["market"], "paper_trades_settled", row["settled_at"][:10],
            [{k: v for k, v in row.items() if not k.startswith("_")}])
    return tmp_path


def india_facts() -> dict:
    return eod_facts.eod_facts(connect("india"), "india", INDIA_DAY, NOW)


def reason_line(item: dict, text: str, cited=None) -> dict:
    return {"id": item["reason_id"], "trade_id": item["trade_id"], "kind": item["kind"], "text": text,
            "cited_ids": cited or [item["trade_id"]], "prompt_version": "eod-v1"}


@pytest.mark.usefixtures("root")
def test_eod_facts_match_the_w1_example_day():
    facts = india_facts()
    example = next(r for r in catalogue("eod_analysis") if r["id"] == "eod-india-2026-10-06")
    assert facts["settled_trades"] == example["settled_trades"] == 11
    assert {k: {"trades": v["trades"], "net_pnl": v["net_pnl"]} for k, v in facts["results"].items()
            if v["trades"]} == {k: {"trades": v["trades"], "net_pnl": v["net_pnl"]}
                                for k, v in example["results"].items() if v["trades"]}
    assert sorted(i["reason_id"] for i in facts["items"]) == sorted(example["reason_ids"])
    wins = [i for i in facts["items"] if i["kind"] == "biggest_win"]
    assert [i["rank"] for i in wins] == [1, 2, 3, 4, 5]
    assert [i["return_pct"] for i in wins] == sorted((i["return_pct"] for i in wins), reverse=True)   # ties: trade id


@pytest.mark.usefixtures("root")
def test_eod_gate_accepts_the_example_reason_and_refuses_bad_ones():
    facts = india_facts()
    item = facts["items"][0]
    example = next(r for r in catalogue("reason_ai") if r["id"] == item["reason_id"])
    good = reason_line(item, example["text"], example["cited_ids"])
    others = [reason_line(i, f"{i['ticker']} trade settled with a net result of {i['net_pnl']}.")
              for i in facts["items"][1:]]
    summary = {"type": "summary", "summary": f"{facts['settled_trades']} paper trades settled today.",
               "cited_ids": [item["trade_id"]], "prompt_version": "eod-v1"}
    valid, kept, errors = eod_gate.validate([good, *others, summary], facts)
    assert errors == [] and len(valid) == len(facts["items"]) and kept == summary

    def problems(line):
        rest = [*others, summary]
        return [e for e in eod_gate.validate([line, *rest], facts)[2] if e["id"] == item["reason_id"]]

    wrong_number = reason_line(item, example["text"].replace("+3.05%", "+3.50%"), example["cited_ids"])
    assert "numbers that match none" in json.dumps(problems(wrong_number))
    wrong_sign = reason_line(item, example["text"].replace("+0.46", "-0.46"), example["cited_ids"])
    assert "(sign)" in json.dumps(problems(wrong_sign))
    invented = reason_line(item, "Verified news nse-ann-9999999 moved it.", [item["trade_id"], "nse-ann-9999999"])
    assert "not among the trade's id" in json.dumps(problems(invented))
    uncited = reason_line(item, "Verified news nse-ann-7781203 moved it.")
    assert "not cited" in json.dumps(problems(uncited))
    advice = reason_line(item, "The stock should rise further, so traders should hold it.")
    assert "must not advise" in json.dumps(problems(advice))
    enum = {**reason_line(item, "Settled."), "kind": "biggest_loss"}
    assert any(e["errors"] for e in eod_gate.validate([enum, *others, summary], facts)[2])
    too_long = reason_line(item, "word " * 61)
    assert "1-60 words" in json.dumps(problems(too_long))
    missing = eod_gate.validate([*others, summary], facts)[2]
    assert any("no reason for" in " ".join(e["errors"]) for e in missing)
    no_summary = eod_gate.validate([good, *others], facts)[2]
    assert any(e["id"] == "summary" for e in no_summary)


@pytest.mark.usefixtures("root")
def test_eod_store_writes_reasons_and_the_analysis_from_stored_facts():
    facts = india_facts()
    lines = [reason_line(i, f"{i['ticker']} settled; net {i['net_pnl']}.") for i in facts["items"]]
    summary = {"type": "summary", "summary": "Eleven trades.", "cited_ids": [], "prompt_version": "eod-v1"}
    good, kept, errors = eod_gate.validate([*lines, summary], facts)
    assert errors == []
    written = eod.store(facts, good, kept, "2026-10-06T12:40:00Z", INDIA_DAY)
    assert written["reasons"] == 11 and written["analysis"] == 1
    again = india_facts()
    assert again["items"] == [] and again["summary_stored"] is True
    rows = [json.loads(x) for x in Path(written["files"][0]).read_text().splitlines()]
    assert rows[0]["settlement_id"].startswith(rows[0]["trade_id"] + "@") and rows[0]["rank"] is None


@pytest.mark.usefixtures("root")
def test_quiet_day_needs_no_analyst():
    facts = eod_facts.eod_facts(connect("india"), "india", date(2026, 10, 7), NOW)
    good, summary, errors = eod_gate.validate([], facts)
    assert facts["settled_trades"] == 0 and errors == []
    written = eod.store(facts, good, summary, "2026-10-07T12:40:00Z", date(2026, 10, 7))
    row = json.loads(Path(written["files"][0]).read_text())
    assert row["summary"] == "No paper trades settled on 2026-10-07."


@pytest.mark.usefixtures("root")
def test_track_record_bands_from_settled_ai_trades():
    bands = track_record.load(connect("us"), datetime(2026, 10, 7, tzinfo=timezone.utc))
    rows = [r for r in catalogue("paper_trade") if r["market"] == "us" and r["family"] == "ai"
            and r["view"] == "accuracy" and r["status"] == "settled"]
    assert sum(cell["n"] for b in bands.values() for cell in b.values()) == len(rows)
    assert sum(cell["hits"] for b in bands.values() for cell in b.values()) == sum(r["gross_pnl"] > 0 for r in rows)
    assert track_record.refusal(0.55, {"0.50-0.60": {"n": 20, "hits": 9, "hit_rate": 0.45, "low": 0.5}})
    assert track_record.refusal(0.55, {"0.50-0.60": {"n": 20, "hits": 10, "hit_rate": 0.5, "low": 0.5}}) is None


def test_per_horizon_inputs_wait_for_b10():
    with pytest.raises(InputsUnavailableError):
        per_horizon("us", NOW)


def director_inputs() -> dict:
    return director_facts.director_facts(connect("us"), "us", date(2026, 10, 6),
                                         datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc))


def new_strategy_diff() -> str:
    text = (REPO / "config" / "strategies.yaml").read_text().splitlines()
    last = len(text)
    lines = ["--- a/config/strategies.yaml", "+++ b/config/strategies.yaml", f"@@ -{last},1 +{last},4 @@",
             " " + text[-1], "+  - id: rule.model_news_p57.v1", "+    family: rule", "+    threshold: 0.57"]
    return "\n".join(lines) + "\n"


@pytest.mark.usefixtures("root")
def test_director_gate_checks_diffs_and_changes_nothing():
    facts = director_inputs()
    leader = facts["leaders_to_date"][0]
    before = (REPO / "config" / "strategies.yaml").read_text()
    finding = {"text": f"{leader['strategy_id']} leads with {leader['trades']} trades.",
               "cited_ids": [leader["strategy_id"]]}
    proposal = {"proposal_id": "p-2026-W41-1", "kind": "threshold", "file": "config/strategies.yaml",
                "diff": new_strategy_diff(), "rationale": "A stricter bar to test.",
                "cited_ids": ["rule.model_news.v1"]}
    review = {"findings": [finding], "proposals": [proposal], "prompt_version": "director-v1"}
    assert director.validate(review, facts) == []
    assert (REPO / "config" / "strategies.yaml").read_text() == before
    broken = {**proposal, "diff": proposal["diff"].replace(" " + before.splitlines()[-1], " no such line")}
    assert "does not apply" in " ".join(director.validate({**review, "proposals": [broken]}, facts))
    other = {**proposal, "file": "config/settings.yaml"}
    assert "is not one of" in " ".join(director.validate({**review, "proposals": [other]}, facts))
    wrong_id = {**proposal, "proposal_id": "p-1"}
    assert "must be 'p-2026-W41-1'" in " ".join(director.validate({**review, "proposals": [wrong_id]}, facts))
    invented = {**finding, "text": f"{leader['strategy_id']} leads with 999 trades."}
    assert "numbers that match none" in " ".join(director.validate({**review, "findings": [invented]}, facts))
    unknown = {**finding, "cited_ids": ["rule.nope.v9"]}
    assert "not in the week's inputs" in " ".join(director.validate({**review, "findings": [unknown]}, facts))
    live = dict(facts["config_files"])
    live["config/strategies.yaml"] = before.replace("    live_from: null", "    live_from: '2026-10-01'", 1)
    change = live["config/strategies.yaml"].splitlines()
    first = change.index("  - id: rule.model_news.v1")
    index = next(i for i, line in enumerate(change) if i > first and line.strip().startswith("threshold:"))
    edit = "\n".join(["--- a/config/strategies.yaml", "+++ b/config/strategies.yaml",
                      f"@@ -{index},3 +{index},3 @@", " " + change[index - 1], "-" + change[index],
                      "+" + change[index].replace("0.55", "0.57"), " " + change[index + 1]]) + "\n"
    live_facts = {**facts, "config_files": live}
    found = director.validate({**review, "proposals": [{**proposal, "diff": edit}]}, live_facts)
    assert any("needs a new id" in e for e in found)


@pytest.mark.usefixtures("root")
def test_director_report_and_row():
    facts = director_inputs()
    review = {"findings": [], "proposals": [{"proposal_id": "p-2026-W41-1", "kind": "threshold",
                                             "file": "config/strategies.yaml", "diff": new_strategy_diff(),
                                             "rationale": "Test.", "cited_ids": ["rule.model_news.v1"]}],
              "prompt_version": "director-v1"}
    written = director_report.store(facts, review, "2026-10-10T14:20:00Z", date(2026, 10, 10))
    text = Path(written["report"]).read_text()
    assert "status: proposed" in text and "```diff" in text and "not investment advice" in text
    row = json.loads(Path(written["to"]).read_text())
    assert row["id"] == "rr-us-2026-W41" and row["proposals"][0]["status"] == "proposed"
    assert {leader["scope"] for leader in row["leaders"]} == {r["family"] for r in facts["leaders_to_date"]}


def test_load_inputs_reads_stored_data_and_b10_records(monkeypatch):
    """load_inputs on the repo's stored US data, with B10's per-horizon records replaced by the fixtures."""
    from traders_fixtures import published_range, score

    from marketbrief.contracts import horizons
    from marketbrief.core.market_config import load_market
    from marketbrief.traders.inputs import load_inputs

    monkeypatch.setattr(horizons, "ranges_asof", lambda *_args, **_kwargs: [published_range(1)])
    monkeypatch.setattr(horizons, "scores_asof", lambda *_args, **_kwargs: [score(1)])
    cfg = load_market("us")
    gi = load_inputs(cfg, datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc))
    assert gi.active == set(cfg["tickers"]) and gi.amounts["NVDA"] == 1000.0 and gi.currency == "USD"
    assert gi.features["NVDA"]["as_of_date"] == date(2026, 10, 6) and gi.features["NVDA"]["quality"] in ("OK", "WARN")
    assert gi.regimes[date(2026, 10, 6)][0] == "TRENDING"
    assert gi.evidence and all(when is None or when.tzinfo is not None for when in list(gi.evidence.values())[:50])
    assert set(gi.ranges) == set(gi.scores) == {"2026-10-06-NVDA-1d"}
    assert gi.stored_predictions == set() and gi.track == {}


@pytest.mark.usefixtures("root")
def test_director_diff_may_touch_only_its_file():
    facts = director_inputs()
    extra = ("--- /dev/null\n+++ b/scripts/evil.py\n@@ -0,0 +1 @@\n+print('x')\n")
    proposal = {"proposal_id": "p-2026-W41-1", "kind": "threshold", "file": "config/strategies.yaml",
                "diff": new_strategy_diff() + extra, "rationale": "Test.", "cited_ids": ["rule.model_news.v1"]}
    errors = director.validate({"findings": [], "proposals": [proposal], "prompt_version": "director-v1"}, facts)
    assert any("must change only config/strategies.yaml" in e for e in errors)
    after, why = director.applied("config/costs.yaml", facts["config_files"]["config/costs.yaml"], extra)
    assert after is None and "must change only" in why
