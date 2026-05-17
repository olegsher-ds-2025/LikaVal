"""Etsy connector.

Creates or updates product listings on Etsy using the Etsy Open API v3.
"""

import logging

import requests

from backend.src.config import CONFIG
from backend.src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_API_BASE = "https://openapi.etsy.com/v3"


class EtsyConnector(BaseConnector):
    name = "etsy"

    def __init__(self) -> None:
        self._cfg = CONFIG["etsy"]

    def _is_enabled(self) -> bool:
        return bool(self._cfg.get("enabled")) and bool(self._cfg.get("api_key"))

    def publish(self, folder: str, product: dict) -> bool:
        """Create an Etsy listing for the product."""
        ai = product.get("ai", {})
        title = ai.get("title_en", folder)[:140]  # Etsy max title length
        description = ai.get("etsy_listing", ai.get("description_en", ""))
        tags = ai.get("seo_tags", [])[:13]  # Etsy max 13 tags
        price = product.get("price_usd", 0)

        if not price:
            logger.warning("Product %s has no USD price — skipping Etsy publish", folder)
            return False

        payload = {
            "title": title,
            "description": description,
            "price": float(price),
            "quantity": 0 if product.get("status") == "sold" else 1,
            "who_made": "i_did",
            "when_made": "2020_2024",
            "is_supply": False,
            "tags": tags,
            "taxonomy_id": 1,  # update with correct taxonomy ID for ceramics
        }

        resp = requests.post(
            f"{_API_BASE}/application/shops/{self._cfg['shop_id']}/listings",
            json=payload,
            headers={
                "x-api-key": self._cfg["api_key"],
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        listing_id = resp.json().get("listing_id")
        logger.info("Created Etsy listing %s for %s", listing_id, folder)
        return True
