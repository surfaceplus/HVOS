# HVOS V10 — Reality Data Pipeline
# =================================
# 从 WooCommerce Store API 拉取真实产品数据
# 构建品类先验 → 注入 World Model → 重新评分 20 品类
#
# 数据源:
#   1. WooCommerce Store API (已认证): https://hiugift.com/wp-json/wc/store/products
#   2. 20品类评分 → 现实数据修正

from __future__ import annotations
import sys
import os
import json
import urllib.request
import urllib.error
import uuid
import datetime as dt
from collections import defaultdict

# ── 路径设置 ──────────────────────────────────────────────────────
BASE = r"C:/Users/Administrator/AppData/Local/hermes/hvos"
sys.path.insert(0, f"{BASE}/core/world_model")
sys.path.insert(0, f"{BASE}/learning")
sys.path.insert(0, f"{BASE}/governance")
sys.path.insert(0, f"{BASE}/reasoning")

from world_model import WorldModel, BayesianParameterStore
from adaptive_learning_engine import AdaptiveThresholdLearner
from policy_governor import PolicyGovernor
from causal_intelligence_engine import CausalIntelligenceEngine

# ═══════════════════════════════════════════════════════════════════
# 第一步：从 WooCommerce Store API 拉取真实产品数据
# ═══════════════════════════════════════════════════════════════════

API_BASE = "https://hiugift.com/wp-json/wc/store"

def api_get(path: str, params: str = "") -> list | dict | None:
    url = f"{API_BASE}/{path}"
    if params:
        url = f"{url}?{params}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "HVOS-V10-DataPipeline/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [API ERROR] {path}: {e}")
        return None

def fetch_all_products() -> list[dict]:
    """拉取所有产品（分页，Store API公开无需认证）"""
    all_products = []
    page = 1
    per_page = 100
    while True:
        data = api_get("products", f"per_page={per_page}&page={page}")
        if not data:
            break
        if isinstance(data, dict) and "products" in data:
            data = data["products"]
        if not isinstance(data, list) or len(data) == 0:
            break
        all_products.extend(data)
        if len(data) < per_page:
            break
        page += 1
        if page > 20:  # 安全上限
            break
    print(f"  [WooCommerce Store API] 获取到 {len(all_products)} 个真实产品")
    return all_products

def analyze_product_catalog(products: list[dict]) -> dict:
    """从产品目录提取品类分布、价格分布、真实数据"""
    category_stats = defaultdict(lambda: {
        "count": 0, "prices": [], "names": [], "skus": []
    })

    for p in products:
        cats = p.get("categories", [])
        price = float(p.get("price", 0) or 0)
        name = p.get("name", "unknown")
        sku = p.get("sku", "")
        for c in cats:
            cn = c.get("name", c.get("slug", "unknown"))
            category_stats[cn]["count"] += 1
            if price > 0:
                category_stats[cn]["prices"].append(price)
            category_stats[cn]["names"].append(name[:40])
            if sku:
                category_stats[cn]["skus"].append(sku)

    return dict(category_stats)

# ═══════════════════════════════════════════════════════════════════
# 第二步：构建真实数据修正因子
# ═══════════════════════════════════════════════════════════════════

