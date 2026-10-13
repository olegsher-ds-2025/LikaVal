# LikaVal — Claude Code Project Guide

## Project Overview

LikaVal is an automated content publishing pipeline for a handmade ceramics brand (Lika Val, Petah Tikva, Israel). It orchestrates: **Google Drive → AI generation → multi-platform publishing** (GitHub Pages, Etsy, Facebook).

Target hardware: Raspberry Pi 4B (4 GB RAM). Keep resource usage minimal.

## Architecture

```
backend/main.py              # Orchestrator — single-run or daemon (APScheduler cron)
backend/generate_merchant_feed.py  # Google Merchant Center TSV feed builder — called
                              #   automatically by main.py after any product publish
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
- **`description.txt` format is free-form, not the old `EN:`/`RU:` labelled spec.** In practice it's:
  a Russian block (first line = title, rest = description, optional trailing "Теги" tag list),
  then a `___` divider, then a line containing the word "ENGLISH" (wording varies —
  "ENGLISH DESCRIPTION", "ENGLISH VERSION", etc.), then the English block in the same
  shape (trailing numbered tag list instead of a "Теги" header). Files are often
  **Google Docs**, not plain-text uploads (mimeType `application/vnd.google-apps.document`)
  and use a UTF-8 BOM — `media_fetcher._download_file` exports them via Drive's
  `files.export(mimeType="text/plain")` rather than `files.get_media`, and
  `parse_description_file` reads with `utf-8-sig`. The old labelled `EN:`/`RU:` format is
  still supported as a fallback but nobody actually writes files that way.
- **Jetson translation is unreliable for titles specifically.** The Qwen2.5-3B model often
  echoes the source-language title back untranslated inside a combined title+description
  prompt (description usually translates fine). `ai_module.translate_to_russian` /
  `translate_to_english` validate the output script (Cyrillic vs Latin), retry once with a
  stricter instruction, then fall back to translating the title and description as separate,
  isolated calls (much more reliable for this size model) before giving up. Never trust a
  translation result without checking it actually changed script.

## Deployment (Raspberry Pi)

The Pi (`10.0.0.100`) runs the real production `likaval-backend` container from
`/home/oleg/LikaVal` (a separate checkout of this repo, not synced automatically with this
machine). SSH: user `oleg` (password known to the user — ask them, don't guess).

- **`docker-compose.yml` bind-mounts `.git` and `frontend/`** in addition to
  `config`/`state`/`logs`/`backend/downloads`. This is required: without it, every
  `docker compose build` bakes a fresh copy of the repo into the image, so any commit the
  *previous* container made (the pipeline auto-commits/pushes on every publish) is invisible
  to the *new* container's local git history — the next push then fails as a non-fast-forward
  rejection against `origin/main` (this happened in practice; only the `gh-pages` deploy step
  silently kept working since it fetches `origin/gh-pages` fresh each time, so the live site
  looked fine while `main` silently fell behind). With `.git` bind-mounted, container commits
  land directly in the host's real repo and stay in sync with `origin`.
- **`Dockerfile` sets `git config --global --add safe.directory /app`** — required because the
  bind-mounted `.git` is host-owned (`oleg`) but the container runs as root; without this every
  git operation fails with "detected dubious ownership".
- **`.env` and `config/gdrive_credentials.json` are gitignored secrets** — they do **not**
  arrive via `git pull`/image rebuild. They must already exist at those exact paths on the Pi
  (`/home/oleg/LikaVal/.env`, `/home/oleg/LikaVal/config/gdrive_credentials.json`) before the
  container can do anything useful; if missing or stale, copy them from this machine (`scp`).
- **Redeploying a `backend/` source change:** `backend/` is baked into the image (not
  bind-mounted), so editing `backend/src/*.py` or `backend/main.py` requires, on the Pi:
  `docker compose build likaval-backend` then `docker compose up -d --force-recreate likaval-backend`.
  A plain `docker restart` does **not** pick up source or `.env` changes.
- **Triggering a one-off run** outside the `0 2 * * *` cron: `docker exec likaval-backend
  python backend/main.py` inside the container.

## MCP Servers

### Etsy (`mcp__etsy__*`)
Configured at `mcp.api.etsycloud.com` in `.claude/settings.json` — but as of this writing has
not actually been reachable/verified in a session (no `mcp__etsy__*` tools have shown up).
`backend/src/connectors/etsy_connector.py` is an **unimplemented stub** — `_create_listing_via_browser`,
`_login`, and `_load_or_create_session` all just `raise NotImplementedError`; it is not wired
into the pipeline regardless of `etsy.enabled`. The config also expects `etsy.username`/
`etsy.password` (browser-login style) while `.env` actually has `ETSY_API_KEY`/`ETSY_SHOP_ID`
(API-key style) — the two don't match up.

**The way Etsy listings actually get created today** is a human-in-the-loop Playwright browser
session: Claude drives a real browser via the `mcp__playwright__*` tools (`browser_navigate`,
`browser_snapshot`, `browser_fill_form`, `browser_file_upload`, etc.), takes a screenshot after
each step, and the user directs/confirms — Claude cannot see or click into the browser on its
own, and Etsy's bot detection makes an unattended headless login unreliable (a fresh `/signin`
request 403'd once in practice). A saved Etsy login session for shop **LVSoulCeramics**
(`adelina.valik@gmail.com`) already exists in this machine's local Playwright browser profile,
so logins have so far just worked without needing the password. Product images live only on
the Pi (`backend/downloads/{folder}/`) — `scp` them to a local path under this repo's
`.playwright-mcp/` directory (Playwright's file-upload tool refuses paths outside the working
directory) before uploading. **Always save as draft, never publish directly**, so the user
reviews before it goes live — prefer the hand-written tags from the original `description.txt`
tag list over the LLM's auto-generated `seo_tags` (noticeably lower quality, e.g. smushed
words like `handmadeceramic`).

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
- `/project:etsy-sync` — Etsy listing status/reference doc — see the Etsy section under
  Deployment above for how listings are actually created (interactive Playwright, not this
  connector)
- `/project:rag-query` — Run a RAG query against product catalog or writing styles using the Jetson GPU
- `/project:seo-refresh` — Audit and refresh SEO metadata, titles, descriptions, hreflang, sitemap for www.likaval.com
- `/project:merchant-publish` — Manual/ad-hoc feed regen and validation walkthrough. **Note:**
  as of this writing, `backend/main.py`'s `run_pipeline()` already calls `build_merchant_feeds()`
  and pushes the result automatically after every run that publishes ≥1 product — this skill is
  now mainly for validation or forcing a regen outside a normal pipeline run, not a required
  manual step. Google Merchant Center itself has no push API on a standard account; the
  integration is a one-time **Scheduled fetch** set up in the Merchant Center UI pointing at
  `https://www.likaval.com/merchant_feed_en.tsv` and `merchant_feed_ru.tsv` (already live, since
  `frontend/merchant_feed_*.tsv` is committed and deployed like any other frontend file).

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
- **Do** verify `GITHUB_TOKEN` in `.env` actually authenticates (`GET /user` with it) before
  assuming a publish failure is something else — it has shipped as an unfilled placeholder
  (`your_github_personal_access_token`) before, which fails silently deep in the push step
- **Don't** commit `config/gdrive_credentials.json` — it's gitignored and contains secrets
- **Don't** force-push to `gh-pages` — the GitHub connector deploys via a temporary worktree,
  not `git subtree push` (the module docstring says subtree but the code doesn't use it)
- **Don't** change the product folder naming convention — state_manager keys off it
- **Don't** assume a `backend/` source edit is live on the Pi until you've rebuilt the image
  and force-recreated the container (see Deployment section) — it is not bind-mounted
- **Don't** trust `ai.title_ru`/`ai.title_en` blindly after a translation call — check the
  script actually matches the target language (see the Jetson translation note above)
