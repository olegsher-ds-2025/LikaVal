"""Etsy connector — Playwright browser automation.

Creates listings on Etsy by driving a real browser session (no API key required).
Playwright logs in with seller credentials, navigates to the listing creation form,
fills all fields, uploads images, and saves as draft.

SOFTWARE REQUIREMENTS (implement with Copilot / Playwright):
=============================================================

Dependencies:
  - playwright>=1.40.0  (async API preferred; use sync_playwright for simplicity)
  - Install browsers once after install: `playwright install chromium`

Config keys (see config/config.yaml etsy section):
  - etsy.username      : Etsy seller account email
  - etsy.password      : Etsy seller account password
  - etsy.shop_name     : Shop name slug (used to build listing URLs)
  - etsy.headless      : bool — run Chromium headlessly (True in production, False for debugging)
  - etsy.slow_mo_ms    : int — milliseconds between actions (0 in prod, ~200 for debugging)
  - etsy.enabled       : bool — master switch

Browser session strategy:
  - Reuse a saved browser storage state (auth cookies) across runs to avoid repeated logins.
  - Storage state file: state/etsy_session.json
  - On first run (or when session expired): perform full login and save new state.
  - Detect session expiry by checking if the post-navigation URL contains "/signin".

Login flow  (https://www.etsy.com/signin):
  1. Fill #email with etsy.username
  2. Fill #password with etsy.password
  3. Click button[type="submit"]
  4. Wait for navigation away from /signin (timeout 15s)
  5. If 2FA prompt appears — raise EtsyLoginError with message "2FA required; complete manually"
  6. Save storage state to state/etsy_session.json

Listing creation flow  (https://www.etsy.com/your/shops/{shop_name}/tools/listings/new):
  Navigate to the new-listing page, then fill fields IN THIS ORDER to avoid Etsy's
  dynamic form re-rendering:

  PHOTOS (must be first — Etsy re-renders the form after photo upload):
    - For each image path (max 10): use page.set_input_files() on the file input
      selector `input[type="file"][accept*="image"]`.
    - Wait for upload confirmation (thumbnail appears) after each file.

  TITLE:
    - Selector: input[name="title"] or #listing-edit-form-title
    - Value: product["ai"]["title_en"] truncated to 140 chars

  CATEGORY / TAXONOMY:
    - Category path: Home & Living > Kitchen & Dining > Ceramics & Pottery
    - Interact with category selector dropdowns sequentially.
    - Wait for each dropdown to populate before selecting next level.

  DESCRIPTION:
    - Selector: textarea[name="description"] or contenteditable div inside the description section
    - Value: product["ai"]["etsy_listing"] (full Etsy-formatted description)

  PRICE:
    - Selector: input[name="price"] or input[data-testid="price-input"]
    - Value: str(product["price_usd"]) — USD, 2 decimal places

  QUANTITY:
    - Selector: input[name="quantity"]
    - Value: "0" if product["status"] == "sold" else "1"

  WHO MADE / WHEN MADE / IS SUPPLY (required dropdowns):
    - Who made: "I did"
    - When made: "2020 – 2025"
    - Is a supply: "No — it's a finished product"

  TAGS:
    - Up to 13 tags from product["ai"]["seo_tags"]
    - Selector: input[placeholder*="tag" i] or input[aria-label*="tag" i]
    - For each tag: type tag text → press Enter → wait for tag chip to appear

  SAVE AS DRAFT:
    - Click the "Save as draft" button (do NOT publish directly).
    - Selector: button[data-testid="save-draft"] or button containing text "Save as draft"
    - Wait for success toast or URL change that includes the new listing ID.
    - Extract listing ID from final URL: /listing/<listing_id>/...

Error handling requirements:
  - Wrap entire flow in try/except; on failure take a screenshot to
    logs/etsy_screenshot_{folder}_{timestamp}.png for debugging.
  - Raise EtsyPublishError on unrecoverable failures (caller logs + marks as failed).
  - On timeout waiting for selectors: retry once with page.reload(), then raise.

State persistence (after successful draft creation):
  - Call state_manager.upsert_product(folder, {..., "published": {
        "etsy_listing_id": listing_id,
        "etsy_state": "draft",
    }})
"""

