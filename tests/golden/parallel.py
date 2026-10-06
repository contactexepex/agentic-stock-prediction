"""Parallel schedule of the golden run (tests/golden/golden.py; docs/REFACTOR_PLAN.md, "Golden outputs").

The serial run (`--serial`) runs every step of both markets one after another in one scratch root.
The parallel run (the default) gives the same bytes faster:
- each market runs in its own isolated copy of the seeded root, in a sibling directory whose path has
  the same length as the run directory's (so a byte count that includes a printed path is unchanged),
  both markets at once (one process each);
- within a market and phase, a step starts as soon as every earlier step it conflicts with has
  finished. Two steps conflict when one writes a resource the other reads or writes (ACCESS below:
  data kinds under data/<market>/ and named work/report files). A step not in ACCESS conflicts with
  every step, so a new step runs in list order until its access is declared. The late phase starts
  after the whole pre_open phase (the overlay steps read GOLDEN_PHASE);
- afterwards each market's directory is merged into the run directory: every file the market
  created or changed (its own path rewritten to the run directory's), in MARKETS order, and every
  input file it deleted is deleted. A file two markets both wrote keeps the later market's version,
  as in the serial run where the later market runs last; such overlaps are listed in outputs.json.

Data reads are declared as every kind, or every kind but the ones listed (`but`), where the step's
code was checked not to read them (its SQL FROM/JOIN targets and the views they use); data writes
and other resources are explicit."""
from __future__ import annotations

import shutil
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Access:
    """What a step reads and writes. data_but: the data kinds it never reads (None: reads no data)."""
    data_but: frozenset | None = frozenset()
    data_writes: frozenset = frozenset()
    reads: frozenset = frozenset()
    writes: frozenset = frozenset()
    after: frozenset = field(default_factory=frozenset)   # labels whose step log this step reads

    def reads_kind(self, kind: str) -> bool:
        return self.data_but is not None and kind not in self.data_but


def access(but=(), data_writes=(), reads=(), writes=(), after=(), no_data: bool = False) -> Access:
    return Access(None if no_data else frozenset(but), frozenset(data_writes), frozenset(reads), frozenset(writes),
                  frozenset(after))


EVERYTHING = None   # a step without declared access: conflicts with every step
NOT_REVIEWS = ("reviews", "replays")
NOT_FEATURE_KINDS = ("features", "regime", "calibration")
WORK = ("context", "predictions", "report")
ACCESS: dict[str, Access] = {
    "market_status": access(no_data=True),
    "market_status_mid_session": access(no_data=True),
    "validate_collect": access(reads=WORK),
    # bars, open_predictions, open_ranges, price_adjustments, track_record, range_record
    "score_predictions": access(but=(*NOT_FEATURE_KINDS, "lessons", "news_clusters"),
                                data_writes=("outcomes", "range_outcomes")),
    # company_events, ohlc, quotes_latest
    "features": access(but=("outcomes", "range_outcomes", "calibration", "lessons", "news_clusters"),
                       data_writes=("features", "regime")),
    # range_record, regime_latest; aci: range_outcomes, range_record; range_inputs: event_history
    "calibrate": access(but=("lessons", "news_clusters"), data_writes=("calibration",)),
    # check_files of features/regime/calibration, bars, features_latest, regime_latest
    "validate_features": access(but=("lessons", "news_clusters")),
    # predictions, outcomes, range_outcomes, ranges_latest, lessons, news, filings, announcements
    "lessons_prepare": access(but=(*NOT_FEATURE_KINDS, "news_clusters"), writes=("lessons_work",)),
    "lessons_write": access(no_data=True, reads=("lessons_work",), writes=("lessons_work",)),
    "lessons_validate": access(but=(*NOT_FEATURE_KINDS, "news_clusters"), reads=("lessons_work",)),
    "lessons_add": access(but=(*NOT_FEATURE_KINDS, "news_clusters"), reads=("lessons_work",),
                          data_writes=("lessons",)),
    # news, announcements, filings, news_articles, news_clusters
    "news_clusters": access(but=(*NOT_FEATURE_KINDS, "lessons", "outcomes", "range_outcomes"),
                            data_writes=("news_clusters",)),
    # context.py and the section modules it imports: no reviews or replays
    "context": access(but=NOT_REVIEWS, writes=("context",)),
    "context_after_ranges": access(but=NOT_REVIEWS, writes=("context",)),
    "validate_context": access(reads=("context",)),
    "validate_forecast_absent": access(reads=("predictions",)),
    "forecaster_file": access(writes=("predictions",)),
    "validate_forecast": access(reads=("predictions",)),
    "append_valid_calls": access(reads=("predictions",), writes=("predictions",), data_writes=("predictions",),
                                 after=("validate_forecast",)),
    "ranges": access(data_writes=("ranges",)),
    "review": access(data_writes=("reviews",), writes=("review_md",)),
    # the not-due path (review ran just before): reviews only
    "review_if_due": access(but=("replays",), reads=("review_md",)),
    # view_data.gather_view: no reviews or replays
    "charts": access(but=NOT_REVIEWS, writes=("charts",)),
    "report": access(reads=("charts",), writes=("report",)),
    "fill_report": access(no_data=True, reads=("report",), writes=("report",), after=("report",)),
    # stage report: check_files of news_enriched/predictions/ranges, check_ranges, build_pool
    "validate_report": access(but=("replays",), reads=("context", "report")),
    "html_report": access(but=NOT_REVIEWS, reads=("report", "charts"), writes=("html",)),
    "notify_slack_dry_run": access(no_data=True, reads=("report", "charts", "html"), writes=("slack_plan",)),
    # predictions, outcomes and evidence rows of the week, reports/<market>/<date>.md
    "spotcheck": access(but=("replays",), reads=("report",)),
    # graph, graph_edges, graph_runs, news, enriched_latest
    "graph_status": access(but=NOT_REVIEWS),
    "backtest": access(but=NOT_REVIEWS, writes=("backtest_md",)),
    "replay": access(data_writes=("replays",), writes=("replay_files",)),
    "replay_aci": access(data_writes=("replays",), writes=("replay_files",)),
    "ai_replay_dates": access(),
    "ai_replay_prepare": access(writes=("ai_replay",)),
    "ai_replay_record": access(no_data=True, reads=("ai_replay",), writes=("ai_replay",)),
    "ai_replay_score": access(reads=("ai_replay",), writes=("ai_replay",)),
    "neo4j_dry_run": access(writes=("neo4j",)),
    "validate_all": EVERYTHING,
}


