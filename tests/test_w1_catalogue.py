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

@pytest.mark.parametrize("module", [protocol, watchlist])   # horizons: built by B10 (tests/test_horizons.py)
def test_contract_functions_are_stubs(module):
    functions = [f for name, f in inspect.getmembers(module, inspect.isfunction) if f.__module__ == module.__name__]
    assert functions
    for function in functions:
        assert function.__doc__, function.__name__
        source = inspect.getsource(function)
        assert "raise NotImplementedError" in source, function.__name__


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
            "research_review"} <= names


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
    rows = load("scoreboard_row.json")
    assert {r["scope"] for r in rows} == {"strategy", "strategy_company", "pick_rule"}
    for r in rows:
        assert (r["ticker"] is not None) == (r["scope"] == "strategy_company")
        assert (r["pick_rule"] is not None) == (r["scope"] == "pick_rule")
        assert (r["strategy_id"] is None) == (r["scope"] == "pick_rule")
    trades = [t for t in load("paper_trade.json") if t["status"] == "settled"]
    for r in rows:
        if r["scope"] == "strategy_company":
            mine = [t for t in trades if t["view"] == "accuracy" and t["strategy_id"] == r["strategy_id"]
                    and t["ticker"] == r["ticker"]]
        elif r["scope"] == "pick_rule":
            mine = [t for t in trades if t["view"] == "head_to_head" and t["family"] == r["family"]
                    and t["pick_rule"] == r["pick_rule"] and t["market"] == r["market"]]
        else:
            continue
        assert r["trades"] == len(mine)
        assert r["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in mine), abs=0.011)
