"""GitHub Pages connector.

Generates static HTML product pages, commits them to the main branch,
then deploys the frontend/ subdirectory to the gh-pages branch root via
`git subtree push`, which triggers GitHub Pages to update the live site.
"""

import logging
import shutil
from pathlib import Path

import git

from backend.src.config import CONFIG
from backend.src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class GitHubConnector(BaseConnector):
    name = "github"

    def __init__(self) -> None:
        self._cfg = CONFIG["github"]
        self._frontend_dir = Path(self._cfg["frontend_dir"])

    def publish(self, folder: str, product: dict) -> bool:
        """Render the product page and push to GitHub Pages."""
        self._render_product_page(folder, product)
        self._update_catalog_page()
        self._git_push()
        return True

    def _render_product_page(self, folder: str, product: dict) -> None:
        """Write an Etsy-style static HTML page for the product in EN and RU."""
        ai = product.get("ai", {})
        images = product.get("images", [])

        # Copy media assets
        asset_dir = self._frontend_dir / "assets" / "products" / folder
        asset_dir.mkdir(parents=True, exist_ok=True)
        for img_path in images:
            src = Path(img_path)
            if src.exists():
                shutil.copy2(src, asset_dir / src.name)

        # Build thumbnail + main image HTML
        def gallery_html(folder_name, imgs):
            if not imgs:
                return '<div class="gallery-main"><div style="aspect-ratio:1;background:#f5f2ef"></div></div>'
            first = Path(imgs[0]).name
            main = (
                f'<div class="gallery-main">'
                f'<img id="gallery-active" src="/assets/products/{folder_name}/{first}" alt="product">'
                f'</div>'
            )
            thumbs = "\n".join(
                f'<button class="gallery-thumb{" active" if i == 0 else ""}" '
                f'data-src="/assets/products/{folder_name}/{Path(img).name}">'
                f'<img src="/assets/products/{folder_name}/{Path(img).name}" alt="view {i+1}">'
                f'</button>'
                for i, img in enumerate(imgs)
            )
            return f'{main}\n<div class="gallery-thumbs">{thumbs}</div>'

        for lang in ("en", "ru"):
            title = ai.get(f"title_{lang}") or ai.get("title_en", folder)
            description = ai.get(f"description_{lang}") or ai.get("description_en", "")
            is_sold = product.get("status") == "sold"
            price = product.get("price_usd", "")
            tags = ai.get("seo_tags", [])
            keywords = ", ".join(tags)

            # Labels
            if lang == "en":
                site_name     = "LikaVal Ceramics"
                catalog_label = "Catalog"
                craft_note    = "Handmade · One of a kind"
                highlight_1   = ("🏺", "Handmade", "Shaped and glazed by hand")
                highlight_2   = ("📦", "Ships from Israel", "Worldwide shipping available")
                highlight_3   = ("✨", "One of a kind", "Each piece is unique")
                desc_label    = "About this piece"
                tags_label    = "Tags"
                btn_available = "Contact to Purchase"
                btn_sold      = "Sold — View similar pieces"
                btn_sold_href = f"/{lang}/catalog.html"
            else:
                site_name     = "LikaVal Керамика"
                catalog_label = "Каталог"
                craft_note    = "Ручная работа · Единственный экземпляр"
                highlight_1   = ("🏺", "Ручная работа", "Лепка и обжиг вручную")
                highlight_2   = ("📦", "Отправка из Израиля", "Доставка по всему миру")
                highlight_3   = ("✨", "Единственный экземпляр", "Каждое изделие уникально")
                desc_label    = "Об изделии"
                tags_label    = "Теги"
                btn_available = "Написать для покупки"
                btn_sold      = "Продано — Смотреть похожие"
                btn_sold_href = f"/{lang}/catalog.html"

            active_en  = ' class="active"' if lang == "en" else ""
            active_ru  = ' class="active"' if lang == "ru" else ""
            badge_html = (
                '<span class="badge sold">Sold</span>' if is_sold
                else '<span class="badge available">Available</span>'
            )
            action_html = (
                f'<a href="{btn_sold_href}" class="btn-primary disabled">{btn_sold}</a>'
                if is_sold else
                '<a href="mailto:info@likaval.com" class="btn-primary">'
                f'{btn_available}</a>\n'
                '<a href="https://www.etsy.com/shop/LikaVal" class="btn-secondary" '
                'target="_blank" rel="noopener">View on Etsy</a>'
            )
            tags_html = "".join(
                f'<span class="product-tag">{t}</span>' for t in tags
            )
            hicon1, hstrong1, hp1 = highlight_1
            hicon2, hstrong2, hp2 = highlight_2
            hicon3, hstrong3, hp3 = highlight_3

            html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {site_name}</title>
  <meta name="description" content="{description[:160]}">
  <meta name="keywords" content="{keywords}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description[:160]}">
  <meta property="og:image" content="/assets/products/{folder}/{Path(images[0]).name if images else ''}">
  <link rel="stylesheet" href="/assets/css/main.css">