import logging
from pathlib import Path

from backend.src.config import CONFIG
from backend.src.connectors.base import BaseConnector
import backend.src.state_manager as state_manager

logger = logging.getLogger(__name__)


class EtsyLoginError(Exception):
    """Raised when browser login to Etsy fails."""


class EtsyPublishError(Exception):
    """Raised when listing creation fails after retries."""


class EtsyConnector(BaseConnector):
    name = "etsy"

    def __init__(self) -> None:
        self._cfg = CONFIG["etsy"]

    def _is_enabled(self) -> bool:
        return (
            bool(self._cfg.get("enabled"))
            and bool(self._cfg.get("username"))
            and bool(self._cfg.get("password"))
        )

    # ── Public interface ───────────────────────────────────────────────────────

    def publish(self, folder: str, product: dict) -> bool:
        """Create a draft Etsy listing via browser automation and persist listing_id."""
        ai = product.get("ai", {})
        title = ai.get("title_en", folder)[:140]
        description = ai.get("etsy_listing", ai.get("description_en", ""))
        tags = ai.get("seo_tags", [])[:13]
        price = product.get("price_usd", 0)

        if not price:
            logger.warning("Product %s has no USD price — skipping Etsy publish", folder)
            return False

        if product.get("published", {}).get("etsy_listing_id"):
            logger.info("Etsy draft already exists for %s — skipping", folder)
            return True

        images = self._collect_images(folder)

        # TODO: implement using Playwright — see module docstring for full requirements
        listing_id = self._create_listing_via_browser(
            folder=folder,
            title=title,
            description=description,
            tags=tags,
            price=float(price),
            status=product.get("status", "available"),
            images=images,
        )

        if not listing_id:
            return False

        state_manager.upsert_product(folder, {
            **product,
            "published": {
                **product.get("published", {}),
                "etsy_listing_id": listing_id,
                "etsy_state": "draft",
            },
        })
        logger.info("Etsy draft created (listing_id=%s) for %s", listing_id, folder)
        return True

    # ── Browser automation (Playwright) — TO BE IMPLEMENTED ───────────────────

    def _create_listing_via_browser(
        self,
        folder: str,
        title: str,
        description: str,
        tags: list[str],
        price: float,
        status: str,
        images: list[Path],
    ) -> int | None:
        """Drive Etsy listing-creation form with Playwright.

        Returns the integer listing_id on success, None on failure.

        TODO: implement this method — see module docstring for step-by-step requirements.
        """
        # PLACEHOLDER — replace with Playwright implementation
        raise NotImplementedError(
            "EtsyConnector._create_listing_via_browser is not yet implemented. "
            "See module docstring for Playwright requirements."
        )

    def _login(self, page) -> None:
        """Log in to Etsy and save session state.

        TODO: implement — see module docstring LOGIN FLOW section.
        """
        # PLACEHOLDER
        raise NotImplementedError

    def _load_or_create_session(self, playwright):
        """Return a Browser + Page with a valid authenticated session.

        Loads state/etsy_session.json if it exists and the session is still valid.
        Falls back to full login and saves new session state.

        TODO: implement — see module docstring BROWSER SESSION STRATEGY section.
        """
        # PLACEHOLDER
        raise NotImplementedError

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _collect_images(self, folder: str) -> list[Path]:
        """Return up to 10 local image paths for the given product folder."""
        download_dir = Path(CONFIG["gdrive"]["download_dir"]) / folder
        images: list[Path] = []
        if download_dir.exists():
            for ext in ("jpg", "jpeg", "png", "webp"):
                images.extend(sorted(download_dir.glob(f"*.{ext}")))
        return images[:10]
