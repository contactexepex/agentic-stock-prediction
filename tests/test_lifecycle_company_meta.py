"""Wave 5 (B18's config change, B1's loader): config/markets/<market>.yaml's `tickers:` becomes `company_meta:`
(per-company metadata only). Membership comes from the watchlist events alone; company_meta entries act as the
implicit seed only while a market has no stored watchlist event. The proof: on the real configs and the real seed
events, everything the lifecycle gives (load_market, the active lists, the accessor, every watchlist state, the
command validator's pending state) is byte-identical with either key, at clocks from before the seed's
effective_from to now. Offline: a temporary data root holding a copy of the repo's watchlist events."""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import common  # noqa: E402
from marketbrief.contracts.watchlist import watchlist  # noqa: E402
from marketbrief.core.clock import clock  # noqa: E402
from marketbrief.core.market_config import load_market  # noqa: E402
from marketbrief.lifecycle import accessor, commands  # noqa: E402
from marketbrief.lifecycle.events import stored_events  # noqa: E402
from marketbrief.lifecycle.loader import active_sectors, active_tickers  # noqa: E402
from marketbrief.lifecycle.seed import seed  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MARKETS = ("india", "us")
STATES = ("collected", "active", "inactive", "deleted")
CLOCKS = (
    "2024-01-01T00:00:00+00:00",   # before the seed's effective_from (the first stored day): no company
    "2024-10-07T00:00:00+00:00",   # the seed's effective_from
    "2025-06-01T12:00:00+00:00",
    "2026-10-07T20:16:30+00:00",   # just after the seed's recorded_at (20:15:58 india, 20:16:00 us)
    "2026-10-07T20:30:00+00:00",
    "2026-10-08T21:00:00+00:00",
)
UNKNOWN = "ZZZZ"


def renamed_config(target: Path, extra: dict | None = None, keep_tickers: bool = False) -> Path:
    """A copy of the real config with `tickers:` renamed to `company_meta:` (plus `extra` entries in it)."""
    shutil.copytree(REPO / "config", target)
    for market in MARKETS:
        path = target / "markets" / f"{market}.yaml"
        text = path.read_text()
        assert len(re.findall(r"^tickers:", text, flags=re.M)) == 1
        text = re.sub(r"^tickers:", "company_meta:", text, flags=re.M)
        if keep_tickers:
            text += "\ntickers:\n  AAPL: {}\n"
        if extra:
            entries = "".join(f"  {ticker}: {json.dumps(meta)}\n" for ticker, meta in extra.items())
            text = re.sub(r"^company_meta:\n", "company_meta:\n" + entries, text, flags=re.M)
            assert {**yaml.safe_load(text)["company_meta"], **extra} == yaml.safe_load(text)["company_meta"]
        path.write_text(text)
    return target


def copy_events(root: Path, markets=MARKETS) -> None:
    """The repo's stored watchlist events (the seed) into a data root."""
    for market in markets:
        shutil.copytree(REPO / "data" / market / "watchlist_events", root / "data" / market / "watchlist_events")


def snapshot(market: str) -> str:
    """Everything the lifecycle gives for one market as of the clock, as its repr (key order and types kept)."""
    cfg = load_market(market)
    seeded = [row["ticker"] for row in stored_events(market)]
    out = {"cfg": cfg, "active": active_tickers(cfg), "active_sectors": active_sectors(cfg),
           "records": accessor.records(market),
           "watchlist": {state: watchlist(market, clock(), state) for state in STATES},
           "pending": {ticker: commands.pending_company(market, ticker, stored_events(market), clock())
                       for ticker in [*seeded, UNKNOWN]}}
    return repr(out)


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    """A data root with the repo's watchlist events."""
    data_root = tmp_path / "root"
    copy_events(data_root)
    monkeypatch.setattr(common, "ROOT", data_root)
    return data_root


@pytest.mark.parametrize("market", MARKETS)
def test_company_meta_gives_byte_identical_lifecycle_outputs(market, tmp_path, monkeypatch):
    renamed = renamed_config(tmp_path / "config_renamed")
    for when in CLOCKS:
        monkeypatch.setenv("MB_NOW", when)
        monkeypatch.setattr(common, "CONFIG", REPO / "config")
        before = snapshot(market)
        monkeypatch.setattr(common, "CONFIG", renamed)
        after = snapshot(market)
        assert after == before, when
        cfg = load_market(market)
        assert "company_meta" not in cfg
        assert len(cfg["tickers"]) == (0 if when < "2024-10-07" else 20), when


@pytest.mark.parametrize("market", MARKETS)
def test_company_meta_entry_without_an_add_never_adds_a_company(market, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CONFIG", renamed_config(tmp_path / "config_extra", {UNKNOWN: {"name": "Not added"}}))
    for when in CLOCKS:
        monkeypatch.setenv("MB_NOW", when)
        assert UNKNOWN not in load_market(market)["tickers"], when
        assert UNKNOWN not in {record["ticker"] for record in accessor.records(market)}, when
        assert commands.pending_company(market, UNKNOWN, stored_events(market), clock()) is None, when


def test_company_meta_seeds_only_a_market_without_any_stored_event(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CONFIG", renamed_config(tmp_path / "config_renamed"))
    monkeypatch.setattr(common, "ROOT", tmp_path / "empty_root")
    monkeypatch.setenv("MB_NOW", "2026-10-08T21:00:00+00:00")
    every = list(yaml.safe_load((tmp_path / "config_renamed" / "markets" / "us.yaml").read_text())["company_meta"])
    assert list(load_market("us")["tickers"]) == every          # no stored event: the implicit seed
    one = next(json.loads(line) for line in (REPO / "data" / "us" / "watchlist_events" / "2026" / "10" /
                                             "2026-10-07.jsonl").read_text().splitlines() if line.strip())
    path = tmp_path / "empty_root" / "data" / "us" / "watchlist_events" / "2026" / "10" / "2026-10-07.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(one) + "\n")
    assert list(load_market("us")["tickers"]) == [one["ticker"]]   # one stored event: membership from events only
    assert [record["ticker"] for record in watchlist("us", clock(), "collected")] == [one["ticker"]]


def test_a_config_with_both_company_keys_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CONFIG", renamed_config(tmp_path / "config_both", keep_tickers=True))
    monkeypatch.setenv("MB_NOW", "2026-10-08T21:00:00+00:00")
    with pytest.raises(ValueError, match="both `company_meta:` and `tickers:`"):
        load_market("us")
    with pytest.raises(ValueError, match="both `company_meta:` and `tickers:`"):
        accessor.records("india")


def test_seed_from_company_meta_writes_the_same_rows_as_from_tickers(tmp_path, monkeypatch):
    monkeypatch.setenv("MB_NOW", "2026-10-08T21:00:00+00:00")
    seeded = {}
    for name, config in (("tickers", REPO / "config"), ("company_meta", renamed_config(tmp_path / "config_renamed"))):
        data_root = tmp_path / f"root_{name}"
        price_day = data_root / "data" / "india" / "prices" / "2024" / "10" / f"{date(2024, 10, 7)}.csv"
        price_day.parent.mkdir(parents=True)
        price_day.write_bytes(b"date,ticker,open,high,low,close,adj_close,volume,collected_at\r\n")
        monkeypatch.setattr(common, "ROOT", data_root)
        monkeypatch.setattr(common, "CONFIG", config)
        result = seed("india", sources=None)
        assert result["ok"], result
        seeded[name] = stored_events("india")
    strip = [[{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
             for rows in seeded.values()]
    assert strip[0] == strip[1] and len(strip[0]) == 20
