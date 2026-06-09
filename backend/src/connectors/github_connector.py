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

SITE_BASE = "https://www.likaval.com"


def _seo_title(title: str, max_chars: int = 48) -> str:
    """Truncate a long product title to fit within Google's ~60-char display limit."""
    if len(title) <= max_chars:
        return title
    return title[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:—–") + "…"


class GitHubConnector(BaseConnector):
    name = "github"

    def __init__(self) -> None:
        self._cfg = CONFIG["github"]
        self._frontend_dir = Path(self._cfg["frontend_dir"])

    def publish(self, folder: str, product: dict) -> bool:
        """Render the product page and push to GitHub Pages."""
        self._render_product_page(folder, product)
        self._update_catalog_page()
        self._update_ru_homepage()
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

        first_img_name = Path(images[0]).name if images else ""

        def gallery_html_with_alt(folder_name, imgs, alt_title):
            if not imgs:
                return '<div class="gallery-main"><div style="aspect-ratio:1;background:#f5f2ef"></div></div>'
            first = Path(imgs[0]).name
            main = (
                f'<div class="gallery-main">'
                f'<img id="gallery-active" src="/assets/products/{folder_name}/{first}"'
                f' alt="{alt_title}">'
                f'</div>'
            )
            thumbs = "\n".join(
                f'<button class="gallery-thumb{" active" if i == 0 else ""}" '
                f'data-src="/assets/products/{folder_name}/{Path(img).name}">'
                f'<img src="/assets/products/{folder_name}/{Path(img).name}"'
                f' alt="{alt_title} — фото {i+1}">'
                f'</button>'
                for i, img in enumerate(imgs)
            )
            return f'{main}\n<div class="gallery-thumbs">{thumbs}</div>'

        # Sold if status field says so, or folder name ends with _sold, or no parseable price
        import re as _re
        _folder_sold = bool(_re.search(r'_sold', folder, _re.IGNORECASE))
        is_sold = product.get("status") == "sold" or _folder_sold

        for lang in ("en", "ru"):
            title = ai.get(f"title_{lang}") or ai.get("title_en", folder)
            description = ai.get(f"description_{lang}") or ai.get("description_en", "")
            price_ils = product.get("price_ils", "")
            price_usd = product.get("price_usd", "")
            tags = ai.get("seo_tags", [])
            canonical_url = f"{SITE_BASE}/{lang}/products/{folder}.html"
            og_image_url  = f"{SITE_BASE}/assets/products/{folder}/{first_img_name}"
            schema_avail  = "https://schema.org/OutOfStock" if is_sold else "https://schema.org/InStock"
            alt_lang      = "ru" if lang == "en" else "en"
            alt_url       = f"{SITE_BASE}/{alt_lang}/products/{folder}.html"
            hreflang_html = (
                f'  <link rel="alternate" hreflang="{lang}" href="{canonical_url}">\n'
                f'  <link rel="alternate" hreflang="{alt_lang}" href="{alt_url}">\n'
                f'  <link rel="alternate" hreflang="x-default" href="{SITE_BASE}/ru/products/{folder}.html">\n'
            )
            noindex_tag = '  <meta name="robots" content="noindex, follow">\n' if is_sold else ""

            if lang == "en":
                site_name      = "LikaVal Ceramics"
                _short         = _seo_title(title)
                site_title_tag = f"{_short} | LikaVal Ceramics"
                meta_desc      = f"{_short}. Handmade ceramic art from Petah Tikva, Israel. {description[:100]}"
                og_locale      = "en_US"
                catalog_label  = "Catalog"
                craft_note     = "Handmade · One of a kind"
                highlight_1    = ("🏺", "Handmade", "Shaped and glazed by hand")
                highlight_2    = ("📦", "Ships from Israel", "Worldwide shipping available")
                highlight_3    = ("✨", "One of a kind", "Each piece is unique")
                desc_label     = "About this piece"
                tags_label     = "Tags"
                btn_available  = "Contact to Purchase"
                btn_sold       = "Sold — View similar pieces"
                btn_sold_href  = f"/{lang}/catalog.html"
                btn_etsy       = "View on Etsy"
                badge_avail    = '<span class="badge available">In Stock</span>'
                badge_sold     = '<span class="badge sold">Sold</span>'
                footer_desc    = "Handmade ceramics studio based in Petah Tikva, Israel."
                footer_nav_html = f'<h3>{catalog_label}</h3><ul><li><a href="/en/catalog.html">{catalog_label}</a></li></ul>'
                price_html     = f'<span class="currency">$</span>{price_usd}'
                keywords       = ", ".join(tags)
            else:
                site_name      = "Лика Вал | Керамика"
                _short         = _seo_title(title)
                site_title_tag = f"{_short} | Лика Вал · Керамика"
                meta_desc      = f"{_short} — авторская керамика из Петах-Тиквы. {description[:110]}"
                og_locale      = "ru_RU"
                catalog_label  = "Каталог"
                craft_note     = "Ручная работа · Единственный экземпляр"
                highlight_1    = ("🏺", "Ручная работа", "Лепка и обжиг вручную")
                highlight_2    = ("📦", "Отправка из Израиля", "Доставка по всему миру")
                highlight_3    = ("✨", "Единственный экземпляр", "Каждое изделие уникально")
                desc_label     = "Об изделии"
                tags_label     = "Теги"
                btn_available  = "Написать в WhatsApp"
                btn_sold       = "Продано — Смотреть похожие"
                btn_sold_href  = f"/{lang}/catalog.html"
                btn_etsy       = "Смотреть на Etsy"
                badge_avail    = '<span class="badge available">В наличии</span>'
                badge_sold     = '<span class="badge sold">Продано</span>'
                footer_desc    = "Авторская керамика ручной работы и мастер-классы в Петах-Тикве, Израиль."
                footer_nav_html = (
                    '<h3>Мастер-классы</h3><ul>'
                    '<li><a href="/ru/workshop-standard.html">Мастер-класс по керамике</a></li>'
                    '<li><a href="/ru/workshop-silver.html">Серебряный мастер-класс</a></li>'
                    '<li><a href="/ru/workshop-gold.html">Золотой мастер-класс</a></li>'
                    '<li><a href="/ru/kruzhok.html">Кружок керамики для взрослых</a></li>'
                    '</ul>'
                )
                price_html     = f'{price_ils} <span class="currency">₪</span>'
                keywords       = ", ".join(t.replace(" ", " ") for t in tags)

            active_en   = ' class="active"' if lang == "en" else ""
            active_ru   = ' class="active"' if lang == "ru" else ""
            badge_html  = badge_sold if is_sold else badge_avail
            _wa_msg = (
                "%D0%9C%D0%BD%D0%B5%20%D0%BF%D0%BE%D0%BD%D1%80%D0%B0%D0%B2%D0%B8%D0%BB%D0%BE%D1%81%D1%8C"
                "%20%D0%B2%D0%B0%D1%88%D0%B5%20%D0%B8%D0%B7%D0%B4%D0%B5%D0%BB%D0%B8%D0%B5%2C"
                "%20%D1%85%D0%BE%D1%87%D1%83%20%D0%BF%D0%BE%D0%B4%D1%80%D0%BE%D0%B1%D0%BD%D0%B5%D0%B5"
                "%20%D1%83%D0%B7%D0%BD%D0%B0%D1%82%D1%8C%20%D0%BE%20%D0%B2%D0%B0%D1%88%D0%B5%D0%BC"
                "%20%D1%82%D0%B2%D0%BE%D1%80%D1%87%D0%B5%D1%81%D1%82%D0%B2%D0%B5"
            )
            _wa_href = f"https://wa.me/972545308681?text={_wa_msg}" if lang == "ru" else "mailto:info@likaval.com"
            action_html = (
                f'<a href="{btn_sold_href}" class="btn-primary disabled">{btn_sold}</a>'
                if is_sold else
                f'<a href="{_wa_href}" class="btn-primary" target="_blank" rel="noopener">{btn_available}</a>\n'
                f'<a href="https://www.etsy.com/shop/LVSoulCeramics" class="btn-secondary"'
                f' target="_blank" rel="noopener">{btn_etsy}</a>'
            )
            tags_html  = "".join(f'<span class="product-tag">{t}</span>' for t in tags)
            hicon1, hstrong1, hp1 = highlight_1
            hicon2, hstrong2, hp2 = highlight_2
            hicon3, hstrong3, hp3 = highlight_3
            alt_title = f"{title} — авторская керамика, Петах-Тиква" if lang == "ru" else title

            nav_extra = (
                '\n      <a href="/ru/workshops.html">Мастер-классы</a>'
                '\n      <a href="/ru/kruzhok.html">Кружок керамики</a>'
            ) if lang == "ru" else ""

            json_ld = (
                '{{"@context":"https://schema.org","@type":"Product",'
                f'"name":"{title}",'
                f'"description":"{description[:200]}",'
                f'"image":"{og_image_url}",'
                '"brand":{{"@type":"Brand","name":"Лика Вал / Soul Ceramics"}},'
                f'"offers":{{"@type":"Offer","priceCurrency":"ILS","price":"{price_ils}",'
                f'"availability":"{schema_avail}",'
                '"seller":{{"@type":"LocalBusiness","name":"Soul Ceramics — Лика Вал",'
                '"address":{{"@type":"PostalAddress","streetAddress":"Нахалат Цви 1",'
                '"addressLocality":"Петах-Тиква","addressCountry":"IL"}}}}}}}}'
            )

            html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{site_title_tag}</title>
  <meta name="description" content="{meta_desc[:160]}">
  <meta name="keywords" content="{keywords}">
  <link rel="canonical" href="{canonical_url}">
{hreflang_html}{noindex_tag}  <meta property="og:type" content="product">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_desc[:160]}">
  <meta property="og:image" content="{og_image_url}">
  <meta property="og:url" content="{canonical_url}">
  <meta property="og:locale" content="{og_locale}">
  <script type="application/ld+json">{json_ld}</script>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="manifest" href="/site.webmanifest">
  <link rel="stylesheet" href="/assets/css/main.css">
  <!-- Event snippet for Page view conversion page -->
  <script>
    gtag('event', 'conversion', {{
        'send_to': 'AW-17964316904/HNvQCOGA1rccEOjxhvZC',
        'value': 1.0,
        'currency': 'ILS'
    }});
  </script>
