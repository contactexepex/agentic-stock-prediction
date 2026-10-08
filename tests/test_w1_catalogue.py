"""W1 (docs/SPEC.md section 10, Wave 1): the new kinds' schemas, config/strategies.yaml, mcp/tools.yaml, the interface
stubs in marketbrief/contracts/ and the example files of design/catalogue/. Offline."""
from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from marketbrief.constants import kinds  # noqa: E402
from marketbrief.contracts import horizons, protocol, strategies, watchlist  # noqa: E402
from marketbrief.core.database import column_spec  # noqa: E402
from marketbrief.core.schema_lab import LAB_SCHEMAS, W1_SCHEMAS  # noqa: E402
from marketbrief.core.schema_lifecycle import LIFECYCLE_SCHEMAS  # noqa: E402
from marketbrief.core.schemas import SCHEMAS  # noqa: E402

W1_KINDS = {
    kinds.KIND_WATCHLIST_EVENTS, kinds.KIND_COMMAND_LOG, kinds.KIND_STRATEGY_PREDICTIONS,
    kinds.KIND_STRATEGY_ABSTENTIONS, kinds.KIND_PAPER_TRADES_SETTLED, kinds.KIND_HEAD_TO_HEAD_PICKS,
    kinds.KIND_TRADE_REASONS_AI, kinds.KIND_TRADE_CHECKS, kinds.KIND_EOD_ANALYSES, kinds.KIND_RESEARCH_REVIEWS,
    kinds.KIND_NEWS_IMPACT,
}
CATALOGUE = REPO / "design" / "catalogue"
STRATEGIES = yaml.safe_load((REPO / "config" / strategies.STRATEGIES_FILE).read_text(encoding="utf-8"))
TOOLS = yaml.safe_load((REPO / "mcp" / "tools.yaml").read_text(encoding="utf-8"))


# ---------------- schemas ----------------

def test_w1_kinds_are_the_spec_section_4_kinds_and_registered():
    assert set(W1_SCHEMAS) == W1_KINDS == set(LAB_SCHEMAS) | set(LIFECYCLE_SCHEMAS)
    assert not set(LAB_SCHEMAS) & set(LIFECYCLE_SCHEMAS)
    for kind in W1_KINDS:
        assert SCHEMAS[kind] == W1_SCHEMAS[kind]


def test_w1_kinds_are_new_names():
    """No W1 kind replaces a kind defined before W1 (the registration is purely additive)."""
    from marketbrief.core import schemas as schemas_module

    source = inspect.getsource(schemas_module)
    assert source.count("W1_SCHEMAS") == 2   # one import line, one spread line
    assert len([line for line in source.splitlines() if "# W1" in line]) == 2
    others = {k for k in SCHEMAS if k not in W1_KINDS}
    assert not others & W1_KINDS


@pytest.mark.parametrize("kind", sorted(W1_KINDS))
def test_w1_schema_types_are_valid_duckdb(kind):
    file_format, columns = SCHEMAS[kind]
    assert file_format == "jsonl"
    assert "id" in columns
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t ({', '.join(f'{name} {sql_type}' for name, sql_type in columns.items())})")
    assert [row[0] for row in con.execute("DESCRIBE t").fetchall()] == list(columns)


def test_w1_kinds_have_a_storage_time_and_market_where_needed():
    """Every kind carries a column the as-of reads filter on (ARCHITECTURE.md 4.3)."""
    stored_at = {"made_at", "recorded_at", "received_at", "settled_at", "created_at", "computed_at", "written_at"}
    for kind in W1_KINDS:
        assert stored_at & set(SCHEMAS[kind][1]), kind


def test_lab_columns_follow_the_spec():
    trade = SCHEMAS[kinds.KIND_PAPER_TRADES_SETTLED][1]
    for column in ("target_reached", "target_reached_session", "max_favourable_pct", "max_adverse_pct", "range_hit",
                   "target_error_pct", "net_pnl", "costs", "quantity", "reason_code", "market_pct", "sector_pct",
                   "news_pct", "company_pct", "view", "pick_rule", "supersedes"):
        assert column in trade
    pred = SCHEMAS[kinds.KIND_STRATEGY_PREDICTIONS][1]
    for column in ("strategy_id", "horizon_days", "direction", "prob_up", "target_price", "lo80", "hi80",
                   "evidence_ids", "made_at", "session_date", "exit_date", "qualifies", "threshold"):
        assert column in pred
    events = SCHEMAS[kinds.KIND_WATCHLIST_EVENTS][1]
    for column in ("event", "effective_from", "recorded_at", "requested_by", "channel", "idempotency_key", "amount",
                   "sector"):
        assert column in events


# ---------------- config/strategies.yaml ----------------

