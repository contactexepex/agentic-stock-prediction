"""Build reports/<market>/dashboard.html (or <out>/dashboard.html) from the stored data and add its path to
the Slack file manifest that html_report.py wrote (work/slack_<market>_files.json), so notify_slack.py
attaches it. Reads data/ only; writes the page and, when present, the manifest under work/."""

from __future__ import annotations

import json
from pathlib import Path

from marketbrief.constants.dashboard import DASHBOARD_FILE, DASHBOARD_STEP, MANIFEST_KEY, SLACK_FILES_MANIFEST
from marketbrief.core import cli, database, paths
from marketbrief.core.clock import clock
from marketbrief.presentation.dashboard.assemble import gather_dashboard
from marketbrief.presentation.dashboard.page import build_page


def relative(path: Path) -> str:
    """A path relative to the repo root when it is inside it, else absolute."""
    try:
        return str(path.resolve().relative_to(paths.ROOT.resolve()))
    except ValueError:
        return str(path)


def add_to_manifest(market: str, page_path: Path) -> str | None:
    """Record the dashboard in the Slack file manifest, when html_report.py wrote one."""
    manifest = paths.ROOT / SLACK_FILES_MANIFEST.format(market=market)
    if not manifest.exists():
        return None
    files = json.loads(manifest.read_text())
    files[MANIFEST_KEY] = relative(page_path)
    manifest.write_text(json.dumps(files, indent=2))
    return relative(manifest)


def run(cfg: dict, out_dir: Path | None = None) -> dict:
    """Build the page; returns the step summary."""
    data = gather_dashboard(cfg, database.connect(cfg["market"]), clock())
    folder = out_dir or paths.ROOT / "reports" / cfg["market"]
    folder.mkdir(parents=True, exist_ok=True)
    page = build_page(data)
    out = folder / DASHBOARD_FILE
    out.write_text(page)
    manifest = add_to_manifest(cfg["market"], out) if out_dir is None else None
    return {
        "step": DASHBOARD_STEP,
        "market": cfg["market"],
        "html": relative(out),
        "as_of": data["as_of"],
        "companies": len(data["companies"]),
        "with_scores": sum(1 for c in data["companies"] if c["model"]),
        "skill": data["skill"]["state"],
        "slack_files": manifest,
        "bytes": len(page.encode()),
    }


def main() -> int:
    """CLI: --market india|us [--out DIR]."""
    parser = cli.market_arg(__doc__)
    parser.add_argument("--out", type=Path, help="write dashboard.html to this folder instead of reports/<market>/")
    args = parser.parse_args()
    print(json.dumps(run(cli.require_market(args), args.out), indent=2))
    return 0
