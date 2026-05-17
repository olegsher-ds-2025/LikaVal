/**
 * LikaVal frontend JavaScript
 * Loads recent products from the products JSON state file and renders them.
 */

const PRODUCTS_URL = "/state/products.json";
const FEATURED_COUNT = 4;

async function loadFeaturedProducts() {
  const grid = document.getElementById("featured-grid");
  if (!grid) return;

  try {
    const resp = await fetch(PRODUCTS_URL);
    if (!resp.ok) return;
    const products = await resp.json();

    const entries = Object.entries(products)
      .sort(([a], [b]) => b.localeCompare(a)) // newest first by folder name
      .slice(0, FEATURED_COUNT);

    grid.innerHTML = entries.map(([folder, p]) => {
      const img = p.images?.[0]
        ? `<img src="/assets/products/${folder}/${p.images[0].split("/").pop()}" alt="${p.ai?.title_en || folder}" loading="lazy">`
        : `<div class="no-image"></div>`;
      const soldClass = p.status === "sold" ? " sold" : "";
      return `
        <article class="product-card${soldClass}">
          <a href="/en/products/${folder}.html">
            ${img}
            <h2>${p.ai?.title_en || folder}</h2>
            <p class="price">$${p.price_usd || ""}</p>
          </a>
        </article>`;
    }).join("");
  } catch {
    // Products JSON not yet available — silently skip
  }
}

document.addEventListener("DOMContentLoaded", loadFeaturedProducts);