</head>
<body>
  <header class="site-header">
    <a href="/{lang}/" class="site-title">{site_name}</a>
    <nav class="site-nav">
      <a href="/{lang}/catalog.html">{catalog_label}</a>
    </nav>
    <div class="lang-switcher">
      <a href="/en/products/{folder}.html"{active_en}>EN</a>
      <a href="/ru/products/{folder}.html"{active_ru}>RU</a>
    </div>
  </header>

  <nav class="breadcrumb" aria-label="breadcrumb">
    <a href="/{lang}/">{site_name}</a>
    <span class="sep">/</span>
    <a href="/{lang}/catalog.html">{catalog_label}</a>
    <span class="sep">/</span>
    <span class="current">{title}</span>
  </nav>

  <main class="product-layout">
    <div class="product-cols">

      <!-- ── Image gallery ── -->
      <div class="product-gallery" role="region" aria-label="Product images">
        {gallery_html(folder, images)}
      </div>

      <!-- ── Info panel ── -->
      <div class="product-panel">
        <a href="/{lang}/" class="product-shop-name">{site_name}</a>

        <h1 class="product-title">{title}</h1>

        <div class="product-craft">
          <span class="product-stars" aria-hidden="true">★★★★★</span>
          <span>{craft_note}</span>
        </div>

        <div class="product-price-row">
          <div class="product-price">
            <span class="currency">$</span>{price}
          </div>
          {badge_html}
        </div>

        <div class="product-actions">
          {action_html}
        </div>

        <div class="product-highlights">
          <div class="highlight-row">
            <span class="highlight-icon" aria-hidden="true">{hicon1}</span>
            <div><strong>{hstrong1}</strong><p>{hp1}</p></div>
          </div>
          <div class="highlight-row">
            <span class="highlight-icon" aria-hidden="true">{hicon2}</span>
            <div><strong>{hstrong2}</strong><p>{hp2}</p></div>
          </div>
          <div class="highlight-row">
            <span class="highlight-icon" aria-hidden="true">{hicon3}</span>
            <div><strong>{hstrong3}</strong><p>{hp3}</p></div>
          </div>
        </div>

        <div class="product-section">
          <div class="product-section-title">{desc_label}</div>
          <p class="product-description">{description}</p>
        </div>

        <div class="product-section">
          <div class="product-section-title">{tags_label}</div>
          <div class="product-tags-list">{tags_html}</div>
        </div>

      </div><!-- /product-panel -->
    </div><!-- /product-cols -->
  </main>

  <footer class="site-footer">
    <div class="footer-inner content-wide">
      <div class="footer-brand">
        <a href="/{lang}/" class="site-title">{site_name}</a>
        <p>Handmade ceramics studio based in Petah Tikva, Israel.</p>
      </div>
      <nav class="footer-nav">
        <h3>{catalog_label}</h3>
        <ul><li><a href="/{lang}/catalog.html">{catalog_label}</a></li></ul>
      </nav>
    </div>
    <p class="footer-bottom">&copy; {site_name}</p>
  </footer>

  <script>
    // Thumbnail gallery switcher
    document.querySelectorAll('.gallery-thumb').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.gallery-thumb').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('gallery-active').src = btn.dataset.src;
      }});
    }});
  </script>
