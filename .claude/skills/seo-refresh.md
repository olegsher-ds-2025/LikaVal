# Skill: seo-refresh

Refresh SEO metadata, product descriptions, and page content for www.likaval.com.
Covers product pages, catalog, homepage, and static workshop/policy pages.

## Usage

```
/project:seo-refresh [FOLDER_NAME] [--descriptions] [--titles] [--sitemap] [--all]
```

- `FOLDER_NAME` — optional; if given, refreshes only that product (e.g. `20260520_280`).
- `--descriptions` — re-generate RU + EN product descriptions via the LLM.
- `--titles` — only fix `<title>` and `<meta description>` tags (no LLM needed).
- `--sitemap` — rebuild sitemap.xml from current state and update lastmod to today.
- `--all` — do everything: descriptions + titles + sitemap + re-render all pages.
- No flag → run a read-only audit and report issues without changing files.

---

## Step 1 — Audit current state

1. Read `state/products.json` — list all products with their `status` and `ai` keys.
2. For each product check:
   - `ai.title_ru` and `ai.title_en` are populated (not empty).
   - `ai.description_ru` and `ai.description_en` are populated.
   - `ai.seo_tags` is a non-empty list.
   - `ai.social_post_ru` is populated.
3. Check that `ai.title_ru` / `ai.title_en` are ≤ 60 chars — longer titles get truncated
   by `_seo_title()` in `github_connector.py` (max 48 chars before brand suffix).
   If the stored title is sentence-style (starts with "Эта"/"This" or is > 10 words),
   flag it for a manual or AI-assisted shortening.
4. For available products, verify the rendered HTML:
   - `frontend/{lang}/products/{folder}.html` exists for both `en` and `ru`.
   - `<title>` is ≤ 70 chars total.
   - `<meta name="description">` is 120–160 chars.
   - `<link rel="canonical">` uses `https://www.likaval.com/`.
   - `<link rel="alternate" hreflang="...">` exists for both languages.
5. Sold products — confirm `<meta name="robots" content="noindex, follow">` is present.
6. Report all found issues before making changes.

---

## Step 2 — Regenerate descriptions (if `--descriptions` or `--all`)

Requires llama-server reachable at `LLM_VISION_URL`/`LLM_TEXT_URL` (Jetson Orin Nano).
Check with: `python -c "from backend.src.ai_module import check_llm_health; print(check_llm_health())"`

For each product that needs updated content:

```python
from backend.src.ai_module import (
    translate_to_russian, translate_to_english,
    generate_seo_tags, generate_social_post_ru,
)
from backend.src.state_manager import load_products, upsert_product
```

- If `title_ru` is missing or is Latin text → call `translate_to_russian(title_en, desc_en)`.
- If `title_en` is missing → call `translate_to_english(title_ru, desc_ru)`.
- If `seo_tags` is empty → call `generate_seo_tags(desc_en or desc_ru)`.
- If `social_post_ru` is empty → call `generate_social_post_ru(product)`.
- Save updates via `upsert_product(folder, product)`.

For improving existing descriptions (user requests richer copy):
- Use the Jetson's text `llama-server` (an aya-8b-class GGUF, if loaded) for multilingual rewrite:
  ```
  POST {LLM_TEXT_URL}/v1/chat/completions
  {
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "Rewrite this handmade ceramics product description in Russian in the style of
           Lika Val (warm, poetic, nature-inspired). Keep under 500 words.
           Original: {description_ru}"}
    ]
  }
  ```
- Validate the result is Cyrillic before saving.
- For EN descriptions, use whatever text-class GGUF is loaded on `LLM_TEXT_URL`.

---

## Step 3 — Re-render product pages

After updating `state/products.json`, regenerate all affected HTML pages:

```python
import sys; sys.path.insert(0, ".")
from backend.src.state_manager import load_products
from backend.src.connectors.github_connector import GitHubConnector

g = GitHubConnector()
products = load_products()

# For a specific folder:
g._render_product_page("FOLDER_NAME", products["FOLDER_NAME"])

# For all:
for folder, product in products.items():
    g._render_product_page(folder, product)

g._update_catalog_page()
g._update_ru_homepage()
```

