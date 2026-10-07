"""The four AI traders (docs/SPEC.md F4.1): their registry entries in config/strategies.yaml and their agent files.

Each trader's agent file (`.claude/agents/trader-*.md`, the Opus one is `forecaster.md`) holds, besides the
frontmatter Claude Code reads (name, model, tools), one fenced block tagged `yaml trader` with the protocol settings
the scripts read:

    strategy_id     the config/strategies.yaml id it writes as
    prompt_version  the version every record must carry (bumped whenever the agent file changes)
    enabled         the kill switch: false = the agent is not run and every active company gets a `killed` abstention
    budget          max_minutes (wall time the caller gives it, never past the deadline) and max_input_kb (the size
                    of the input file `prepare` writes; sections beyond it are cut and say so)

`trader_problems` checks that the agent file and the registry agree (model, horizons, whether it sees the score)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from marketbrief.contracts.strategies import STRATEGIES_FILE
from marketbrief.core import paths

AGENTS_DIR = Path(".claude") / "agents"
TRADER_FILES = {
    "ai.news_results.sonnet.v1": "trader-news-results.md",
    "ai.pattern_mood.sonnet.v1": "trader-pattern-mood.md",
    "ai.combined.sonnet.v1": "trader-combined.md",
    "ai.combined.opus.v1": "forecaster.md",
}
BLOCK = re.compile(r"```yaml trader\n(.*?)\n```", re.S)
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
MODEL_NAMES = {"sonnet": "claude-sonnet-", "opus": "claude-opus-"}


@dataclass(frozen=True)
class Trader:
    """One AI trader as the scripts see it."""

    strategy_id: str
    entry: dict           # its config/strategies.yaml entry
    agent_file: Path
    agent_model: str      # the frontmatter model
    prompt_version: str
    enabled: bool
    budget: dict

    @property
    def horizons(self) -> tuple[int, ...]:
        """The horizons it predicts (decision 38: N+1, N+3, N+5)."""
        return tuple(self.entry["horizons"])

    @property
    def sees_model_score(self) -> bool:
        """True for the combined traders: they are bound by the model anchor (F2.6)."""
        return bool(self.entry["parameters"]["sees_model_score"])

    @property
    def inputs(self) -> tuple[str, ...]:
        """The input categories it reads (config/strategies.yaml parameters.inputs)."""
        return tuple(self.entry["parameters"]["inputs"])

    @property
    def threshold(self) -> float:
        """The minimum prob_up for an up prediction to trade (F1.2)."""
        return float(self.entry["threshold"])

    @property
    def config_hash(self) -> str:
        """sha256 of its registry entry (canonical JSON), stored on every prediction."""
        text = json.dumps(self.entry, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_registry() -> dict:
    """config/strategies.yaml."""
    return yaml.safe_load((paths.CONFIG / STRATEGIES_FILE).read_text(encoding="utf-8"))


def agent_settings(path: Path) -> tuple[dict, dict]:
    """(frontmatter, the `yaml trader` block) of an agent file."""
    text = path.read_text(encoding="utf-8")
    front = FRONTMATTER.match(text)
    block = BLOCK.search(text)
    if front is None or block is None:
        raise SystemExit(f"{path}: needs YAML frontmatter and a ```yaml trader block")
    return yaml.safe_load(front.group(1)), yaml.safe_load(block.group(1))


def load_traders(root: Path | None = None) -> dict[str, Trader]:
    """Every AI trader of the registry with its agent file's settings, by strategy id."""
    root = root or paths.CODE
    entries = {entry["id"]: entry for entry in load_registry()["strategies"] if entry["family"] == "ai"}
    out = {}
    for strategy_id, entry in sorted(entries.items()):
        if strategy_id not in TRADER_FILES:
            raise SystemExit(f"{strategy_id}: no agent file is mapped in marketbrief/traders/registry.py")
        path = root / AGENTS_DIR / TRADER_FILES[strategy_id]
        front, block = agent_settings(path)
        out[strategy_id] = Trader(strategy_id, entry, path, str(front.get("model", "")), str(block["prompt_version"]),
                                  bool(block["enabled"]), dict(block.get("budget") or {}))
    return out


def trader(strategy_id: str, root: Path | None = None) -> Trader:
    """One trader by id; exits naming the known ids."""
    traders = load_traders(root)
    if strategy_id not in traders:
        raise SystemExit(f"unknown AI trader {strategy_id!r}; known: {sorted(traders)}")
    return traders[strategy_id]


def trader_problems(root: Path | None = None) -> list[str]:
    """Disagreements between the registry and the agent files (empty = consistent)."""
    problems = []
    ai_horizons = load_registry()["ai_horizons"]
    for strategy_id, one in load_traders(root).items():
        _, block = agent_settings(one.agent_file)
        if block.get("strategy_id") != strategy_id:
            problems.append(f"{one.agent_file.name}: strategy_id {block.get('strategy_id')!r} is not {strategy_id}")
        want_model = MODEL_NAMES[one.entry["parameters"]["model"]]
        if not one.agent_model.startswith(want_model):
            problems.append(f"{one.agent_file.name}: model {one.agent_model!r} is not a {want_model}* model")
        if list(one.horizons) != list(ai_horizons):
            problems.append(f"{strategy_id}: horizons {list(one.horizons)} are not ai_horizons {ai_horizons}")
        for key in ("max_minutes", "max_input_kb"):
            if not isinstance(one.budget.get(key), int) or one.budget[key] <= 0:
                problems.append(f"{one.agent_file.name}: budget.{key} must be a positive integer")
        if not isinstance(block.get("enabled"), bool):
            problems.append(f"{one.agent_file.name}: enabled (the kill switch) must be true or false")
    return problems
