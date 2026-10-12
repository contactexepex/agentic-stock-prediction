"""The evening run's ranges (B17's post-go-live batch, option C; B10's part): `ranges.py --evening` ranks the day's
close into ranges_evening with the same ids as the pre-open rows, no overnight cue, `run: "evening"`; the pre-open
rows in `ranges` stay the revision of record, and ranges_asof reads the evening rows only when asked."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from marketbrief.constants.horizons import RUN_EVENING  # noqa: E402
from marketbrief.contracts import horizons as contract  # noqa: E402
from marketbrief.core.database import connect  # noqa: E402
from test_guard import ALL, assert_cue_applied, build, market, quotes, snapshot  # noqa: E402, F401
from test_pipeline import MARKET, run  # noqa: E402

EVENING = "2026-10-02T21:30:00+00:00"     # Friday's evening run, after the 20:00 UTC close of the as-of session
PRE_OPEN = "2026-10-05T11:30:00+00:00"    # Monday's pre-open run, before D's 13:30 UTC open


def stored(root: Path, kind: str) -> list[dict]:
    return [json.loads(line) for path in sorted((root / "data" / MARKET / kind).rglob("*.jsonl"))
            for line in path.read_text().splitlines()]


def test_evening_rows_carry_no_cue_and_the_same_ids(market):  # noqa: F811 (test_guard's fixture)
    root, _, cfg, rc = market
    quotes(root, "2026-10-02T13:00:00+00:00")             # the as-of day's own pre-open cue (its session has closed)
    snapshot(root, "2026-10-02T21:00:00+00:00")           # the evening features carry that cue
    evening = {r["id"]: r for r in build_run(cfg, rc, EVENING)}
    assert sorted(evening) == ALL
    assert all(r["run"] == RUN_EVENING and r["center"] == 0.0 and r["notes"] == [
        "evening: no overnight cue yet (the pre-open revision adds it)"] for r in evening.values())
    assert all("beta_split" not in r["inputs"] for r in evening.values())
    quotes(root, "2026-10-05T10:55:00+00:00")             # Monday's overnight cue
    snapshot(root, "2026-10-05T11:00:00+00:00")
    pre_open = build(cfg, rc, PRE_OPEN)
    assert sorted(pre_open) == sorted(evening) and all("run" not in r for r in pre_open.values())
    assert_cue_applied(pre_open, rc)
    for rid, row in pre_open.items():                     # same window: entry, exit and target
        assert {k: row[k] for k in ("entry_date", "exit_date", "target_date", "horizon_label")} == {
            k: evening[rid][k] for k in ("entry_date", "exit_date", "target_date", "horizon_label")}


def build_run(cfg, rc, now: str) -> list[dict]:
    from marketbrief.analytics import range_publication
    return range_publication.build(cfg, rc, connect(MARKET), now, RUN_EVENING)


def test_cli_writes_each_run_to_its_own_kind_once(market):  # noqa: F811 (test_guard's fixture)
    root, cfg_dir, _, _ = market
    snapshot(root, "2026-10-02T21:00:00+00:00")
    first = run("ranges.py", root, cfg_dir, "--evening", "--now", EVENING)
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert (summary["run"], summary["written"]) == ("evening", len(ALL))
    assert not (root / "data" / MARKET / "ranges").exists()                       # never in ranges
    again = json.loads(run("ranges.py", root, cfg_dir, "--evening", "--now", EVENING).stdout)
    assert again["written"] == 0                                                  # once per id in ranges_evening
    snapshot(root, "2026-10-05T11:00:00+00:00")
    morning = json.loads(run("ranges.py", root, cfg_dir, "--now", PRE_OPEN).stdout)
    assert morning["written"] == len(ALL) and "run" not in morning               # not blocked by evening ids
    assert sorted(r["id"] for r in stored(root, "ranges")) == ALL == sorted(
        r["id"] for r in stored(root, "ranges_evening"))
    assert json.loads(run("ranges.py", root, cfg_dir, "--evening", "--now", EVENING).stdout)["written"] == 0


def test_ranges_asof_reads_the_evening_rows_only_when_asked(market, monkeypatch):  # noqa: F811 (test_guard's fixture)
    root, cfg_dir, _, _ = market
    monkeypatch.setattr(common, "CONFIG", cfg_dir)                                # ranges_asof loads the market
    snapshot(root, "2026-10-02T21:00:00+00:00")
    assert run("ranges.py", root, cfg_dir, "--evening", "--now", EVENING).returncode == 0
    assert contract.ranges_asof(MARKET, "2026-10-03T00:00:00+00:00") == []      # the default never sees them
    rows = contract.ranges_asof(MARKET, "2026-10-03T00:00:00+00:00", run="evening")
    assert sorted(r["id"] for r in rows) == ALL and all("run" not in r for r in rows)
    assert contract.ranges_asof(MARKET, "2026-10-02T21:00:00+00:00", run="evening") == []   # made after the time
    snapshot(root, "2026-10-05T11:00:00+00:00")
    quotes(root, "2026-10-05T10:55:00+00:00")
    assert run("ranges.py", root, cfg_dir, "--now", PRE_OPEN).returncode == 0
    pre_open = {r["id"]: r for r in contract.ranges_asof(MARKET, "2026-10-05T12:00:00+00:00")}
    evening = {r["id"]: r for r in contract.ranges_asof(MARKET, "2026-10-05T12:00:00+00:00", run="evening")}
    assert sorted(pre_open) == sorted(evening) == ALL
    assert all(pre_open[rid]["center"] > 0 == evening[rid]["center"] for rid in ALL)   # the cue is the revision
    with pytest.raises(SystemExit):
        contract.ranges_asof(MARKET, "2026-10-05T12:00:00+00:00", run="noon")