---

## Step 4 — Verify title and meta description quality

After rendering, check each available product page:

```bash
grep -h "<title\|<meta name=\"description" frontend/ru/products/*.html frontend/en/products/*.html
```

Rules:
- `<title>` total length ≤ 70 chars. If over, shorten the `title_ru`/`title_en` in `products.json`
  to ≤ 48 chars and re-render.
- `<meta name="description">` should be 120–160 chars, end at a complete sentence or phrase.
- Titles must not start with "Эта"/"This"/"The" — these are sentence starters, not product names.
  The `_seo_title()` function in `github_connector.py` truncates but doesn't fix the opener.
  Edit the `ai.title_ru`/`ai.title_en` in `state/products.json` directly if needed.

---

## Step 5 — Rebuild sitemap (if `--sitemap` or `--all`)

The sitemap must reflect the current state of products.json:

1. Read `state/products.json` — identify all `status: available` products.
2. Today's date (for `lastmod`) → `python -c "from datetime import date; print(date.today())"`.
3. Update `frontend/sitemap.xml`:
   - Only include available product pages (sold have `noindex`, exclude from sitemap).
   - Every `<url>` entry must have `<xhtml:link>` pairs for `hreflang="ru"`, `hreflang="en"`,
     and `hreflang="x-default"` (x-default always points to `/ru/`).
   - Workshop pages (`ru/workshops.html`, `ru/workshop-*.html`, `ru/kruzhok.html`) are RU-only —
     only one `hreflang="ru"` entry, no EN counterpart.
   - Return policy pages have counterpart in both languages.
   - All URLs must start with `https://www.likaval.com/`.
4. Validate XML is well-formed: `python -c "import xml.etree.ElementTree as ET; ET.parse('frontend/sitemap.xml')"`.

---

## Step 6 — Check non-product pages

Pages to audit: `ru/index.html`, `ru/workshops.html`, `ru/workshop-*.html`, `ru/kruzhok.html`,
`ru/return-policy.html`, `en/return-policy.html`, `en/index.html`.

For each:
- `<link rel="canonical">` uses `https://www.likaval.com/`.
- `<meta name="description">` exists and is 120–160 chars.
- `<title>` is ≤ 70 chars.
- If the page has a counterpart in another language, `hreflang` links are present.

Workshop pages have no EN counterpart — their hreflang should only declare `ru` + `x-default=ru`.

---

## Step 7 — Commit and push

```bash
git add frontend/ state/products.json
git commit -m "seo: refresh descriptions and metadata — $(date +%Y-%m-%d)"
```

Then remind the user to push and to submit the sitemap in Google Search Console
at https://search.google.com/search-console → Sitemaps → `https://www.likaval.com/sitemap.xml`.

---

## Key files

| File | Purpose |
|---|---|
| `state/products.json` | Master content store — all AI titles, descriptions, tags |
| `backend/src/connectors/github_connector.py` | HTML rendering — `_render_product_page`, `_update_catalog_page`, `_update_ru_homepage` |
| `backend/src/ai_module.py` | llama.cpp calls — `translate_to_russian`, `translate_to_english`, `generate_seo_tags` |
| `config/writing_styles.yaml` | Lika Val's voice and prompt templates — edit here to tune all AI output |
| `frontend/sitemap.xml` | Submit to Google Search Console after every update |

## GGUF models (Jetson, one llama-server process per model)

| Model | Use | Server |
|---|---|---|
| aya-8b GGUF | RU/EN multilingual rewrites | (assign a port) |
| mistral-7b-instruct or qwen2.5-7b-instruct GGUF | General text, translation | `LLM_TEXT_URL` |
| llava-phi3 GGUF (with `--mmproj`) | Vision — analyse product images if no description exists | `LLM_VISION_URL` |
