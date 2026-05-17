"""Media fetcher module.

Monitors a Google Drive folder for new product subdirectories, downloads
images and videos, and parses folder names into product metadata.

Folder naming convention: YYYYMMDD_PRICE[_sold]
  Example: 20260517_200        → available, 200 ILS
           20250101_100_sold   → sold, 100 ILS
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import io

from backend.src.config import CONFIG
from backend.src.state_manager import is_processed, upsert_product, log_error

logger = logging.getLogger(__name__)

_FOLDER_RE = re.compile(r"^(\d{8})_(\d+)(_sold)?$")
_SUPPORTED_IMAGES = {f.lower() for f in CONFIG["gdrive"]["supported_image_formats"]}
_SUPPORTED_VIDEOS = {f.lower() for f in CONFIG["gdrive"]["supported_video_formats"]}

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

    @property
    def price_usd(self) -> float:
        ratio = CONFIG["currency"]["ils_to_usd_ratio"]
        return round(self.price_ils * ratio)

    @property
    def status(self) -> str:
        return "sold" if self.is_sold else "available"


def _parse_folder_name(name: str) -> dict | None:
    """Parse folder name. Returns metadata dict or None if invalid."""
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
    query = f"'{parent_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
    results = []
    page_token = None
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token,
        ).execute()
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


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
    """
    Scan the configured Google Drive folder, download new product media,
    and return a list of ProductFolder objects ready for AI processing.
    """
    folder_id = CONFIG["gdrive"]["folder_id"]
    download_base = Path(CONFIG["gdrive"]["download_dir"])

    if not folder_id:
        logger.warning("GDRIVE_FOLDER_ID not configured — skipping media fetch")
        return []

    service = _build_drive_service()
    folders = _list_items(
        service, folder_id, mime_type="application/vnd.google-apps.folder"
    )

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

        logger.info("Processing new product folder: %s", name)
        product = ProductFolder(
            folder_id=folder["id"],
            folder_name=name,
            **meta,
        )

        dest_dir = download_base / name
        files = _list_items(service, folder["id"])

        for f in files:
            ext = Path(f["name"]).suffix.lstrip(".").lower()
            dest = dest_dir / f["name"]
            try:
                _download_file(service, f["id"], dest)
                if ext in _SUPPORTED_IMAGES:
                    product.images.append(dest)
                elif ext in _SUPPORTED_VIDEOS:
                    product.videos.append(dest)
            except Exception as exc:
                log_error(name, f"Download failed for {f['name']}: {exc}")

        # Persist initial metadata to state
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