</head>
<body>
  <header class="site-header">
    <a href="/{lang}/" class="site-title">{site_name}</a>
    <nav class="site-nav">
      <a href="/{lang}/catalog.html">{catalog_label}</a>{nav_extra}
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
        {gallery_html_with_alt(folder, images, alt_title)}
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
            {price_html}
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
        <p>{footer_desc}</p>
      </div>
      <nav class="footer-nav">
        {footer_nav_html}
      </nav>
    </div>
    <p class="footer-bottom">&copy; {site_name} · <a href="mailto:info@likaval.com" style="color:inherit">info@likaval.com</a></p>
  </footer>

  <!-- Google tag (gtag.js) -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=AW-17964316904"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', 'AW-17964316904');
  </script>

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
        """Regenerate Etsy-style catalog/shop pages for EN and RU."""
        from backend.src.state_manager import load_products

        products = load_products()
        total = len(products)
        available = sum(1 for p in products.values() if p.get("status") != "sold")

        for lang in ("en", "ru"):
            title_key  = f"title_{lang}"
            active_en  = ' class="active"' if lang == "en" else ""
            active_ru  = ' class="active"' if lang == "ru" else ""

            if lang == "en":
                site_name      = "LikaVal Ceramics"
                shop_tagline   = "Handmade ceramics studio · Petah Tikva, Israel"
                catalog_label  = "Catalog"
                home_label     = "Home"
                etsy_label     = "View on Etsy"
                filter_all     = "All"
                filter_avail   = "Available"
                filter_sold    = "Sold"
                count_label    = f"{available} available · {total} total"
                price_prefix   = "$"
                sold_label     = "Sold"
            else:
                site_name      = "LikaVal Керамика"
                shop_tagline   = "Авторская керамика ручной работы · Петах-Тиква, Израиль"
                catalog_label  = "Каталог"
                home_label     = "Главная"
                etsy_label     = "Смотреть на Etsy"
                filter_all     = "Все"
                filter_avail   = "Доступно"
                filter_sold    = "Продано"
                count_label    = f"{available} доступно · {total} изделий"
                price_prefix   = ""
                price_suffix   = " ₪"
                sold_label     = "Продано"

            if lang == "en":
                price_prefix = "$"
                price_suffix = ""

            cards_html = ""
            for f_name, p in sorted(products.items(), reverse=True):
                ai      = p.get("ai", {})
                title   = ai.get(title_key) or ai.get("title_en", f_name)
                status  = p.get("status", "available")
                is_sold = status == "sold"
                images  = p.get("images", [])
                price   = p.get("price_usd" if lang == "en" else "price_ils", "")
                thumb   = (
                    f'<img src="/assets/products/{f_name}/{Path(images[0]).name}" '
                    f'alt="{title}" loading="lazy">'
                    if images else '<div class="catalog-card__no-image"></div>'
                )
                sold_ribbon = f'<span class="catalog-card__sold-ribbon">{sold_label}</span>' if is_sold else ""
                data_status = "sold" if is_sold else "available"

                cards_html += f"""
      <article class="catalog-card" data-status="{data_status}">
        <a href="/{lang}/products/{f_name}.html" class="catalog-card__link">
          <div class="catalog-card__img-wrap">
            {thumb}
            {sold_ribbon}
          </div>
          <div class="catalog-card__body">
            <h2 class="catalog-card__title">{title}</h2>
            <p class="catalog-card__price">{price_prefix}{price}{price_suffix}</p>
          </div>
        </a>
      </article>"""

            _cat_canonical = f"{SITE_BASE}/{lang}/catalog.html"
            _cat_alt_lang  = "ru" if lang == "en" else "en"
            _cat_alt_url   = f"{SITE_BASE}/{_cat_alt_lang}/catalog.html"
            catalog_html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{catalog_label} — {site_name}</title>
  <meta name="description" content="{shop_tagline}">
  <link rel="canonical" href="{_cat_canonical}">
  <link rel="alternate" hreflang="{lang}" href="{_cat_canonical}">
  <link rel="alternate" hreflang="{_cat_alt_lang}" href="{_cat_alt_url}">
  <link rel="alternate" hreflang="x-default" href="{SITE_BASE}/ru/catalog.html">
  <link rel="stylesheet" href="/assets/css/main.css">
