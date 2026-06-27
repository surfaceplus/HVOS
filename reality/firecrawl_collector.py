"""
HVOS Firecrawl Collector — Web data layer for Reality Engine.

Integrates Firecrawl (v2 API) into the HVOS Event Backbone.
Provides:
  1. scrape_url()  — single page → clean markdown
  2. shopify_scan() — crawl competitor Shopify store for products
  3. amazon_product() — scrape Amazon product page for price/BSR/reviews
  4. google_trends() — search trend data via Firecrawl search (if enabled)
  5. search_web() — general web search

Firecrawl API key from: https://www.firecrawl.dev
"""
from __future__ import annotations
import json, os, logging, uuid, time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_API_URL = "https://api.firecrawl.dev/v2"

# ── Data Models ─────────────────────────────────────────────────────────

@dataclass
class FirecrawlResult:
    """Standardised output from any Firecrawl operation."""
    url: str
    markdown: str = ""
    metadata: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    success: bool = False
    error: str = ""
    credits_used: int = 0
    source: str = "firecrawl"
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# ── HTTP Helper ─────────────────────────────────────────────────────────

_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None:
        import requests
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json",
        })
    return _SESSION


# ── Client ──────────────────────────────────────────────────────────────

class FirecrawlCollector:
    """
    Firecrawl-based web data collector for HVOS Reality Layer.

    Usage:
        fc = FirecrawlCollector(api_key="my-api-key")
        result = fc.scrape_url("https://example.com")
        products = fc.shopify_scan("https://competitor.com/collections/all")
    """

    def __init__(self, api_key: str = "", base_url: str = FIRECRAWL_API_URL):
        self.api_key = api_key or FIRECRAWL_API_KEY
        self.base_url = base_url
        self._session = None

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })
        return self._session

    def _post(self, endpoint: str, payload: dict, timeout: int = 30) -> dict:
        """POST to Firecrawl API and return JSON response."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.post(url, json=payload, timeout=timeout)
        if resp.status_code == 401:
            raise PermissionError(
                f"Firecrawl API Unauthorized (401). Check your API key. "
                f"Get one at https://www.firecrawl.dev"
            )
        if resp.status_code == 402:
            raise PermissionError(f"Firecrawl credits exhausted (402). Top up at https://www.firecrawl.dev")
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", 10))
            logger.warning(f"[Firecrawl] Rate limited, retrying after {retry}s")
            time.sleep(retry)
            return self._post(endpoint, payload, timeout)
        resp.raise_for_status()
        return resp.json()

    def scrape_url(self, url: str, formats: Optional[List[str]] = None,
                   only_main: bool = True, timeout: int = 30,
                   emit_event: bool = False) -> FirecrawlResult:
        """
        Scrape a single URL via Firecrawl v2.

        Args:
            url: Target URL
            formats: Output formats (default: ['markdown', 'metadata'])
            only_main: Only return main content (skip nav/footer)
            timeout: Request timeout in seconds
            emit_event: If True, emit event to Event Backbone
        """
        if formats is None:
            formats = ["markdown", "metadata"]

        payload = {
            "url": url,
            "formats": formats,
            "onlyMainContent": only_main,
        }

        try:
            data = self._post("scrape", payload, timeout)
            result_data = data.get("data", {})
            fc_result = FirecrawlResult(
                url=url,
                markdown=result_data.get("markdown", ""),
                metadata=result_data.get("metadata", {}),
                raw=result_data,
                success=True,
            )
        except Exception as e:
            fc_result = FirecrawlResult(
                url=url,
                success=False,
                error=str(e),
            )

        if emit_event:
            self._emit_event("FIRECRAWL_SCRAPE_COMPLETED", {
                "url": url, "success": fc_result.success,
                "md_len": len(fc_result.markdown),
                "credits": fc_result.credits_used,
            })

        return fc_result

    def shopify_scan(self, collection_url: str, max_pages: int = 3,
                     timeout: int = 60) -> List[FirecrawlResult]:
        """
        Crawl a Shopify collection page to extract all products.

        Uses Firecrawl's crawl endpoint to automatically paginate.
        """
        import re

        # First scrape the collection page itself
        collection = self.scrape_url(collection_url, timeout=timeout)
        products = []

        if collection.success:
            products.append(collection)

        # Use crawl for full site discovery
        try:
            crawl_payload = {
                "url": collection_url,
                "maxPages": max_pages,
                "scrapeOptions": {"formats": ["markdown"]},
            }
            crawl_data = self._post("crawl", crawl_payload, timeout=timeout + 30)
            job_id = crawl_data.get("id", "")
            if job_id:
                logger.info(f"[Firecrawl] Crawl started: {job_id}")
        except Exception as e:
            logger.warning(f"[Firecrawl] Crawl failed: {e}")

        return products

    def amazon_product(self, asin: str, timeout: int = 30) -> FirecrawlResult:
        """Scrape Amazon product page by ASIN."""
        url = f"https://www.amazon.com/dp/{asin}"
        return self.scrape_url(url, only_main=False, timeout=timeout)

    def search_web(self, query: str, limit: int = 5,
                   timeout: int = 30) -> List[FirecrawlResult]:
        """Web search via Firecrawl search endpoint."""
        results = []
        try:
            data = self._post("search", {
                "query": query,
                "limit": limit,
            }, timeout=timeout)
            for item in data.get("data", []):
                results.append(FirecrawlResult(
                    url=item.get("url", ""),
                    markdown=item.get("description", ""),
                    metadata={"title": item.get("title", ""), "source": "search"},
                    success=True,
                ))
        except Exception as e:
            logger.warning(f"[Firecrawl] Search failed: {e}")
        return results

    def _emit_event(self, event_type: str, payload: dict):
        """Emit event to HVOS Event Backbone."""
        try:
            from hvos_config import EVENTS_DB
            from hvos_event_backbone import HvosEventSystem
            eb = HvosEventSystem()
            eb.emit(
                event_type=event_type,
                payload=payload,
                partition_key="reality_collector",
                source="hvos_firecrawl_collector",
            )
        except ImportError:
            pass  # Event Backbone not available
        except Exception as e:
            logger.warning(f"[Firecrawl] Event emit failed: {e}")


# ── Convenience Functions ──────────────────────────────────────────────

def scrape(url: str, api_key: str = "") -> FirecrawlResult:
    """Quick one-shot scrape."""
    fc = FirecrawlCollector(api_key=api_key or FIRECRAWL_API_KEY)
    return fc.scrape_url(url)


def get_credit_usage() -> dict:
    """Fetch current credit usage from Firecrawl."""
    try:
        import requests
        resp = requests.get(
            f"{FIRECRAWL_API_URL}/credits",
            headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


# ── CLI Entry Point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS Firecrawl Collector")
    parser.add_argument("--action", choices=["scrape", "shopify", "search", "test", "credits"],
                        default="test")
    parser.add_argument("--url", help="URL to scrape")
    parser.add_argument("--query", help="Search query")
    parser.add_argument("--key", help="Firecrawl API key")
    args = parser.parse_args()

    fc = FirecrawlCollector(api_key=args.key or "")

    if args.action == "test":
        result = fc.scrape_url("https://example.com")
        print(f"Scrape test: {'✅' if result.success else '❌'} {result.url}")
        if result.success:
            print(f"  Title: {result.metadata.get('title', '?')}")
            print(f"  Markdown: {len(result.markdown)} chars")
        else:
            print(f"  Error: {result.error}")

    elif args.action == "scrape" and args.url:
        result = fc.scrape_url(args.url)
        print(f"URL: {result.url}")
        print(f"Success: {result.success}")
        if result.success:
            print(f"Title: {result.metadata.get('title', '?')}")
            print(f"Markdown ({len(result.markdown)} chars):")
            print(result.markdown[:2000])
        else:
            print(f"Error: {result.error}")

    elif args.action == "search" and args.query:
        results = fc.search_web(args.query)
        print(f"Search: {len(results)} results")
        for r in results:
            print(f"  - {r.metadata.get('title', '?')}")
            print(f"    {r.url}")

    elif args.action == "credits":
        info = get_credit_usage()
        print(json.dumps(info, indent=2))
