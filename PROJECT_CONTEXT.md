# LikaVal — Project Context (auto-maintained, last updated 2026-06-09)

> Keep this file updated after significant changes. It exists to avoid re-reading all source
> files at the start of each session. Covers architecture, state schema, API surface, and
> current product inventory.

---

## Pipeline Flow

```
Google Drive
  └─ media_fetcher.fetch_new_products()      # discovers folders, downloads images/videos
        │
        ▼
main.run_pipeline()
  ├─ ai_module.generate_product_content()    # vision → EN text → RU translation → SEO tags
  ├─ state_manager.upsert_product()          # persists to state/products.json
  └─ for each connector:
       ├─ GitHubConnector.publish()          # renders HTML, git-push to gh-pages
       ├─ EtsyConnector.publish()            # Playwright browser automation
       └─ FacebookConnector.publish()        # Graph API photo/text post
```

Run modes: `python backend/main.py` (single run) or `--daemon` (APScheduler cron, default `0 2 * * *`).

---

## Source Files — Size & Responsibility

| File | Lines | Responsibility |
|---|---|---|
| `backend/main.py` | 202 | Orchestrator: `run_pipeline()`, `run_daemon()`, CLI entry |
| `backend/src/ai_module.py` | 404 | Ollama LLM: vision→EN, EN→RU, SEO tags, social posts |
| `backend/src/media_fetcher.py` | 360 | Google Drive watcher; `ProductFolder` dataclass; folder name parser |
| `backend/src/state_manager.py` | 102 | JSON R/W helpers; all product state mutations |
| `backend/src/config.py` | ~50 | YAML loader with `${ENV_VAR:default}` resolution |
| `backend/src/connectors/github_connector.py` | 638 | Static HTML generation (EN+RU product pages, catalog, homepage) + git push |
| `backend/src/connectors/etsy_connector.py` | 223 | Playwright-based Etsy listing creation |
| `backend/src/connectors/facebook_connector.py` | ~70 | Graph API post with photo |
| `backend/src/connectors/base.py` | small | `BaseConnector` abstract class |

---

## Key Classes & Functions

### `media_fetcher.py`
- `ProductFolder` — dataclass: `folder_name, date, price_ils, images[], videos[], description_text`
  - `.price_usd` property — converts via `ILS_TO_USD_RATIO`
  - `.status` property — returns `"sold"` if `_sold` suffix, else `"available"`
- `fetch_new_products() → list[ProductFolder]` — Drive API → downloads to `backend/downloads/`
- `_parse_folder_name(name) → dict|None` — parses `YYYYMMDD_PRICE[_sold]`
- `parse_description_file(path) → dict` — reads optional `description.txt` from Drive folder

### `ai_module.py`
- `generate_product_content(folder, images, videos, description_text) → dict`
  - Returns: `title_en, description_en, title_ru, description_ru, seo_tags[], etsy_listing`
- `translate_to_russian(title_en, description_en) → {title_ru, description_ru}`
- `generate_social_post_ru(product) → str`
- `generate_seo_tags(description_en) → list[str]`
- `check_ollama_health() → bool`
- Internal: `_generate(prompt, image_path, model)` — Ollama `/api/generate`
- Internal: `_chat(user_message, system, model, num_predict)` — Ollama `/api/chat`

### `state_manager.py`
- `load_products() / save_products(products)` — full dict R/W
- `upsert_product(folder, data)` — merge-update a single product
- `get_product(folder) → dict|None`
- `is_processed(folder) → bool` — has `ai_content` key
- `is_pending_text(folder) → bool` — `pending_text` flag is truthy
- `mark_published(folder, platform)` — sets `published[platform] = True`
- `append_sync_entry(entry)` — appends to `state/sync_log.json`

### `github_connector.py`
- `publish(folder, product) → bool`
- `_render_product_page(folder, product)` — writes EN + RU HTML to `frontend/{en,ru}/products/`
- `_update_catalog_page()` — regenerates `frontend/{en,ru}/catalog.html`
- `_update_ru_homepage()` — updates `frontend/ru/index.html`
- `_git_push()` — `git subtree push --prefix frontend origin gh-pages`

---

## State Schema — `state/products.json`

```jsonc
{
  "20260214_250": {
    "status": "available",          // "available" | "sold"
    "price_ils": 250,
    "price_usd": 200,
    "images": ["IMG_7896.JPG", ...],
    "videos": ["IMG_7890.MOV"],
    "pending_text": false,          // true = no description yet, page published with placeholder
    "ai_content": {
      "title_en": "...",
      "description_en": "...",
      "title_ru": "...",
      "description_ru": "...",
      "seo_tags": ["ceramics", ...],
      "etsy_listing": "...",
      "social_post_ru": "..."
    },
    "published_to": {               // key presence = published
      "github": true,
      "etsy": true,
      "facebook": true
    },
    "etsy_listing_id": null,        // Etsy numeric listing ID after publish
    "error": null
  }
}
```

