# Copilot Instructions for LikaVal

## Commands

```bash
# Install backend dependencies
pip install -r backend/requirements.txt

# Run pipeline once (requires .env configured)
python backend/main.py

# Run as scheduled daemon (cron from config)
python backend/main.py --daemon

# Build and run with Docker
docker compose up --build

# Run a single backend module directly
python -m backend.src.media_fetcher

# Run all tests
pytest backend/tests/

# Run a single test file
pytest backend/tests/test_media_fetcher.py

# Run a single test by name
pytest backend/tests/test_media_fetcher.py::TestParseFolderName::test_available_product
```

> **External dependency:** `ffmpeg` must be installed on the host for video frame extraction in the AI module.

---

## Project Overview

LikaVal is an automated content publishing platform for a handmade ceramics brand. It consists of:

- **Static multilingual frontend** — hosted on GitHub Pages (HTML5/CSS3/vanilla JS or lightweight framework)
- **Python backend automation service** — runs on Linux (Raspberry Pi 4B target; Docker-compatible)
- **AI content generation module** — integrates with [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`) instances on a Jetson Orin Nano
- **Publishing connectors** — Etsy, Facebook, and GitHub (extensible architecture)

There is no relational database. All state and configuration is stored in human-readable, Git-compatible text files (JSON, YAML, TOML, or Markdown with frontmatter).

---

## Architecture

```
Google Drive (media source)
    └── Media Fetcher (daily cron)
            └── AI Module (llama.cpp via HTTP)
                    └── Publishing Automation
                            ├── GitHub (git push → GitHub Pages frontend)
                            ├── Etsy connector
                            └── Facebook connector
```

State is tracked in flat files (processed folders, publish status, error logs) — no database.

Configuration is layered: base YAML/JSON files + `.env` overrides for secrets/environment-specific values.

---

## Frontend Structure

The website is static and served from GitHub Pages. Content is organized by language:

```
/en/   ← brand presentation, product catalog, sold archive, custom orders
/ru/   ← local workshops, pottery classes, events (targeting Russian speakers in Israel)
/he/   ← Hebrew content
```

Product pages include images, short videos, AI-generated descriptions, USD pricing, and availability status. Sold products remain visible for portfolio purposes.

---

## Backend Conventions

### Product Folder Naming

Media folders in Google Drive follow this strict naming convention:

```
YYYYMMDD_PRICE           ← available product
YYYYMMDD_PRICE_sold      ← sold product
```

Examples: `20260517_200`, `20250101_100_sold`

- `PRICE` is in **ILS** (Israeli New Shekel)
- The `_sold` suffix drives availability status

### Pricing

Prices are stored in ILS and converted to USD via a configurable coefficient (no live exchange rate by default). Example: `100 ILS → 80 USD`. The conversion ratio lives in config, not hardcoded.

### AI Integration

The backend communicates with llama.cpp (`llama-server`) via HTTP. The vision/text endpoints (IP + port) are configurable. AI generates: product titles, short descriptions, SEO tags, social media captions, Etsy listing text, and Facebook post drafts. Prompts are configurable.

### State Files

Backend state (processed folders, publish timestamps, sync status, error logs) is stored in editable text files. All state files must be Git-compatible. No SQLite, no Postgres.

A product is considered **already processed** when `state/products.json` contains an entry for that folder with a non-empty `ai.title_en` field. This is the check in `state_manager.is_processed()` — avoid re-generating AI content for entries that pass this check.

---

## Adding a New Publishing Connector

All connectors live in `backend/src/connectors/`. To add a new platform:

1. Subclass `BaseConnector` from `backend/src/connectors/base.py`
2. Set the `name` class attribute (used as the platform key in `state/products.json`)
3. Implement `publish(self, folder: str, product: dict) -> bool`
4. Optionally override `_is_enabled(self) -> bool` (reads from `CONFIG`)
5. Add the connector to the `connectors` list in `backend/main.py`

`safe_publish()` on the base class wraps `publish()` with error handling and logging — always call `safe_publish()` from the pipeline, never `publish()` directly.

---

## AI Module — Two-Model Setup

The AI module talks to two separate `llama-server` (llama.cpp) processes on the Jetson,
configured in `config/config.yaml`:

| Key | Default | Purpose |
|---|---|---|
| `llm.vision_url` | `http://10.0.0.20:8001` | Vision GGUF — analyzes images via `/v1/chat/completions` |
| `llm.text_url` | `http://10.0.0.20:8002` | Text-only GGUF — translation, SEO tags, social posts via `/v1/chat/completions` |

Use `_generate()` for vision tasks (passes a base64 `image_url` content part). Use `_chat()` for text tasks — it sets a `system` message to constrain language and output length. Both retry transient network failures via `_post_with_retry()` before the caller's `try/except` degrades to empty output.

Prompts are fully configurable under `llm.prompts` in `config.yaml` and support `{placeholder}` substitution at call time.

---

## Configuration

Config is loaded from `config/config.yaml` as a singleton (`from backend.src.config import CONFIG`). Values support `${ENV_VAR:default}` placeholders — the loader substitutes them from environment variables or `.env` at startup. Secrets go in `.env` (gitignored). Structure config stays in YAML (committed).

| Parameter | Description |
|---|---|
| `llm.vision_url` / `llm.text_url` | AI service endpoints (IP:port) |
| `gdrive_folder_id` / `gdrive_folder_name` | Google Drive media source (ID takes priority) |
| `ils_to_usd_ratio` | Currency conversion coefficient |
| `publish_schedule` | Cron timing for automation runs |
| Platform credentials | API keys for Etsy, Facebook, GitHub |
| Frontend output paths | Where to write generated HTML |

Secrets go in `.env` (gitignored). Structure config stays in YAML/JSON (committed).

---

## Deployment

- Primary target: **Raspberry Pi 4B**, ARM64, 4 GB RAM, Linux
- Docker: backend runs in a container with persistent volumes for config and logs
- Frontend: deployed via `git push` to the GitHub Pages branch
- Keep resource usage minimal — optimize for low CPU/RAM environments