def conflicts(first: Access | None, then: Access | None, first_label: str) -> bool:
    """True when `then` (later in the list) must wait for `first`."""
    if first is None or then is None or first_label in then.after:
        return True
    if first.writes & (then.reads | then.writes) or first.reads & then.writes:
        return True
    if any(then.reads_kind(k) for k in first.data_writes) or first.data_writes & then.data_writes:
        return True
    return any(first.reads_kind(k) for k in then.data_writes)


def dependencies(labels: list[str]) -> list[set[int]]:
    """For each step, the earlier steps it waits for."""
    acc = [ACCESS.get(label, EVERYTHING) for label in labels]
    return [{i for i in range(j) if conflicts(acc[i], acc[j], labels[i])} for j in range(len(labels))]


def run_dag(labels: list[str], run_step, jobs: int) -> None:
    """Run run_step(i) for every step, each once its dependencies finished, at most `jobs` at a time,
    starting ready steps in list order. The first exception stops the schedule and is raised."""
    deps = dependencies(labels)
    pending, done, running = list(range(len(labels))), set(), {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        while pending or running:
            for i in [i for i in pending if deps[i] <= done][:max(0, jobs - len(running))]:
                pending.remove(i)
                running[pool.submit(run_step, i)] = i
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                future.result()
                done.add(running.pop(future))


def market_dir(run_dir: Path, market: str) -> Path:
    """A sibling of run_dir with a path of the same length, unique per market."""
    if len(run_dir.name) < 3:
        raise SystemExit(f"run directory name {run_dir.name!r} too short for a same-length sibling")
    return run_dir.parent / (run_dir.name + "~" + market[0])[-len(run_dir.name):]


def file_hashes(base: Path, hasher) -> dict[str, str]:
    return {p.relative_to(base).as_posix(): hasher(p.read_bytes()) for p in sorted(base.rglob("*")) if p.is_file()}


def merge_market(source: Path, run_dir: Path, base: dict[str, str], hasher, skip: set[str]) -> tuple[list, list]:
    """Copy into run_dir every file of source that is new or differs from base (relative path -> hash
    of the run directory before the market ran), with source's path rewritten to run_dir's; delete in
    run_dir every base file that source no longer has. Returns (written, deleted) relative paths."""
    old, new = str(source).encode(), str(run_dir).encode()
    written, deleted = [], []
    present = set()
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = path.relative_to(source).as_posix()
        present.add(rel)
        if rel in skip:
            continue
        content = path.read_bytes()
        if base.get(rel) == hasher(content):
            continue
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.replace(old, new))
        written.append(rel)
    for rel in sorted(set(base) - present - skip):
        (run_dir / rel).unlink(missing_ok=True)
        deleted.append(rel)
    return written, deleted


def copy_base(run_dir: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(run_dir, target)
