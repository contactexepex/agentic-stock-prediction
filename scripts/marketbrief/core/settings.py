"""Loading config/settings.yaml and config/validate.yaml from the current config folder."""

from __future__ import annotations

import yaml

from marketbrief.constants.files import FILE_SETTINGS_CONFIG, FILE_VALIDATE_CONFIG
from marketbrief.core import paths


def load_settings():
    """config/settings.yaml as parsed (repo URL, Slack channel id, model_training_cutoff ...)."""
    return yaml.safe_load((paths.CONFIG / FILE_SETTINGS_CONFIG).read_text())


def load_validate_config():
    """config/validate.yaml as parsed (the daily run's validation thresholds)."""
    return yaml.safe_load((paths.CONFIG / FILE_VALIDATE_CONFIG).read_text())