---

## Current Product Inventory (as of 2026-06-09)

| Folder | Price ILS | Price USD | Images | Videos | AI Content | Published |
|---|---|---|---|---|---|---|
| `20260214_250` | 250 | 200 | 10 | 1 | none | none |
| `20260215_200` | 200 | 160 | 10 | 1 | none | none |
| `20260216_100` | 100 | 80 | 9 | 1 | none | none |
| `20260216_200` | 200 | 160 | 9 | 1 | none | none |
| `20260519-150` | 150 | 120 | 10 | 1 | none | none |
| `20260519_150` | 150 | 120 | 10 | 1 | none | none |
| `20260520_280` | 280 | 224 | 10 | 0 | none | none |

**Note:** `20260519-150` and `20260519_150` appear to be duplicates (hyphen vs underscore variant).
No product has AI content generated or has been published yet.

---

## Frontend Structure

```
frontend/
  index.html                  # root redirect → /en/
  en/
    index.html                # English homepage
    shop.html                 # EN shop listing
    catalog.html              # EN product catalog (auto-generated)
    products/{folder}.html    # EN product pages (auto-generated)
  ru/
    index.html                # Russian homepage
    shop.html                 # RU shop
    catalog.html              # RU catalog (auto-generated)
    products/{folder}.html    # RU product pages (auto-generated)
    workshops.html            # Workshops landing
    workshop-standard.html    # Standard wheel-throwing workshop
    workshop-silver.html      # Silver firing workshop (1080°C, age 15+)
    workshop-gold.html        # Gold workshop
    kruzhok.html              # Ceramics circle/club page
  he/
    index.html                # Hebrew stub
  assets/
    css/main.css
    js/main.js, shop.js
    products/{folder}/*.JPG   # Product images served statically
    images/                   # Brand images, workshop photos
```

Deployed via `git subtree push --prefix frontend origin gh-pages`.
Custom domain in `CNAME`. `robots.txt` + `sitemap.xml` present.

---

## AI Models

| Model | Purpose |
|---|---|
| `llava-phi3:latest` (4B) | Vision — product image analysis |
| `mistral:7b-instruct-q4_K_M` | Text generation, EN content, SEO tags |
| `aya:8b` | Multilingual, EN→RU translation (Jetson) |

Ollama host: env `OLLAMA_HOST` (default localhost:11434).
Jetson Orin Nano GPU at `http://10.0.0.20:11434` for heavier inference.

---

## Config Files

- `config/config.yaml` — main config with `${ENV_VAR:default}` template vars
- `config/writing_styles.yaml` — AI prompt templates and Lika Val's voice/style (edit to tune output)
- `config/products.yaml` — static product type definitions
- `config/gdrive_credentials.json` — **gitignored**, Google OAuth credentials

---

## Pipeline Runs (sync_log.json)

| Timestamp | Event | Details |
|---|---|---|
| 2026-05-19 20:21 UTC | pipeline_start | — |
| 2026-06-01 11:16 UTC | pipeline_start | — |
| 2026-06-01 11:41 UTC | pipeline_complete | 3 new products |

---

## Known Issues / Flags

- `20260519-150` vs `20260519_150` — duplicate entry with hyphen vs underscore; investigate which is canonical before publishing
- All 7 products have `ai_content: {}` — no content has been generated yet; next pipeline run with Ollama healthy will generate
- `pending_text=True` path: product HTML is published with placeholder, then re-published when content arrives

---

## Quick Commands

```bash
# Single pipeline run
python backend/main.py

# Daemon mode
python backend/main.py --daemon

# Check state
cat state/products.json | python3 -m json.tool

# Check Ollama health
curl http://localhost:11434/api/tags

# Force-push frontend to gh-pages (done by connector, but manual if needed)
git subtree push --prefix frontend origin gh-pages
```

---

## Connector Enable Conditions

- **GitHub**: always enabled if `GITHUB_TOKEN` + `GITHUB_REPO` set
- **Etsy**: requires `ETSY_API_KEY` + `ETSY_SHOP_ID`; uses Playwright browser session at `config/etsy_session.json`
- **Facebook**: requires `FACEBOOK_PAGE_ID` + `FACEBOOK_ACCESS_TOKEN`
