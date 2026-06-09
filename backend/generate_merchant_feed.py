#!/usr/bin/env python3
"""Google Merchant Center product feed generator.

Produces two TSV files in frontend/:
  merchant_feed_en.tsv  — English feed (USD, /en/ URLs)
  merchant_feed_ru.tsv  — Russian feed (ILS, /ru/ URLs)

Feed spec: https://support.google.com/merchants/answer/7052112

Run from project root:
    python backend/generate_merchant_feed.py
"""

import csv
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.src.config import CONFIG
from backend.src.state_manager import load_products, upsert_product
from backend.src.ai_module import (
    translate_to_russian, translate_to_english,
    check_ollama_health, _chat,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SITE_URL   = "https://www.likaval.com"
BRAND_EN   = "Lika Val"
BRAND_RU   = "Лика Вал"
CONDITION  = "new"

# Google Product Taxonomy — full path required (IDs as comments)
# Verify paths at: https://www.google.com/basepages/producttype/taxonomy-with-ids.en-US.txt
CATEGORY_BY_FOLDER = {
    "20260216_100": "Home & Garden > Decor > Decorative Accents",                           # 4166
    "20260519_150": "Home & Garden > Kitchen & Dining > Tableware > Serveware",             # 3574
    "20260520_280": "Home & Garden > Kitchen & Dining > Tableware > Drinkware > Mugs",      # 2920
}
DEFAULT_CATEGORY = "Home & Garden > Decor > Decorative Accents"

# Brutto (packaged) shipping weight in kg — update when measured
WEIGHT_BY_FOLDER: dict[str, str] = {
    "20260216_100": "0.15 kg",   # owl whistle
    "20260519_150": "0.45 kg",   # olive dish
    "20260520_280": "0.55 kg",   # owl mug
}
DEFAULT_WEIGHT = ""

# TSV columns in spec order
COLUMNS = [
    "id",
    "title",
    "description",
    "link",
    "image_link",
    "additional_image_link",
    "price",
    "availability",
    "condition",
    "brand",
    "google_product_category",
    "identifier_exists",
    "mpn",
    "material",
    "color",
    "shipping_weight",
]


def _is_cyrillic(text: str) -> bool:
    return bool(re.search(r"[Ѐ-ӿ]", text))


def _short_title(text: str, max_len: int = 150) -> str:
    """Return text truncated cleanly to max_len characters."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def _generate_short_title(title: str, description: str, lang: str, ollama_ok: bool) -> str:
    """Ask Ollama to write a concise merchant product title (max 10 words)."""
    if not ollama_ok:
        return _short_title(title)

    if lang == "en":
        prompt = (
            f"Write a concise Google Merchant Center product title (max 10 words, "
            f"no punctuation at the end) for this handmade ceramic product.\n"
            f"Current title: {title}\n"
            f"Description excerpt: {description[:200]}\n"
            f"Format: Brand + Product Type + Key Feature\n"
            f"Example: 'Lika Val Handmade Ceramic Owl Whistle'\n"
            f"Output ONLY the title, nothing else."
        )
        system = "You are a product title writer. Output only the product title, no explanation."
    else:
        prompt = (
            f"Напиши краткое название товара для Google Merchant Center (максимум 10 слов, "
            f"без знаков препинания в конце) для этого керамического изделия ручной работы.\n"
            f"Текущее название: {title}\n"
            f"Описание: {description[:200]}\n"
            f"Формат: Бренд + Тип изделия + Ключевая особенность\n"
            f"Пример: 'Лика Вал Керамическая Совушка-Свистулька Ручной Работы'\n"
            f"Выводи ТОЛЬКО название, без пояснений."
        )
        system = "Ты — автор названий товаров. Выводи только название товара, без пояснений."

    try:
        result = _chat(user_message=prompt, system=system, num_predict=60)
        result = result.strip().strip('"').strip("'")
        # Validate language: RU output must contain Cyrillic
        if lang == "ru" and not _is_cyrillic(result):
            logger.warning("Short title for RU came back in wrong script — using fallback")
            return _fallback_short_title(title, lang)
        logger.info("Generated short title (%s): %s", lang, result)
        return result or _fallback_short_title(title, lang)
    except Exception as exc:
        logger.warning("Short title generation failed: %s", exc)
        return _fallback_short_title(title, lang)


def _fix_ru_translation(folder: str, product: dict, ollama_ok: bool) -> dict:
    """Fix products where title_ru is stored in English (translation was skipped/failed)."""
    ai = product.get("ai", {})
    title_ru = ai.get("title_ru", "")
    title_en = ai.get("title_en", "")
    desc_en  = ai.get("description_en", "")

    if title_ru and not _is_cyrillic(title_ru) and title_en:
        if ollama_ok:
            logger.info("title_ru is Latin for %s — re-translating EN→RU", folder)
            t = translate_to_russian(title_en, desc_en)
            if t.get("title_ru") and _is_cyrillic(t["title_ru"]):
                ai["title_ru"]       = t["title_ru"]
                ai["description_ru"] = t["description_ru"]
                product["ai"] = ai
                upsert_product(folder, product)
                logger.info("Fixed RU content for %s: %s", folder, t["title_ru"][:60])
            else:
                logger.warning("Translation produced non-Cyrillic result for %s — skipping fix", folder)
        else:
            logger.warning("Ollama unavailable — cannot fix RU translation for %s", folder)
    return product


def _fallback_short_title(title: str, lang: str) -> str:
    """Strip leading sentence starters and take the first 10 words."""
    sentence_starters = {
        "en": {"this", "these", "the", "a", "an", "it", "its"},
        "ru": {"эта", "этот", "эти", "этой", "это", "он", "она", "оно"},
    }
    words = title.split()
    starters = sentence_starters.get(lang, set())
    # Drop leading sentence starters
    while words and words[0].lower().rstrip(",") in starters:
        words = words[1:]
    short = " ".join(words[:10]).rstrip(".,;:—–-")
    return short[:1].upper() + short[1:] if short else title[:150]


def _needs_short_title(title: str) -> bool:
    """True if the title looks like a sentence rather than a product name."""
    words = title.split()
    # Sentence heuristics: starts with "This/These/Эта/Этот", >8 words
    starts_sentence = words[0].lower() in {
        "this", "these", "the", "a", "an",
        "эта", "этот", "эти", "этой",
    } if words else False
    return starts_sentence or len(words) > 10


def build_feeds(output_dir: Path, ollama_ok: bool) -> None:
    products = load_products()

    rows_en: list[dict] = []
    rows_ru: list[dict] = []

    for folder, product in sorted(products.items()):
        if product.get("status") != "available":
            continue

        # Fix broken RU translation first
        product = _fix_ru_translation(folder, product, ollama_ok)

        ai     = product.get("ai", {})
        images = product.get("images", [])
        price_usd = product.get("price_usd", "")
        price_ils = product.get("price_ils", "")

        # Image URLs (only files that actually exist in frontend/assets/products/)
        asset_dir = Path("frontend/assets/products") / folder
        pub_images = sorted(asset_dir.glob("*.JPG")) + sorted(asset_dir.glob("*.jpg"))
        if not pub_images:
            # Fall back to download paths mapped to expected URLs
            pub_images = [Path(p) for p in images if Path(p).exists()]

        if not pub_images:
            logger.warning("No images for %s — skipping", folder)
            continue

        image_link     = f"{SITE_URL}/assets/products/{folder}/{pub_images[0].name}"
        extra_images   = ",".join(
            f"{SITE_URL}/assets/products/{folder}/{p.name}"
            for p in pub_images[1:5]   # up to 4 additional
        )

        category = CATEGORY_BY_FOLDER.get(folder, DEFAULT_CATEGORY)
        weight   = WEIGHT_BY_FOLDER.get(folder, DEFAULT_WEIGHT)
        material = "ceramic, clay, glaze"

        # ── English row ────────────────────────────────────────────────────
        title_en = ai.get("title_en", "")
        desc_en  = ai.get("description_en", "")

        if not title_en:
            logger.warning("No EN title for %s — skipping EN row", folder)
        else:
            merchant_title_en = (
                _generate_short_title(title_en, desc_en, "en", ollama_ok)
                if _needs_short_title(title_en)
                else _short_title(title_en)
            )
            rows_en.append({
                "id":                    folder,
                "title":                 merchant_title_en,
                "description":           _short_title(desc_en, 5000),
                "link":                  f"{SITE_URL}/en/products/{folder}.html",
                "image_link":            image_link,
                "additional_image_link": extra_images,
                "price":                 f"{price_ils:.2f} ILS",
                "availability":          "in_stock",
                "condition":             CONDITION,
                "brand":                 BRAND_EN,
                "google_product_category": category,
                "identifier_exists":     "FALSE",
                "mpn":                   folder,
                "material":              material,
                "color":                 "",
                "shipping_weight":       weight,
            })

        # ── Russian row ────────────────────────────────────────────────────
        title_ru = ai.get("title_ru", "")
        desc_ru  = ai.get("description_ru", "")

        if not title_ru or not _is_cyrillic(title_ru):
            logger.warning("No valid RU title for %s — skipping RU row", folder)
        else:
            merchant_title_ru = (
                _generate_short_title(title_ru, desc_ru, "ru", ollama_ok)
                if _needs_short_title(title_ru)
                else _short_title(title_ru)
            )
            rows_ru.append({
                "id":                    folder,
                "title":                 merchant_title_ru,
                "description":           _short_title(desc_ru, 5000),
                "link":                  f"{SITE_URL}/ru/products/{folder}.html",
                "image_link":            image_link,
                "additional_image_link": extra_images,
                "price":                 f"{price_ils:.2f} ILS",
                "availability":          "in_stock",
                "condition":             CONDITION,
                "brand":                 BRAND_RU,
                "google_product_category": category,
                "identifier_exists":     "FALSE",
                "mpn":                   folder,
                "material":              "керамика, глина, глазурь",
                "color":                 "",
                "shipping_weight":       weight,
            })

    def _clean(row: dict) -> dict:
        """Strip newlines/tabs from every field — TSV cannot contain them unescaped."""
        return {
            k: re.sub(r"[\t\n\r]+", " ", str(v)).strip()
            for k, v in row.items()
        }

    # Write TSV files
    output_dir.mkdir(parents=True, exist_ok=True)

    for lang, rows in (("en", rows_en), ("ru", rows_ru)):
        out = output_dir / f"merchant_feed_{lang}.tsv"
        with open(out, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=COLUMNS, delimiter="\t",
                quoting=csv.QUOTE_NONE, escapechar="\\",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(_clean(row))
        logger.info("Wrote %s (%d product(s)): %s", out.name, len(rows), out)


if __name__ == "__main__":
    ollama_ok = check_ollama_health()
    logger.info("Ollama reachable: %s", ollama_ok)
    build_feeds(Path("frontend"), ollama_ok)
    logger.info("Done")
