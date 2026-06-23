"""
HVOS V10 — Amazon Market Data Collector (Fast Edition)
Uses APIClaw API (categories endpoint — reliable <15s).
Other endpoints (products/market) on-demand only.
"""
import os, json, subprocess, sys, sqlite3, logging, time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger("hvos.amazon_collector")

APICLAW_SCRIPT = os.path.expanduser(r"~\AppData\Local\hermes\skills\product-intelligence\apiclaw-amazon-analysis\scripts\apiclaw.py")
EVENTS_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")


def run_apiclaw(*args, timeout=12) -> dict:
    """Run APIClaw CLI — 12s timeout (categories is fast, others fail fast on rate-limit)"""
    if not os.path.isfile(APICLAW_SCRIPT):
        return {"success": False, "error": f"APIClaw script not found"}

    api_key = os.environ.get("APICLAW_API_KEY", "")
    if not api_key:
        # Try read from config.json
        config_path = os.path.dirname(APICLAW_SCRIPT)
        cfg = os.path.join(config_path, "config.json")
        if os.path.isfile(cfg):
            try:
                with open(cfg) as f:
                    api_key = json.load(f).get("api_key", "")
            except:
                pass
        if not api_key:
            return {"success": False, "error": "APICLAW_API_KEY not set and no config.json"}

    try:
        result = subprocess.run(
            [sys.executable, APICLAW_SCRIPT] + list(args),
            capture_output=True, timeout=timeout,
            env={**os.environ, "APICLAW_API_KEY": api_key}
        )
        raw = result.stdout.decode("utf-8", errors="replace").strip()
        if result.returncode == 0 and raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"success": False, "error": f"JSON parse fail: {raw[:200]}"}
        return {"success": False, "error": f"RC={result.returncode}", "stderr": result.stderr.decode()[:200]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@dataclass
class AmazonCategory:
    """Category data from categories endpoint"""
    category_id: str
    category_name: str
    category_path: List[str]
    product_count: int = 0
    marketplace: str = "US"
    level: int = 0
    has_children: bool = False
    link: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_event_dict(self) -> dict:
        return {
            "source": "amazon",
            "event_type": "category_snapshot",
            "category": self.category_name,
            "category_id": self.category_id,
            "metric_name": "market_capacity",
            "metric_value": float(self.product_count),
            "metric_unit": "products",
            "tags": ["amazon", "market_data", self.marketplace],
            "raw_data": self.__dict__,
            "collected_at": self.collected_at,
        }


def search_categories(keyword: str) -> List[AmazonCategory]:
    """Fast category search — reliable <15s, returns productCount"""
    result = run_apiclaw("categories", "--keyword", keyword)
    if not result.get("success", False):
        if result.get("error"):
            logger.warning(f"categories failed: {result['error']}")
        return []

    data = result.get("data", [])
    if not isinstance(data, list):
        return []

    cats = []
    for cat in data:
        cid = cat.get("categoryId", "")
        if not cid:
            continue
        cats.append(AmazonCategory(
            category_id=cid,
            category_name=cat.get("categoryName", ""),
            category_path=cat.get("categoryPath", []),
            product_count=cat.get("productCount", 0),
            marketplace=cat.get("marketplace", "US"),
            level=cat.get("level", 0),
            has_children=cat.get("hasChildren", False),
            link=cat.get("link", ""),
        ))
    return cats


def get_category_detail(category_id: str) -> Optional[AmazonCategory]:
    """Get single category by ID"""
    # search_categories is fast, just do a narrow search
    result = run_apiclaw("categories", "--keyword", category_id)
    if result.get("success"):
        data = result.get("data", [])
        if isinstance(data, list) and data:
            cat = data[0]
            return AmazonCategory(
                category_id=cat.get("categoryId", ""),
                category_name=cat.get("categoryName", ""),
                category_path=cat.get("categoryPath", []),
                product_count=cat.get("productCount", 0),
                marketplace=cat.get("marketplace", "US"),
                level=cat.get("level", 0),
                has_children=cat.get("hasChildren", False),
                link=cat.get("link", ""),
            )
    return None


def collect_market_intel(keywords: List[str] = None) -> List[dict]:
    """Collect market data for multiple keywords. Returns list of event dicts."""
    if keywords is None:
        keywords = ["gift box", "party decoration", "home decor", "kitchen gadget",
                    "outdoor furniture", "pet supplies", "beauty", "fitness"]

    events = []
    for kw in keywords:
        try:
            cats = search_categories(kw)
            for c in cats:
                events.append(c.to_event_dict())
        except Exception as e:
            logger.error(f"Failed {kw}: {e}")
    return events


def compare_categories(keywords: List[str]) -> List[AmazonCategory]:
    """Compare multiple category keywords — returns best market data per keyword"""
    all_cats = []
    for kw in keywords:
        cats = search_categories(kw)
        all_cats.extend(cats)
        time.sleep(0.5)  # Be gentle on rate limits
    return all_cats


# CLI
if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "search"

    if action == "search":
        kw = " ".join(sys.argv[2:]) or "gift box"
        cats = search_categories(kw)
        print(f"\nAmazon categories for '{kw}': {len(cats)} results")
        for c in cats:
            print(f"\n  [{c.category_id}] {c.category_name}")
            print(f"     Path: {' > '.join(c.category_path)}")
            print(f"     Products: {c.product_count:,}")
            print(f"     Level: {c.level} | Children: {'Yes' if c.has_children else 'No'}")
            print(f"     Link: {c.link}")

    elif action == "compare":
        kws = sys.argv[2:] or ["gift box", "party decoration", "home decor"]
        cats = compare_categories(kws)
        print(f"\n{'='*60}")
        print(f"  Category Comparison")
        print(f"{'='*60}")
        # Sort by product_count
        cats_sorted = sorted(cats, key=lambda c: c.product_count, reverse=True)
        for c in cats_sorted:
            print(f"\n  [{c.category_id}] {c.category_name}")
            print(f"     Products: {c.product_count:,}")
            print(f"     Path: {' > '.join(c.category_path)}")
        print(f"\n  Total: {len(cats_sorted)} categories across {len(kws)} keywords")

    elif action == "collect":
        events = collect_market_intel()
        print(f"Generated {len(events)} events")
        for e in events[:5]:
            print(f"  [{e['source']}] {e['category']}: {e['metric_value']:.0f} products")

    else:
        print("Usage: amazon_collector.py [search|compare|collect] [args...]")
