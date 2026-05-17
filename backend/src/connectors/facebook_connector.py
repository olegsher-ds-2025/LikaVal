"""Facebook connector.

Publishes product posts to a Facebook Page using the Graph API.
"""

import logging
from pathlib import Path

import requests

from backend.src.config import CONFIG
from backend.src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class FacebookConnector(BaseConnector):
    name = "facebook"

    def __init__(self) -> None:
        self._cfg = CONFIG["facebook"]

    def _is_enabled(self) -> bool:
        return (
            bool(self._cfg.get("enabled"))
            and bool(self._cfg.get("access_token"))
            and bool(self._cfg.get("page_id"))
        )

    def publish(self, folder: str, product: dict) -> bool:
        """Publish a product post (with photo) to the Facebook Page."""
        ai = product.get("ai", {})
        caption = ai.get("social_caption", ai.get("description_en", ""))
        images = product.get("images", [])

        if images:
            return self._post_with_photo(folder, caption, Path(images[0]))
        else:
            return self._post_text(folder, caption)

    def _post_with_photo(self, folder: str, caption: str, image_path: Path) -> bool:
        url = f"{_GRAPH_API_BASE}/{self._cfg['page_id']}/photos"
        with open(image_path, "rb") as img_fh:
            resp = requests.post(
                url,
                data={"caption": caption, "access_token": self._cfg["access_token"]},
                files={"source": img_fh},
                timeout=60,
            )
        resp.raise_for_status()
        post_id = resp.json().get("post_id") or resp.json().get("id")
        logger.info("Published Facebook photo post %s for %s", post_id, folder)
        return True

    def _post_text(self, folder: str, message: str) -> bool:
        url = f"{_GRAPH_API_BASE}/{self._cfg['page_id']}/feed"
        resp = requests.post(
            url,
            json={"message": message, "access_token": self._cfg["access_token"]},
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("Published Facebook text post for %s", folder)
        return True
