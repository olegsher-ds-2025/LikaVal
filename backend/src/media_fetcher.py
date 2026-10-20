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

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials

from backend.src.config import CONFIG
from backend.src.state_manager import get_product, is_processed, upsert_product, log_error

register_heif_opener()

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


_ENGLISH_MARKER_RE = re.compile(r"^.*\bENGLISH\b.*$", re.IGNORECASE | re.MULTILINE)
_LANG_HEADER_RE = re.compile(r"^\s*(RUSSIAN|РУССКИЙ)\b", re.IGNORECASE)
_TAGS_HEADER_RE = re.compile(r"^\s*(\d+\s+)?(Теги|тегов|Tags|Etsy\s+tags)\b", re.IGNORECASE)
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+[.)]\s+\S")
_TRAILING_DIVIDER_RE = re.compile(r"(\n\s*_{3,}\s*)+\Z")


def _strip_tags_block(lines: list[str]) -> list[str]:
    """Drop a trailing tag list: everything from a 'Теги'/'Tags' header onward,
    or — absent a header — a trailing run of numbered '1. foo' lines."""
    for i, line in enumerate(lines):
        if _TAGS_HEADER_RE.match(line):
            return lines[:i]
    end = len(lines)
    while end > 0 and (not lines[end - 1].strip() or _NUMBERED_LINE_RE.match(lines[end - 1])):
        end -= 1
    return lines[:end]


def _extract_tags(block: str) -> list[str]:
    """Hand-written tags that follow a 'Теги'/'Tags' header: numbered lines or a comma list."""
    lines = block.split("\n")
    start = next((i for i, line in enumerate(lines) if _TAGS_HEADER_RE.match(line)), None)
    if start is None:
        return []
    tags: list[str] = []
    for line in lines[start + 1:]:
        for part in re.sub(r"^\s*\d+[.)]\s*", "", line).split(","):
            if part.strip():
                tags.append(part.strip())
    return tags


def _extract_title_and_body(block: str) -> tuple[str, str]:
    """First content line is the title; the rest (minus any tag list) is the body."""
    lines = _strip_tags_block(block.split("\n"))
    while lines and (
        not lines[0].strip()
        or _LANG_HEADER_RE.match(lines[0])
        or _ENGLISH_MARKER_RE.match(lines[0])
    ):
        lines.pop(0)
    if not lines:
        return "", ""
    title = lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    return title, body