def parameter_problems(spec: dict) -> list[str]:
    """The parameter and threshold rules of one registry entry."""
    sid, params, problems = spec["id"], spec["parameters"], []
    expected = strategies.AI_PARAMETERS if spec["family"] == "ai" else strategies.RULE_PARAMETERS
    if set(params) != set(expected):
        return [f"{sid}: parameters must be exactly {expected}"]
    if spec["family"] == "ai":
        if params["model"] not in strategies.AI_MODELS or not set(params["inputs"]) <= set(strategies.AI_INPUTS):
            problems.append(f"{sid}: unknown model or input")
        if params["sees_model_score"] != ("model_score" in params["inputs"]):
            problems.append(f"{sid}: sees_model_score must match its inputs")
    else:
        if params["signal"] not in strategies.SIGNALS or params["news_weight"] not in strategies.NEWS_WEIGHTS:
            problems.append(f"{sid}: unknown signal or news weight")
        if not set(params["news_statuses"]) <= set(strategies.NEWS_STATUSES) or not set(
                params["news_materiality"]) <= set(strategies.MATERIALITY_LEVELS):
            problems.append(f"{sid}: unknown news status or materiality")
    no_probability = spec["family"] != "ai" and params["signal"] in strategies.SIGNALS_WITHOUT_PROBABILITY
    threshold = spec["threshold"]
    if no_probability != (threshold is None) or (threshold is not None and not 0.5 <= threshold < 1):
        problems.append(f"{sid}: threshold must be null exactly for signals without a probability, else 0.5-1")
    return problems


def comparison_problems(spec: dict, by_id: dict) -> list[str]:
    """F2.5: an entry differs from the strategy it is compared with in exactly the parameter it names."""
    sid = spec["id"]
    if (spec["compared_to"] is None) != (spec["differs_in"] is None):
        return [f"{sid}: compared_to and differs_in go together"]
    if spec["compared_to"] is None:
        return []
    other = by_id.get(spec["compared_to"])
    if other is None:
        return [f"{sid}: compares to an unknown strategy"]
    params = spec["parameters"]
    diff = {key for key in params if params[key] != other["parameters"].get(key)}
    # The threshold counts as a parameter only when both sides have one. A signal without a probability
    # (always_up, momentum) has no threshold by construction (checked in parameter_problems), so its null
    # threshold is part of its `signal` difference, not a second one.
    if spec["threshold"] is not None and other["threshold"] is not None and spec["threshold"] != other["threshold"]:
        diff.add("threshold")
    if diff != {spec["differs_in"]}:
        return [f"{sid}: differs from {spec['compared_to']} in {sorted(diff)}, not only {spec['differs_in']}"]
    return []


def entry_problems(spec: dict, horizons_list: list, ai_horizons: list, by_id: dict) -> list[str]:
    sid = spec.get("id", "?")
    missing = set(strategies.StrategySpec.__annotations__) - set(spec)
    if missing:
        return [f"{sid}: missing {sorted(missing)}"]
    problems = []
    prefix = strategies.ID_PREFIX.get(spec["family"], "?") + "."
    if not re.match(strategies.ID_PATTERN, sid) or not sid.startswith(prefix):
        problems.append(f"{sid}: id does not match its family")
    if not spec["description"] or len(spec["description"].split()) < 8:
        problems.append(f"{sid}: needs a plain-language description")
    allowed = ai_horizons if spec["family"] == "ai" else horizons_list
    if not spec["horizons"] or not set(spec["horizons"]) <= set(allowed):
        problems.append(f"{sid}: horizons outside the allowed list")
    if spec["live_from"] is not None and not isinstance(spec["live_from"], date):
        problems.append(f"{sid}: live_from must be a date or null")
    return problems + parameter_problems(spec) + comparison_problems(spec, by_id)


def strategy_problems(registry: dict) -> list[str]:
    """Every rule of config/strategies.yaml (the registry's schema, F2.1, F2.5, F2.7)."""
    problems = []
    horizons_list = registry.get("horizons")
    if not (isinstance(horizons_list, list) and horizons_list and horizons_list == sorted(set(horizons_list))
            and all(isinstance(h, int) and 1 <= h <= strategies.MAX_HORIZON for h in horizons_list)):
        problems.append("horizons must be a sorted list of distinct integers 1..21")
        horizons_list = []
    ai_horizons = registry.get("ai_horizons") or []
    if not set(ai_horizons) <= set(horizons_list):
        problems.append("ai_horizons must be a subset of horizons")
    entries = registry.get("strategies", [])
    ids = [s.get("id") for s in entries]
    if len(ids) != len(set(ids)):
        problems.append("duplicate strategy ids")
    by_id = {s.get("id"): s for s in entries}
    for spec in entries:
        problems += entry_problems(spec, horizons_list, ai_horizons, by_id)
    return problems


