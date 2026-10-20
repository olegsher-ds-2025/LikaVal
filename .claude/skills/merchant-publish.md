# Skill: merchant-publish

Generate and validate Google Merchant Center TSV product feeds (EN + RU) for Israel,
then guide upload to Google Merchant Center.

**Note:** `backend/main.py`'s `run_pipeline()` now calls `build_merchant_feeds()` and pushes
the result automatically after every run that publishes ≥1 product (see
`backend/src/connectors/github_connector.py:publish_static_files`). This skill is mainly
useful now for an ad-hoc regen/validation outside a normal pipeline run — Step 2 below is no
longer a required manual step for day-to-day operation. Google Merchant Center delivery is a
one-time **Scheduled fetch** setup (see Step 7), not a per-run manual upload.

## Usage

```
/project:merchant-publish [--dry-run] [--validate-only]
```

- `--dry-run` — regenerate feeds and run validation, but don't commit or prompt to upload.
- `--validate-only` — check existing `frontend/merchant_feed_*.tsv` without regenerating.
- No flag → full run: regenerate → validate → commit → upload instructions.

---

## Step 1 — Pre-flight checks

Before regenerating:

1. Confirm `state/products.json` is current:
   ```bash
   python -c "
   import json, pathlib
   p = json.loads(pathlib.Path('state/products.json').read_text())
   for k, v in p.items():
       print(k, v.get('status'), v.get('price_ils'), v.get('ai', {}).get('title_en', '')[:40])
   "
   ```
   Look for: products with `status: available`, both `price_ils` and `price_usd` set,
   `ai.title_en` and `ai.title_ru` non-empty.

2. Check `CATEGORY_BY_FOLDER` and `WEIGHT_BY_FOLDER` in `backend/generate_merchant_feed.py`:
   - Every product in the feed must have a matching entry in `CATEGORY_BY_FOLDER`.
   - Category paths must be full Google Product Taxonomy paths starting with `Home & Garden >`.
   - `WEIGHT_BY_FOLDER` should have an entry for every product (use typical postal weights).
   - If a product is missing, add it before continuing.

3. Check that product image files exist under `frontend/assets/products/{folder}/`:
   ```bash
   python -c "
   import json, pathlib
   p = json.loads(pathlib.Path('state/products.json').read_text())
   for k, v in p.items():
       imgs = v.get('images', [])
       if imgs:
           path = pathlib.Path(f'frontend/assets/products/{k}/{imgs[0]}')
           print(k, '✓' if path.exists() else f'MISSING {path}')
   "
   ```

---

## Step 2 — Regenerate feeds

```bash
cd /mnt/data/projects/LikaVal
python backend/generate_merchant_feed.py
```

Expected output: two files written (or confirmed up-to-date):
- `frontend/merchant_feed_en.tsv`
- `frontend/merchant_feed_ru.tsv`

If the script errors, common causes:
- Missing `price_ils` field in `products.json` — add it via `state_manager.upsert_product()`.
- Missing `ai.title_en` or `ai.description_en` — run `/project:seo-refresh --descriptions` first.
- `CATEGORY_BY_FOLDER` missing a folder key — add it to the script.

---

## Step 3 — Validate TSV feeds

Run column count and content checks:

```bash
python - <<'EOF'
import re, sys, pathlib

REQUIRED_COLS = 16  # current column count, update if schema changes
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0001F1E0-\U0001F1FF]+"
)

for fname in ["frontend/merchant_feed_en.tsv", "frontend/merchant_feed_ru.tsv"]:
    path = pathlib.Path(fname)
    lines = path.read_bytes().split(b"\n")
    print(f"\n=== {fname} ===")
    for i, raw in enumerate(lines):
        line = raw.decode("utf-8", errors="replace").rstrip("\r")
        if not line:
            continue
        cols = line.split("\t")
        n = len(cols)
        if n != REQUIRED_COLS:
            print(f"  Row {i+1}: {n} cols (expected {REQUIRED_COLS}) ← ERROR")
        if i == 0:
            print(f"  Header: {cols}")
        else:
            if EMOJI_RE.search(line):
                print(f"  Row {i+1}: contains emoji ← ERROR")
            currency = cols[9] if len(cols) > 9 else ""
            if "USD" in currency:
                print(f"  Row {i+1}: price column has USD (should be ILS) ← ERROR")
            if "ILS" in currency:
                print(f"  Row {i+1}: price OK ({currency})")
            print(f"  Row {i+1}: id={cols[0]}, title={cols[1][:50]}")
print("\nValidation complete.")
EOF
```

All data rows must show:
- Exactly `REQUIRED_COLS` columns (currently 16)
- No emoji characters
- Prices in ILS (not USD)
- Non-empty `id`, `title`, `description`, `link`, `image_link`, `price`, `brand`, `google_product_category`

---

## Step 4 — Spot-check feed content

Review one row of each feed for human issues:

