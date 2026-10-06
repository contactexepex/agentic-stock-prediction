"""News verification phase B, pure rules: quoted numbers and their tolerance, status precedence per fact
and per cluster, each news id's own status, and the news-status rules of the forecast gate
(prediction_rules.check_news_status and validate.py --stage forecast on a synthetic US tree)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.analytics import verification_status as vs  # noqa: E402
from marketbrief.analytics.claim_numbers import half_step_of, quoted_numbers, values_match  # noqa: E402
from marketbrief.analytics.prediction_rules import check_news_status  # noqa: E402
import test_validate  # noqa: E402
from test_validate import GOOD_NEWS_ID, call, codes, forecast, write_jsonl  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    """test_validate's synthetic US tree (bars, today's fetches, features, regime)."""
    return test_validate.root.__wrapped__(tmp_path, monkeypatch)


# ---------- numbers ----------


def test_quoted_numbers_scale_unit_and_rounding():
    found = {n.literal: (n.value, n.unit, n.half_step) for n in quoted_numbers(
        "Q2 480K deliveries; raise $3.8 billion; up 24.7%; 486,532 cars; Rs1,915.5 a share; 25 bps")}
    assert found["480K"] == (480000.0, None, 5000.0)
    assert found["$3.8 billion"] == (3.8e9, "usd", 5e7)
    assert found["24.7%"] == (24.7, "pct", 0.05)
    assert found["486,532"] == (486532.0, None, 0.5)
    assert found["Rs1,915.5"] == (1915.5, "inr", 0.05)
    assert found["25 bps"] == (25.0, "bps", 0.5)
    assert not any(n.literal in ("2", "Q2") for n in quoted_numbers("Q2 480K"))   # inside a token: skipped


@pytest.mark.parametrize("a,b,ok", [
    ((486532, "486,532"), (486532, "486,532"), True),
    ((486532, "486,532"), (486000, "486,000"), True),          # within 1%
    ((486532, "486,532"), (480000, "480K"), False),            # 1.3% off and outside 480K's rounding (+-5,000)
    ((486532, "486,532"), (490000, "490K"), True),             # 0.7%: within 1%
    ((3.83e9, "$3.83 billion"), (3.8e9, "$3.8 billion"), True),
    ((3.92e9, "$3.92 billion"), (3.8e9, "$3.8 billion"), False),   # 3.1%, rounding step 0.05 bn
    ((462000, "462,000"), (457000, "457,000"), False),         # the two TIKR consensus figures
    ((30000, "30,000"), (34000, "34,000"), True),              # 30,000 states a 10,000 step: +-5,000
    ((24.7, "24.7%"), (24.9, "24.9%"), True),                  # within 1% of 24.9
    ((24.7, "24.7%"), (25.3, "25.3%"), False),
])
def test_numeric_match_tolerance(a, b, ok):
    assert values_match(a, b) is ok and values_match(b, a) is ok


def test_half_step_unreadable_is_zero():
    assert half_step_of(None) == 0 and half_step_of("n/a") == 0


# ---------- status precedence ----------

def st(source_id, kind="article", fact="f", value=None, unit=None, text=None, **kw):  # noqa: PLR0913
    """One statement (a stored claim's fields the status rules read)."""
    row = {"fact_key": fact, "source_kind": kind, "quote_source_id": source_id, "claim_type": "earnings_guidance",
           "attribution": "on_record", "stance": "affirms", "value_num": value, "unit": unit, "value_text": text,
           "period": None, "news_ids": [source_id] if kind == "article" else [],
           "source_available_at": "2026-10-05T14:00:00+00:00"}
    row.update(kw)
    return row


ORIGINS = {"n1": "wire:Reuters", "n2": "outlet:mint.com", "n3": "outlet:bs.com"}


def status(statements):
    return vs.fact_status(statements, ORIGINS)


def test_confirmed_primary_numeric_match_and_mismatch_flag():
    r = status([st("acc-1", "filing", value=486532, unit="count", text="486,532", period="Q3 2026"),
                st("n1", value=486000, unit="count", text="486,000", period="Q3"),
                st("n2", value=480000, unit="count", text="480K", period="Q2")])
    assert r["status"] == "confirmed_primary" and r["primary_ids"] == ["acc-1"]
    assert r["mismatch_ids"] == ["n2"] and "mismatch_primary" in r["flags"]
    assert r["confirmed_at"] == "2026-10-05T14:00:00+00:00"
    assert [c["value"] for c in r["conflicts"]] == [480000, 486532]


def test_period_mismatch_alone_flags_the_outlet():
    r = status([st("acc-1", "filing", value=486532, unit="count", text="486,532", period="Q3 2026"),
                st("n1", value=486532, unit="count", text="486,532", period="Q2")])
    assert r["status"] == "confirmed_primary" and r["mismatch_ids"] == ["n1"]


def test_numeric_claim_needs_a_primary_value():
    r = status([st("acc-1", "filing"), st("n1", value=486532, unit="count", text="486,532")])
    assert r["status"] == "single_source" and "primary_without_value" in r["flags"]
    r = status([st("acc-1", "filing"), st("n1")])                      # non-numeric fact: the filing confirms it
    assert r["status"] == "confirmed_primary"


def test_contradicted_beats_everything():
    assert status([st("acc-1", "filing", value=1.0, unit="usd", text="$1"),
                   st("acc-2", "filing", value=2.0, unit="usd", text="$2")])["status"] == "contradicted"
    r = status([st("nse-ann-1", "announcement", stance="denies"), st("n1", claim_type="rumour",
                                                                      attribution="sources_say")])
    assert r["status"] == "contradicted" and "primary_denies" in r["flags"] and r["mismatch_ids"] == ["n1"]
    r = status([st("n1", value=462000, unit="count", text="462,000"), st("n2", value=457000, unit="count",
                                                                          text="457,000"),
                st("n3", value=462000, unit="count", text="462,000")])
    assert r["status"] == "contradicted" and "outlet_values_disagree" in r["flags"]
    assert status([st("n1"), st("n2", stance="denies")])["status"] == "contradicted"


def test_corroborated_rumour_promotional_single_unverified():
    assert status([st("n1"), st("n2")])["status"] == "corroborated"
    assert status([st("n1"), st("n1b", news_ids=["n1"])])["status"] == "single_source"   # one origin twice
    assert status([st("n1", attribution="sources_say")])["status"] == "rumour"
    assert status([st("n1", attribution="sources_say"), st("n2", attribution="sources_say")])["status"] == \
        "corroborated"                                             # precedence: corroborated > rumour
    assert status([st("n1", claim_type="promotional")])["status"] == "promotional"
    assert status([st("n1", claim_type="rumour"), st("n2", claim_type="promotional")])["status"] == "rumour"
    assert status([st("n9")])["status"] == "unverified"              # no verified origin
    assert status([st("n1", claim_type="opinion"), st("n2", attribution="opinion")])["status"] == "unverified"


def cluster(**kw):
    c = {"cluster_id": "CVX-n1", "id": "CVX-n1@x", "news_ids": ["n1", "n2", "n4", "n5"], "duplicate_ids": ["n6"],
         "independent_origins": 1, "flags": ["single_source"], "unvetted_ids": ["n4"],
         "origin_groups": [{"origin": "wire:Reuters", "news_ids": ["n1", "n4"], "verified": True},
                           {"origin": "provider:TIKR", "news_ids": ["n5"], "promotional": True, "verified": False}]}
    c.update(kw)
    return c


@pytest.mark.parametrize("status", ["rumour", "promotional", "contradicted"])
def test_ids_never_weaker_than_a_blocking_cluster_status(status):
    """An unvetted or opinion copy of a rumour (or promotional / contradicted event) keeps that status."""
    c = cluster(news_ids=["n1", "n4", "n7"], origin_groups=[
        {"origin": "wire:Reuters", "news_ids": ["n1", "n4"], "verified": True},
        {"origin": "outlet:sa.com", "news_ids": ["n7"], "opinion": True, "verified": False}])
    ids = vs.id_statuses(c, status, set())
    assert ids["n4"] == ids["n7"] == status                              # unvetted, opinion
    assert vs.id_statuses(c, "single_source", set())["n4"] == "unverified"


def test_headline_values_are_never_compared():
    """A value quoted from a headline (cut, hedges dropped) neither needs nor contradicts a primary value."""
    r = status([st("acc-1", "filing"), st("n1", value=480000, unit="count", text="480K", quote_field="title")])
    assert r["status"] == "confirmed_primary" and r["mismatch_ids"] == [] and r["conflicts"] == []
    r = status([st("acc-1", "filing", value=486532, unit="count", text="486,532"),
                st("n1", value=480000, unit="count", text="480K", quote_field="extract")])
    assert r["mismatch_ids"] == ["n1"]                                   # the same value in an article body
    r = status([st("n1", value=1, unit="usd", text="$1", quote_field="title"),
                st("n2", value=3, unit="usd", text="$3", quote_field="title")])
    assert r["status"] == "corroborated"                                 # headline values: no conflict


def test_confirmed_at_is_when_the_primary_was_public():
    r = status([st("acc-1", "filing", source_published_at="2026-10-02T13:04:26+00:00",
                   source_available_at="2026-10-06T18:33:02+00:00")])
    assert r["confirmed_at"] == "2026-10-02T13:04:26+00:00"
    assert status([st("n1", attribution="outlet_reporting"), st("n2", attribution="outlet_reporting")])["status"] \
        == "corroborated"                                                # an outlet's own reporting is factual


def test_primary_only_side_fact_never_confirms_the_event():
    """ICICIBANK case: an unconfirmed outlet story plus an allotment quoted only from the exchange filing."""
    res, facts = vs.cluster_status(cluster(), [
        st("n1", fact="ceo-exit", quote_field="title"),
        st("nse-ann-9", "announcement", fact="allotment", source_published_at="2026-10-05T04:00:00+00:00")])
    assert facts["allotment"]["status"] == "confirmed_primary" and "primary_only" in facts["allotment"]["flags"]
    assert res["status"] == "single_source" and res["primary_ids"] == [] and res["confirmed_at"] is None
    assert "primary_only" not in res["flags"]


def test_cluster_status_highest_of_facts_and_base():
    res, facts = vs.cluster_status(cluster(), [])
    assert res["status"] == "single_source" and facts == {}
    assert res["ids"] == {"n1": "single_source", "n2": "single_source", "n4": "unverified", "n5": "promotional",
                          "n6": "single_source"}
    assert vs.base_status(cluster(independent_origins=2)) == "corroborated"
    assert vs.base_status(cluster(flags=["sources_say"])) == "rumour"
    assert vs.base_status(cluster(independent_origins=0, flags=["promotional_provider"])) == "promotional"
    assert vs.base_status(cluster(independent_origins=0, flags=[])) == "unverified"
    res, facts = vs.cluster_status(cluster(flags=["sources_say"]), [
        st("acc-1", "filing", fact="cfo"), st("n1", fact="cfo"),
        st("n5", fact="first", claim_type="promotional")])
    assert facts["cfo"]["status"] == "confirmed_primary" and facts["first"]["status"] == "promotional"
    assert res["status"] == "confirmed_primary" and res["primary_ids"] == ["acc-1"]
    res, _ = vs.cluster_status(cluster(independent_origins=2), [
        st("acc-1", "filing", fact="d", value=486532, unit="count", text="486,532"),
        st("n2", fact="d", value=480000, unit="count", text="480K")])
    assert res["status"] == "confirmed_primary" and res["ids"]["n2"] == "contradicted"   # disagrees with the filing
    res, _ = vs.cluster_status(cluster(independent_origins=2), [st("n1", fact="c", value=1, unit="usd", text="$1"),
                                                                 st("n2", fact="c", value=3, unit="usd", text="$3")])
    assert res["status"] == "contradicted" and set(res["ids"].values()) >= {"contradicted"}


# ---------- forecast gate rules ----------

@pytest.mark.parametrize("statuses,widen,conf,want", [
    (["confirmed_primary"], None, 0.9, []),
    (["corroborated", "single_source"], None, 0.85, []),
    (["corroborated", "single_source"], None, 0.86, ["NEWS_STATUS_CONFIDENCE"]),
    (["corroborated", "unverified"], None, 0.9, ["NEWS_STATUS_CONFIDENCE"]),
    (["single_source"], None, 0.6, ["NEWS_STATUS_MAIN"]),
    (["unverified"], None, 0.6, ["NEWS_STATUS_MAIN"]),
    (["rumour"], None, 0.6, ["NEWS_STATUS_MAIN", "NEWS_STATUS_BLOCKED"]),
    (["confirmed_primary", "promotional"], None, 0.6, ["NEWS_STATUS_BLOCKED"]),
    (["confirmed_primary", "contradicted"], None, 0.6, ["NEWS_STATUS_CONTRADICTED"]),
    (["confirmed_primary", "contradicted"], 0.2, 0.6, []),
    (["contradicted"], 0.2, 0.6, ["NEWS_STATUS_MAIN"]),
])
def test_check_news_status_codes(statuses, widen, conf, want):
    rec = {"evidence_ids": [f"id{i}" for i in range(len(statuses))], "range_widen": widen, "confidence": conf}
    assert [code for code, _ in check_news_status(rec, statuses)] == want


FILING = "0000320193-26-000001"        # AAPL 8-K of the test tree


def status_row(news_ids, statuses, as_of="2026-10-06T11:00:00+00:00", cluster_id="AAPL-x", primary_ids=(),
               ticker="AAPL"):
    return {"id": f"{cluster_id}|*@{as_of[:19]}", "as_of": as_of, "cluster_id": cluster_id, "cluster_row_id": "r",
            "claim_id": None, "level": "cluster", "ticker": ticker, "status": statuses[0],
            "primary_ids": list(primary_ids),
            "outlet_ids": [], "mismatch_ids": [], "status_ids": news_ids, "id_statuses": statuses,
            "independent_origins": 1, "unread_vetted_origins": 0, "origins": [], "conflicts": [], "flags": [],
            "first_reported_at": as_of, "confirmed_at": None, "inputs_until": as_of, "state_hash": "h",
            "method_version": "nv-b1"}


def test_forecast_gate_before_the_feature_only_warns(root):
    out = forecast(root, [call()])
    assert out["ok"] and codes(out, "warnings")["NEWS_STATUS_MISSING"]["tickers"] == ["AAPL"]


@pytest.mark.parametrize("status,ids,conf,widen,code", [
    ("corroborated", [GOOD_NEWS_ID], 0.6, None, None),
    ("single_source", [GOOD_NEWS_ID], 0.6, None, "NEWS_STATUS_MAIN"),
    ("rumour", ["0000320193-26-000001", GOOD_NEWS_ID], 0.6, None, "NEWS_STATUS_BLOCKED"),
    ("promotional", ["0000320193-26-000001", GOOD_NEWS_ID], 0.6, None, "NEWS_STATUS_BLOCKED"),
    ("contradicted", ["0000320193-26-000001", GOOD_NEWS_ID], 0.6, None, "NEWS_STATUS_CONTRADICTED"),
    ("contradicted", ["0000320193-26-000001", GOOD_NEWS_ID], 0.6, 0.2, None),
    ("single_source", ["0000320193-26-000001", GOOD_NEWS_ID], 0.9, None, "NEWS_STATUS_CONFIDENCE"),
    ("single_source", ["0000320193-26-000001", GOOD_NEWS_ID], 0.85, None, None),
])
def test_forecast_gate_status_as_of_made_at(root, status, ids, conf, widen, code):
    write_jsonl(root, "news_verified", date(2026, 10, 6), [
        status_row([GOOD_NEWS_ID], [status]),
        status_row([], ["confirmed_primary"], cluster_id="AAPL-8k", primary_ids=[FILING])])   # the 8-K confirms
    out = forecast(root, [call(evidence_ids=ids, confidence=conf, range_widen=widen)])
    if code is None:
        assert out["ok"], out["failures"]
        assert out["info"]["evidence_status"]["2026-10-05-AAPL-5d"][GOOD_NEWS_ID] == status
    else:
        assert not out["ok"] and code in codes(out) and codes(out)[code]["tickers"] == ["AAPL"]


def test_forecast_gate_ignores_status_rows_after_made_at(root):
    """A status computed after the call is not the status the call saw."""
    write_jsonl(root, "news_verified", date(2026, 10, 6), [
        status_row([GOOD_NEWS_ID], ["single_source"], as_of="2026-10-06T11:00:00+00:00"),
        status_row([GOOD_NEWS_ID], ["corroborated"], as_of="2026-10-06T11:50:00+00:00")])
    out = forecast(root, [call()])                                    # made_at 11:45
    assert codes(out)["NEWS_STATUS_MAIN"] and "single_source" in codes(out)["NEWS_STATUS_MAIN"]["detail"]
    out = forecast(root, [call(made_at="2026-10-06T11:55:00+00:00")])
    assert out["ok"], out["failures"]


def test_forecast_gate_status_is_per_ticker(root):
    other = {**status_row([GOOD_NEWS_ID], ["corroborated"], cluster_id="MSFT-x"), "ticker": "MSFT"}
    write_jsonl(root, "news_verified", date(2026, 10, 6), [other])
    out = forecast(root, [call()])
    assert "unverified" in codes(out)["NEWS_STATUS_MAIN"]["detail"]  # corroborated for MSFT, not for AAPL


@pytest.mark.parametrize("confirming,why", [
    (None, "a filing that confirms no event (e.g. a Form 4)"),
    ({"cluster_id": "MSFT-x", "ticker": "MSFT"}, "a filing that confirms another ticker's event"),
    ({"cluster_id": "AAPL-y"}, "a filing in an event that is not confirmed_primary"),
])
def test_unrelated_filing_is_not_main_evidence(root, confirming, why):
    rows = [status_row([GOOD_NEWS_ID], ["single_source"])]
    if confirming is not None:
        status = "single_source" if confirming["cluster_id"] == "AAPL-y" else "confirmed_primary"
        rows.append(status_row([], [status], primary_ids=[FILING], **confirming))
    write_jsonl(root, "news_verified", date(2026, 10, 6), rows)
    out = forecast(root, [call(evidence_ids=[FILING, GOOD_NEWS_ID])])
    assert f"main evidence {FILING} is unverified" in codes(out)["NEWS_STATUS_MAIN"]["detail"], why


def test_unrelated_announcement_is_not_main_evidence(root):
    """An NSE-style announcement of the ticker (e.g. a share allotment) that confirms no event."""
    write_jsonl(root, "announcements", date(2026, 10, 6), [{
        "id": "nse-ann-1", "ticker": "AAPL", "company": "Apple", "published_at": "2026-10-06T09:00:00+00:00",
        "category": "Allotment", "subject": "Allotment of 202836 shares", "url": "https://x", "source": "NSE",
        "first_seen_at": "2026-10-06T09:05:00+00:00"}])
    write_jsonl(root, "news_verified", date(2026, 10, 6), [status_row([GOOD_NEWS_ID], ["single_source"])])
    out = forecast(root, [call(evidence_ids=["nse-ann-1"], confidence=0.9)])
    assert {"NEWS_STATUS_MAIN", "NEWS_STATUS_CONFIDENCE"} <= set(codes(out))


def test_forecast_gate_report_lists_codes_json(root):
    write_jsonl(root, "news_verified", date(2026, 10, 6), [status_row([GOOD_NEWS_ID], ["rumour"])])
    out = forecast(root, [call()])
    assert json.loads(json.dumps(out))["ok"] is False
    assert {f["code"] for f in out["failures"]} == {"NEWS_STATUS_MAIN", "NEWS_STATUS_BLOCKED"}