def test_strategies_registry_is_valid():
    assert strategy_problems(STRATEGIES) == []


def test_strategies_registry_matches_the_spec():
    assert STRATEGIES["horizons"] == [1, 2, 3, 4, 5]           # decision 37
    assert STRATEGIES["ai_horizons"] == [1, 3, 5]               # decision 38
    families = [s["family"] for s in STRATEGIES["strategies"]]
    assert families.count("rule") == 8 and families.count("baseline") == 3 and families.count("ai") == 4   # F2.5, F4
    ids = {s["id"] for s in STRATEGIES["strategies"]}
    assert {"base.always_up.v1", "base.momentum.v1", "base.model_only.v1"} <= ids   # F2.2
    assert {"ai.news_results.sonnet.v1", "ai.pattern_mood.sonnet.v1", "ai.combined.sonnet.v1",
            "ai.combined.opus.v1"} <= ids   # F4.1
    blind = {s["id"]: s["parameters"]["sees_model_score"] for s in STRATEGIES["strategies"] if s["family"] == "ai"}
    assert blind == {"ai.news_results.sonnet.v1": False, "ai.pattern_mood.sonnet.v1": False,
                     "ai.combined.sonnet.v1": True, "ai.combined.opus.v1": True}   # decision 10
    rules = [s for s in STRATEGIES["strategies"] if s["family"] == "rule"]
    assert len({s["differs_in"] for s in rules if s["differs_in"]}) >= 6   # the set varies several parameters


@pytest.mark.parametrize("broken, message", [
    ({"horizons": [1, 1, 2]}, "horizons must be"),
    ({"ai_horizons": [7]}, "ai_horizons must be"),
])
def test_strategy_problems_catches_bad_top_level(broken, message):
    registry = {**STRATEGIES, **broken}
    assert any(message in p for p in strategy_problems(registry))


def test_strategy_problems_catches_bad_entries():
    def with_change(index: int, **change) -> list[str]:
        specs = [dict(s) for s in STRATEGIES["strategies"]]
        specs[index] = {**specs[index], **change}
        return strategy_problems({**STRATEGIES, "strategies": specs})

    half = next(i for i, s in enumerate(STRATEGIES["strategies"]) if s["id"] == "rule.model_news_half.v1")
    always = next(i for i, s in enumerate(STRATEGIES["strategies"]) if s["id"] == "base.always_up.v1")
    assert any("not only" in p for p in with_change(half, threshold=0.6))
    assert any("threshold must be null" in p for p in with_change(always, threshold=0.55))
    assert any("id does not match" in p for p in with_change(half, family="baseline"))
    assert any("horizons outside" in p for p in with_change(half, horizons=[6]))
    params = {**STRATEGIES["strategies"][half]["parameters"], "news_weight": 3.0}
    assert any("unknown signal or news weight" in p for p in with_change(half, parameters=params))


# ---------------- mcp/tools.yaml ----------------

F10_TOOLS = {"get_overview", "get_company", "get_scoreboard", "compare_rule_vs_ai", "get_news", "get_trades",
             "explain", "add_company", "deactivate_company", "reactivate_company", "set_paper_amount",
             "delete_company", "add_paper_trade"}


def test_tools_are_the_f10_set_with_every_channel():
    tools = {t["name"]: t for t in TOOLS["tools"]}
    assert set(tools) == F10_TOOLS and len(TOOLS["tools"]) == len(F10_TOOLS)
    for tool in tools.values():
        assert set(tool["channels"]) == set(TOOLS["channels"]) == {"dashboard", "slack", "claude_code", "claude_app"}
        assert tool["kind"] in ("read", "read_ai", "write")
        assert tool["description"] and tool["inputs"]["market"]
        for value in tool["channels"].values():
            assert value is True or value is False or (isinstance(value, str) and value)
    delete = tools["delete_company"]["channels"]
    assert delete["slack"] is False and delete["claude_code"] is False and delete["claude_app"] is False   # 15, 20
    assert delete["dashboard"] and tools["delete_company"]["inputs"]["confirm"]["required"] is True


def test_write_tools_need_an_idempotency_key_and_write_known_kinds():
    refs = TOOLS["common_inputs"]
    for tool in TOOLS["tools"]:
        for spec in tool["inputs"].values():
            if "$ref" in spec:
                assert spec["$ref"].split(".", 1)[1] in refs
        if tool["kind"] == "write":
            key = tool["inputs"].get("idempotency_key")
            assert key and key["required"] is True, tool["name"]
            assert "command_log" in tool["writes"] and set(tool["writes"]) <= set(SCHEMAS), tool["name"]
            assert tool["validator"]
        else:
            assert "writes" not in tool and "idempotency_key" not in tool["inputs"]