</head>
<body>
  <header class="site-header">
    <a href="/{lang}/" class="site-title">{site_name}</a>
    <nav class="site-nav">
      <a href="/{lang}/">{home_label}</a>
      <a href="/{lang}/catalog.html" class="active">{catalog_label}</a>
    </nav>
    <div class="lang-switcher">
      <a href="/en/catalog.html"{active_en}>EN</a>
      <a href="/ru/catalog.html"{active_ru}>RU</a>
    </div>
  </header>

  <!-- Shop banner -->
  <div class="shop-banner">
    <div class="shop-banner__inner content-wide">
      <div class="shop-banner__avatar" aria-hidden="true">🏺</div>
      <div class="shop-banner__info">
        <h1 class="shop-banner__name">{site_name}</h1>
        <p class="shop-banner__tagline">{shop_tagline}</p>
        <div class="shop-banner__meta">
          <span class="shop-banner__count">{count_label}</span>
          <span class="shop-banner__sep">·</span>
          <span class="shop-banner__stars" aria-label="5 stars">★★★★★</span>
        </div>
        <a href="https://www.etsy.com/shop/LVSoulCeramics"
           class="btn-outline shop-banner__etsy"
           target="_blank" rel="noopener">{etsy_label}</a>
      </div>
    </div>
  </div>

  <main class="content-wide catalog-main">
    <!-- Filter tabs -->
    <div class="catalog-filters" role="group" aria-label="Filter">
      <button class="catalog-filter active" data-filter="all">{filter_all}</button>
      <button class="catalog-filter" data-filter="available">{filter_avail}</button>
      <button class="catalog-filter" data-filter="sold">{filter_sold}</button>
    </div>

    <!-- Product grid -->
    <div class="catalog-grid" id="catalog-grid">
{cards_html}
    </div>
  </main>

  <footer class="site-footer">
    <div class="footer-inner">
      <div class="footer-brand">
        <a href="/{lang}/" class="site-title">{site_name}</a>
        <p>{shop_tagline}</p>
      </div>
      <nav class="footer-nav">
        <h3>{catalog_label}</h3>
        <ul><li><a href="/{lang}/catalog.html">{catalog_label}</a></li></ul>
      </nav>
    </div>
    <p class="footer-bottom">&copy; {site_name}</p>
  </footer>

  <script>
    // Filter tabs
    document.querySelectorAll('.catalog-filter').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.catalog-filter').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const filter = btn.dataset.filter;
        document.querySelectorAll('.catalog-card').forEach(card => {{
          card.style.display =
            (filter === 'all' || card.dataset.status === filter) ? '' : 'none';
        }});
      }});
    }});
  </script>
