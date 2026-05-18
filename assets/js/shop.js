/**
 * shop.js — renders product cards from state/products.json
 * Supports category filter buttons.
 */

const isRu = document.documentElement.lang === 'ru';

const LABELS = {
  inquire: isRu ? 'Написать в WhatsApp' : 'Inquire on WhatsApp',
  sold:    isRu ? 'Продано'            : 'Sold',
};

async function loadProducts() {
  try {
    const res = await fetch('/state/products.json');
    if (!res.ok) throw new Error('not found');
    return await res.json();
  } catch {
    return {};
  }
}

function buildCard(product) {
  const wa = `https://wa.me/972545308681?text=${encodeURIComponent(
    isRu
      ? `Здравствуйте! Интересует работа: ${product.title_ru || product.title}`
      : `Hello! I'm interested in: ${product.title}`
  )}`;

  const price = product.price_usd
    ? `$${product.price_usd}`
    : product.price_ils
    ? `₪${product.price_ils}`
    : '';

  const title = isRu ? (product.title_ru || product.title) : product.title;
  const desc  = isRu ? (product.description_ru || product.description || '') : (product.description || '');
  const img   = (product.images && product.images[0]) ? product.images[0] : '';

  return `
    <article class="product-card" data-category="${product.category || 'other'}">
      <div class="product-card__image">
        ${img ? `<img src="${img}" alt="${title}" loading="lazy">` : ''}
      </div>
      <div class="product-card__body">
        <h2 class="product-card__title">${title}</h2>
        ${desc ? `<p class="product-card__desc">${desc}</p>` : ''}
        ${price ? `<p class="product-card__price">${price}</p>` : ''}
        ${product.sold
          ? `<span class="product-card__sold">${LABELS.sold}</span>`
          : `<a href="${wa}" class="product-card__cta" target="_blank" rel="noopener">${LABELS.inquire}</a>`
        }
      </div>
    </article>`;
}

async function init() {
  const grid  = document.getElementById('shop-grid');
  const empty = document.getElementById('shop-empty');
  if (!grid) return;

  const data = await loadProducts();
  const products = Object.values(data).filter(p => !p.hidden);

  if (!products.length) {
    empty.style.display = 'block';
    return;
  }

  grid.innerHTML = products.map(buildCard).join('');

  // Filter buttons
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const filter = btn.dataset.filter;
      document.querySelectorAll('.product-card').forEach(card => {
        card.style.display =
          filter === 'all' || card.dataset.category === filter ? '' : 'none';
      });
    });
  });
}

init();