def test_no_tool_mentions_orders_or_brokers():
    text = (REPO / "mcp" / "tools.yaml").read_text(encoding="utf-8").lower()
    assert "no tool places, routes or simulates a broker order" in text
    for word in ("place_order", "submit_order", "broker_api"):
        assert word not in text


# ---------------- contracts ----------------

# All three contracts are built: watchlist by B1 (tests/test_lifecycle.py), horizons by B10 (tests/test_horizons.py),
# protocol by B2 (delegation checked below), so no stub test remains.


def test_protocol_contract_delegates_to_the_lab_with_the_same_signatures():
    """B2 built the F1 engine: each contract function forwards to marketbrief/lab/protocol.py unchanged."""
    from marketbrief.lab import protocol as lab_protocol

    functions = [f for _, f in inspect.getmembers(protocol, inspect.isfunction) if f.__module__ == protocol.__name__]
    assert len(functions) == 9
    for function in functions:
        assert function.__doc__, function.__name__
        source = inspect.getsource(function)
        assert "NotImplementedError" not in source and f"lab_protocol.{function.__name__}(" in source
        target = getattr(lab_protocol, function.__name__)
        assert list(inspect.signature(function).parameters) == list(inspect.signature(target).parameters)


def test_horizon_records_extend_todays_kinds():
    assert set(SCHEMAS["model_scores"][1]) <= set(horizons.HorizonScore.__annotations__)
    assert set(SCHEMAS["ranges"][1]) <= set(horizons.HorizonRange.__annotations__)
    for record in (horizons.HorizonScore, horizons.HorizonRange):
        assert {"horizon_label", "entry_date", "exit_date"} <= set(record.__annotations__)


def test_contract_values_match_the_schemas_and_registry():
    assert set(STRATEGIES["strategies"][0]) == set(strategies.StrategySpec.__annotations__)
    assert watchlist.DEFAULT_AMOUNT == {"india": 100000.0, "us": 1000.0}   # decision 26
    assert protocol.MIN_TRADES_PER_COMPANY == 20                              # decision 41


# ---------------- design/catalogue ----------------

def catalogue_files() -> list[Path]:
    return sorted(CATALOGUE.glob("*.json"))


def test_catalogue_has_every_entity():
    names = {p.stem for p in catalogue_files()}
    assert {"company", "prediction", "paper_trade", "head_to_head_pick", "strategy", "scoreboard_row", "reason_ai",
            "news_item", "results_digest", "trade_check", "lifecycle_event", "market_status", "portfolio",
            "agreement", "open_trade", "abstention", "command_log", "eod_analysis", "news_impact",
            "research_review", "calendar_event", "bar", "scoreboard_backtest_row", "heatmap_cell",
            "cumulative_line", "track_record", "assistant_answer"} <= names


@pytest.mark.parametrize("path", catalogue_files(), ids=lambda p: p.name)
def test_catalogue_file_is_a_marked_example(path):
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["_example"] is True and "EXAMPLE" in body["_note"]
    assert body["records"]
    anchor = body["catalogue"].split("#", 1)[1]
    catalogue_md = (REPO / "docs" / "DATA_CATALOGUE.md").read_text(encoding="utf-8")
    assert f'<a id="{anchor}"></a>' in catalogue_md, anchor
    if body["kind"] is not None:
        columns = SCHEMAS[body["kind"]][1]
        for record in body["records"]:
            assert list(record) == list(columns)


@pytest.mark.parametrize("path", [p for p in catalogue_files()
                                  if json.loads(p.read_text(encoding="utf-8"))["kind"]], ids=lambda p: p.name)
def test_catalogue_rows_load_with_the_kind_types(path, tmp_path):
    body = json.loads(path.read_text(encoding="utf-8"))
    rows = tmp_path / "rows.jsonl"
    rows.write_text("".join(json.dumps(r) + "\n" for r in body["records"]), encoding="utf-8")
    spec = column_spec(SCHEMAS[body["kind"]][1])
    query = f"SELECT count(*) FROM read_json('{rows.as_posix()}', format='newline_delimited', columns={spec})"
    count = duckdb.connect().execute(query).fetchone()[0]
    assert count == len(body["records"])


def load(name: str) -> list[dict]:
    return json.loads((CATALOGUE / name).read_text(encoding="utf-8"))["records"]


def test_catalogue_covers_both_markets_and_all_horizons():
    preds = load("prediction.json")
    assert {p["market"] for p in preds} == {"india", "us"}
    assert {p["horizon_days"] for p in preds} == {1, 2, 3, 4, 5}
    assert {p["currency"] for p in preds if p["market"] == "india"} == {"INR"}
    assert {p["currency"] for p in preds if p["market"] == "us"} == {"USD"}
    ids = {s["id"] for s in STRATEGIES["strategies"]}
    assert {p["strategy_id"] for p in preds} == ids
    for p in preds:
        assert p["id"] == f"{p['strategy_id']}:{p['as_of_date']}-{p['ticker']}-{p['horizon_days']}d"
        assert p["lo80"] <= p["lo50"] <= p["hi50"] <= p["hi80"]


