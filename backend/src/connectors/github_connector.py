"""GitHub Pages connector.

Generates static HTML product pages and commits them to the gh-pages branch
via a git push, which triggers GitHub Pages to update the live site.
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
        """Write a static HTML page for the product."""
        lang = "en"
        out_dir = self._frontend_dir / lang / "products"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{folder}.html"

        ai = product.get("ai", {})
        images = product.get("images", [])
        img_tags = "\n".join(
            f'<img src="/assets/products/{folder}/{Path(img).name}" '
            f'alt="{ai.get("title_en", folder)}" loading="lazy">'
            for img in images
        )

        tags_html = " ".join(
            f'<span class="tag">{t}</span>' for t in ai.get("seo_tags", [])
        )
        sold_badge = (
            '<span class="badge sold">Sold</span>'
            if product.get("status") == "sold"
            else '<span class="badge available">Available</span>'
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{ai.get("title_en", folder)} — LikaVal Ceramics</title>
  <meta name="description" content="{ai.get("description_en", "")}">
  <meta name="keywords" content="{", ".join(ai.get("seo_tags", []))}">
  <link rel="stylesheet" href="/assets/css/main.css">
</head>
<body>
  <header>
    <a href="/en/" class="logo">LikaVal Ceramics</a>
    <nav>
      <a href="/en/">Home</a>
      <a href="/en/catalog.html">Catalog</a>
    </nav>
  </header>
  <main class="product-page">
    <div class="product-images">{img_tags}</div>
    <div class="product-info">
      <h1>{ai.get("title_en", folder)}</h1>
      {sold_badge}
      <p class="price">${product.get("price_usd", "")}</p>
      <p class="description">{ai.get("description_en", "")}</p>
      <div class="tags">{tags_html}</div>
    </div>
  </main>
  <footer><p>&copy; LikaVal Ceramics</p></footer>
</body>
</html>"""

        dest.write_text(html, encoding="utf-8")
        logger.info("Rendered product page: %s", dest)

        # Copy media assets
        for img_path in images:
            src = Path(img_path)
            asset_dir = self._frontend_dir / "assets" / "products" / folder
            asset_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, asset_dir / src.name)

    def _update_catalog_page(self) -> None:
        """Regenerate the /en/catalog.html index page."""
        from backend.src.state_manager import load_products

        products = load_products()
        items_html = ""
        for f_name, p in sorted(products.items(), reverse=True):
            ai = p.get("ai", {})
            status_cls = "sold" if p.get("status") == "sold" else "available"
            images = p.get("images", [])
            thumb = (
                f'<img src="/assets/products/{f_name}/{Path(images[0]).name}" '
                f'alt="{ai.get("title_en", f_name)}" loading="lazy">'
                if images
                else '<div class="no-image"></div>'
            )
            items_html += f"""
  <article class="product-card {status_cls}">
    <a href="/en/products/{f_name}.html">
      {thumb}
      <h2>{ai.get("title_en", f_name)}</h2>
      <p class="price">${p.get("price_usd", "")}</p>
    </a>
  </article>"""

        catalog_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Catalog — LikaVal Ceramics</title>
  <link rel="stylesheet" href="/assets/css/main.css">
</head>
<body>
  <header>
    <a href="/en/" class="logo">LikaVal Ceramics</a>
    <nav>
      <a href="/en/">Home</a>
      <a href="/en/catalog.html" class="active">Catalog</a>
    </nav>
  </header>
  <main>
    <h1>Product Catalog</h1>
    <div class="product-grid">{items_html}
    </div>
  </main>
  <footer><p>&copy; LikaVal Ceramics</p></footer>
</body>
</html>"""

        dest = self._frontend_dir / "en" / "catalog.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(catalog_html, encoding="utf-8")
        logger.info("Updated catalog page")

    def _git_push(self) -> None:
        """Stage all frontend changes and push to GitHub Pages branch."""
        repo = git.Repo(search_parent_directories=True)
        frontend_rel = str(self._frontend_dir)
        repo.index.add([frontend_rel])

        if not repo.index.diff("HEAD"):
            logger.info("No frontend changes to commit")
            return

        repo.index.commit(self._cfg["commit_message"])

        remote_url = f"https://{self._cfg['token']}@github.com/{self._cfg['repo']}.git"
        origin = repo.remote("origin")
        origin.set_url(remote_url)
        origin.push(
            refspec=f"HEAD:refs/heads/{self._cfg['pages_branch']}"
        )
        logger.info("Pushed frontend to %s branch", self._cfg["pages_branch"])
