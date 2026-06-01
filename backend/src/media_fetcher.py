"""Media fetcher module.

Monitors a Google Drive folder for new product subdirectories, downloads
images and videos, and parses folder names into product metadata.

Folder naming convention: YYYYMMDD_PRICE[_sold]
  Example: 20260517_200        → available, 200 ILS
           20250101_100_sold   → sold, 100 ILS

Google Drive authentication uses a service account key file.
Share the target Drive folder with the service account e-mail address.

Root folder resolution order:
  1. GDRIVE_FOLDER_ID env / config  — used directly when non-empty
  2. GDRIVE_FOLDER_NAME env / config — looked up by name in My Drive root
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials

from backend.src.config import CONFIG
from backend.src.state_manager import is_processed, upsert_product, log_error

logger = logging.getLogger(__name__)

_FOLDER_RE = re.compile(r"^(\d{8})_(\d+)(_sold)?$")
_SUPPORTED_IMAGES = {f.lower() for f in CONFIG["gdrive"]["supported_image_formats"]}
_SUPPORTED_VIDEOS = {f.lower() for f in CONFIG["gdrive"]["supported_video_formats"]}
_MAX_IMAGES: int = int(CONFIG["gdrive"].get("max_images", 10))
_MAX_VIDEOS: int = int(CONFIG["gdrive"].get("max_videos", 1))

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


@dataclass
class ProductFolder:
    folder_id: str
    folder_name: str
    date_str: str
    price_ils: int
    is_sold: bool
    images: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    description_file: Path | None = None

    @property
    def price_usd(self) -> float:
        ratio = CONFIG["currency"]["ils_to_usd_ratio"]
        return round(self.price_ils * ratio)

    @property
    def status(self) -> str:
        return "sold" if self.is_sold else "available"


def parse_description_file(path: Path) -> dict:
    """Parse a ``description.txt`` file with EN:/RU: labelled sections.

    Expected format::

        EN:
        Title: My Product
        Description: Some multi-line text...

        RU:
        Название: Мой продукт
        Описание: Текст...

    Returns a dict with keys: title_en, description_en, title_ru, description_ru.
    Missing fields are returned as empty strings.
    """
    text = path.read_text(encoding="utf-8").strip()
    result: dict = {"title_en": "", "description_en": "", "title_ru": "", "description_ru": ""}

    # Split by language section headers (EN: or RU: on their own line)
    parts = re.split(r"\n\s*(EN|RU)\s*:\s*\n", text, flags=re.IGNORECASE)
    # parts layout: [preamble, LABEL, block, LABEL, block, ...]
    i = 1
    while i + 1 < len(parts):
        lang = parts[i].strip().upper()
        block = parts[i + 1]

        if lang == "EN":
            title_m = re.search(r"^Title\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
            desc_m = re.search(r"^Description\s*:\s*([\s\S]+)", block, re.MULTILINE | re.IGNORECASE)
            if title_m:
                result["title_en"] = title_m.group(1).strip()
            if desc_m:
                result["description_en"] = desc_m.group(1).strip()
        elif lang == "RU":
            title_m = re.search(r"^(?:Title|Название)\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
            desc_m = re.search(r"^(?:Description|Описание)\s*:\s*([\s\S]+)", block, re.MULTILINE | re.IGNORECASE)
            if title_m:
                result["title_ru"] = title_m.group(1).strip()
            if desc_m:
                result["description_ru"] = desc_m.group(1).strip()

        i += 2

    return result


def _parse_folder_name(name: str) -> dict | None:
    """Parse folder name into metadata dict, or None if the name is invalid."""
    match = _FOLDER_RE.match(name)
    if not match:
        return None
    date_str, price_str, sold_flag = match.groups()
    return {
        "date_str": date_str,
        "price_ils": int(price_str),
        "is_sold": bool(sold_flag),
    }


def _build_drive_service():
    creds = Credentials.from_service_account_file(
        CONFIG["gdrive"]["credentials_file"], scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_items(service, parent_id: str, mime_type: str | None = None) -> list[dict]:
    """List all non-trashed items under *parent_id*, optionally filtered by MIME type."""
    query = f"'{parent_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
    results: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType)",
                orderBy="name",
                pageToken=page_token,
            )
            .execute()
        )
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def _resolve_root_folder_id(service) -> str:
    """Return the Drive folder ID to scan for product subfolders.

    Uses GDRIVE_FOLDER_ID when set; otherwise searches My Drive by
    GDRIVE_FOLDER_NAME and returns the first matching folder ID.
    Raises RuntimeError if the folder cannot be found.
    """
    folder_id: str = CONFIG["gdrive"]["folder_id"]
    if folder_id:
        return folder_id

    folder_name: str = CONFIG["gdrive"].get("folder_name", "")
    if not folder_name:
        raise RuntimeError(
            "Neither GDRIVE_FOLDER_ID nor GDRIVE_FOLDER_NAME is configured."
        )

    logger.info("Searching Drive for folder named '%s'", folder_name)
    # Escape single quotes in the name for the query
    safe_name = folder_name.replace("'", "\\'")
    resp = (
        service.files()
        .list(
            q=(
                f"name = '{safe_name}'"
                " and mimeType = 'application/vnd.google-apps.folder'"
                " and trashed = false"
            ),
            fields="files(id, name)",
            pageSize=5,
        )
        .execute()
    )
    matches = resp.get("files", [])
    if not matches:
        raise RuntimeError(
            f"Google Drive folder '{folder_name}' not found. "
            "Make sure it is shared with the service account."
        )
    if len(matches) > 1:
        logger.warning(
            "Multiple Drive folders named '%s' found — using the first one (id=%s)",
            folder_name,
            matches[0]["id"],
        )
    folder_id = matches[0]["id"]
    logger.info("Resolved '%s' → folder id=%s", folder_name, folder_id)
    return folder_id


def _download_file(service, file_id: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    logger.info("Downloaded %s", dest_path)


def fetch_new_products() -> list[ProductFolder]:
    """Scan the configured Google Drive folder, download new product media,
    and return a list of ProductFolder objects ready for AI processing.

    Each product folder yields at most *max_images* images and *max_videos*
    videos (configurable via config.yaml / env vars).
    """
    gdrive_cfg = CONFIG["gdrive"]
    download_base = Path(gdrive_cfg["download_dir"])

    if not gdrive_cfg.get("folder_id") and not gdrive_cfg.get("folder_name"):
        logger.warning(
            "Neither GDRIVE_FOLDER_ID nor GDRIVE_FOLDER_NAME configured — skipping"
        )
        return []

    service = _build_drive_service()

    try:
        root_id = _resolve_root_folder_id(service)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return []

    folders = _list_items(
        service, root_id, mime_type="application/vnd.google-apps.folder"
    )
    logger.info("Found %d subfolder(s) in root Drive folder", len(folders))

    new_products: list[ProductFolder] = []

    for folder in folders:
        name = folder["name"]
        meta = _parse_folder_name(name)
        if not meta:
            logger.debug("Skipping non-product folder: %s", name)
            continue

        if is_processed(name):
            logger.debug("Already processed: %s", name)
            continue

        logger.info("New product folder detected: %s", name)
        product = ProductFolder(folder_id=folder["id"], folder_name=name, **meta)

        dest_dir = download_base / name
        files = _list_items(service, folder["id"])  # already ordered by name

        image_count = 0
        video_count = 0

        for f in files:
            fname = f["name"]
            dest = dest_dir / fname

            # Special case: always download description.txt if present
            if fname.lower() == "description.txt":
                try:
                    _download_file(service, f["id"], dest)
                    product.description_file = dest
                    logger.info("Downloaded description file for %s", name)
                except Exception as exc:
                    log_error(name, f"Download failed for {fname}: {exc}")
                continue

            ext = Path(fname).suffix.lstrip(".").lower()
            is_image = ext in _SUPPORTED_IMAGES
            is_video = ext in _SUPPORTED_VIDEOS

            if not is_image and not is_video:
                logger.debug("Ignoring unsupported file: %s", fname)
                continue

            if is_image and image_count >= _MAX_IMAGES:
                logger.debug("Image limit (%d) reached — skipping %s", _MAX_IMAGES, fname)
                continue
            if is_video and video_count >= _MAX_VIDEOS:
                logger.debug("Video limit (%d) reached — skipping %s", _MAX_VIDEOS, fname)
                continue

            try:
                _download_file(service, f["id"], dest)
            except Exception as exc:
                log_error(name, f"Download failed for {fname}: {exc}")
                continue

            if is_image:
                product.images.append(dest)
                image_count += 1
            else:
                product.videos.append(dest)
                video_count += 1

        logger.info(
            "Downloaded %d image(s) and %d video(s) for %s",
            image_count, video_count, name,
        )

        # Persist initial metadata to state before AI processing
        upsert_product(name, {
            "folder": name,
            "date": f"{meta['date_str'][:4]}-{meta['date_str'][4:6]}-{meta['date_str'][6:]}",
            "price_ils": product.price_ils,
            "price_usd": product.price_usd,
            "status": product.status,
            "images": [str(p) for p in product.images],
            "videos": [str(p) for p in product.videos],
            "ai": {},
            "published": {"github": False, "etsy": False, "facebook": False},
        })

        new_products.append(product)

    logger.info("Fetched %d new product(s)", len(new_products))
    return new_products