def test_catalogue_trades_are_internally_consistent():
    for t in load("paper_trade.json"):
        if t["status"] != "settled":
            continue
        assert t["costs"] == pytest.approx(sum(t["cost_lines"].values()), abs=0.011)
        assert t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["costs"], abs=0.011)
        assert t["return_pct"] == pytest.approx(t["net_pnl"] / t["amount"] * 100, abs=0.011)
        assert t["move_pct"] == pytest.approx(t["market_pct"] + t["sector_pct"] + t["news_pct"] + t["company_pct"],
                                              abs=0.011)
        if t["market"] == "india":
            assert t["quantity"] == int(t["quantity"])
        assert t["range_hit"] == (t["lo80"] <= t["exit_price"] <= t["hi80"])
    predictions = {p["id"] for p in load("prediction.json")}
    for pick in load("head_to_head_pick.json"):
        if pick["status"] == "picked" and pick["as_of_date"] == "2026-10-06" and pick["ticker"] in ("NVDA", "RELIANCE"):
            assert pick["prediction_id"] in predictions
    events = {e["id"] for e in load("lifecycle_event.json")}
    for command in load("command_log.json"):
        assert set(command["record_ids"]) <= events


def test_tool_channel_values_read_the_same_in_yaml_1_1_and_1_2():
    """yes/no/on/off are booleans in YAML 1.1 (PyYAML) but strings in YAML 1.2 (the TypeScript tool layer)."""
    ambiguous = re.compile(r":\s*(yes|no|on|off|y|n)\s*[,}]", re.IGNORECASE)
    for line in (REPO / "mcp" / "tools.yaml").read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("#"):
            assert not ambiguous.search(line), line


def test_catalogue_lifecycle_events_match_their_market():
    exchanges = {"india": {"NSE"}, "us": {"NYSE", "NASDAQ"}}
    currencies = {"india": "INR", "us": "USD"}
    events = load("lifecycle_event.json")
    for event in events:
        if event["event"] == "add":
            assert event["exchange"] in exchanges[event["market"]], event["id"]
            assert (event["nse_symbol"] is not None) == (event["market"] == "india"), event["id"]
            assert event["cik"] is None or event["market"] == "us", event["id"]
        if event["currency"] is not None:
            assert event["currency"] == currencies[event["market"]], event["id"]
    added = {(e["market"], e["ticker"]) for e in events if e["event"] == "add"}
    for company in load("company.json"):
        assert (company["market"], company["ticker"]) in added
        assert company["currency"] == currencies[company["market"]]
        assert company["exchange"] in exchanges[company["market"]]


