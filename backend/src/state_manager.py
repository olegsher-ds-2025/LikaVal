"""State manager.

Persists pipeline state to JSON files in the state/ directory.
No database — all state is human-readable and Git-compatible.

State files:
  state/products.json  — product metadata and publish status
  state/sync_log.json  — per-run sync history and error log
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.src.config import CONFIG

logger = logging.getLogger(__name__)

_STATE_DIR = Path(CONFIG["state"]["dir"])
_PRODUCTS_FILE = Path(CONFIG["state"]["products_file"])
_SYNC_LOG_FILE = Path(CONFIG["state"]["sync_log_file"])


def _ensure_state_dir() -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return default


def _save_json(path: Path, data: Any) -> None:
    _ensure_state_dir()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
    logger.debug("Saved state to %s", path)


# ── Products ──────────────────────────────────────────────────────────────────

def load_products() -> dict[str, dict]:
    """Return product state keyed by folder name."""
    return _load_json(_PRODUCTS_FILE, {})


def save_products(products: dict[str, dict]) -> None:
    _save_json(_PRODUCTS_FILE, products)


def get_product(folder: str) -> dict | None:
    return load_products().get(folder)


def upsert_product(folder: str, data: dict) -> None:
    """Insert or update a product entry, setting updated_at automatically."""
    products = load_products()
    now = datetime.now(timezone.utc).isoformat()
    if folder not in products:
        data.setdefault("created_at", now)
    data["updated_at"] = now
    products[folder] = data
    save_products(products)


def is_processed(folder: str) -> bool:
    """Return True if the folder has already been fully processed (has AI text content)."""
    product = get_product(folder)
    return bool(product and product.get("ai", {}).get("title_en"))


def is_pending_text(folder: str) -> bool:
    """Return True if the folder was registered but is waiting for a description text file."""
    product = get_product(folder)
    return bool(product and product.get("pending_text"))


def mark_published(folder: str, platform: str) -> None:
    """Mark a product as published on the given platform."""
    products = load_products()
    if folder in products:
        products[folder].setdefault("published", {})[platform] = True
        products[folder]["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_products(products)


# ── Sync log ──────────────────────────────────────────────────────────────────

def append_sync_entry(entry: dict) -> None:
    """Append a sync run record to the sync log."""
    log = _load_json(_SYNC_LOG_FILE, [])
    log.append({**entry, "timestamp": datetime.now(timezone.utc).isoformat()})
    _save_json(_SYNC_LOG_FILE, log)


def log_error(folder: str, error: str) -> None:
    append_sync_entry({"event": "error", "folder": folder, "error": error})
    logger.error("Error processing %s: %s", folder, error)
