# Skill: generate-content

Re-generate AI content (translation/SEO tags) for a product without publishing it. **There is
no `--lang` flag or dedicated CLI entrypoint for this** — `backend/main.py` takes no arguments
for targeting a single product or language; content generation only happens as part of a full
pipeline run, driven entirely by `description.txt`.

## How content generation actually works today

`backend/src/ai_module.generate_product_content` (the vision-model-driven generator, images →
title/description) is imported in `main.py` but **never called** — it's dead code in the
current pipeline. `main.py`'s own docstring is explicit about this: "Build content from
description file only (no vision model)". The vision `llama-server` (`LLM_VISION_URL`) is
therefore not actually used by the automated pipeline at all right now.

The real flow, entirely inside `run_pipeline()` in `backend/main.py`:
1. `media_fetcher.parse_description_file` parses whatever's in the product's Drive-folder
   `description.txt` — see CLAUDE.md's note on the actual free-form format (not the old
   `EN:`/`RU:` labelled spec).
2. Whichever language is missing gets filled in via `ai_module.translate_to_russian` /
   `translate_to_english` (Jetson text model) — these already retry and fall back to isolated
   per-field translation if the combined prompt leaves a title untranslated; still spot-check
   the result actually changed script before trusting it.
3. `ai_module.generate_seo_tags` fills `seo_tags` from whichever description is available —
   only if `state/products.json` doesn't already have a tag list started.

## To manually re-run generation for one already-published product

There's no skill/flag for this — do it directly, the same way the Jetson translation fix was
applied in this session:

```python
# on the laptop (10.0.0.100), inside the container
from backend.src.ai_module import translate_to_russian  # or translate_to_english
from backend.src.state_manager import get_product, upsert_product
from backend.src.connectors.github_connector import GitHubConnector

product = get_product(folder)
ai = product["ai"]
t = translate_to_russian(ai["title_en"], ai["description_en"])
ai["title_ru"], ai["description_ru"] = t["title_ru"], t["description_ru"]
product["ai"] = ai
upsert_product(folder, product)
GitHubConnector().publish(folder, get_product(folder))  # re-renders + pushes the page
```

To make the pipeline re-process a product from scratch (re-fetch `description.txt`, etc.), set
`pending_text: true` on it in `state/products.json` first.

## Notes

- Writing style is controlled by `config/writing_styles.yaml` — edit there to tune voice
  (used by the still-unused vision path and by `generate_social_post_ru`/`etsy_listing`
  prompts, neither of which the pipeline currently calls either).
- Prompts are in `config/config.yaml` under `llm.prompts`.
- `description.txt` belongs in the product's **Google Drive** folder, not
  `backend/downloads/` directly — `media_fetcher` downloads it from Drive into
  `backend/downloads/FOLDER_NAME/` automatically. Dropping a file directly into
  `backend/downloads/` would work locally but gets wiped/ignored on the next real fetch.
