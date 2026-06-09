# LikaVal — Claude Code Project Guide

## Project Overview

LikaVal is an automated content publishing pipeline for a handmade ceramics brand (Lika Val, Petah Tikva, Israel). It orchestrates: **Google Drive → AI generation → multi-platform publishing** (GitHub Pages, Etsy, Facebook).

Target hardware: Raspberry Pi 4B (4 GB RAM). Keep resource usage minimal.

## Architecture

```
backend/main.py              # Orchestrator — single-run or daemon (APScheduler cron)
backend/src/
  ai_module.py               # Ollama LLM calls: EN/RU content, SEO tags, Etsy listings
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
- **AI stack:** Ollama local — vision model (llava-phi3) + text model (mistral:7b)
- **No Docker runtime changes** without confirming — container runs `python backend/main.py --daemon`

## MCP Servers

### Etsy (`mcp__etsy__*`)
Configured at `mcp.api.etsycloud.com`. Use to inspect/manage Etsy listings and shop inventory.

### Ollama on Jetson Orin Nano (`mcp__ollama-jetson__*`)
Local GPU at `http://10.0.0.20:11434`. Use for RAG and embedding-heavy tasks — offloads inference from the host machine.

**Available models on Jetson:**
| Model | Size | Best for |
|---|---|---|
| `qwen3-coder:latest` | 30.5B Q4 | Code, structured output |
| `mistral:7b-instruct-q4_K_M` | 7B | Chat, translation |
| `qwen2.5:7b-instruct-q4_K_M` | 7.6B | RAG retrieval + synthesis |
| `llava-phi3:latest` | 4B | Vision (product images) |
| `llama3.2:latest` | 3.2B | Fast summarization |
| `aya:8b` | 8B | Multilingual (EN/RU/HE) |

**RAG use cases to offload to Jetson:**
- Embedding generation for product catalog semantic search
- Retrieval + synthesis over writing_styles.yaml context
- Multilingual content generation (EN → RU via `aya:8b`)
- Batch product description generation when publishing many products

## Skills Available

- `/project:publish-product` — Run the full pipeline for a specific product folder
- `/project:generate-content` — Re-generate AI content for a product (no publishing)
- `/project:check-state` — Inspect current state of products.json and sync_log.json
- `/project:etsy-sync` — Force-sync products to Etsy via MCP or etsy_connector
- `/project:rag-query` — Run a RAG query against product catalog or writing styles using the Jetson GPU

## Environment Variables (key ones)

| Variable | Purpose |
|---|---|
| `OLLAMA_HOST` | Ollama API base URL |
| `OLLAMA_MODEL` | Vision model (default: llava-phi3) |
| `OLLAMA_TEXT_MODEL` | Text model (default: mistral:7b) |
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
