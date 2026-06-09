#!/usr/bin/env python3
"""Drive→State full sync.

What it does:
  1. Scans Google Drive for all valid product folders (YYYYMMDD_PRICE[_sold])
  2. Products in state that are no longer in Drive → marked 'sold'
  3. For each Drive folder: finds description file (Google Doc preferred, description.txt fallback)
  4. Google Docs (Russian primary) exported as plain text and parsed
  5. Missing language generated via Ollama:
       RU-only doc  → translate RU→EN  (English for Etsy)
       EN-only doc  → translate EN→RU  (Russian for the site)
  6. SEO tags and social post refreshed when content changed
  7. GitHub pages re-rendered for every changed product
  8. Catalog + RU homepage regenerated
  9. state/products.json + frontend/ committed to main and pushed
     Frontend deployed to gh-pages branch

Run from project root:
    python backend/sync_from_drive.py
"""

import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.src.config import CONFIG
from backend.src.state_manager import (
    load_products, upsert_product, append_sync_entry, log_error,
)
from backend.src.ai_module import (
    translate_to_english, translate_to_russian, generate_seo_tags,
    generate_social_post_ru, check_ollama_health,
)
from backend.src.media_fetcher import (
    _build_drive_service, _list_items, _resolve_root_folder_id,
    _parse_folder_name, _download_file, parse_description_file,
)
from backend.src.connectors.github_connector import GitHubConnector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_GDOC_MIME = "application/vnd.google-apps.document"


# ── Description file helpers ──────────────────────────────────────────────────

def _export_gdoc(service, file_id: str) -> str:
    """Export a Google Docs file as plain UTF-8 text."""
    raw = service.files().export(fileId=file_id, mimeType="text/plain").execute()
    return (raw.decode("utf-8") if isinstance(raw, bytes) else raw).strip()


