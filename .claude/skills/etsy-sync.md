# Skill: etsy-sync

For the working step-by-step flow see `etsy-draft.md`.

**Status as of this writing: there is no working automated Etsy publishing path.** This doc
used to describe one (via an Etsy MCP server or `etsy_connector.py`), but neither actually
works — see below. Read this before trying either route again; it'll save you the discovery
loop.

## Why the "automated" routes don't work

- **Etsy MCP** (`mcp.api.etsycloud.com`, configured in `.claude/settings.json` and
  `.continue/mcpServers/etsy.yaml`) — no `mcp__etsy__*` tools have actually shown up available
  in a session. Configured, but not confirmed reachable/functional.
- **`backend/src/connectors/etsy_connector.py`** — the browser-automation methods
  (`_create_listing_via_browser`, `_login`, `_load_or_create_session`) are all unimplemented
  stubs that `raise NotImplementedError`. It is not wired into `main.py`'s pipeline regardless
  of `config/config.yaml`'s `etsy.enabled` flag. Its config also expects
  `etsy.username`/`etsy.password` (browser-login style), while `.env` actually has
  `ETSY_API_KEY`/`ETSY_SHOP_ID` (API-key style) — the two were never made to match.

## What actually works: interactive Playwright, human-in-the-loop

Claude drives a real browser directly via the `mcp__playwright__*` tools (`browser_navigate`,
`browser_snapshot`, `browser_type`, `browser_fill_form`, `browser_file_upload`,
`browser_take_screenshot`, ...), taking a screenshot after each step so the user can see and
direct it. This is not headless/unattended — Claude cannot see or click into the browser on
its own, so the user stays in the loop for anything sensitive (confirming the account, 2FA if
it comes up).

Etsy's bot detection is real: a cold `browser_navigate` to `/signin` 403'd once in practice
before anything else happened. A saved login session for shop **LVSoulCeramics**
(`adelina.valik@gmail.com`) already exists in this machine's local Playwright browser profile,
so in practice `/signin` has redirected straight to the dashboard without needing the
password — don't assume that'll always be true; ask the user if it isn't.

### Steps (repeat per product)

1. Ask the user which product folder to list (or confirm if they already said).
2. Pull the product's data from the production host's (laptop, `10.0.0.100`) `state/products.json` (that's the live state, not
   this machine's) — `title_en`, `description_en`, `price_usd`, `images`.
3. `scp` the product's images from the laptop (`backend/downloads/{folder}/*.JPG`) to a local path
   under this repo's `.playwright-mcp/` directory — Playwright's `browser_file_upload` refuses
   paths outside the working directory, so a `/tmp` copy won't work.
4. Navigate to `https://www.etsy.com/your/shops/me/listing-editor/create`, upload the photos,
   fill title/description/category/tags/price/quantity/shipping profile.
5. **Prefer the hand-written tags from the original `description.txt`'s tag list** (e.g. "1.
   ceramic pomegranate, 2. pomegranate vase, ...") over `ai.seo_tags` in `state/products.json`
   — the LLM-generated ones are noticeably lower quality (smushed words like
   `handmadeceramic`, no spaces).
6. **Always click "Сохранить как черновик" (Save as draft), never "Опубликовать"** — the user
   reviews and publishes it themselves.
7. Delete any temporary local image copies afterward (they're just for the upload).

## If a real automated integration is wanted later

Two realistic paths, in order of preference:
1. **Etsy's official Open API v3** (the API key request was rejected as of 2026-10; OAuth2, real REST API) — would need a registered Etsy app,
   OAuth flow, and replacing the stubbed `etsy_connector.py` with real HTTP calls. This is the
   only approach Etsy's ToS actually sanctions for unattended/scripted listing creation.
2. Finishing the Playwright automation in `etsy_connector.py` for *unattended* use — explicitly
   against Etsy's Terms of Use (no scripted dashboard access outside the official API) and much
   more likely to trip bot detection with no human around to clear it. Only pursue this with
   the user's explicit informed consent to that risk.