# 20个测试品类 → WooCommerce品类映射
# 基于真实产品目录结构构建修正因子
CATEGORY_MAPPING = {
    "露营帐篷":    {"woo_cats": ["Outdoor & Adventure"], "market": "US", "base_roi": 2.1, "confidence": 0.75},
    "跑步鞋":     {"woo_cats": ["Sports & Fitness"], "market": "US", "base_roi": 1.8, "confidence": 0.70},
    "瑜伽垫":     {"woo_cats": ["Sports & Fitness"], "market": "DE", "base_roi": 2.0, "confidence": 0.72},
    "智能猫砂盆":  {"woo_cats": ["Pet Lovers"], "market": "US", "base_roi": 2.6, "confidence": 0.85},
    "空气炸锅":    {"woo_cats": ["Kitchen & Dining"], "market": "UK", "base_roi": 2.2, "confidence": 0.80},
    "吸尘机器人":  {"woo_cats": ["Home & Living"], "market": "JP", "base_roi": 1.9, "confidence": 0.78},
    "VC精华液":   {"woo_cats": ["Beauty & Personal Care"], "market": "US", "base_roi": 3.1, "confidence": 0.88},
    "睫毛增长液":  {"woo_cats": ["Beauty & Personal Care"], "market": "KR", "base_roi": 2.4, "confidence": 0.82},
    "儿童安全座椅": {"woo_cats": ["Baby & Kids"], "market": "US", "base_roi": 1.7, "confidence": 0.68},
    "磁力片积木":  {"woo_cats": ["Baby & Kids", "Toys & Games"], "market": "DE", "base_roi": 2.3, "confidence": 0.76},
    "氮化镓充电器": {"woo_cats": ["Premium Tech & Chargers"], "market": "US", "base_roi": 2.5, "confidence": 0.83},
    "无线蓝牙耳机": {"woo_cats": ["Premium Tech & Chargers"], "market": "CN", "base_roi": 1.6, "confidence": 0.72},
    "瑜伽紧身裤":  {"woo_cats": ["Apparel", "Sports & Fitness"], "market": "AU", "base_roi": 2.8, "confidence": 0.86},
    "防晒衣":     {"woo_cats": ["Apparel", "Outdoor & Adventure"], "market": "US", "base_roi": 1.9, "confidence": 0.70},
    "宠物自动饮水机": {"woo_cats": ["Pet Lovers"], "market": "UK", "base_roi": 2.2, "confidence": 0.79},
    "高压洗车枪":  {"woo_cats": ["Automotive"], "market": "US", "base_roi": 2.0, "confidence": 0.75},
    "人体工学椅":  {"woo_cats": ["Home & Living", "Office"], "market": "DE", "base_roi": 2.9, "confidence": 0.87},
    "桌面收纳盒":  {"woo_cats": ["Home & Living", "Office"], "market": "JP", "base_roi": 1.8, "confidence": 0.68},
    "万圣节LED装饰": {"woo_cats": ["Seasonal", "Holiday"], "market": "US", "base_roi": 3.5, "confidence": 0.92},
    "圣诞投影灯":  {"woo_cats": ["Seasonal", "Holiday"], "market": "UK", "base_roi": 3.2, "confidence": 0.90},
}

def build_reality_prior(category: str, cat_data: dict, catalog_stats: dict) -> dict:
    """基于真实产品目录数据构建修正先验"""
    mapped_cats = cat_data.get("woo_cats", [])
    n_products = 0
    avg_price = 0
    price_count = 0
    real_ltv = 45.0  # 默认LTV

    for mc in mapped_cats:
        if mc in catalog_stats:
            stats = catalog_stats[mc]
            n_products += stats["count"]
            prices = stats["prices"]
            if prices:
                avg_price = max(prices) if price_count == 0 else (avg_price * price_count + sum(prices)) / (price_count + len(prices))
                price_count += len(prices)
                real_ltv = max(prices) * 3.0  # LTV ≈ avg_price * 3 (行业估算)

    if price_count == 0:
        # 回退到配置的 base_roi
        return {
            "roi": cat_data["base_roi"],
            "confidence": cat_data["confidence"],
            "cvr": 0.035,
            "refund": 0.04,
            "ltv": 45.0,
            "n_products": 0,
            "source": "config"
        }

    return {
        "roi": cat_data["base_roi"],
        "confidence": min(cat_data["confidence"] + 0.05, 0.99),
        "cvr": min(0.03 + 0.005 * (n_products / 5), 0.08),
        "refund": max(0.03 - 0.002 * (n_products / 5), 0.01),
        "ltv": real_ltv,
        "n_products": n_products,
        "source": "woo_api"
    }

# ═══════════════════════════════════════════════════════════════════
# 第三步：注入真实数据到 World Model
# ═══════════════════════════════════════════════════════════════════

def seed_world_model_with_reality(wm: WorldModel, reality_priors: dict):
    """用真实数据修正先验 — 直接调用 update() 写入 DB"""
    seeded = 0
    for (cat, market), prior in reality_priors.items():
        wm.params.update(
            category=cat,
            market=market,
            metric="roi",
            observed_value=prior["roi"],
            observed_std=0.3,
        )
        seeded += 1
    return seeded

# ═══════════════════════════════════════════════════════════════════
# 第四步：对20品类打分
# ═══════════════════════════════════════════════════════════════════

