"""Seeded kinds for the golden run (tests/golden/golden.py): the pinned data has no rows of the
relationship, fundamentals, macro, short-selling, NSE, graph, options, price-source and SEC-time
kinds, so the modules, SQL views and Neo4j shapers that read them would only see empty tables.

The real collectors fill a separate scratch root (SEED_KINDS below) from the test fixtures:
- India, NSE: collect_relations_india.py and collect_nse_india.py replay tests/fixtures/nse/real
  (--replay, --today 2026-10-05, --full): insiders, holdings, announcements, financials, flows,
  delivery; then collect_relations_india.py replays tests/fixtures/nse/synthetic (dates set
  relative to 2026-10-05) for deals and insider trades of watchlist tickers (the real snapshot
  has none);
- US, SEC: collect_insiders, collect_stakes, collect_holdings and collect_fundamentals read
  tests/fixtures/sec through MB_SEC_FIXTURES (the urls.json map built here, as in
  tests/test_relationships.py and tests/test_fundamentals.py; the seed config tracks the fixture
  13F filer 9999200 instead of the real filers): insiders, stakes, holdings, fundamentals;
- free sources: tests/golden/seed_sources.py runs collect_macro, collect_shorts and
  collect_flows_india on tests/fixtures/sources (macro, shorts, short_interest, fpi, indices);
- graph.py add tests/fixtures/graph_edges.jsonl (India connection map; its 4th edge is invalid on
  purpose, so that step exits 1) and graph.py attempt (graph_runs);
- small rule-built rows for options (US), price_sources (India) and sec_times (US), whose
  collectors need Yahoo or the SEC header pages, and India financials of the quarter a year before
  the fixtures' latest one (INFY consolidated, HDFCBANK and SBILIFE standalone, 2025-04-01..06-30),
  so the year-over-year columns of the "Latest quarterly results" section have values;
- the fixture 13F tables are served with the AAPL common-share values multiplied by
  F13_VALUE_SCALE (a copy in the seed folder; tests/fixtures is unchanged), so the 13F section's
  value_bn is billions with two significant decimals instead of 0.0.
The seed root's data files are then copied into the golden root (never over an existing file).
- the collectors that need Yahoo, RSS feeds, article pages or SEC header pages (collect_prices,
  collect_quotes, collect_events, collect_news, collect_articles, collect_filings, collect_options,
  check_sec_times) run through tests/golden/seed_collectors.py (offline stand-ins for those services,
  at the third-party boundary) on a copy of the seed root (`collectors_<market>`: the seeded kinds, the
  pinned events and news, and the pinned prices up to PRICE_CUTOFF); their outputs are compared (the
  copy is kept in run/seed/collectors_<market>) but not copied into the golden root, so the later steps
  do not change.
Every seed step's exit code, stdout and stderr is logged and compared like any other step."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from seed_fixtures import (
    CODE,
    COLLECTOR_COPIED_KINDS,
    COLLECTOR_SCRIPTS,
    FIXTURES,
    PRICE_CUTOFF,
    SEED_CLOCKS,
    SEED_KINDS,
    nse_replay_folder,
    rule_rows,
    sec_collectors_map,
    sec_fixture_map,
    seed_config,
    synthetic_nse,
)


def collectors_root(scratch: Path, seed_root: Path, golden_root: Path, market: str) -> Path:
    """A copy of the seed root for one market's collectors: the pinned events and news, and the pinned
    bars up to PRICE_CUTOFF (Yahoo's stand-in serves the later ones)."""
    target = scratch / f"collectors_{market}"
    shutil.copytree(seed_root, target)
    for kind in COLLECTOR_COPIED_KINDS:
        source = golden_root / "data" / market / kind
        if source.is_dir():
            shutil.copytree(source, target / "data" / market / kind, dirs_exist_ok=True)
    pinned_prices = golden_root / "data" / market / "prices"
    for path in sorted(pinned_prices.rglob("*.csv")):
        if path.stem <= PRICE_CUTOFF:
            destination = target / "data" / market / "prices" / path.relative_to(pinned_prices)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    return target


def collector_steps(market: str) -> list[tuple[str, str, list[str]]]:
    """(market, label, argv) of the Yahoo, RSS, article and SEC-header collectors through seed_collectors.py."""
    runner = str(CODE / "tests" / "golden" / "seed_collectors.py")
    return [(market, script.removesuffix(".py"), ["{python}", runner, market, script]) for script in COLLECTOR_SCRIPTS]


def seed_steps() -> list[tuple[str, str, list[str]]]:
    """(market, label, argv) in order; '{python}', '{seed_dir}' and '{fixtures}' are filled in by run_seed."""
    nse = ["--replay", "{fixtures}/nse/real", "--today", "2026-10-05", "--full"]
    return [
        ("india", "collect_relations_india", ["{python}", "collect_relations_india.py", *nse]),
        ("india", "collect_relations_india_synthetic",
         ["{python}", "collect_relations_india.py", "--replay", "{seed_dir}/nse_synthetic", "--today", "2026-10-05",
          "--only", "deals", "--only", "insiders"]),
        ("india", "collect_nse_india", ["{python}", "collect_nse_india.py", *nse]),
        ("india", "graph_add", ["{python}", "graph.py", "add", "{fixtures}/graph_edges.jsonl"]),
        ("india", "graph_attempt", ["{python}", "graph.py", "attempt", "--note", "golden seed"]),
        ("india", "seed_sources", ["{python}", str(CODE / "tests" / "golden" / "seed_sources.py"), "india"]),
        ("us", "collect_insiders", ["{python}", "collect_insiders.py"]),
        ("us", "collect_stakes", ["{python}", "collect_stakes.py"]),
        ("us", "collect_holdings", ["{python}", "collect_holdings.py"]),
        ("us", "collect_fundamentals", ["{python}", "collect_fundamentals.py"]),
        ("us", "seed_sources", ["{python}", str(CODE / "tests" / "golden" / "seed_sources.py"), "us"]),
    ]


def run_seed(run_dir: Path, golden_root: Path, environment, scripts: Path, parallel: bool = False) -> None:
    """Fill a scratch seed root with the collectors, keep a copy in run_dir/seed/root, then copy
    SEED_KINDS into golden_root/data. The seed root lives outside the checkout (a temporary
    directory): the NSE --replay guard refuses any write target inside a repository. parallel: the
    two markets' step lists run at the same time (each list in order; they write different
    data/<market> folders)."""
    scratch = Path(tempfile.mkdtemp(prefix="mb-golden-seed-"))
    try:
        seed_root = scratch / "root"
        (seed_root / "data").mkdir(parents=True)
        (seed_root / ".scratch-ok").write_text("golden seed root\n")
        seed_config(golden_root, seed_root)
        sec_fixture_map(run_dir / "seed" / "sec")
        rule_rows(seed_root)
        synthetic_nse(run_dir / "seed" / "nse_synthetic")
        sec_collectors_map(run_dir / "seed" / "sec_collectors")
        nse_replay_folder(run_dir / "seed" / "nse_replay")
        run_seed_steps(run_dir, seed_root, environment, scripts, parallel)
        shutil.copytree(seed_root, run_dir / "seed" / "root")
        roots = {market: collectors_root(scratch, seed_root, golden_root, market) for market in SEED_CLOCKS}
        run_collector_steps(run_dir, roots, golden_root, environment, scripts, parallel)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    copy_seeded(run_dir / "seed" / "root", golden_root, run_dir / "steps" / "seed")


def run_seed_steps(run_dir: Path, seed_root: Path, environment, scripts: Path, parallel: bool = False) -> None:
    """Run seed_steps() on seed_root; logs in run_dir/steps/seed/ with the seed root's path as <SEED>."""
    log_dir = run_dir / "steps" / "seed"
    log_dir.mkdir(parents=True)

    def run_market(market: str) -> None:
        for step_market, label, command in seed_steps():
            if step_market == market:
                run_seed_step(run_dir, seed_root, environment, scripts, (market, label, command))
    if parallel:
        with ThreadPoolExecutor(max_workers=len(SEED_CLOCKS)) as pool:
            for future in [pool.submit(run_market, market) for market in SEED_CLOCKS]:
                future.result()
    else:
        for step in seed_steps():
            run_seed_step(run_dir, seed_root, environment, scripts, step)


def run_collector_steps(run_dir: Path, roots: dict[str, Path], golden_root: Path, environment,
                        scripts: Path, parallel: bool = False) -> None:
    """Run collector_steps() of each market on its own root (a collectors_root copy), then keep
    each copy in run_dir/seed/collectors_<market>."""

    def run_market(market: str) -> None:
        extra = {"MB_SEC_FIXTURES": str(run_dir / "seed" / "sec_collectors"),
                 "GOLDEN_NSE_REPLAY": str(run_dir / "seed" / "nse_replay"),
                 "GOLDEN_PRICE_SOURCE": str(golden_root / "data" / market / "prices")}
        for step in collector_steps(market):
            run_seed_step(run_dir, roots[market], environment, scripts, step, extra)
    if parallel:
        with ThreadPoolExecutor(max_workers=len(SEED_CLOCKS)) as pool:
            for future in [pool.submit(run_market, market) for market in SEED_CLOCKS]:
                future.result()
    else:
        for market in SEED_CLOCKS:
            run_market(market)
    for market, root in roots.items():
        shutil.copytree(root, run_dir / "seed" / f"collectors_{market}")


def run_seed_step(run_dir: Path, seed_root: Path, environment, scripts: Path, step: tuple,
                  extra_env: dict | None = None) -> None:
    """One seed step on seed_root; its log files are named <market>.<label>.<stream>."""
    market, label, command = step
    env = environment(seed_root, market, SEED_CLOCKS[market])
    env.update({"MB_SEC_FIXTURES": str(run_dir / "seed" / "sec"), "MB_NETGUARD_LOG": str(run_dir / "netguard.log"),
                "SEC_USER_AGENT": "market-brief golden golden@example.com", **(extra_env or {})})
    argv = [a.format(python=sys.executable, seed_dir=run_dir / "seed", fixtures=FIXTURES) for a in command]
    proc = subprocess.run(argv, cwd=scripts, env=env, capture_output=True, text=True, check=False)
    log_dir = run_dir / "steps" / "seed"
    for stream, text in (("stdout", proc.stdout), ("stderr", proc.stderr), ("exit", f"{proc.returncode}\n")):
        (log_dir / f"{market}.{label}.{stream}").write_text(text.replace(str(seed_root.parent), "<SEED>"))


def copy_seeded(seed_root: Path, golden_root: Path, log_dir: Path) -> None:
    """Copy each SEED_KINDS folder of seed_root/data into golden_root/data, never over a file."""
    for market, kinds in SEED_KINDS.items():
        for kind in kinds:
            source = seed_root / "data" / market / kind
            if not source.is_dir():
                raise SystemExit(f"seed produced no {market}/{kind} rows; see {log_dir}")
            for path in sorted(p for p in source.rglob("*") if p.is_file()):
                target = golden_root / "data" / market / kind / path.relative_to(source)
                if target.exists():
                    raise SystemExit(f"seed would overwrite {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