def test_catalogue_scoreboard_has_every_slice():
    """scoreboard_row.json is built by B2's lab/scoreboard.py; each slice's counts and profit match paper_trade.json."""
    rows = load("scoreboard_row.json")
    assert {r["scope"] for r in rows} == {"strategy", "strategy_company", "pick_rule", "strategy_regime"}
    for r in rows:
        assert (r["ticker"] is not None) == (r["scope"] == "strategy_company")
        assert (r["pick_rule"] is not None) == (r["scope"] == "pick_rule")
        assert (r["strategy_id"] is None) == (r["scope"] == "pick_rule")
        assert (r["regime"] is not None) == (r["scope"] == "strategy_regime")
    trades = [t for t in load("paper_trade.json") if t["status"] == "settled"]
    for r in rows:
        mine = [t for t in trades if t["market"] == r["market"] and t["view"] == r["view"]
                and r["horizon_days"] in ("all", t["horizon_days"])
                and r["strategy_id"] in (None, t["strategy_id"]) and r["family"] == t["family"]
                and r["ticker"] in (None, t["ticker"]) and r["pick_rule"] in (None, t["pick_rule"])
                and r["regime"] in (None, t["regime"])]
        assert r["trades"] == len(mine), r
        assert r["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in mine), abs=0.011)
        assert r["luck_test"]["n"] == len(mine)


def test_catalogue_cost_views_agree_with_the_trades():
    """cost_view.json (B2's kind): settlement rows repeat the trade's market costs; your cost = market + own lines."""
    trades = {t["id"]: t for t in load("paper_trade.json")}
    rows = load("cost_view.json")
    assert {r["record_kind"] for r in rows} == {"prediction", "pick", "settlement"}
    for r in rows:
        assert r["your_costs"] == pytest.approx(sum(r["your_cost_lines"].values()), abs=0.011)
        assert set(r["market_cost_lines"].items()) <= set(r["your_cost_lines"].items())
        if r["record_kind"] == "settlement":
            trade = trades[r["record_id"]]
            assert r["market_costs"] == trade["costs"] and r["market_cost_lines"] == trade["cost_lines"]
            assert r["net_pnl_market"] == pytest.approx(trade["net_pnl"], abs=0.011)
            assert r["cost_viable"] is None
        else:
            gain = r["expected_gain_your_pct"]   # owner decision 2026-10-07 (B2): viable = gain after your cost > 0
            assert r["cost_viable"] == (None if gain is None else gain > 0)   # no probability (baselines): null


def test_catalogue_trade_checks_use_the_real_check_ids_and_carry_the_b9_columns():
    for r in load("trade_check.json"):
        assert re.fullmatch(r"ic-(india|us)-\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", r["check_id"])
        assert r["id"] == f"{r['check_id']}-{r['trade_id']}" and r["check_row_id"] == f"{r['check_id']}-{r['ticker']}"
        assert r["quality"] == "ok" and r["entry_adj"] == r["entry_price"] * r["basis_factor"]
        assert r["sessions_held"] == pytest.approx(r["session_number"] - 1 + r["elapsed_fraction"], abs=0.0002)


def test_trade_check_rows_view_reads_old_split_rows_and_new_single_rows():
    """Issue #78: the B9 view takes each moved column from trade_checks when set, else from trade_check_details."""
    views = (REPO / "sql" / "views.sql").read_text(encoding="utf-8")
    statement = views[views.index("CREATE OR REPLACE VIEW trade_check_rows"):]
    statement = statement[:statement.index(";") + 1]
    con = duckdb.connect()
    for kind in (kinds.KIND_TRADE_CHECKS, "trade_check_details"):
        con.execute(f"CREATE TABLE {kind} ({', '.join(f'{c} {t}' for c, t in SCHEMAS[kind][1].items())})")
    con.execute("INSERT INTO trade_checks (id, computed_at, quality, target_reached) VALUES "
                "('new', '2026-10-08T00:00:00Z', 'ok', true), ('old', '2026-10-07T00:00:00Z', NULL, NULL)")
    con.execute("INSERT INTO trade_check_details (id, computed_at, quality, target_reached) VALUES "
                "('old', '2026-10-07T00:00:00Z', 'stale_quote', false)")
    con.execute(statement)
    got = con.execute("SELECT id, quality, target_reached FROM trade_check_rows ORDER BY id").fetchall()
    assert got == [("new", "ok", True), ("old", "stale_quote", False)]
    columns = [row[0] for row in con.execute("DESCRIBE trade_check_rows").fetchall()]
    assert len(columns) == len(set(columns)) and set(columns) == set(SCHEMAS[kinds.KIND_TRADE_CHECKS][1])


def test_catalogue_calendar_follows_the_engine():
    from marketbrief.analytics.earnings_reaction import affected_sessions
    from marketbrief.core import calendar
    from marketbrief.core.market_config import load_market

    rows = load("calendar_event.json")
    start, end = date(2026, 10, 7), date(2026, 12, 2)
    for market in ("india", "us"):
        cfg = load_market(market)
        mine = [r for r in rows if r["market"] == market]
        configured = sorted((str(e["date"]), e["type"], e["name"], e["major"])
                            for e in calendar.market_events(cfg, start, end))
        assert sorted((r["date"], r["type"], r["name"], r["major"]) for r in mine
                      if r["source"] == "config/events.yaml") == configured
        closed = [str(d) for d in (date.fromordinal(n) for n in range(start.toordinal(), end.toordinal() + 1))
                  if d.weekday() < 5 and not calendar.is_session(cfg, d)]
        assert [r["date"] for r in mine if r["type"] == "holiday"] == closed
        for row in mine:
            assert row["widens"] == ("market" if row["major"] else "company" if row["type"] == "earnings" else None)
            if row["ticker"]:
                assert row["ticker"] in cfg["active_tickers"] and row["ticker"] not in ("INDIGO", "DAL")
                assert row["major"] is False and row["source"].startswith("events")
            if row["type"] == "earnings":
                day = date.fromisoformat(row["date"])
                assert row["reaction_sessions"] == [str(s) for s in affected_sessions(cfg, day, row["timing"])]
    by_ticker = {r["ticker"]: r for r in rows if r["type"] == "earnings"}
    assert by_ticker["AAPL"]["date"] == "2026-10-29"        # the 2 Nov row was first seen after the cut-off
    assert by_ticker["HDFCBANK"]["reaction_sessions"] == ["2026-10-19"]   # a Saturday date reacts on Monday
    assert {"TCS", "NVDA", "JPM", "RELIANCE", "HDFCBANK", "MARUTI", "AAPL"} <= set(by_ticker)


def test_catalogue_market_status_benchmark_and_vol_index():
    from marketbrief.core.market_config import load_market

    for status in load("market_status.json"):
        symbols = load_market(status["market"])["symbols"]
        for role in ("benchmark", "vol_index"):
            block = status[role]
            assert symbols[block["symbol"]]["role"] == role and symbols[block["symbol"]]["name"] == block["name"]
            assert block["close_date"] == status["as_of"]
    india = {s["market"]: s for s in load("market_status.json")}["india"]
    assert india["benchmark"]["change_pct"] == round((22776.0996 / 22555.75 - 1) * 100, 2)   # stored Nifty closes
    assert india["benchmark"]["change_5d_pct"] == round((22776.0996 / 22780.25 - 1) * 100, 2)


def test_catalogue_bars_are_60_consecutive_sessions_ending_at_the_as_of_close():
    from marketbrief.core import calendar
    from marketbrief.core.market_config import load_market

    bars = load("bar.json")
    last_close = {c["ticker"]: c["last_close"] for c in load("company.json") if c["state"] == "active"}
    for ticker in last_close:
        mine = [b for b in bars if b["ticker"] == ticker]
        cfg = load_market(mine[0]["market"])
        days = [date.fromisoformat(b["date"]) for b in mine]
        assert len(mine) == 60 and days[-1] == date(2026, 10, 6)
        assert all(calendar.next_session(cfg, a, include=False) == b for a, b in zip(days, days[1:]))
        assert mine[-1]["close"] == last_close[ticker]
        assert all(b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"] for b in mine)


def test_catalogue_backtest_rows_are_apart_from_forward_rows():
    backtest = load("scoreboard_backtest_row.json")
    assert {r["basis"] for r in backtest} == {"backtest"} and {r["view"] for r in backtest} == {"accuracy"}
    assert {r["strategy_id"] for r in backtest} == {"base.always_up.v1", "base.momentum.v1", "base.model_only.v1"}
    assert {r["market"] for r in backtest} == {"india", "us"}
    assert {r["horizon_days"] for r in backtest} == {1, 2, 3, 4, 5, "all"}
    assert {r["basis"] for r in load("scoreboard_row.json")} == {"forward"}
    for market in ("india", "us"):
        for sid in ("base.always_up.v1", "base.momentum.v1", "base.model_only.v1"):
            mine = {r["horizon_days"]: r for r in backtest if r["market"] == market and r["strategy_id"] == sid}
            assert mine["all"]["trades"] == sum(mine[k]["trades"] for k in range(1, 6))


def test_catalogue_heatmap_cells_and_lines_add_up_to_the_scoreboard():
    cells, lines = load("heatmap_cell.json"), load("cumulative_line.json")
    board = {(r["market"], r["view"], r["strategy_id"]): r for r in load("scoreboard_row.json")
             if r["scope"] == "strategy" and r["horizon_days"] == "all"}
    for (market, view, sid), row in board.items():
        for dimension in ("horizon", "company", "reason_code"):
            mine = [c for c in cells if (c["market"], c["view"], c["strategy_id"], c["dimension"], c["week"])
                    == (market, view, sid, dimension, "all")]
            assert sum(c["trades"] for c in mine) == row["trades"]
            assert round(sum(c["net_pnl"] for c in mine), 2) == round(row["net_pnl"], 2)
        weekly = [c for c in cells if (c["market"], c["view"], c["strategy_id"], c["dimension"]) == (market, view, sid,
                  "horizon") and c["week"] != "all"]
        assert sum(c["trades"] for c in weekly) == row["trades"]
        if view == "accuracy":
            assert [p for p in lines if (p["market"], p["view"], p["series"]) == (market, view, sid)][-1][
                "cumulative_net_pnl"] == round(row["net_pnl"], 2)


def test_catalogue_w40_reviews_are_written_before_the_cut_off_from_trades_settled_by_then():
    body = json.loads((CATALOGUE / "research_review.json").read_text(encoding="utf-8"))
    trades = load("paper_trade.json")
    w40 = [r for r in body["records"] if r["iso_week"] == "2026-W40"]
    assert {r["market"] for r in w40} == {"india", "us"}
    for review in w40:
        assert review["written_at"] < body["as_of"]
        for leader in review["leaders"]:
            known = [t for t in trades if t["market"] == review["market"] and t["strategy_id"] == leader["strategy_id"]
                     and t["view"] == "accuracy" and t["status"] == "settled"
                     and t["settled_at"] <= review["written_at"]]
            assert leader["trades"] == len(known)
            assert leader["net_pnl"] == round(sum(t["net_pnl"] for t in known), 2)
        for leader in review["leaders"]:   # the top of B3's director order (net_pnl desc, trades desc, strategy_id)
            settled = [t for t in trades if t["market"] == review["market"] and t["family"] == leader["scope"]
                       and t["view"] == "accuracy" and t["status"] == "settled"
                       and t["settled_at"] <= review["written_at"]]
            totals = {}
            for t in settled:
                count, net = totals.get(t["strategy_id"], (0, 0.0))
                totals[t["strategy_id"]] = (count + 1, net + t["net_pnl"])
            ranked = sorted(totals, key=lambda sid: (-round(totals[sid][1], 2), -totals[sid][0], sid))
            assert leader["strategy_id"] == ranked[0]


def test_catalogue_track_record_calls_are_the_forecaster_example_calls_close_to_close():
    trades = load("paper_trade.json")
    for payload in load("track_record.json"):
        assert payload["example_parts"] == ["calls", "weekly"] and payload["skill"]["state"] == "paper"
        mine = [t for t in trades if t["market"] == payload["market"] and t["strategy_id"] == "ai.combined.opus.v1"
                and t["view"] == "accuracy" and t["status"] == "settled"]
        (block,) = payload["calls"]
        assert block["basis"] == "close_to_close" and block["all"]["n"] == len(mine)
        assert sum(r["n"] for r in block["all"]["reliability"]) == len(mine)
        assert sum(b["n"] for b in block["by_horizon"].values()) == len(mine)
        assert all(key.endswith("legacy_cc") for key in block["by_horizon"])
        (series,) = payload["weekly"]   # the same calls per ISO week of their target date
        assert series["key"] == block["key"] and sum(w["n"] for w in series["weeks"]) == len(mine)
        assert sum(w["hits"] for w in series["weeks"]) == block["all"]["hits"]
        hits = 0   # the engine's close-to-close window: the as-of close to the close h stored bars later
        bars = {b["ticker"]: {x["date"]: x["close"] for x in load("bar.json") if x["ticker"] == b["ticker"]}
                for b in load("bar.json") if b["market"] == payload["market"]}
        for trade in mine:
            closes = bars[trade["ticker"]]
            later = sorted(day for day in closes if day > "2026-09-29")
            hits += closes[later[trade["horizon_days"] - 1]] > closes["2026-09-29"]
        assert block["all"]["hits"] == hits


def test_catalogue_assistant_answers_cite_existing_records_before_their_as_of():
    by_id = {r["id"]: r for name in ("paper_trade.json", "eod_analysis.json", "news_item.json") for r in load(name)}
    cut_off = json.loads((CATALOGUE / "assistant_answer.json").read_text(encoding="utf-8"))["as_of"]
    words = {"rule": "Rule strategies", "ai": "AI traders", "baseline": "Baselines"}
    for answer in load("assistant_answer.json"):
        assert answer["as_of"] <= answer["asked_at"] <= cut_off   # a page at the cut-off can show every answer
        assert answer["cited_ids"] == [c["id"] for c in answer["cited"]]
        for cited in answer["cited"]:
            assert cited["as_of"] <= answer["as_of"] and cited["id"] in by_id
        if answer["declined"] or answer["not_in_data"]:
            assert answer["cited"] == []
            continue
        record = by_id[answer["cited_ids"][0]]
        if "return_pct" in record:
            value, minus = record["return_pct"], "\u2212"
            assert f"{minus if value < 0 else '+'}{abs(value):.2f} %" in answer["text"]
        else:
            for family, word in words.items():
                assert f"{word}: {record['results'][family]['trades']} trades" in answer["text"]
        assert "_" not in answer["text"].replace("rule.model_news.v1", "")   # plain words, no raw codes


def test_catalogue_news_page_items_are_stored_news_as_of_the_cut_off():
    body = json.loads((CATALOGUE / "news_item.json").read_text(encoding="utf-8"))
    items, cut_off = body["records"], body["as_of"]
    assert [i["origin"] for i in items[:6]] == ["invented"] * 6
    stored = [i for i in items if i["origin"] == "stored"]
    for market in ("india", "us"):
        mine = [i for i in stored if i["market"] == market]
        assert len(mine) == 28 and {i["scope"] for i in mine} == {"company", "market"}
        assert sum("2026-10-06T12:00:00Z" <= i["first_seen_at"] for i in mine) >= 12
    for news in stored:
        assert "2026-10-04T12:00:00Z" <= news["first_seen_at"] <= cut_off
        assert news["enrichment"]["analyzed_at"] <= cut_off
        assert news["status_as_of"] is None or news["status_as_of"] <= cut_off
        assert news["scope"] == ("company" if news["primary_tickers"] else "market")
        assert news["summary_source"] in ("article", "analyst", "none") and (news["summary"] is None) == (
            news["summary_source"] == "none")
    for news in items:
        materiality, kind = news["enrichment"]["materiality"], news["enrichment"]["event_type"]
        assert news["market_moving"] == (materiality == "high" and (news["scope"] == "market" or kind == "earnings"))
