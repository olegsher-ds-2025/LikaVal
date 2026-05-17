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
```

---

## Project Overview

LikaVal is an automated content publishing platform for a handmade ceramics brand. It consists of:

- **Static multilingual frontend** — hosted on GitHub Pages (HTML5/CSS3/vanilla JS or lightweight framework)
- **Python backend automation service** — runs on Linux (Raspberry Pi 4B target; Docker-compatible)
- **AI content generation module** — integrates with a local [Ollama](https://ollama.com) instance
- **Publishing connectors** — Etsy, Facebook, and GitHub (extensible architecture)

There is no relational database. All state and configuration is stored in human-readable, Git-compatible text files (JSON, YAML, TOML, or Markdown with frontmatter).

---

## Architecture

```
Google Drive (media source)
    └── Media Fetcher (daily cron)
            └── AI Module (Ollama via HTTP)
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

The backend communicates with Ollama via HTTP. The endpoint (IP + port) is configurable. AI generates: product titles, short descriptions, SEO tags, social media captions, Etsy listing text, and Facebook post drafts. Prompts are configurable.

### State Files

Backend state (processed folders, publish timestamps, sync status, error logs) is stored in editable text files. All state files must be Git-compatible. No SQLite, no Postgres.

---

## Configuration

Config files should use YAML, JSON, or `.env`. Key parameters:

| Parameter | Description |
|---|---|
| `ollama_host` | AI service endpoint (IP:port) |
| `gdrive_folder_id` | Google Drive media source |
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