```bash
python - <<'EOF'
import pathlib, json

for fname in ["frontend/merchant_feed_en.tsv", "frontend/merchant_feed_ru.tsv"]:
    lines = pathlib.Path(fname).read_text(encoding="utf-8").split("\n")
    header = lines[0].split("\t")
    for row_line in lines[1:]:
        if not row_line.strip():
            continue
        row = row_line.split("\t")
        print(f"\n--- {fname} ---")
        for col, val in zip(header, row):
            print(f"  {col:30s}: {val[:80]}")
        break  # just the first data row
EOF
```

Things to verify visually:
- `title` is a short product name (not a sentence starting "Эта кружка...")
- `description` is a paragraph, no tabs/newlines/emoji
- `link` and `image_link` use `https://www.likaval.com/`
- `google_product_category` is a full path like `Home & Garden > Kitchen & Dining > ...`
- `shipping_weight` has value like `0.55 kg`
- `availability` is `in stock` (or `out of stock` for sold items, but sold items should be excluded)
- `condition` is `new`

---

## Step 5 — Excluded products check

Products with `status: sold` in `products.json` must NOT appear in either feed.

```bash
python - <<'EOF'
import json, pathlib

products = json.loads(pathlib.Path("state/products.json").read_text())
sold = [k for k, v in products.items() if v.get("status") == "sold"]

for fname in ["frontend/merchant_feed_en.tsv", "frontend/merchant_feed_ru.tsv"]:
    content = pathlib.Path(fname).read_text(encoding="utf-8")
    for folder in sold:
        if folder in content:
            print(f"ERROR: {fname} contains sold product {folder}")
        else:
            print(f"OK:    {fname} correctly excludes {folder}")
EOF
```

If a sold product appears, remove it from the generator's data source in
`backend/generate_merchant_feed.py` (the products dict is filtered by status — check that filter).

---

## Step 6 — Commit

If no errors from Steps 3–5:

```bash
git add frontend/merchant_feed_en.tsv frontend/merchant_feed_ru.tsv
git commit -m "merchant: regenerate EN+RU feeds — $(date +%Y-%m-%d)"
```

Push when ready: `git push origin main`

---

## Step 7 — Google Merchant Center delivery (one-time setup, then automatic)

Google Merchant Center has no push API for a standard account, but the feed files are already
live and auto-updating (pushed to `gh-pages` by the pipeline itself) at:
- `https://www.likaval.com/merchant_feed_en.tsv`
- `https://www.likaval.com/merchant_feed_ru.tsv`

So the correct integration is a **Scheduled fetch** pointed at those URLs — set up once, never
touched again:

### For Israel — EN feed
1. Go to → https://merchants.google.com → Products → Feeds → Add feed
2. Language: "English", Target country: "Israel", method: **Scheduled fetch**
3. Fetch URL: `https://www.likaval.com/merchant_feed_en.tsv`, frequency: daily
4. Wait for the first fetch to process; check for errors under "Diagnostics"

### For Israel — RU feed
1. Same path — Add feed
2. Language: "Russian", Target country: "Israel", method: **Scheduled fetch**
3. Fetch URL: `https://www.likaval.com/merchant_feed_ru.tsv`, frequency: daily

After this one-time setup, every pipeline run that publishes a product regenerates and
publishes both TSVs automatically, and Merchant Center picks up the changes on its next
scheduled fetch — no manual upload step needed going forward.

### Common Merchant Center errors and fixes

| Error | Cause | Fix |
|---|---|---|
| "Too few column separators" | Row has fewer tabs than the header | Re-run generator; check `QUOTE_NONE` + `escapechar` in DictWriter |
| "Wrong currency" | Feed uses USD but shipping profile is ILS | Both feeds must use ILS (price column: `280 ILS` not `224.0 USD`) |
| "Invalid value [google_product_category]" | Short path without parent categories | Use full path from Google taxonomy, starting with `Home & Garden >` |
| "Emoji not allowed" | Description field has emoji chars | `_EMOJI_RE.sub()` should strip them; re-run generator |
| "Image URL not found" | Image file missing or wrong URL | Check file at `frontend/assets/products/{folder}/{filename}` and that it's pushed to GitHub |
| "Shipping settings missing" | No shipping rule for Israel | Add shipping rule in Merchant Center: Israel, carrier, cost |

---

## Key files

| File | Purpose |
|---|---|
| `backend/generate_merchant_feed.py` | Feed generator — edit `CATEGORY_BY_FOLDER`, `WEIGHT_BY_FOLDER` here |
| `frontend/merchant_feed_en.tsv` | EN feed (English titles, ILS prices, Israel target) |
| `frontend/merchant_feed_ru.tsv` | RU feed (Russian titles, ILS prices, Israel target) |
| `state/products.json` | Source of truth for product data — must be up-to-date |

## Feed schema (16 columns, in order)

```
id  title  description  link  image_link  additional_image_link
availability  condition  price  brand  google_product_category
item_group_id  material  color  shipping_weight  identifier_exists
```

- `price` format: `280 ILS` (number + space + currency code)
- `availability`: `in stock` | `out of stock` | `preorder`
- `identifier_exists`: `no` (handmade items have no barcode/GTIN/MPN)
- `color`: empty string is valid (handmade — colour varies)
- All fields use tab delimiter; no quotes; no embedded newlines or emoji
