"""
HVOS V10 — 1688 采购中心 (1688-cli 驱动版)
使用 npx 1688-cli 获取真实供应链数据，替代 Jina Reader HTML 解析
"""
import os, json, subprocess, sys, logging
from datetime import datetime

logger = logging.getLogger("hvos.sourcing.1688")
BASE = os.path.dirname(os.path.abspath(__file__))
HUB_FILE = os.path.join(BASE, "1688_hub.json")


def _run_cli(*args, timeout=60):
    """调用 npx 1688-cli"""
    try:
        r = subprocess.run(["npx.cmd", "1688-cli"] + list(args),
                          capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            try:
                return {"ok": True, "data": json.loads(r.stdout) if r.stdout.strip() else {}}
            except json.JSONDecodeError:
                return {"ok": True, "data": r.stdout[:2000]}
        return {"ok": False, "error": r.stderr[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_1688(keyword: str, max_results: int = 10):
    """搜索 1688 产品 — 返回结构化结果"""
    result = _run_cli("search", keyword, "--max", str(max_results))
    if result.get("ok"):
        data = result["data"]
        if isinstance(data, dict):
            offers = data.get("offers", [])
            return {
                "keyword": keyword,
                "total": data.get("total", data.get("totalBeforeFilter", len(offers))),
                "offers": offers,
            }
        return {"keyword": keyword, "total": 0, "offers": []}
    logger.warning(f"search_1688 failed for '{keyword}': {result.get('error')}")
    return {"keyword": keyword, "total": 0, "offers": []}


def extract_products(result: dict):
    """从搜索结果提取精简产品信息"""
    products = []
    for o in result.get("offers", [])[:10]:
        price_obj = o.get("price", {})
        if isinstance(price_obj, dict):
            price = price_obj.get("min") or price_obj.get("max") or 0
        else:
            price = price_obj or 0
        
        title = o.get("title", "未知")
        offer_id = o.get("offerId", "")
        supplier = o.get("supplier", {})
        if isinstance(supplier, dict):
            supplier_name = supplier.get("name", ""),
            shop_url = supplier.get("shopUrl", "")
        else:
            supplier_name, shop_url = "", ""
        
        products.append({
            "title": title,
            "price_cny": float(price) if price else 0,
            "offer_id": offer_id,
            "url": f"https://detail.1688.com/offer/{offer_id}.html" if offer_id else "",
            "supplier": supplier_name if isinstance(supplier_name, str) else (supplier_name[0] if isinstance(supplier_name, tuple) else ""),
        })
    return products


def sync_to_hvos(products: list, category: str):
    """同步到 HVOS 采购中心"""
    os.makedirs(os.path.dirname(HUB_FILE), exist_ok=True)
    hub = {}
    if os.path.exists(HUB_FILE):
        with open(HUB_FILE, "r", encoding="utf-8") as f:
            try: hub = json.load(f)
            except: hub = {}
    
    hub[category] = {
        "category": category,
        "last_synced": datetime.now().isoformat(),
        "candidates": products[:5],
    }
    
    with open(HUB_FILE, "w", encoding="utf-8") as f:
        json.dump(hub, f, ensure_ascii=False, indent=2)
    print(f"已同步 {len(products)} 个产品到 {category}")


def load_hub():
    if os.path.exists(HUB_FILE):
        with open(HUB_FILE) as f:
            return json.load(f)
    return {}


def save_hub(hub):
    with open(HUB_FILE, "w", encoding="utf-8") as f:
        json.dump(hub, f, ensure_ascii=False, indent=2)


# ===== CLI =====
if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "search"
    if action == "search":
        kw = " ".join(sys.argv[2:]) or "gift box"
        result = search_1688(kw)
        products = extract_products(result)
        print(f"找到 {len(products)} 个产品 (共 {result['total']} 条)")
        for i, p in enumerate(products):
            print(f"  [{i+1}] ¥{p['price_cny']:.2f} | {p['title'][:50]}")
            if p['url']: print(f"       {p['url']}")
    elif action == "hub":
        hub = load_hub()
        print(json.dumps(hub, ensure_ascii=False, indent=2))
    elif action == "print":
        hub = load_hub()
        print("=" * 60)
        print("  HVOS 1688 采购中心")
        print("=" * 60)
        for name, info in hub.items():
            print(f"\n📦 {name}")
            for c in info.get("candidates", []):
                print(f"   ¥{c.get('price_cny','?'):.2f} | {c.get('title','')[:40]}")