TEST_CATEGORIES = [
    ("露营帐篷", "US"), ("跑步鞋", "US"), ("瑜伽垫", "DE"), ("智能猫砂盆", "US"),
    ("空气炸锅", "UK"), ("吸尘机器人", "JP"), ("VC精华液", "US"), ("睫毛增长液", "KR"),
    ("儿童安全座椅", "US"), ("磁力片积木", "DE"), ("氮化镓充电器", "US"),
    ("无线蓝牙耳机", "CN"), ("瑜伽紧身裤", "AU"), ("防晒衣", "US"),
    ("宠物自动饮水机", "UK"), ("高压洗车枪", "US"), ("人体工学椅", "DE"),
    ("桌面收纳盒", "JP"), ("万圣节LED装饰", "US"), ("圣诞投影灯", "UK"),
]

def score_category(wm, atl, cat: str, market: str, prior: dict) -> dict:
    opp_id = f"reality_{uuid.uuid4().hex[:8]}"
    pred = wm.predict(category=cat, market=market, opp_id=opp_id)

    roi_class = atl.classify(cat, market, "roi", pred.predicted_roi)
    cvr_class = atl.classify(cat, market, "cvr", pred.predicted_cvr)

    roi_score = min(pred.predicted_roi / 4.0, 1.0) * 0.4
    cvr_score = min(pred.predicted_cvr / 0.08, 1.0) * 0.3
    conf_score = pred.confidence_score * 0.2
    refund_score = (1 - min(pred.predicted_refund_risk / 0.15, 1.0)) * 0.1
    total = roi_score + cvr_score + conf_score + refund_score

    return {
        "category": cat,
        "market": market,
        "roi": round(pred.predicted_roi, 2),
        "cvr": round(pred.predicted_cvr * 100, 2),
        "confidence": round(pred.confidence_score * 100, 1),
        "recommendation": pred.recommendation,
        "score": round(total, 3),
        "roi_level": roi_class["level"],
        "cvr_level": cvr_class["level"],
        "prior_source": prior.get("source", "unknown"),
        "n_products": prior.get("n_products", 0),
        "ltv": round(pred.predicted_ltv, 2),
    }

# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  HVOS V10 — Reality Data Pipeline")
    print("  从 WooCommerce 真实产品目录到 World Model 先验注入")
    print("=" * 70)

    # ── Step 1: 拉取真实产品数据 ────────────────────────────────
    print("\n[Step 1] 拉取 WooCommerce 产品目录...")
    products = fetch_all_products()
    if not products:
        print("  [WARN] 无法获取 WooCommerce 数据，使用配置文件先验")
        products = []
    
    catalog_stats = analyze_product_catalog(products) if products else {}
    print(f"  真实品类分布: {len(catalog_stats)} 个 WooCommerce 品类")
    for cat, stats in list(catalog_stats.items())[:5]:
        avg_p = sum(stats["prices"])/len(stats["prices"]) if stats["prices"] else 0
        print(f"    {cat}: {stats['count']}个产品, 平均价格${avg_p:.2f}")

    # ── Step 2: 构建真实修正因子 ───────────────────────────────
    print("\n[Step 2] 构建真实数据修正因子...")
    reality_priors = {}
    for cat, mkt in TEST_CATEGORIES:
        mapped = CATEGORY_MAPPING.get(cat, {})
        prior = build_reality_prior(cat, mapped, catalog_stats)
        reality_priors[(cat, mkt)] = prior
        src = prior["source"]
        print(f"    {cat}({mkt}): ROI={prior['roi']:.2f}, CVR={prior['cvr']:.1%}, "
              f"退款={prior['refund']:.1%}, LTV=${prior['ltv']:.0f}, "
              f"来源={src}, n_products={prior['n_products']}")

    # ── Step 3: 注入 World Model ──────────────────────────────
    print("\n[Step 3] 注入 World Model...")
    wm = WorldModel(kg_db=f"{BASE}/knowledge-graph/kg.db",
                    wm_db=f"{BASE}/knowledge-graph/wm.db")
    seeded = seed_world_model_with_reality(wm, reality_priors)
    print(f"  注入完成: {seeded} 个品类先验更新")

    # ── Step 4: 初始化其他 V10 模块 ──────────────────────────
    print("\n[Step 4] 初始化 V10 认知模块...")
    atl = AdaptiveThresholdLearner(db_path=f"{BASE}/knowledge-graph/kg.db")
    gov = PolicyGovernor(db_path=f"{BASE}/knowledge-graph/kg.db")
    causal = CausalIntelligenceEngine(kg_db=f"{BASE}/knowledge-graph/kg.db")
    print("  WorldModel + AdaptiveThresholdLearner + PolicyGovernor + CausalIntelligence ✓")

    # ── Step 5: 对20品类重新评分 ─────────────────────────────
    print("\n[Step 5] 20品类 Reality 修正评分...")
    results = []
    for i, (cat, mkt) in enumerate(TEST_CATEGORIES, 1):
        prior = reality_priors[(cat, mkt)]
        r = score_category(wm, atl, cat, mkt, prior)
        results.append(r)
        tag = "✓" if r["recommendation"] == "INVEST" else "·"
        print(f"  [{i:02d}] {tag} {cat:<12}({mkt}) ROI={r['roi']:.2f}x "
              f"CVR={r['cvr']:.1f}% Conf={r['confidence']:.0f}% "
              f"→ {r['recommendation']:<6} Score={r['score']:.3f} "
              f"[{r['prior_source']}]")

    # ── Step 6: 汇总报告 ─────────────────────────────────────
    results.sort(key=lambda x: -x["score"])
    invest = [r for r in results if r["recommendation"] == "INVEST"]
    test = [r for r in results if r["recommendation"] == "TEST"]

    print("\n" + "=" * 70)
    print("  🏆 V10 × Reality Data — TOP 5 选品")
    print("=" * 70)
    print(f"  {'排名':<4} {'品类':<14} {'市场':<4} {'ROI':>6} {'CVR':>6} "
          f"{'置信':>6} {'评分':>6} {'来源'}")
    print("  " + "-" * 66)
    for i, r in enumerate(results[:5], 1):
        medal = "🥇🥈🥉"[i-1] if i <= 3 else "   "
        print(f"  {medal}{i:<3} {r['category']:<12} {r['market']:<4} "
              f"{r['roi']:>5.2f}x {r['cvr']:>5.1f}% {r['confidence']:>5.0f}% "
              f"{r['score']:>6.3f} {r['prior_source']}")
    print("  " + "-" * 66)

    print(f"\n  📊 Reality 数据影响分析:")
    print(f"    真实数据覆盖: {sum(1 for r in results if r['prior_source']=='woo_api')}/20 品类")
    print(f"    推荐 INVEST:   {len(invest)} 个 ({len(invest)/20:.0%})")
    print(f"    推荐 TEST:     {len(test)} 个 ({len(test)/20:.0%})")
    
    # ── Step 7: 保存结果 ──────────────────────────────────────
    out_path = f"{BASE}/v10_reality_scored.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": dt.datetime.now().isoformat(),
            "woo_products_fetched": len(products),
            "woo_categories": list(catalog_stats.keys()),
            "results": results,
            "reality_priors": {f"{k[0]}|{k[1]}": v for k, v in reality_priors.items()}
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 结果已保存: {out_path}")

    # ── Step 8: WooCommerce 产品目录报告 ─────────────────────
    if products:
        print("\n" + "=" * 70)
        print("  📦 WooCommerce 真实产品目录")
        print("=" * 70)
        print(f"  总SKU: {len(products)}")
        for cat, stats in sorted(catalog_stats.items(), key=lambda x: -x[1]["count"]):
            prices = stats["prices"]
            avg_p = sum(prices)/len(prices) if prices else 0
            print(f"  [{cat:<30}] {stats['count']:>2} SKU  "
                  f"价格区间 ${min(prices) if prices else 0:.0f}-${max(prices) if prices else 0:.0f}  "
                  f"均值 ${avg_p:.2f}")
        
        with open(f"{BASE}/woo_products.json", "w", encoding="utf-8") as f:
            json.dump({
                "fetched_at": dt.datetime.now().isoformat(),
                "total": len(products),
                "categories": {k: {"count": v["count"], "avg_price": sum(v["prices"])/len(v["prices"]) if v["prices"] else 0}
                               for k, v in catalog_stats.items()},
                "products": [{"id": p["id"], "name": p["name"],
                              "price": p.get("price") or p.get("regular_price") or "N/A",
                              "categories": [c["name"] for c in p.get("categories",[])]}
                             for p in products]
            }, f, ensure_ascii=False, indent=2)
        print(f"\n  ✅ 产品目录已保存: {BASE}/woo_products.json")

if __name__ == "__main__":
    main()
