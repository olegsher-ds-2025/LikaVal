"""Configuration loader.

Reads config/config.yaml and resolves ${ENV_VAR:default} placeholders.
Values can be overridden by environment variables or a .env file.
"""

import os
import re
import logging
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Resolve .env relative to the project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"
_CONFIG_FILE = _PROJECT_ROOT / "config" / "config.yaml"

_ENV_PLACEHOLDER = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _resolve(value: Any) -> Any:
    """Recursively resolve ${VAR:default} placeholders in strings."""
    if isinstance(value, str):
        def replacer(match: re.Match) -> str:
            var_name, default = match.group(1), match.group(2) or ""
            return os.environ.get(var_name, default)
        return _ENV_PLACEHOLDER.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(item) for item in value]
    return value


def load_config(config_file: Path = _CONFIG_FILE) -> dict:
    """Load and return the resolved configuration dictionary."""
    load_dotenv(_ENV_FILE)

    with open(config_file, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    config = _resolve(raw)

    # Coerce numeric string fields
    try:
        config["currency"]["ils_to_usd_ratio"] = float(
            config["currency"]["ils_to_usd_ratio"]
        )
    except (KeyError, ValueError, TypeError):
        pass

    logger.debug("Configuration loaded from %s", config_file)
    return config


# Module-level singleton — import and use directly:
#   from backend.src.config import CONFIG
CONFIG: dict = load_config()