def _parse_text(text: str) -> dict:
    """Parse description text into {title_en, description_en, title_ru, description_ru}.

    Handles three formats in priority order:
      1. EN:/RU: section blocks  (same as description.txt)
      2. Labelled keys  (Название: … / Описание: … or Title: … / Description: …)
      3. Freeform Russian  (first non-empty line = title, rest = description)
    """
    result: dict = {"title_en": "", "description_en": "", "title_ru": "", "description_ru": ""}

    # Format 1 – EN:/RU: section blocks
    if re.search(r"\n\s*(EN|RU)\s*:\s*\n", text, re.IGNORECASE):
        parts = re.split(r"\n\s*(EN|RU)\s*:\s*\n", text, flags=re.IGNORECASE)
        i = 1
        while i + 1 < len(parts):
            lang = parts[i].strip().upper()
            block = parts[i + 1]
            if lang == "EN":
                m_t = re.search(r"^Title\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
                m_d = re.search(r"^Description\s*:\s*([\s\S]+)", block, re.MULTILINE | re.IGNORECASE)
                if m_t:
                    result["title_en"] = m_t.group(1).strip()
                if m_d:
                    result["description_en"] = m_d.group(1).strip()
            elif lang == "RU":
                m_t = re.search(r"^(?:Title|Название)\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
                m_d = re.search(r"^(?:Description|Описание)\s*:\s*([\s\S]+)", block, re.MULTILINE | re.IGNORECASE)
                if m_t:
                    result["title_ru"] = m_t.group(1).strip()
                if m_d:
                    result["description_ru"] = m_d.group(1).strip()
            i += 2
        return result

    # Format 2 – labelled keys anywhere in the text
    m_tru = re.search(r"^Название\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    m_dru = re.search(r"^Описание\s*:\s*([\s\S]+)", text, re.MULTILINE | re.IGNORECASE)
    m_ten = re.search(r"^Title\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    m_den = re.search(r"^Description\s*:\s*([\s\S]+)", text, re.MULTILINE | re.IGNORECASE)

    if m_tru or m_dru or m_ten or m_den:
        if m_tru:
            result["title_ru"] = m_tru.group(1).strip()
        if m_dru:
            result["description_ru"] = m_dru.group(1).strip()
        if m_ten:
            result["title_en"] = m_ten.group(1).strip()
        if m_den:
            result["description_en"] = m_den.group(1).strip()
        return result

    # Format 3 – freeform (treat as Russian, first line = title)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        result["title_ru"] = lines[0]
        result["description_ru"] = " ".join(lines[1:]) if len(lines) > 1 else ""
    return result


# ── Main sync ─────────────────────────────────────────────────────────────────

def sync() -> None:
    append_sync_entry({"event": "drive_sync_start"})

    ollama_ok = check_ollama_health()
    logger.info("Ollama reachable: %s", ollama_ok)

    # Connect to Drive
    try:
        service = _build_drive_service()
        root_id = _resolve_root_folder_id(service)
    except Exception as exc:
        logger.error("Drive connection failed: %s", exc)
        append_sync_entry({"event": "drive_sync_error", "error": str(exc)})
        return

    # Build name → folder_id map (valid product folder names only)
    drive_folders = _list_items(service, root_id, mime_type="application/vnd.google-apps.folder")
    drive_map: dict[str, str] = {}
    for f in drive_folders:
        if _parse_folder_name(f["name"]):
            drive_map[f["name"]] = f["id"]
    logger.info("Drive: %d valid product folder(s) found", len(drive_map))

    products = load_products()
    changed_folders: list[str] = []

    # ── Step 1: mark deleted folders as sold ─────────────────────────────────
    for folder_name, product in products.items():
        if folder_name not in drive_map and product.get("status") != "sold":
            logger.info("Folder absent from Drive → marking sold: %s", folder_name)
            product["status"] = "sold"
            upsert_product(folder_name, product)
            changed_folders.append(folder_name)

    # ── Step 2: process each Drive folder ────────────────────────────────────
    download_base = Path(CONFIG["gdrive"]["download_dir"])

    for folder_name, folder_id in drive_map.items():
        meta = _parse_folder_name(folder_name)
        if not meta:
            continue

        # Find description files in this Drive folder
        files = _list_items(service, folder_id)
        gdoc = next((f for f in files if f["mimeType"] == _GDOC_MIME), None)
        txt  = next((f for f in files if f["name"].lower() == "description.txt"), None)

        if not gdoc and not txt:
            logger.debug("No description file for %s", folder_name)
            continue

        # Export / download description
        try:
            if gdoc:
                logger.info("Exporting Google Doc '%s' for %s", gdoc["name"], folder_name)
                raw_text = _export_gdoc(service, gdoc["id"])
                parsed = _parse_text(raw_text)
            else:
                dest = download_base / folder_name / "description.txt"
                _download_file(service, txt["id"], dest)
                parsed = parse_description_file(dest)
        except Exception as exc:
            log_error(folder_name, f"Description fetch/parse failed: {exc}")
            continue

        title_ru = parsed.get("title_ru", "").strip()
        desc_ru  = parsed.get("description_ru", "").strip()
        title_en = parsed.get("title_en", "").strip()
        desc_en  = parsed.get("description_en", "").strip()

        if not title_ru and not title_en:
            logger.warning("No usable title in description for %s — skipping", folder_name)
            continue

        # Translate missing language
        if title_ru and not title_en:
            if ollama_ok:
                logger.info("RU-only doc → translating RU→EN for %s", folder_name)
                t = translate_to_english(title_ru, desc_ru)
                title_en, desc_en = t["title_en"], t["description_en"]
            else:
                logger.warning("Ollama unavailable — EN translation skipped for %s", folder_name)
        elif title_en and not title_ru:
            if ollama_ok:
                logger.info("EN-only doc → translating EN→RU for %s", folder_name)
                t = translate_to_russian(title_en, desc_en)
                title_ru, desc_ru = t["title_ru"], t["description_ru"]
            else:
                logger.warning("Ollama unavailable — RU translation skipped for %s", folder_name)

        # Compare with current state to detect real changes
        existing = products.get(folder_name, {})
        prev_ai  = existing.get("ai", {})
        content_changed = (
            prev_ai.get("title_ru")       != title_ru
            or prev_ai.get("description_ru") != desc_ru
            or prev_ai.get("title_en")       != title_en
            or prev_ai.get("description_en") != desc_en
        )

        # Also re-render if status changed (e.g. folder renamed to _sold in Drive)
        drive_status = "sold" if meta["is_sold"] else "available"
        status_changed = existing.get("status") != drive_status

        if not content_changed and not status_changed:
            logger.info("No change for %s — skipping", folder_name)
            continue

        # Generate SEO tags and social post when content is fresh or was empty
        seo_tags       = prev_ai.get("seo_tags", [])
        social_post_ru = prev_ai.get("social_post_ru", "")

        if ollama_ok and (content_changed or not seo_tags):
            seo_tags = generate_seo_tags(desc_en or desc_ru)

        if ollama_ok and (content_changed or not social_post_ru):
            ratio     = float(CONFIG["currency"]["ils_to_usd_ratio"])
            price_usd = existing.get("price_usd") or round(meta["price_ils"] * ratio)
            social_post_ru = generate_social_post_ru({
                "status":    drive_status,
                "price_usd": price_usd,
                "ai": {
                    "title_ru":       title_ru,
                    "description_ru": desc_ru,
                    "title_en":       title_en,
                    "description_en": desc_en,
                },
            })

        # Build updated product record
        ratio     = float(CONFIG["currency"]["ils_to_usd_ratio"])
        price_ils = meta["price_ils"]
        price_usd = round(price_ils * ratio)

        product_data = {
            **existing,
            "folder":       folder_name,
            "date":         f"{meta['date_str'][:4]}-{meta['date_str'][4:6]}-{meta['date_str'][6:]}",
            "price_ils":    price_ils,
            "price_usd":    price_usd,
            "status":       drive_status,
            "pending_text": False,
            "ai": {
                **prev_ai,
                "title_en":       title_en,
                "description_en": desc_en,
                "title_ru":       title_ru,
                "description_ru": desc_ru,
                "seo_tags":       seo_tags,
                "etsy_listing":   prev_ai.get("etsy_listing", ""),
                "social_post_ru": social_post_ru,
            },
        }

        upsert_product(folder_name, product_data)
        changed_folders.append(folder_name)
        logger.info("Updated state for %s (content_changed=%s, status_changed=%s)",
                    folder_name, content_changed, status_changed)

    # ── Step 3: re-render GitHub pages ───────────────────────────────────────
    if not changed_folders:
        logger.info("No changes detected — nothing to push")
        append_sync_entry({"event": "drive_sync_complete", "updated": [], "count": 0})
        return

    products = load_products()  # reload after all upserts
    github = GitHubConnector()

    for folder_name in changed_folders:
        product = products.get(folder_name)
        if not product:
            continue
        logger.info("Re-rendering GitHub page: %s", folder_name)
        try:
            github._render_product_page(folder_name, product)
        except Exception as exc:
            log_error(folder_name, f"GitHub render failed: {exc}")

    try:
        github._update_catalog_page()
        github._update_ru_homepage()
    except Exception as exc:
        logger.error("Catalog/homepage update failed: %s", exc)

    # ── Step 4: commit state/ + frontend/ and push ───────────────────────────
    try:
        import git as _git
        repo = _git.Repo(search_parent_directories=True)
        repo_root = Path(repo.working_dir)
        # Stage state/products.json so _git_push() includes it in the commit
        products_rel = Path("state/products.json")
        repo.index.add([str(products_rel)])
        logger.info("Staged state/products.json")
    except Exception as exc:
        logger.error("Failed to stage state/products.json: %s", exc)

    try:
        github._git_push()
    except Exception as exc:
        logger.error("Git push failed: %s", exc)
        append_sync_entry({"event": "drive_sync_error", "error": f"push failed: {exc}"})
        return

    append_sync_entry({
        "event": "drive_sync_complete",
        "updated": changed_folders,
        "count": len(changed_folders),
    })
    logger.info("Sync complete — %d product(s) updated and pushed", len(changed_folders))


if __name__ == "__main__":
    sync()