</body>
</html>"""

            dest = self._frontend_dir / lang / "catalog.html"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(catalog_html, encoding="utf-8")
            logger.info("Updated %s catalog page", lang.upper())

    def _update_ru_homepage(self) -> None:
        """Inject the 3 latest products into the RU homepage latest-works section."""
        from backend.src.state_manager import load_products
        import re as _re

        products = load_products()
        available = [
            (k, v) for k, v in products.items() if v.get("status") != "sold"
        ]
        latest = sorted(available, reverse=True)[:3]

        cards_html = ""
        for f_name, p in latest:
            ai     = p.get("ai", {})
            title  = ai.get("title_ru") or ai.get("title_en", f_name)
            images = p.get("images", [])
            price  = p.get("price_ils", "")
            thumb  = (
                f'<img src="/assets/products/{f_name}/{Path(images[0]).name}" '
                f'alt="{title}" loading="lazy">'
                if images else '<div class="catalog-card__no-image"></div>'
            )

            cards_html += f"""
        <article class="catalog-card" data-status="available">
          <a href="/ru/products/{f_name}.html" class="catalog-card__link">
            <div class="catalog-card__img-wrap">
              {thumb}
            </div>
            <div class="catalog-card__body">
              <h3 class="catalog-card__title">{title}</h3>
              <p class="catalog-card__price">{price} ₪</p>
            </div>
          </a>
        </article>"""

        homepage = self._frontend_dir / "ru" / "index.html"
        if not homepage.exists():
            logger.warning("RU homepage not found, skipping latest-works update")
            return

        html = homepage.read_text(encoding="utf-8")
        # Replace content between the sentinel comments / inside #latest-products div
        new_block = (
            '<div class="catalog-grid">'
            + cards_html
            + "\n      </div>"
        )
        html = _re.sub(
            r'<div class="catalog-grid">.*?</div>(\s*</section>)',
            new_block + r"\1",
            html,
            flags=_re.DOTALL,
            count=1,
        )
        homepage.write_text(html, encoding="utf-8")
        logger.info("Updated RU homepage with %d latest products", len(latest))

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
