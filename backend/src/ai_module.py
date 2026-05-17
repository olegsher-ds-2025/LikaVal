"""AI content generation module.

Communicates with a local Ollama instance to generate product content
from images. All prompts are configurable via config/config.yaml.

Uses the Ollama /api/generate endpoint with vision-capable models (e.g. llava).
"""

import base64
import logging
from pathlib import Path

import requests

from backend.src.config import CONFIG

logger = logging.getLogger(__name__)

_OLLAMA_HOST = CONFIG["ollama"]["host"].rstrip("/")
_MODEL = CONFIG["ollama"]["model"]
_TIMEOUT = int(CONFIG["ollama"]["timeout"])
_PROMPTS = CONFIG["ollama"]["prompts"]


def _encode_image(image_path: Path) -> str:
    """Return base64-encoded image content."""
    with open(image_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


def _generate(prompt: str, image_path: Path | None = None) -> str:
    """
    Send a prompt to Ollama and return the response text.
    Optionally include an image for multimodal models.
    """
    payload: dict = {
        "model": _MODEL,
        "prompt": prompt,
        "stream": False,
    }
    if image_path:
        payload["images"] = [_encode_image(image_path)]

    try:
        resp = requests.post(
            f"{_OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.RequestException as exc:
        logger.error("Ollama request failed: %s", exc)
        raise


def generate_product_content(
    images: list[Path],
    videos: list[Path] | None = None,
) -> dict:
    """
    Generate all AI content for a product given its media files.

    Returns a dict with keys:
      title_en, description_en, seo_tags, social_caption, etsy_listing
    """
    # Use the first available image as the primary reference
    primary_image = images[0] if images else None

    if not primary_image:
        logger.warning("No images available for AI generation — using text-only prompts")

    def run(key: str) -> str:
        prompt = _PROMPTS[key]
        logger.info("Generating '%s' content via Ollama (%s)...", key, _MODEL)
        return _generate(prompt, image_path=primary_image)

    content: dict = {}

    for key in ("title", "description", "seo_tags", "social_caption", "etsy_listing"):
        try:
            content[f"{key}_en" if key in ("title", "description") else key] = run(key)
        except Exception as exc:
            logger.error("Failed to generate '%s': %s", key, exc)
            content[f"{key}_en" if key in ("title", "description") else key] = ""

    # Parse SEO tags into a list
    raw_tags = content.get("seo_tags", "")
    content["seo_tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]

    logger.info("AI content generation complete")
    return content


def check_ollama_health() -> bool:
    """Return True if the Ollama service is reachable."""
    try:
        resp = requests.get(f"{_OLLAMA_HOST}/api/tags", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False
