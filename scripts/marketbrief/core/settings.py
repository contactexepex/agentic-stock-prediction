"""Loading config/settings.yaml and config/validate.yaml from the current config folder."""

from __future__ import annotations

import yaml

from marketbrief.constants.files import FILE_SETTINGS_CONFIG, FILE_VALIDATE_CONFIG
from marketbrief.constants.warehouse import FILE_WAREHOUSE_CONFIG
from marketbrief.core import paths


def load_settings():
    """config/settings.yaml as parsed (repo URL, Slack channel id, model_training_cutoff ...)."""
    return yaml.safe_load((paths.CONFIG / FILE_SETTINGS_CONFIG).read_text())


def load_validate_config():
    """config/validate.yaml as parsed (the daily run's validation thresholds)."""
    return yaml.safe_load((paths.CONFIG / FILE_VALIDATE_CONFIG).read_text())


def app_url() -> str | None:
    """The app's address (config/warehouse.yaml app_url), the target of Slack links; None when not configured."""
    path = paths.CONFIG / FILE_WAREHOUSE_CONFIG
    doc = yaml.safe_load(path.read_text()) if path.exists() else None
    return (doc or {}).get("app_url") or None
