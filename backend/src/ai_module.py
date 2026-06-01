"""AI content generation module.

Communicates with a local Ollama instance to generate product content
from images and video frames. All prompts are configurable via config/config.yaml.

For each product the module produces:
  - title_en / description_en   — English title + description
  - title_ru / description_ru   — Russian title + description
  - seo_tags                    — list of SEO keywords
  - etsy_listing                — full Etsy listing text

Video files are sampled into `vision_frames` key frames (via ffmpeg) and
those frames are treated as additional images for the vision model.
"""

import base64
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import requests

from backend.src.config import CONFIG

logger = logging.getLogger(__name__)

_OLLAMA_HOST = CONFIG["ollama"]["host"].rstrip("/")
_MODEL = CONFIG["ollama"]["model"]
_TEXT_MODEL = CONFIG["ollama"].get("text_model", _MODEL)
_TIMEOUT = int(CONFIG["ollama"]["timeout"])
_TEXT_TIMEOUT = int(CONFIG["ollama"].get("text_timeout", 60))
_PROMPTS = CONFIG["ollama"]["prompts"]
_VISION_FRAMES: int = int(CONFIG["ollama"].get("vision_frames", 3))


# ── Media helpers ─────────────────────────────────────────────────────────────

def _encode_image(image_path: Path) -> str:
    """Return base64-encoded image bytes."""
    with open(image_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


def _extract_video_frames(video_path: Path, n_frames: int = _VISION_FRAMES) -> list[Path]:
    """Extract *n_frames* evenly-spaced frames from a video using ffmpeg.

    Returns a list of temporary JPEG paths. The caller is responsible for
    cleaning up the temp directory when done.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="likaval_frames_"))
    pattern = str(tmp_dir / "frame_%02d.jpg")

    # Use select filter to pick evenly-spaced frames across the whole clip
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"select=not(mod(n\\,max(1\\,trunc(n/{n_frames})))),setpts=N/FRAME_RATE/TB",
        "-frames:v", str(n_frames),
        "-q:v", "3",
        pattern,
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("Frame extraction failed for %s: %s", video_path.name, exc)
        return []

    frames = sorted(tmp_dir.glob("frame_*.jpg"))
    logger.info("Extracted %d frame(s) from %s", len(frames), video_path.name)
    return frames


def _collect_vision_inputs(images: list[Path], videos: list[Path]) -> list[Path]:
    """Return a combined, deduplicated list of image paths for the vision model.

    Up to 3 product images + frames extracted from each video are included.
    Keeping the count low speeds up inference significantly.
    """
    selected: list[Path] = list(images[:3])  # first 3 images give good coverage

    for video in videos:
        frames = _extract_video_frames(video)
        selected.extend(frames)

    return selected


# ── Ollama API ────────────────────────────────────────────────────────────────

def _generate(prompt: str, image_path: Path | None = None, model: str | None = None) -> str:
    """Send a prompt (optionally with an image) to Ollama; return response text."""
    payload: dict = {"model": model or _MODEL, "prompt": prompt, "stream": False}
    if image_path:
        payload["images"] = [_encode_image(image_path)]

    resp = requests.post(
        f"{_OLLAMA_HOST}/api/generate",
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _chat(user_message: str, system: str, model: str | None = None, num_predict: int = 300) -> str:
    """Send a chat request with a system message to Ollama; return response text.

    Using /api/chat with an explicit system role reliably constrains the language
    and output length, avoiding the Chinese-fallback issue with qwen2.5.
    """
    payload = {
        "model": model or _TEXT_MODEL,
        "stream": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    }
    resp = requests.post(
        f"{_OLLAMA_HOST}/api/chat",
        json=payload,
        timeout=_TEXT_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def _parse_structured(text: str, title_key: str, desc_key: str) -> tuple[str, str]:
    """Parse TITLE:/DESCRIPTION: (or Russian equivalents) from model output.

    Falls back gracefully when the model doesn't follow the format exactly.
    """
    title_match = re.search(rf"{re.escape(title_key)}[:\s]+(.+)", text, re.IGNORECASE)
    desc_match = re.search(rf"{re.escape(desc_key)}[:\s]+(.+)", text, re.IGNORECASE | re.DOTALL)

    title = title_match.group(1).strip().split("\n")[0] if title_match else ""
    desc = desc_match.group(1).strip() if desc_match else ""

    # If parsing failed, use first line as title and the rest as description
    if not title:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        title = lines[0] if lines else text[:80]
        desc = " ".join(lines[1:]) if len(lines) > 1 else ""

    return title, desc


# ── Public API ────────────────────────────────────────────────────────────────

def generate_social_post_ru(product: dict) -> str:
    """Generate a Facebook/Instagram post in Lika Val's authentic voice (Russian).

    Uses the `social_post_ru` prompt from config, which embeds her writing-style
    example and all style rules so the model produces first-person storytelling
    posts — not generic marketing copy.
    """
    prompt_template = _PROMPTS.get("social_post_ru", "")
    if not prompt_template:
        logger.warning("social_post_ru prompt not configured — skipping social post")
        return ""

    ai = product.get("ai", {})
    status_label = "Продано" if product.get("status") == "sold" else "Доступно для заказа"
    prompt = (
        prompt_template
        .replace("{title_ru}", ai.get("title_ru", ai.get("title_en", "")))
        .replace("{description_ru}", ai.get("description_ru", ai.get("description_en", "")))
        .replace("{price_usd}", str(product.get("price_usd", "")))
        .replace("{status}", status_label)
    )

    try:
        logger.info("Generating social post (RU) via %s...", _TEXT_MODEL)
        post = _chat(
            user_message=prompt,
            system=(
                "Ты — Лика Вал. Пиши исключительно от первого лица на русском языке "
                "в тёплом, личном, storytelling стиле. Никаких маркетинговых клише."
            ),
            num_predict=400,
        )
        logger.info("Social post generated (%d chars)", len(post))
        return post
    except Exception as exc:
        logger.error("Social post generation failed: %s", exc)
        return ""


def generate_workshop_post_ru(
    workshop_title: str,
    workshop_description: str,
    price: str = "",
    details: str = "",
) -> str:
    """Generate a Facebook/Instagram workshop announcement in Lika Val's voice.

    Uses the `workshop_post_ru` prompt — philosophical, healing-focused tone
    with anaphora on clay as a living/magical material.
    """
    prompt_template = _PROMPTS.get("workshop_post_ru", "")
    if not prompt_template:
        logger.warning("workshop_post_ru prompt not configured")
        return ""

    prompt = (
        prompt_template
        .replace("{workshop_title}", workshop_title)
        .replace("{workshop_description}", workshop_description)
        .replace("{price}", price)
        .replace("{details}", details)
    )

    try:
        logger.info("Generating workshop post (RU) via %s...", _TEXT_MODEL)
        post = _chat(
            user_message=prompt,
            system=(
                "Ты — Лика Вал. Пиши исключительно от первого лица на русском языке. "
                "Стиль: тёплый, философский, поэтический. Глина — живой и магический материал. "
                "Никаких маркетинговых клише и жёстких призывов к покупке."
            ),
            num_predict=500,
        )
        logger.info("Workshop post generated (%d chars)", len(post))
        return post
    except Exception as exc:
        logger.error("Workshop post generation failed: %s", exc)
        return ""



def generate_product_content(
    images: list[Path],
    videos: list[Path] | None = None,
) -> dict:
    """Generate AI content for a product from its images and videos.

    Returns a dict with keys:
      title_en, description_en, title_ru, description_ru,
      seo_tags (list), etsy_listing
    """
    videos = videos or []
    vision_inputs = _collect_vision_inputs(images, videos)
    # Use the best single image as the primary reference for all prompts
    primary = vision_inputs[0] if vision_inputs else None

    if not primary:
        logger.warning("No visual inputs available — AI output will be text-only")

    content: dict = {}

    # — English summary (vision model) —
    try:
        logger.info("Generating English summary via %s...", _MODEL)
        raw_en = _generate(_PROMPTS["summary_en"], image_path=primary)
        content["title_en"], content["description_en"] = _parse_structured(
            raw_en, "TITLE", "DESCRIPTION"
        )
        logger.info("EN title: %s", content["title_en"])
    except Exception as exc:
        logger.error("English summary failed: %s", exc)
        content["title_en"] = content["description_en"] = ""

    # — Russian summary (chat API with Russian system message — prevents Chinese fallback) —
    try:
        logger.info("Generating Russian translation via %s...", _TEXT_MODEL)
        user_msg = _PROMPTS["translate_ru"].replace(
            "{title}", content.get("title_en", "")
        ).replace(
            "{description}", content.get("description_en", "")
        )
        raw_ru = _chat(
            user_message=user_msg,
            system="Ты профессиональный переводчик. Отвечай исключительно на русском языке.",
            num_predict=250,
        )
        content["title_ru"], content["description_ru"] = _parse_structured(
            raw_ru, "НАЗВАНИЕ", "ОПИСАНИЕ"
        )
        logger.info("RU title: %s", content["title_ru"])
    except Exception as exc:
        logger.error("Russian translation failed: %s", exc)
        content["title_ru"] = content["description_ru"] = ""

    # — SEO tags (chat API for consistent format) —
    try:
        logger.info("Generating SEO tags via %s...", _TEXT_MODEL)
        tags_prompt = _PROMPTS["seo_tags"].replace(
            "{description}", content.get("description_en", "handmade ceramic piece")
        )
        raw_tags = _chat(
            user_message=tags_prompt,
            system="You are an SEO expert. Output only what is asked, no extra text.",
            num_predict=150,
        )
        raw_tags = re.sub(r"[\*\-\d]+[\.\)]\s*", "", raw_tags)
        content["seo_tags"] = [
            t.strip().lower() for t in re.split(r"[,\n]", raw_tags)
            if t.strip() and len(t.strip()) < 60
        ][:13]
    except Exception as exc:
        logger.error("SEO tags failed: %s", exc)
        content["seo_tags"] = []

    # — Etsy listing (vision model) —
    try:
        logger.info("Generating Etsy listing via %s...", _MODEL)
        content["etsy_listing"] = _generate(_PROMPTS["etsy_listing"], image_path=primary)
    except Exception as exc:
        logger.error("Etsy listing failed: %s", exc)
        content["etsy_listing"] = ""

    # — Social post in Lika Val's voice (Russian, text model) —
    try:
        logger.info("Generating social post (RU) via %s...", _TEXT_MODEL)
        prompt_template = _PROMPTS.get("social_post_ru", "")
        if prompt_template:
            post_prompt = (
                prompt_template
                .replace("{title_ru}", content.get("title_ru", content.get("title_en", "")))
                .replace("{description_ru}", content.get("description_ru", content.get("description_en", "")))
                .replace("{price_usd}", "")   # price unknown at generation time; connector fills it
                .replace("{status}", "Доступно для заказа")
            )
            content["social_post_ru"] = _chat(
                user_message=post_prompt,
                system=(
                    "Ты — Лика Вал. Пиши исключительно от первого лица на русском языке "
                    "в тёплом, личном, storytelling стиле. Никаких маркетинговых клише."
                ),
                num_predict=400,
            )
        else:
            content["social_post_ru"] = ""
    except Exception as exc:
        logger.error("Social post generation failed: %s", exc)
        content["social_post_ru"] = ""

    logger.info("AI content generation complete")
    return content


def generate_seo_tags(description_en: str) -> list[str]:
    """Generate SEO tags for a product given its English description.

    Returns a list of up to 13 lowercase tags, or an empty list on failure.
    """
    try:
        logger.info("Generating SEO tags via %s...", _TEXT_MODEL)
        tags_prompt = _PROMPTS["seo_tags"].replace(
            "{description}", description_en or "handmade ceramic piece"
        )
        raw_tags = _chat(
            user_message=tags_prompt,
            system="You are an SEO expert. Output only what is asked, no extra text.",
            num_predict=150,
        )
        raw_tags = re.sub(r"[\*\-\d]+[\.\)]\s*", "", raw_tags)
        return [
            t.strip().lower() for t in re.split(r"[,\n]", raw_tags)
            if t.strip() and len(t.strip()) < 60
        ][:13]
    except Exception as exc:
        logger.error("SEO tags failed: %s", exc)
        return []


def check_ollama_health() -> bool:
    """Return True if the Ollama service is reachable."""
    try:
        resp = requests.get(f"{_OLLAMA_HOST}/api/tags", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False
