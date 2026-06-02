"""LikaVal backend pipeline entrypoint.

Orchestrates the full pipeline:
  1. Fetch new media from Google Drive
  2. Generate AI content via Ollama
  3. Publish to configured platforms (GitHub, Etsy, Facebook)

Run modes:
  python main.py          — run the pipeline once immediately
  python main.py --daemon — run on schedule defined by PUBLISH_SCHEDULE in config
"""

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

# Ensure project root is on sys.path when running directly
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.src.config import CONFIG
from backend.src.ai_module import generate_product_content, generate_seo_tags, check_ollama_health, translate_to_russian
from backend.src.media_fetcher import fetch_new_products, parse_description_file
from backend.src.state_manager import upsert_product, mark_published, append_sync_entry, log_error
from backend.src.connectors.github_connector import GitHubConnector
from backend.src.connectors.etsy_connector import EtsyConnector
from backend.src.connectors.facebook_connector import FacebookConnector


def _setup_logging() -> None:
    log_dir = Path(CONFIG["logging"]["dir"])
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_dir / "pipeline.log",
        maxBytes=CONFIG["logging"]["max_bytes"],
        backupCount=CONFIG["logging"]["backup_count"],
        encoding="utf-8",
    )
    console = logging.StreamHandler()

    level = getattr(logging, CONFIG["logging"]["level"].upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    root.addHandler(console)


logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    """Execute the full publish pipeline once."""
    logger.info("=== LikaVal pipeline started ===")
    append_sync_entry({"event": "pipeline_start"})

    # 1. Check Ollama availability (non-fatal — products with description files can proceed)
    ollama_ok = check_ollama_health()
    if not ollama_ok:
        logger.warning(
            "Ollama is not reachable at %s — AI generation will be skipped for products "
            "without a description file", CONFIG["ollama"]["host"]
        )

    # 2. Fetch new product media from Google Drive
    new_products = fetch_new_products()
    if not new_products:
        logger.info("No new products found — pipeline complete")
        append_sync_entry({"event": "pipeline_complete", "new_products": 0})
        return

    connectors = [
        GitHubConnector(),
        EtsyConnector(),
        FacebookConnector(),
    ]

    published_count = 0

    for product_folder in new_products:
        folder = product_folder.folder_name
        logger.info("Processing product: %s", folder)

        # 3. Build content from description file only (no Ollama vision)
        try:
            if product_folder.description_file and product_folder.description_file.exists():
                logger.info("Using description file for %s", folder)
                parsed = parse_description_file(product_folder.description_file)

                title_ru = parsed["title_ru"]
                desc_ru  = parsed["description_ru"]

                # If RU section missing but EN present → translate via Ollama
                if not title_ru and parsed.get("title_en"):
                    if ollama_ok:
                        logger.info("No RU text found — translating EN→RU for %s", folder)
                        translated = translate_to_russian(
                            parsed["title_en"], parsed["description_en"]
                        )
                        title_ru = translated["title_ru"]
                        desc_ru  = translated["description_ru"]
                    else:
                        logger.warning(
                            "Ollama unavailable — EN→RU translation skipped for %s", folder
                        )

                ai_content: dict = {
                    "title_en":       parsed["title_en"],
                    "description_en": parsed["description_en"],
                    "title_ru":       title_ru,
                    "description_ru": desc_ru,
                    "seo_tags":       [],
                    "etsy_listing":   "",
                    "social_post_ru": "",
                }
                # Generate SEO tags from available text
                text_for_tags = desc_ru or parsed["description_en"]
                if ollama_ok and text_for_tags:
                    ai_content["seo_tags"] = generate_seo_tags(text_for_tags)

            else:
                # No description file yet — publish empty page, mark pending
                logger.info(
                    "No description file for %s — publishing empty page (pending_text=True)",
                    folder,
                )
                ai_content = {
                    "title_en": "", "description_en": "",
                    "title_ru": "", "description_ru": "",
                    "seo_tags": [], "etsy_listing": "", "social_post_ru": "",
                }

        except Exception as exc:
            log_error(folder, f"Content processing failed: {exc}")
            continue

        # Update state — clear pending_text when content is available
        from backend.src.state_manager import get_product
        product_data = get_product(folder) or {}
        product_data["ai"] = ai_content
        has_content = bool(ai_content.get("title_ru") or ai_content.get("title_en"))
        product_data["pending_text"] = not has_content
        upsert_product(folder, product_data)
        product_data = get_product(folder)  # reload after upsert

        # 4. Publish to each platform
        for connector in connectors:
            success = connector.safe_publish(folder, product_data)
            if success:
                mark_published(folder, connector.name)

        published_count += 1

    logger.info("=== Pipeline complete — %d product(s) published ===", published_count)
    append_sync_entry({"event": "pipeline_complete", "new_products": published_count})


def run_daemon() -> None:
    """Run the pipeline on the configured cron schedule."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    cron_expr = CONFIG["scheduler"]["cron"]
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        CronTrigger.from_crontab(cron_expr),
        name="likaval_pipeline",
    )
    logger.info("Daemon started — pipeline scheduled as: %s", cron_expr)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Daemon stopped")


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(description="LikaVal content publishing pipeline")
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously on schedule instead of a single execution",
    )
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
