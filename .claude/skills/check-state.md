# Skill: check-state

Inspect the current pipeline state: products registry and sync log.

## Usage

```
/project:check-state [FOLDER_NAME]
```

- Without argument: summarize all products and their publish status per platform.
- With `FOLDER_NAME`: show full detail for that product.

## Steps

1. Read `state/products.json`.
2. For each product (or the specified one), report:
   - Folder name → price (ILS/USD), sold status
   - AI content: title EN/RU, description, tags — present or missing
   - Publish status: `github`, `etsy`, `facebook` — published / pending / error
   - Last updated timestamp
3. Read `state/sync_log.json` — show last 5 pipeline run entries, highlighting any errors.
4. Check LLM reachability: `python -c "from backend.src.ai_module import check_llm_health; print(check_llm_health())"` — report whether the Jetson's `llama-server` instances (`LLM_VISION_URL`/`LLM_TEXT_URL`) are up.

## Output Format

Present as a compact table for the summary view, full detail for single-product view.
Flag products with errors or stuck in pending state.
