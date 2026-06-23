#!/usr/bin/env python3
"""
HVOS V10 — Multi-Platform Product Research Bridge
统一入口：Amazon (APIClaw) + 1688 (1688-cli) + Shopify + Google Trends
对接 HVOS Opportunity Engine / Reality Layer / Knowledge Graph
"""
import os, sys, json, argparse
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HVOS_ROOT = os.path.dirname(_SCRIPT_DIR)  # scripts/ -> hvos root

# Ensure hvos root is in sys.path
if HVOS_ROOT not in sys.path:
    sys.path.insert(0, HVOS_ROOT)
os.chdir(HVOS_ROOT)

# ============================================================
# MODULE IMPORTS
# ============================================================
# Reality collectors
from reality.amazon_collector import search_categories, compare_categories, collect_market_intel
from reality.collector_1688 import search_products as search_1688, research_keywords as research_1688

# Opportunity engine
try:
    from opportunity.alpha_scorer import AlphaScorer, OpportunitySignal, score_with_real_data
    HAS_SCORER = True
except ImportError:
    HAS_SCORER = False

# Knowledge graph
try:
    from hvos_kg_engine import KnowledgeGraphEngine
    HAS_KG = True
except ImportError:
    HAS_KG = False

# Shopify spy
try:
    import shopify_spy
    HAS_SHOPIFY = True
except ImportError:
    HAS_SHOPIFY = False


def cmd_full_research(keyword: str, category_id: str = None):
    """全平台选品调研：Amazon + 1688 + 评分"""
    print(f"\n{'='*60}")
    print(f"  HVOS V10 全平台调研: {keyword}")
    print(f"{'='*60}")
    
    report = {
        "keyword": keyword,
        "timestamp": datetime.now().isoformat(),
        "amazon": {},
        "1688": {},
        "google_trends": {},
        "score": {},
    }
    
    # 1. Amazon market
    print(f"\n📦 Amazon 市场分析...")
    try:
        if category_id:
            cat_data = amazon_collect_cat(category_id, keyword)
            report["amazon"] = cat_data
            m = cat_data.get("metrics", {})
            print(f"   SKUs: {m.get('total_skus','?')}")
            print(f"   月销量: {m.get('monthly_sales','?')}")
            print(f"   FBA率: {m.get('fba_rate','?'):.1%}" if m.get('fba_rate') else "   FBA率: N/A")
            print(f"   CR10: {m.get('top10_brand_concentration','?'):.1%}" if m.get('top10_brand_concentration') else "   CR10: N/A")
        else:
            cats = search_categories(keyword)
            if cats:
                c = cats[0]
                report["amazon"]["category"] = c.category_name
                report["amazon"]["metrics"] = {
                    "total_skus": c.total_sku_count,
                    "monthly_sales": c.sample_avg_monthly_sales,
                    "fba_rate": c.sample_fba_rate,
                    "cr10": c.sample_top10_brand_sales_rate,
                }
                print(f"   {c.category_name}: {c.total_sku_count} SKUs, {c.sample_avg_monthly_sales}/mo")
    except Exception as e:
        print(f"   ❌ Amazon error: {e}")
    
    # 2. 1688 supply chain
    print(f"\n🏭 1688 供应链分析...")
    try:
        supply = search_1688(keyword)
        offers = supply.get("offers", [])
        report["1688"]["total"] = supply.get("total", len(offers))
        
        prices = []
        suppliers = set()
        for o in offers[:10]:
            p = o.get("price", {})
            if isinstance(p, dict):
                min_p = p.get("min")
                if min_p: prices.append(float(min_p))
            sup = o.get("supplier", {})
            if isinstance(sup, dict) and sup.get("name"):
                suppliers.add(sup["name"])
        
        report["1688"]["avg_price_cny"] = sum(prices)/len(prices) if prices else 0
        report["1688"]["supplier_count"] = len(suppliers)
        report["1688"]["offer_count"] = len(offers)
        
        print(f"   结果: {supply.get('total',0)} 条")
        print(f"   均价: ¥{report['1688']['avg_price_cny']:.2f}")
        print(f"   供应商: {len(suppliers)} 家")
    except Exception as e:
        print(f"   ❌ 1688 error: {e}")
    
    # 3. Alpha score
    if HAS_SCORER:
        print(f"\n📊 Alpha 评分...")
        try:
            result = score_with_real_data(keyword, category_id)
            report["score"] = {
                "alpha": result.get("alpha_score"),
                "signals": result.get("signals", 0),
                "confidence": result.get("confidence"),
            }
            print(f"   Alpha Score: {result.get('alpha_score','?')}")
            print(f"   Signals: {result.get('signals',0)}")
        except Exception as e:
            print(f"   ❌ Scorer error: {e}")
    
    # Summary
    print(f"\n{'='*60}")
    print(f"  📋 调研摘要")
    print(f"{'='*60}")
    print(f"  Amazon: {report['amazon'].get('metrics',{}).get('total_skus','?')} SKUs, "
          f"{report['amazon'].get('metrics',{}).get('monthly_sales','?')}/mo")
    print(f"  1688:   {report['1688'].get('offer_count',0)} offers, "
          f"¥{report['1688'].get('avg_price_cny',0):.2f} avg")
    if report["score"].get("alpha"):
        print(f"  评分:   {report['score']['alpha']}/100")
    
    return report


