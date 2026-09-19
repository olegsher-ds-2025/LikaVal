# LikaVal — Claude Code Project Guide

## Project Overview

LikaVal is an automated content publishing pipeline for a handmade ceramics brand (Lika Val, Petah Tikva, Israel). It orchestrates: **Google Drive → AI generation → multi-platform publishing** (GitHub Pages, Etsy, Facebook).

Target hardware: Raspberry Pi 4B (4 GB RAM). Keep resource usage minimal.

## Architecture

```
backend/main.py              # Orchestrator — single-run or daemon (APScheduler cron)
backend/src/
  ai_module.py               # llama.cpp LLM calls: EN/RU content, SEO tags, Etsy listings
  media_fetcher.py           # Google Drive watcher — downloads images/videos
  state_manager.py           # JSON-based persistence (no database)
  config.py                  # YAML config with ${ENV_VAR:default} resolution
  connectors/
    base.py                  # Abstract BaseConnector
    github_connector.py      # Static HTML generation + gh-pages deploy
    etsy_connector.py        # Etsy API product listings
    facebook_connector.py    # Facebook Page posts
config/
  config.yaml                # Main config (env-var templated)
  writing_styles.yaml        # AI prompt templates and Lika Val's voice/style examples
state/
  products.json              # Master product registry (keyed by folder name YYYYMMDD_PRICE)
  sync_log.json              # Pipeline run history
frontend/                    # Static multilingual site: en/ ru/ he/
```

## Key Conventions

- **Product folder naming:** `YYYYMMDD_PRICE[_sold]` — e.g. `20260215_200` = 200 ILS
- **Currency:** ILS → USD via `ILS_TO_USD_RATIO` (default 0.80)
- **State:** Zero-database — all state in `state/*.json`; Git-compatible
- **Languages:** EN (primary/USD), RU (ILS), HE (stub)
- **AI stack:** llama.cpp (`llama-server`) on the Jetson — one process per GGUF: vision model on `LLM_VISION_URL`, text model on `LLM_TEXT_URL`
- **No Docker runtime changes** without confirming — container runs `python backend/main.py --daemon`

## MCP Servers

### Etsy (`mcp__etsy__*`)
Configured at `mcp.api.etsycloud.com`. Use to inspect/manage Etsy listings and shop inventory.

### Jetson Orin Nano — llama.cpp (no MCP server; direct HTTP)
`llama-server` instances on the Jetson, reached directly via `LLM_VISION_URL`/`LLM_TEXT_URL`
(OpenAI-compatible `/v1/chat/completions`, health at `/health`). There is no llama.cpp MCP
server — `mcp-server-ollama` doesn't speak this API, so it was removed rather than swapped.
llama.cpp serves **one GGUF per process**, unlike Ollama's hot-swap — running more than the
vision + text pair concurrently needs its own port per model and enough of the Jetson's 8 GB RAM.

**GGUF models to load per llama-server instance:**
| Model | Size | Best for |
|---|---|---|
| qwen3-coder GGUF | 30.5B Q4 | Code, structured output |
| mistral-7b-instruct GGUF | 7B | Chat, translation |
| qwen2.5-7b-instruct GGUF | 7.6B | RAG retrieval + synthesis |
| llava-phi3 GGUF (`--mmproj`) | 4B | Vision (product images) — `LLM_VISION_URL` |
| llama-3.2 GGUF | 3.2B | Fast summarization |
| aya-8b GGUF | 8B | Multilingual (EN/RU/HE) |

**RAG use cases to offload to Jetson:**
- Embedding generation for product catalog semantic search (dedicated `llama-server --embedding` instance)
- Retrieval + synthesis over writing_styles.yaml context
- Multilingual content generation (EN → RU via an aya-8b GGUF)
- Batch product description generation when publishing many products

## Skills Available

- `/project:publish-product` — Run the full pipeline for a specific product folder
- `/project:generate-content` — Re-generate AI content for a product (no publishing)
- `/project:check-state` — Inspect current state of products.json and sync_log.json
- `/project:etsy-sync` — Force-sync products to Etsy via MCP or etsy_connector
- `/project:rag-query` — Run a RAG query against product catalog or writing styles using the Jetson GPU
- `/project:seo-refresh` — Audit and refresh SEO metadata, titles, descriptions, hreflang, sitemap for www.likaval.com
- `/project:merchant-publish` — Regenerate, validate, and upload EN+RU Google Merchant Center TSV feeds for Israel

## Environment Variables (key ones)

| Variable | Purpose |
|---|---|
| `LLM_VISION_URL` | Vision `llama-server` base URL (default: `http://10.0.0.20:8001`) |
| `LLM_TEXT_URL` | Text `llama-server` base URL (default: `http://10.0.0.20:8002`) |
| `GDRIVE_FOLDER_ID` | Google Drive source folder |
| `GITHUB_TOKEN` | GitHub API token for publishing |
| `GITHUB_REPO` | Target repo (owner/repo) |
| `ETSY_API_KEY` | Etsy API key |
| `ETSY_SHOP_ID` | Etsy shop ID |
| `FACEBOOK_PAGE_ID` | Facebook Page ID |
| `FACEBOOK_ACCESS_TOKEN` | Facebook Graph API token |
| `ILS_TO_USD_RATIO` | Currency conversion (default: 0.80) |
| `PUBLISH_SCHEDULE` | Cron expression (default: `0 2 * * *`) |

## Do / Don't

- **Do** edit `config/writing_styles.yaml` to tune Lika Val's voice — this drives all AI output
- **Do** check `state/products.json` before running the pipeline to avoid re-publishing
- **Don't** commit `config/gdrive_credentials.json` — it's gitignored and contains secrets
- **Don't** force-push to `gh-pages` — the GitHub connector uses `git subtree push`
- **Don't** change the product folder naming convention — state_manager keys off it
