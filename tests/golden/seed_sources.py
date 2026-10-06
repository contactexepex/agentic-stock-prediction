"""Golden seed (tests/golden/seed.py): run the free-source collectors on tests/fixtures/sources,
as tests/test_sources.py does, with a fixture client in place of the network.

  python tests/golden/seed_sources.py us|india     (MB_ROOT, MB_CONFIG and MB_NOW set by the caller)

US: collect_macro (Treasury, FRED, Cboe) and collect_shorts (FINRA); India: collect_flows_india
(NSDL FPI, NSE index closes). Prints each collector's JSON summary."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]
FIXTURES = CODE / "tests" / "fixtures" / "sources"
sys.path.insert(0, str(CODE / "scripts"))

import collect_flows_india  # noqa: E402
import collect_macro  # noqa: E402
import collect_shorts  # noqa: E402
import common  # noqa: E402
from sources import FetchError  # noqa: E402

FIXTURE_DAY = date(2026, 10, 5)
ROUTES = {
    "macro": [("daily-treasury-rates.csv/2026", "treasury_2026.csv"), ("id=BAMLH0A0HYM2", "fred_BAMLH0A0HYM2.csv"),
              ("id=T10YIE", "fred_T10YIE.csv"), ("id=BAMLC0A0CM", "fred_BAMLC0A0CM.csv"),
              ("2026-10-01_daily_options", "cboe_2026-10-01_daily_options.json"),
              ("2026-10-02_daily_options", "cboe_2026-10-02_daily_options.json")],
    "shorts": [("CNMSshvol20261001", "CNMSshvol20261001.txt"), ("CNMSshvol20261002", "CNMSshvol20261002.txt"),
               ("consolidatedShortInterest", "finra_short_interest.json")],
    "flows": [("fpi.nsdl.co.in", "nsdl_fpi_latest.html")] + [
        (f"ind_close_all_{day}", f"ind_close_all_{day}.csv")
        for day in ("25092026", "29092026", "30092026", "01102026", "05102026")],
}


class FixtureClient:
    """Answers a URL from the first route whose key it contains; anything else is an HTTP 404."""

    def __init__(self, routes: list[tuple[str, str]]):
        self.routes, self.requests = routes, 0

    def get(self, url: str, *, data=None, headers=None) -> bytes:  # noqa: ARG002
        """The fixture bytes for url."""
        self.requests += 1
        for key, name in self.routes:
            if key in url:
                return (FIXTURES / name).read_bytes()
        raise FetchError(url, "HTTP 404 from the golden fixtures", status=404)

    def json(self, url: str, **kwargs):
        """The fixture for url, parsed as JSON."""
        return json.loads(self.get(url, **kwargs))


def main() -> int:
    market = sys.argv[1]
    cfg, now = common.load_market(market), common.utc_now()
    if market == "us":
        cfg["macro"]["cboe"]["lookback_days"] = 4      # the fixture sessions, as in tests/test_sources.py
        runs = [(collect_macro, "macro"), (collect_shorts, "shorts")]
    else:
        runs = [(collect_flows_india, "flows")]
    for module, routes in runs:
        print(json.dumps(module.collect(cfg, FixtureClient(ROUTES[routes]), FIXTURE_DAY, now), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
