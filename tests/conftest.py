"""Shared test setup: the network guard (the suite runs offline), the `slow` tier and xdist grouping.

  python -m pytest -m "not slow" -n auto     fast tier, on each edit
  python -m pytest -n auto                   full suite, before review or merge (CI runs it without
                                             test_every_logged_commit_exists, see tests.yml)

Network guard: every test runs with Python's socket module patched (tests/netguard/mb_netguard.py)
in this process and, through tests/netguard/sitecustomize.py on PYTHONPATH, in every child Python
process. A connection or name lookup to anything but loopback is refused and fails the test. Proxy
variables are removed so no request can reach the network through a local proxy. Only Python
sockets are seen: a C library or a node process opening its own sockets is not. A test that must
reach the network is marked `network` (only the opt-in live Neo4j test).

Slow tier: the tests listed in SLOW (end-to-end runs of the scripts as subprocesses, replays, the full
pipeline) get the `slow` marker here, in one place. A listed file that no longer exists, or a listed
name missing from a collected file, fails the collection, so the list cannot go stale silently.

xdist: tests that use a module- or session-scoped fixture defined in their own module are put in one
xdist group per module (`--dist loadgroup` in pytest.ini's addopts; pytest-xdist is a required dev
dependency in requirements.txt), so the expensive shared setup runs once per run, not once per worker."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
NETGUARD = TESTS / "netguard"
sys.path.insert(0, str(NETGUARD))
import mb_netguard  # noqa: E402

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_saved_proxies = {k: os.environ[k] for k in PROXY_VARS if k in os.environ}

# test file -> test function names (without parameters) in the slow tier: tests that took 1.5 s or
# more in either of two serial runs on 2026-10-06 (each runs scripts as subprocesses: pipeline,
# replays, CLIs), plus every test on test_ai_replay's shared `prepared` setup (three prepare runs).
# A new end-to-end test goes here.
SLOW = {
    "tests/test_aci_scoring.py": {
        "test_aci_off_reproduces_ranges_byte_for_byte",
        "test_replay_aci_has_no_lookahead",
        "test_replay_aci_off_rows_unchanged",
        "test_replay_held_out_selects_on_tuning_dates_and_reports_test_dates",
    },
    "tests/test_ai_replay.py": {
        "test_assumed_earnings_are_opt_in_and_labelled",
        "test_backfill_refuses_real_data",
        "test_prepare_keeps_exactly_what_was_public",
        "test_prepare_no_look_ahead",
        "test_prepare_reads_source",
        "test_prepare_refuses_unsafe_roots_and_training_period",
        "test_record_validation",
        "test_sample_dates_cli",
        "test_score_cli_on_recorded_calls",
        "test_training_cutoff_comes_from_config",
    },
    "tests/test_call_basis.py": {
        "test_no_entry_open_no_score_and_old_rows_read_as_close_to_close",
        "test_scoring_bases_match_the_model_labels",
    },
    "tests/test_determinism.py": {
        "test_score_predictions_queries",
        "test_views_insider_flow_and_split_factors",
    },
    "tests/test_fundamentals.py": {
        "test_collect_gate_new_filing_and_views",
    },
    "tests/test_guard.py": {
        "test_context_and_report_label_mid_session_ranges_late",
        "test_context_pack_labels_late_ranges",
        "test_late_calls_left_out_of_slack_count_and_news_window",
        "test_market_status_cli_now",
        "test_ranges_cli_in_session_flag",
        "test_ranges_cli_late_flag",
        "test_ranges_holiday_and_early_close",
        "test_ranges_mid_session_publishes_5d_only_labelled_late",
        "test_report_labels_late_ranges_and_links_the_review",
        "test_scoring_skips_every_horizon_made_after_the_open",
        "test_scoring_skips_records_made_after_the_first_session_closed",
        "test_slack_ranges_line_says_late",
    },
    "tests/test_judge_fails.py": {
        "test_context_pack_prints_the_section",
    },
    "tests/test_lessons.py": {
        "test_add_appends_once_with_recomputed_facts",
        "test_context_section_last3_per_ticker_and_market_wide",
        "test_future_outcomes_change_nothing_at_a_past_made_at",
        "test_lesson_never_visible_before_available_from",
    },
    "tests/test_neo4j_sync.py": {
        "test_rerun_is_idempotent_and_incremental",
    },
    "tests/test_nse_india.py": {
        "test_announcement_enrichment_view_and_context",
        "test_nse_primary_sources_on_real_responses",
        "test_relations_on_real_responses",
        "test_transient_error_is_retried_once",
    },
    "tests/test_pipeline.py": {
        "test_backtest_coverage_is_calibrated",
        "test_calibrate_ranges_and_scoring",
        "test_context_shows_sector_etf_mapping",
        "test_features_regime_and_context",
        "test_scoring_and_context",
    },
    "tests/test_range_inputs.py": {
        "test_backtest_scores_inputs",
        "test_late_run_guard_drops_late_index_cue_and_options",
        "test_ranges_apply_inputs",
    },
    "tests/test_relations.py": {
        "test_collector_skips_market_without_relations",
        "test_graph_add_hits_and_retract",
        "test_graph_refresh_due_once_per_month",
        "test_relations_collector_flags_and_context",
        "test_replay_scratch_root_rules",
    },
    "tests/test_relationships.py": {
        "test_holdings_collect_changes_and_gate",
        "test_ranges_carry_activist_note",
        "test_ranges_ignore_a_13d_accepted_after_made_at",
    },
    "tests/test_replay.py": {
        "test_replay_cli_writes_report_json_and_record",
        "test_replay_has_no_lookahead",
        "test_replay_ranges_equal_ranges_py",
    },
    "tests/test_review.py": {
        "test_model_check_reruns_the_backtest_into_work",
        "test_review_end_to_end",
        "test_review_with_little_data_makes_no_live_proposal",
    },
    "tests/test_sec_times.py": {
        "test_stored_shifted_rows_are_corrected_on_read",
    },
    "tests/test_signal_model.py": {
        "test_daily_scores_end_to_end",
    },
    "tests/test_split_adjust.py": {
        "test_hold_persists_after_the_frame_moves_past_the_stored_bars",
    },
    "tests/test_validate.py": {
        "test_cli_exit_code",
        "test_collector_summaries",
        "test_collector_summaries_are_sources_but_validate_outputs_are_not",
        "test_context_pack",
        "test_features_and_regime",
        "test_forecast_valid_and_absent",
        "test_late_run_does_not_require_todays_bar",
        "test_price_basis_warnings_surface",
        "test_report_stage_flags_planted_number",
        "test_spotcheck_if_due",
        "test_spotcheck_sample_is_deterministic_and_in_week",
    },
}


def pytest_configure(config):
    for k in PROXY_VARS:
        os.environ.pop(k, None)
    os.environ["MB_NETGUARD"] = "on"
    paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if str(NETGUARD) not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(NETGUARD), *paths])
    mb_netguard.install()


@pytest.hookimpl(tryfirst=True)       # before xdist reads the xdist_group markers
def pytest_collection_modifyitems(config, items):
    seen: dict[str, set[str]] = {}
    for item in items:
        rel = Path(str(item.fspath)).resolve().relative_to(TESTS.parent).as_posix()
        name = getattr(item, "originalname", None) or item.name.split("[")[0]
        seen.setdefault(rel, set()).add(name)
        if name in SLOW.get(rel, ()):
            item.add_marker(pytest.mark.slow)
        info = getattr(item, "_fixtureinfo", None)
        defs = getattr(info, "name2fixturedefs", {}) if info else {}
        module_id = item.nodeid.split("::")[0]
        if any(d and d[-1].scope in ("module", "session") and d[-1].baseid == module_id for d in defs.values()):
            item.add_marker(pytest.mark.xdist_group(f"shared-{rel}"))
    missing = [rel for rel in SLOW if not (TESTS.parent / rel).is_file()]
    missing += [f"{rel}::{n}" for rel, names in SLOW.items() if rel in seen for n in sorted(names - seen[rel])]
    if missing:
        raise pytest.UsageError(f"tests/conftest.py SLOW lists tests that do not exist: {missing}")


@pytest.fixture(scope="session", autouse=True)
def _netguard_session_log(tmp_path_factory):
    """Refusals outside a test (in a module- or session-scoped fixture) land here; the next test fails."""
    log = tmp_path_factory.mktemp("netguard") / "session.log"
    os.environ["MB_NETGUARD_LOG"] = str(log)
    yield log
    os.environ.pop("MB_NETGUARD_LOG", None)


@pytest.fixture(autouse=True)
def _no_network(request, _netguard_session_log):
    log = _netguard_session_log.parent / f"{uuid.uuid4().hex}.log"
    allowed = request.node.get_closest_marker("network") is not None
    os.environ["MB_NETGUARD_LOG"] = str(log)
    if allowed:
        os.environ["MB_NETGUARD"] = "off"
        os.environ.update(_saved_proxies)
    try:
        yield
    finally:
        os.environ["MB_NETGUARD_LOG"] = str(_netguard_session_log)
        if allowed:
            os.environ["MB_NETGUARD"] = "on"
            for k in PROXY_VARS:
                os.environ.pop(k, None)
    hits = log.read_text() if log.exists() else ""
    if _netguard_session_log.exists():
        hits += _netguard_session_log.read_text()
        _netguard_session_log.unlink()
    if hits:
        pytest.fail("the test reached for the network (tests must run offline):\n" + hits, pytrace=False)
