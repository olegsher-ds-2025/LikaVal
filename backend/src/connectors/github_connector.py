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
        """Write a static HTML page for the product in EN and RU."""
        ai = product.get("ai", {})
        images = product.get("images", [])

        # Copy media assets first
        asset_dir = self._frontend_dir / "assets" / "products" / folder
        asset_dir.mkdir(parents=True, exist_ok=True)
        for img_path in images:
            src = Path(img_path)
            if src.exists():
                shutil.copy2(src, asset_dir / src.name)

        img_tags = "\n".join(
            f'<img src="/assets/products/{folder}/{Path(img).name}" '
            f'alt="{ai.get("title_en", folder)}" loading="lazy">'
            for img in images
        )
        tags_html = " ".join(
            f'<span class="tag">{t}</span>' for t in ai.get("seo_tags", [])
        )

        for lang in ("en", "ru"):
            title_key = f"title_{lang}"
            desc_key = f"description_{lang}"
            title = ai.get(title_key) or ai.get("title_en", folder)
            description = ai.get(desc_key) or ai.get("description_en", "")
            sold_badge = (
                '<span class="badge sold">Sold</span>'
                if product.get("status") == "sold"
                else '<span class="badge available">Available</span>'
            )
            price_label = "Price" if lang == "en" else "Цена"
            back_label = "← Catalog" if lang == "en" else "← Каталог"
            back_href = f"/{lang}/catalog.html"
            site_name = "LikaVal Ceramics" if lang == "en" else "LikaVal Керамика"

            active_en = 'class="active"' if lang == "en" else ""
            active_ru = 'class="active"' if lang == "ru" else ""
            keywords = ", ".join(ai.get("seo_tags", []))

            html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {site_name}</title>
  <meta name="description" content="{description[:160]}">
  <meta name="keywords" content="{keywords}">
  <link rel="stylesheet" href="/assets/css/main.css">
</head>
<body>
  <header class="site-header">
    <a href="/{lang}/" class="site-title">{site_name}</a>
    <nav class="site-nav"><a href="/{lang}/catalog.html">{back_label}</a></nav>
    <div class="lang-switcher">
      <a href="/en/products/{folder}.html" {active_en}>EN</a>
      <a href="/ru/products/{folder}.html" {active_ru}>RU</a>
    </div>
  </header>
  <main class="product-page">
    <div class="product-images">{img_tags}</div>
    <div class="product-info">
      <h1>{title}</h1>
      {sold_badge}
      <p class="price">{price_label}: ${product.get("price_usd", "")}</p>
      <p class="description">{description}</p>
      <div class="tags">{tags_html}</div>
    </div>
  </main>
  <footer class="site-footer"><p>&copy; {site_name}</p></footer>
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