</body>
</html>"""

            out_dir = self._frontend_dir / lang / "products"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{folder}.html").write_text(html, encoding="utf-8")
            logger.info("Rendered %s product page: %s/%s", lang.upper(), lang, folder)

    def _update_catalog_page(self) -> None:
        """Regenerate catalog index pages for EN and RU."""
        from backend.src.state_manager import load_products

        products = load_products()

        for lang in ("en", "ru"):
            title_key = f"title_{lang}"
            catalog_title = "Product Catalog" if lang == "en" else "Каталог товаров"
            site_name = "LikaVal Ceramics" if lang == "en" else "LikaVal Керамика"
            home_label = "Home" if lang == "en" else "Главная"

            items_html = ""
            for f_name, p in sorted(products.items(), reverse=True):
                ai = p.get("ai", {})
                title = ai.get(title_key) or ai.get("title_en", f_name)
                status_cls = "sold" if p.get("status") == "sold" else "available"
                images = p.get("images", [])
                thumb = (
                    f'<img src="/assets/products/{f_name}/{Path(images[0]).name}" '
                    f'alt="{title}" loading="lazy">'
                    if images else '<div class="no-image"></div>'
                )
                items_html += f"""
  <article class="product-card {status_cls}">
    <a href="/{lang}/products/{f_name}.html">
      {thumb}
      <h2>{title}</h2>
      <p class="price">${p.get("price_usd", "")}</p>
    </a>
  </article>"""

            active_en = 'class="active"' if lang == "en" else ""
            active_ru = 'class="active"' if lang == "ru" else ""

            catalog_html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{catalog_title} — {site_name}</title>
  <link rel="stylesheet" href="/assets/css/main.css">
</head>
<body>
  <header class="site-header">
    <a href="/{lang}/" class="site-title">{site_name}</a>
    <nav class="site-nav">
      <a href="/{lang}/">{home_label}</a>
      <a href="/{lang}/catalog.html" class="active">{catalog_title}</a>
    </nav>
    <div class="lang-switcher">
      <a href="/en/catalog.html" {active_en}>EN</a>
      <a href="/ru/catalog.html" {active_ru}>RU</a>
    </div>
  </header>
  <main>
    <h1>{catalog_title}</h1>
    <div class="product-grid">{items_html}
    </div>
  </main>
  <footer class="site-footer"><p>&copy; {site_name}</p></footer>
</body>
</html>"""

            dest = self._frontend_dir / lang / "catalog.html"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(catalog_html, encoding="utf-8")
            logger.info("Updated %s catalog page", lang.upper())

    def _git_push(self) -> None:
        """Commit all frontend changes on main, then deploy to gh-pages via worktree.

        Checks out the gh-pages branch into a temporary worktree, rsyncs the
        frontend/ directory contents there, commits, and pushes. This avoids
        git subtree history issues and works regardless of branch divergence.
        Authentication uses GITHUB_TOKEN when configured, otherwise falls back
        to git's stored credentials.
        """
        import tempfile

        repo = git.Repo(search_parent_directories=True)
        repo_root = Path(repo.working_dir)
        frontend_abs = (repo_root / self._frontend_dir).resolve()

        # Resolve relative frontend path
        if self._frontend_dir.is_absolute():
            frontend_abs = self._frontend_dir.resolve()
        else:
            frontend_abs = (repo_root / self._frontend_dir).resolve()

        # Stage and commit on main
        frontend_rel = frontend_abs.relative_to(repo_root)
        repo.index.add([str(frontend_rel)])

        if repo.index.diff("HEAD") or repo.untracked_files:
            repo.index.commit(self._cfg["commit_message"])
            logger.info("Committed frontend changes to main")
        else:
            logger.info("No frontend changes to commit on main")

        # Build authenticated remote URL if token provided
        token = self._cfg.get("token", "")
        gh_repo = self._cfg.get("repo", "")
        remote_url = (
            f"https://{token}@github.com/{gh_repo}.git"
            if token
            else repo.remote("origin").url
        )
        origin = repo.remote("origin")
        origin.set_url(remote_url)
        origin.push(refspec="HEAD:refs/heads/main")
        logger.info("Pushed main branch")

        # Deploy via worktree: checkout gh-pages, copy frontend contents, push
        pages_branch = self._cfg["pages_branch"]
        with tempfile.TemporaryDirectory(prefix="likaval_ghpages_") as tmpdir:
            # Fetch latest gh-pages
            origin.fetch(pages_branch)

            # Add worktree in detached HEAD state at origin/gh-pages
            repo.git.worktree("add", "--detach", tmpdir, f"origin/{pages_branch}")

            try:
                # Copy frontend/ contents into the worktree root (strip the frontend/ prefix)
                for src in frontend_abs.rglob("*"):
                    if not src.is_file():
                        continue
                    rel = src.relative_to(frontend_abs)
                    dest = Path(tmpdir) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

                # Commit and push from the worktree
                wt_repo = git.Repo(tmpdir)
                wt_repo.git.add(A=True)
                if wt_repo.index.diff("HEAD") or wt_repo.untracked_files:
                    wt_repo.index.commit(self._cfg["commit_message"])
                    wt_repo.remote("origin").set_url(remote_url)
                    wt_repo.remote("origin").push(
                        refspec=f"HEAD:refs/heads/{pages_branch}"
                    )
                    logger.info("Deployed frontend/ to %s branch", pages_branch)
                else:
                    logger.info("gh-pages already up to date")
            finally:
                repo.git.worktree("remove", tmpdir, "--force")