def _is_mostly_cyrillic(text: str) -> bool:
    cyrillic = len(re.findall(r"[а-яёА-ЯЁ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    return cyrillic > latin


def parse_description_file(path: Path) -> dict:
    """Parse a hand-written ``description.txt`` into title/description per language.

    Supports the legacy labelled format::

        EN:
        Title: My Product
        Description: Some multi-line text...

        RU:
        Название: Мой продукт
        Описание: Текст...

    ...and the free-form format actually used day-to-day: a Russian block
    (optionally starting with a "РУССКИЙ ВАРИАНТ" header), a "___" divider,
    then a line containing "ENGLISH" (e.g. "🇬🇧 ENGLISH VERSION") introducing
    the English block. Within each block the first line is the title, and a
    trailing tag list (a "Теги"/"Tags" header, or a bare numbered list) is
    stripped from the description body. A file with only one language is
    detected by Cyrillic-vs-Latin letter ratio.

    Returns a dict with keys: title_en, description_en, title_ru, description_ru.
    Missing fields are returned as empty strings.
    """
    text = path.read_text(encoding="utf-8-sig").strip()
    result: dict = {
        "title_en": "", "description_en": "", "title_ru": "", "description_ru": "",
        "tags_en": [], "tags_ru": [],
    }

    # Legacy labelled format, still supported.
    if re.search(r"\n\s*(EN|RU)\s*:\s*\n", text, flags=re.IGNORECASE):
        parts = re.split(r"\n\s*(EN|RU)\s*:\s*\n", text, flags=re.IGNORECASE)
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

    # Free-form format: RU block, then a line containing "ENGLISH" starts the EN block.
    marker = _ENGLISH_MARKER_RE.search(text)
    if marker:
        ru_block = _TRAILING_DIVIDER_RE.sub("", text[: marker.start()]).strip()
        en_block = text[marker.end() :].strip()

        result["title_ru"], result["description_ru"] = _extract_title_and_body(ru_block)
        result["title_en"], result["description_en"] = _extract_title_and_body(en_block)
        result["tags_ru"], result["tags_en"] = _extract_tags(ru_block), _extract_tags(en_block)
        return result

    # No marker: two blocks back to back in either order — split where the script flips.
    lines = text.split("\n")
    scripts = [_is_mostly_cyrillic(line) if line.strip() else None for line in lines]
    first = next((x for x in scripts if x is not None), None)
    flip = next((i for i, x in enumerate(scripts) if x is not None and x != first), None)
    if flip is not None:
        blocks = ("\n".join(lines[:flip]), "\n".join(lines[flip:]))
        ru_block, en_block = blocks if first else blocks[::-1]
        result["title_ru"], result["description_ru"] = _extract_title_and_body(ru_block)
        result["title_en"], result["description_en"] = _extract_title_and_body(en_block)
        result["tags_ru"], result["tags_en"] = _extract_tags(ru_block), _extract_tags(en_block)
        return result

    # A single free-form block; detect the language.
    title, body = _extract_title_and_body(text)
    if _is_mostly_cyrillic(text):
        result["title_ru"], result["description_ru"] = title, body
    else:
        result["title_en"], result["description_en"] = title, body
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


def _find_description_item(files: list[dict]) -> dict | None:
    """Return the folder's single text file: a Google Doc, a text/plain upload or any *.txt,
    whatever its name (it has been misspelled, e.g. "discription.txt")."""
    return next(
        (
            f for f in files
            if f.get("mimeType") in ("application/vnd.google-apps.document", "text/plain")
            or f["name"].lower().endswith(".txt")
        ),
        None,
    )


def _download_file(service, file_id: str, dest_path: Path, mime_type: str = "") -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # Google Docs/Sheets/Slides have no binary content — must be exported, not downloaded.
    if mime_type == "application/vnd.google-apps.document":
        request = service.files().export_media(fileId=file_id, mimeType="text/plain")
    else:
        request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    logger.info("Downloaded %s", dest_path)


def _heic_to_jpeg(heic_path: Path) -> Path:
    """Convert a downloaded HEIC/HEIF photo to JPEG (browsers and Etsy can't use HEIC)."""
    jpeg_path = heic_path.with_suffix(".jpg")
    with Image.open(heic_path) as img:
        ImageOps.exif_transpose(img).convert("RGB").save(jpeg_path, "JPEG", quality=92)
    heic_path.unlink()
    return jpeg_path


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

        existing = get_product(name)

        if existing and existing.get("ignored"):
            logger.debug("Ignored product: %s", name)
            continue

        # Fully processed (has text content) → skip entirely
        if is_processed(name):
            logger.debug("Already processed: %s", name)
            continue

        # Pending text file → only check Drive for description.txt, reuse local images
        if existing and existing.get("pending_text"):
            logger.info("Pending text — re-checking Drive for a text file: %s", name)
            files = _list_items(service, folder["id"])
            desc_item = _find_description_item(files)
            if not desc_item:
                logger.debug("Still no text file for pending product: %s", name)
                continue
            dest_dir = download_base / name
            dest = dest_dir / "description.txt"
            try:
                _download_file(service, desc_item["id"], dest, desc_item.get("mimeType", ""))
            except Exception as exc:
                log_error(name, f"Description download failed: {exc}")
                continue
            # Return with existing local image/video paths from state (no re-download)
            pf = ProductFolder(
                folder_id=folder["id"], folder_name=name, **meta,
                images=[Path(p) for p in existing.get("images", []) if Path(p).exists()],
                videos=[Path(p) for p in existing.get("videos", []) if Path(p).exists()],
                description_file=dest,
            )
            logger.info("Found text file for pending product %s — queued for processing", name)
            new_products.append(pf)
            continue

        logger.info("New product folder detected: %s", name)
        product = ProductFolder(folder_id=folder["id"], folder_name=name, **meta)

        dest_dir = download_base / name
        files = _list_items(service, folder["id"])  # already ordered by name

        image_count = 0
        video_count = 0
        desc_item = _find_description_item(files)

        for f in files:
            fname = f["name"]
            dest = dest_dir / fname

            if f is desc_item:
                dest = dest_dir / "description.txt"
                try:
                    _download_file(service, f["id"], dest, f.get("mimeType", ""))
                    product.description_file = dest
                    logger.info("Downloaded description file %s for %s", fname, name)
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
                if ext in ("heic", "heif"):
                    dest = _heic_to_jpeg(dest)
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
