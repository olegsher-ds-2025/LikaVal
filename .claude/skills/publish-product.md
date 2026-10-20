# Skill: publish-product

Run the full LikaVal pipeline. **There is no per-product CLI flag** — `backend/main.py` only
supports a full run (processes every pending/new product it finds) or `--daemon` (runs on the
`PUBLISH_SCHEDULE` cron inside the container). To target one specific product, that product
must be the only one in a `pending_text`/new state — there's no way to cherry-pick a folder
from the CLI.

## Usage

This runs against the **laptop's live container** (10.0.0.100), not this machine, since that's where the real
state and secrets are:

```
ssh oleg@10.0.0.100
cd /home/oleg/LikaVal
docker exec likaval-backend python backend/main.py
```

## Steps

1. Check the laptop's `state/products.json` for pending products (`pending_text: true` or new
   folders not yet in state) before running — avoid surprise re-publishes.
2. Run the command above. It: fetches new Drive folders, generates/translates AI content,
   renders and pushes GitHub Pages pages, and (new) regenerates + pushes the Google Merchant
   Center feeds automatically if anything published (see `/project:merchant-publish`).
3. Read the command's own stdout — `main.py` logs directly to console (and `logs/pipeline.log`
   inside the container), no separate log-tailing step needed.
4. Verify: `git fetch origin main gh-pages` on this machine, then check
   `origin/gh-pages:{en,ru}/products/{folder}.html` has real content (not an empty
   title/description — that's the signature of a `parse_description_file` failure, see
   CLAUDE.md's description.txt format note).
5. Etsy is **not** part of this automated flow — see `/project:etsy-sync` for how listings
   actually get created (interactive, human-in-the-loop, separate from this pipeline run).

## Notes

- Products with `_sold` suffix in folder name are marked sold — skip or list as unavailable.
- AI content is cached in `state/products.json` under the `ai` key; re-generation requires
  clearing it and resetting `pending_text: true` for that product via `upsert_product`.
- llama-server must be reachable at `LLM_VISION_URL`/`LLM_TEXT_URL` for AI steps; pipeline
  degrades gracefully if not (products with a `description.txt` can still publish without it,
  just without EN⇄RU translation for whichever language wasn't in the file).
- If you edited any `backend/` source file, the laptop's container needs a rebuild + recreate
  first (see CLAUDE.md's Deployment section) — it won't pick up source changes on its own.
