"""
HVOS V10 — Shopify Store Collector
Scrapes Shopify stores for product/competitor intelligence using shopify-spy.
Integrates into Reality Hub's data pipeline.
"""
import os, json, sys, logging, re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

logger = logging.getLogger("hvos.shopify_collector")

EVENTS_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")


@dataclass
class ShopifyProduct:
    """Normalized Shopify product data"""
    title: str
    price: float = 0.0
    compare_at_price: float = 0.0
    currency: str = "USD"
    vendor: str = ""
    product_type: str = ""
    tags: List[str] = field(default_factory=list)
    published_scope: str = "global"
    url: str = ""
    store_url: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_event_dict(self) -> dict:
        discount_pct = 0.0
        if self.compare_at_price > 0 and self.price < self.compare_at_price:
            discount_pct = (self.compare_at_price - self.price) / self.compare_at_price * 100

        return {
            "source": "shopify",
            "event_type": "product_snapshot",
            "category": self.product_type or "general",
            "metric_name": "product_count",
            "metric_value": 1.0,
            "metric_unit": "products",
            "tags": ["shopify", "product", self.vendor, self.product_type] + self.tags,
            "raw_data": {
                "title": self.title,
                "price": self.price,
                "compare_at_price": self.compare_at_price,
                "discount_pct": discount_pct,
                "vendor": self.vendor,
                "type": self.product_type,
                "tags": self.tags,
                "url": self.url,
            },
            "collected_at": self.collected_at,
        }


def scrape_store_products(store_url: str, max_products: int = 50) -> List[ShopifyProduct]:
    """
    Scrape products from a Shopify store.
    Uses shopify-spy for extraction.
    """
    try:
        import shopify_spy
    except ImportError:
        logger.warning("shopify-spy not installed. Run: uv pip install shopify-spy")
        return []

    if not store_url.startswith("http"):
        store_url = "https://" + store_url

    products = []

    try:
        # Try the simple scrape approach
        result = shopify_spy.scrape_store(store_url, max_products=max_products)
        if result and isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    products.append(_dict_to_product(item, store_url))
        elif isinstance(result, dict):
            # Single product or structured result
            products.append(_dict_to_product(result, store_url))

    except Exception as e:
        logger.warning(f"shopify-spy.scrape_store failed for {store_url}: {e}")

    # Fallback: try products endpoint directly via requests
    if not products:
        products = _scrape_via_api(store_url, max_products)

    return products


def _dict_to_product(item: dict, store_url: str) -> ShopifyProduct:
    """Convert a dict to ShopifyProduct"""
    price_val = 0.0
    price_raw = item.get("price") or item.get("price_str", "0")
    if isinstance(price_raw, str):
        price_raw = re.sub(r'[^\d.]', '', price_raw)
    try:
        price_val = float(price_raw)
    except (ValueError, TypeError):
        pass

    compare_raw = item.get("compare_at_price") or "0"
    if isinstance(compare_raw, str):
        compare_raw = re.sub(r'[^\d.]', '', compare_raw)
    compare_val = 0.0
    try:
        compare_val = float(compare_raw)
    except (ValueError, TypeError):
        pass

    tags = item.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    return ShopifyProduct(
        title=item.get("title", "Unknown"),
        price=price_val,
        compare_at_price=compare_val,
        currency=item.get("currency", "USD"),
        vendor=item.get("vendor", item.get("brand", "")),
        product_type=item.get("product_type", item.get("type", "")),
        tags=tags if isinstance(tags, list) else [],
        published_scope=item.get("published_scope", "global"),
        url=item.get("url", item.get("link", "")),
        store_url=store_url,
    )


def _scrape_via_api(store_url: str, max_products: int) -> List[ShopifyProduct]:
    """Fallback: scrape products via Shopify Storefront API (public endpoints)"""
    import urllib.request

    products = []
    # Extract store domain
    domain = store_url.replace("https://", "").replace("http://", "").rstrip("/")

    # Try to get products.json (many Shopify stores expose this publicly)
    try:
        products_url = f"https://{domain}/products.json?limit={min(max_products, 50)}"
        req = urllib.request.Request(products_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))

        for item in data.get("products", []):
            variants = item.get("variants", [])
            first_var = variants[0] if variants else {}
            price = float(first_var.get("price", 0))
            compare = float(first_var.get("compare_at_price") or 0)

            tags = [t.strip() for t in item.get("tags", "").split(",") if t.strip()]

            products.append(ShopifyProduct(
                title=item.get("title", "Unknown"),
                price=price,
                compare_at_price=compare,
                vendor=item.get("vendor", ""),
                product_type=item.get("product_type", ""),
                tags=tags,
                url=item.get("handle", ""),
                store_url=store_url,
            ))
        logger.info(f"Scraped {len(products)} products via products.json from {domain}")
    except Exception as e:
        logger.warning(f"products.json fallback failed for {domain}: {e}")

    return products


def collect_store_products(store_url: str, max_products: int = 50) -> List[dict]:
    """Main entry point — scrape and convert to event dicts"""
    raw_products = scrape_store_products(store_url, max_products)
    return [p.to_event_dict() for p in raw_products]


def collect_multiple_stores(store_urls: List[str], max_per_store: int = 20) -> List[dict]:
    """Collect products from multiple Shopify stores"""
    all_events = []
    for url in store_urls:
        try:
            events = collect_store_products(url, max_per_store)
            all_events.extend(events)
        except Exception as e:
            logger.warning(f"Failed to collect {url}: {e}")
    return all_events


# CLI
if __name__ == "__main__":
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "scrape"
    url = sys.argv[2] if len(sys.argv) > 2 else ""

    if action == "scrape":
        if not url:
            print("Usage: python shopify_collector.py scrape <store-url>")
            print("Example: python shopify_collector.py scrape allbirds.com")
            sys.exit(1)
        products = scrape_store_products(url)
        print(f"\nScraped {len(products)} products from {url}:")
        for p in products[:10]:
            discount = f" ({100*(p.compare_at_price-p.price)/p.compare_at_price:.0f}% off)" if p.compare_at_price > p.price > 0 else ""
            print(f"  ${p.price:.2f}{discount} | {p.title[:50]}")
            print(f"       Vendor: {p.vendor} | Type: {p.product_type}")

    elif action == "collect":
        if not url:
            print("Usage: python shopify_collector.py collect <store-url>")
            sys.exit(1)
        events = collect_store_products(url)
        print(f"Generated {len(events)} events")
        for e in events[:5]:
            print(f"  [{e['source']}] {e['category']}: {e['metric_value']}")

    elif action == "multi":
        urls = sys.argv[2:] or ["allbirds.com", "bombas.com", "stitchfix.com"]
        events = collect_multiple_stores(urls)
        print(f"Collected {len(events)} events from {len(urls)} stores")

    else:
        print("Usage: python shopify_collector.py [scrape|collect|multi] [url]")
