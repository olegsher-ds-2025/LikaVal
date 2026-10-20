# Skill: etsy-draft

Create an Etsy **draft** listing for one product, with up to 10 photos and 1 video, by driving
the Etsy listing editor through the `mcp__playwright__*` tools. Interactive only — see
`etsy-sync.md` for why there is no automated route (the Etsy API key request was rejected).

## Usage

```
/project:etsy-draft FOLDER_NAME
```

## Steps

1. **Data.** `ssh oleg@10.0.0.100` (key auth works; production now runs on the laptop at that
   address) and read `/home/oleg/LikaVal/state/products.json` for the folder: `ai.title_en`,
   `ai.description_en`, `price_usd`, `images`, `videos`, `ai.etsy_tags`. For products
   published before tags were stored, parse `backend/downloads/FOLDER/description.txt` with
   `media_fetcher.parse_description_file` (`tags_en`). Use the text exactly as written.
2. **Files.** `scp` the images (max 10) and the first video from
   `/home/oleg/LikaVal/backend/downloads/FOLDER/` into `.playwright-mcp/FOLDER/` — Playwright's
   file upload refuses paths outside the working directory.
3. **Video.** Etsy's uploader rejected the iPhone `.MOV` with a format error. Convert first
   (listing videos must be ≤15 s and ≤100 MB):
   `ffmpeg -i IMG.MOV -vf scale=1920:-2 -c:v libx264 -crf 23 -preset fast -c:a aac -movflags +faststart IMG.mp4`
4. **Editor.** Navigate to `https://www.etsy.com/your/shops/me/tools/listings/create` (the saved
   LVSoulCeramics login redirects to the editor; UI is in Russian).
   - Photos: click the upload tile, then `browser_file_upload` all images in one call.
   - Video: click `.wt-text-title-small:has-text("Добавить видео")`, upload the MP4, wait ~30 s
     for the thumbnail. A red "format" toast from an earlier failed attempt can linger — ignore it.
   - `browser_fill_form`: Название, Описание, Цена (USD, `price_usd`), Количество = 1.
     Do not click Etsy's "Применить вариант" title suggestion.
   - Tags: type all in the "Добавить тег" box, comma-separated, then Enter. Etsy allows 13 tags
     of ≤20 characters; cut longer ones at the last whole word that fits and tell the user.
   - Category: type slowly (`slowly: true`; plain fill doesn't trigger suggestions). Russian
     search is poor — pick the generic "Керамика" unless the user names a better one, and flag it.
   - Required attribute "Тип работы": focus the field, click the label
     "Керамика и гончарное дело" (the checkbox itself is covered by its label).
   - "Кто изготовил" / "Готовый товар" / "2020 – 2026" come pre-selected.
5. **Save as draft** with `[data-testid="save"]` ("Сохранить как черновик") — **never**
   "Опубликовать". Etsy blocks the save with a red banner naming any missing required field.
6. **Verify** at `/your/shops/me/tools/listings?state=draft&sort=update_date` (the draft should
   show price, stock and a "Видео" badge; the Active count must not change).
7. **Tell the user** what still needs a human decision before publishing: shipping profile
   ("Выбрать профиль"), category choice, ceramic type, auto-renew (defaults to on, US$0.20).
8. **Clean up** the temporary files in `.playwright-mcp/FOLDER/` and any screenshots or
   snapshots saved to the repo root (relative filenames resolve against the workspace root).