def cmd_amazon_scan(keyword: str):
    """仅扫描 Amazon 市场"""
    cats = search_categories(keyword)
    if not cats:
        print(f"No categories found for '{keyword}'")
        return
    
    print(f"\nAmazon market scan: '{keyword}'")
    for c in cats[:3]:
        print(f"\n  📦 {c.category_name}")
        print(f"     {' > '.join(c.category_path)}")
        print(f"     SKUs: {c.total_sku_count} | Sales/mo: {c.sample_avg_monthly_sales}")
        print(f"     FBA: {c.sample_fba_rate:.1%}" if c.sample_fba_rate else "")
        print(f"     CR10: {c.sample_top10_brand_sales_rate:.1%}" if c.sample_top10_brand_sales_rate else "")
        print(f"     Opp Index: {c.sample_opportunity_index:.2f}" if c.sample_opportunity_index else "")


def cmd_1688_scan(keyword: str):
    """仅扫描 1688 供应链"""
    snap = search_1688(keyword)
    offers = snap.get("offers", [])
    print(f"\n1688 supply scan: '{keyword}' — {snap.get('total',0)} total")
    for i, o in enumerate(offers[:5]):
        title = o.get("title", "")[:60]
        price = o.get("price", {})
        price_str = f"¥{price.get('min','?')}" if isinstance(price, dict) else f"¥{price}"
        print(f"  [{i+1}] {title}")
        print(f"       Price: {price_str}")


def cmd_status():
    """检查所有平台连接状态"""
    print(f"\n{'='*60}")
    print(f"  HVOS V10 Multi-Platform Bridge — 状态检查")
    print(f"{'='*60}")
    
    # Amazon
    try:
        cats = search_categories("gift box")
        print(f"  ✅ Amazon (APIClaw): {len(cats)} categories found")
    except Exception as e:
        print(f"  ❌ Amazon (APIClaw): {e}")
    
    # 1688
    try:
        snap = search_1688("gift box")
        print(f"  ✅ 1688-cli: {snap.get('total',0)} results")
    except Exception as e:
        print(f"  ❌ 1688-cli: {e}")
    
    # Shopify
    if HAS_SHOPIFY:
        print(f"  ✅ shopify-spy: installed")
    else:
        print(f"  ⚠️ shopify-spy: not installed")
    
    # Scorer
    print(f"  ✅ Alpha Scorer: {'available' if HAS_SCORER else 'N/A'}")
    
    # Env
    print(f"  ✅ APICLAW_API_KEY: {'set' if os.environ.get('APICLAW_API_KEY') else 'MISSING'}")


# ===== CLI =====
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HVOS V10 Multi-Platform Product Research Bridge")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["research", "amazon", "1688", "status"])
    parser.add_argument("keyword", nargs="?", default="gift box")
    parser.add_argument("--category", "-c", help="Amazon category ID")
    
    args = parser.parse_args()
    
    if args.action == "research":
        cmd_full_research(args.keyword, args.category)
    elif args.action == "amazon":
        cmd_amazon_scan(args.keyword)
    elif args.action == "1688":
        cmd_1688_scan(args.keyword)
    else:
        cmd_status()
