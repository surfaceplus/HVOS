"""
HVOS V10 — 1688 Supply Chain Data Collector
Uses 1688-cli (npx) to collect real 1688 sourcing data.
Integrates into Reality Hub's data pipeline.
"""
import os, json, subprocess, logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from pathlib import Path

logger = logging.getLogger("hvos.collector_1688")

HUB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sourcing", "1688_hub.json")


@dataclass
class AlibabaSupplySnapshot:
    keyword: str
    total_results: int
    offers: List[Dict]
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_event_dict(self) -> dict:
        avg_price = 0.0
        if self.offers:
            prices = [o.get("price", {}).get("min", 0) or 0 for o in self.offers if o.get("price")]
            prices = [p for p in prices if p > 0]
            avg_price = sum(prices) / len(prices) if prices else 0
        
        return {
            "source": "alibaba_1688",
            "event_type": "supply_chain_snapshot",
            "category": self.keyword,
            "metric_name": "supplier_count",
            "metric_value": self.total_results,
            "metric_unit": "suppliers",
            "tags": ["1688", "sourcing", "supply_chain"],
            "raw_data": {
                "keyword": self.keyword,
                "total_results": self.total_results,
                "avg_price_cny": avg_price,
                "offer_count": len(self.offers),
            },
            "collected_at": self.collected_at,
        }


def run_1688(*args: str, timeout: int = 60) -> dict:
    """Run 1688-cli and return parsed JSON or text result"""
    try:
        result = subprocess.run(
            ["npx.cmd", "1688-cli"] + list(args),
            capture_output=True, timeout=timeout, text=True
        )
        if result.returncode == 0:
            # Try JSON parse
            try:
                return {"success": True, "data": json.loads(result.stdout) if result.stdout.strip() else {}}
            except json.JSONDecodeError:
                return {"success": True, "data": result.stdout[:2000]}
        else:
            return {"success": False, "error": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout"}
    except FileNotFoundError:
        return {"success": False, "error": "npx/1688-cli not found. Run: npm install -g 1688-cli"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_products(keyword: str, max_results: int = 10) -> AlibabaSupplySnapshot:
    """Search 1688 for products by keyword"""
    result = run_1688("search", keyword, "--max", str(max_results))
    
    if not result.get("success"):
        logger.warning(f"1688 search failed: {result.get('error')}")
        return AlibabaSupplySnapshot(keyword=keyword, total_results=0, offers=[])
    
    data = result.get("data", {})
    if isinstance(data, dict):
        offers = data.get("offers", [])
        total = data.get("total", data.get("totalBeforeFilter", len(offers)))
    elif isinstance(data, list):
        offers = data
        total = len(data)
    else:
        offers = []
        total = 0
    
    return AlibabaSupplySnapshot(keyword=keyword, total_results=total or len(offers), offers=offers)


def research_keywords(*keywords: str) -> List[AlibabaSupplySnapshot]:
    """Multi-keyword research with scoring"""
    results = []
    for kw in keywords[:5]:  # Max 5 keywords
        snap = search_products(kw, max_results=5)
        results.append(snap)
    return results


def save_to_hub(snapshots: List[AlibabaSupplySnapshot], category: str):
    """Save results to the 1688 sourcing hub file"""
    os.makedirs(os.path.dirname(HUB_FILE), exist_ok=True)
    
    hub = {}
    if os.path.exists(HUB_FILE):
        with open(HUB_FILE, 'r', encoding='utf-8') as f:
            try:
                hub = json.load(f)
            except:
                hub = {}
    
    for snap in snapshots:
        if snap.offers:
            hub[snap.keyword] = {
                "category": category,
                "keyword": snap.keyword,
                "last_checked": snap.collected_at,
                "total_results": snap.total_results,
                "candidates": [
                    {
                        "title": o.get("title", "")[:80],
                        "price": o.get("price", {}).get("min", o.get("price")),
                        "offer_id": o.get("offerId", ""),
                        "supplier": o.get("supplier", {}).get("name", "") if isinstance(o.get("supplier"), dict) else "",
                    }
                    for o in snap.offers[:5]
                ]
            }
    
    with open(HUB_FILE, 'w', encoding='utf-8') as f:
        json.dump(hub, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved {len(snapshots)} snapshots to hub")


# ===== CLI =====
if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "search"
    
    if action == "search":
        kw = " ".join(sys.argv[2:]) or "gift box"
        snap = search_products(kw)
        print(f"🔍 1688: '{kw}' — {snap.total_results} results")
        for i, o in enumerate(snap.offers[:5]):
            title = o.get("title", "")[:60]
            price = o.get("price", {})
            if isinstance(price, dict):
                price_str = f"¥{price.get('min','?')}~{price.get('max','?')}"
            else:
                price_str = f"¥{price}"
            print(f"  [{i+1}] {title}")
            print(f"       Price: {price_str}")
    
    elif action == "research":
        kws = sys.argv[2:] or ["gift box", "present box"]
        snaps = research_keywords(*kws)
        for s in snaps:
            print(f"  {s.keyword}: {s.total_results} results, {len(s.offers)} offers")
    
    elif action == "hub":
        save_to_hub([search_products("gift box")], "gift")
        print("Saved to hub")
