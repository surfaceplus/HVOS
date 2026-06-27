# HVOS V10 — WooCommerce 真实数据管道 (MySQL 直连)
# ========================================================
# 通过 SSH+VPS 直连 MySQL 获取真实数据：
#   1. 18个产品真实价格 ($11-$38)
#   2. 品类分布
#   3. 库存状态
#   4. 零订单（冷启动店铺）
#
# 数据来源: WooCommerce HPOS (wp_0dd69b_wc_orders等表)
# VPS SSH: root/QQ33945551 @ 89.117.22.200

from __future__ import annotations
import sys, os, json, uuid, datetime as dt
from collections import defaultdict

BASE = r"C:/Users/Administrator/AppData/Local/hermes/hvos"
sys.path.insert(0, f"{BASE}/core/world_model")
sys.path.insert(0, f"{BASE}/learning")
sys.path.insert(0, f"{BASE}/governance")
sys.path.insert(0, f"{BASE}/reasoning")

from world_model import WorldModel
from adaptive_learning_engine import AdaptiveThresholdLearner
from policy_governor import PolicyGovernor
from causal_intelligence_engine import CausalIntelligenceEngine

# ═══════════════════════════════════════════════════════════════════
# SSH + MySQL 连接器
# ═══════════════════════════════════════════════════════════════════

VPS_HOST = "89.117.22.200"
VPS_USER = "root"
VPS_PASS = "QQ33945551"
MYSQL_USER = "sql_hiugift_com"
MYSQL_PASS = "d441c6b635d2e8"
MYSQL_DB   = "sql_hiugift_com"
PRE        = "wp_0dd69b_"   # WooCommerce HPOS 表前缀

def ssh_mysql(query: str) -> tuple[str, str]:
    """通过 SSH 隧道执行 MySQL 查询，返回 (stdout, stderr)"""
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    cmd = (f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB} "
           "-e \"" + query.replace('"', '\\"') + "\"")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    client.close()
    return out, err

def mysql_rows(query: str) -> list[dict]:
    """执行查询并返回字典列表"""
    out, err = ssh_mysql(query)
    if err.strip():
        print(f"  [MySQL WARN] {err.strip()[:100]}")
    lines = [l for l in out.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        vals = line.split("\t")
        row = {h: v for h, v in zip(headers, vals)}
        rows.append(row)
    return rows

# ═══════════════════════════════════════════════════════════════════
# Step 1: 拉取 WooCommerce 产品真实数据
# ═══════════════════════════════════════════════════════════════════

def fetch_woo_products() -> list[dict]:
    print("\n[Step 1] 连接 VPS MySQL 拉取 WooCommerce 真实产品数据...")
    q = (f"SELECT p.ID, p.post_title,"
         f" MAX(CASE WHEN pm.meta_key='_price' THEN pm.meta_value END) as price,"
         f" MAX(CASE WHEN pm.meta_key='_regular_price' THEN pm.meta_value END) as regular_price,"
         f" MAX(CASE WHEN pm.meta_key='_sale_price' THEN pm.meta_value END) as sale_price,"
         f" MAX(CASE WHEN pm.meta_key='_sku' THEN pm.meta_value END) as sku,"
         f" MAX(CASE WHEN pm.meta_key='_stock' THEN pm.meta_value END) as stock,"
         f" MAX(CASE WHEN pm.meta_key='_weight' THEN pm.meta_value END) as weight "
         f"FROM {PRE}posts p "
         f"JOIN {PRE}postmeta pm ON pm.post_id=p.ID "
         f"WHERE p.post_type='product' AND p.post_status='publish' "
         f"GROUP BY p.ID ORDER BY p.ID")
    products = mysql_rows(q)
    print(f"  [MySQL] 获取 {len(products)} 个产品")

    # 拉取品类映射
    q_cat = (f"SELECT p.ID as product_id, GROUP_CONCAT(t.name) as cats "
             f"FROM {PRE}posts p "
             f"JOIN {PRE}term_relationships tr ON tr.object_id=p.ID "
             f"JOIN {PRE}term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id "
             f"JOIN {PRE}terms t ON t.term_id=tt.term_id "
             f"WHERE p.post_type='product' AND p.post_status='publish' "
             f"AND tt.taxonomy='product_cat' GROUP BY p.ID")
    cat_rows = mysql_rows(q_cat)
    cat_map = {r["product_id"]: r["cats"].split(",") if r["cats"] else [] for r in cat_rows}

    for p in products:
        def fv(v):
            try: return float(v) if v and v != "NULL" else 0.0
            except: return 0.0
        def iv(v):
            try: return int(v) if v and v != "NULL" else 0
            except: return 0

        p["price"] = fv(p.get("price"))
        p["regular_price"] = fv(p.get("regular_price")) or p["price"]
        p["sale_price"] = fv(p.get("sale_price")) or p["price"]
        p["categories"] = cat_map.get(p["ID"], [])
        p["weight"] = fv(p.get("weight"))
        p["stock"] = iv(p.get("stock"))
        # LTV 估算: price * 3 (dropshipping 3x markup)
        p["ltv_est"] = p["price"] * 3.0

    return products

# ═══════════════════════════════════════════════════════════════════
# Step 2: 拉取 WooCommerce 订单数据
# ═══════════════════════════════════════════════════════════════════

def fetch_woo_orders() -> dict:
    print("\n[Step 2] 拉取 WooCommerce 订单数据...")
    q = (f"SELECT status, COUNT(*) as cnt, "
         f"SUM(total_amount) as revenue, AVG(total_amount) as aov "
         f"FROM {PRE}wc_orders GROUP BY status")
    rows = mysql_rows(q)

    total_orders = 0
    total_revenue = 0.0
    order_by_status = {}
    for r in rows:
        cnt = int(r.get("cnt", 0) or 0)
        rev = float(r.get("revenue", 0) or 0)
        aov = float(r.get("aov", 0) or 0)
        status = r.get("status", "unknown")
        order_by_status[status] = {"orders": cnt, "revenue": rev, "aov": aov}
        total_orders += cnt
        total_revenue += rev

    print(f"  订单总数: {total_orders}, 总营收: ${total_revenue:.2f}")
    for s, d in order_by_status.items():
        print(f"    {s}: {d['orders']}单, ${d['revenue']:.2f}, AOV=${d['aov']:.2f}")

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "by_status": order_by_status
    }

# ═══════════════════════════════════════════════════════════════════
# Step 3: 构建品类级真实指标
# ═══════════════════════════════════════════════════════════════════

CATEGORY_MAPPING = {
    # 20品类 → WooCommerce品类 + 市场
    "露营帐篷":          {"woo_cats": ["Outdoor & Adventure"], "market": "US"},
    "跑步鞋":            {"woo_cats": ["Sports & Fitness"], "market": "US"},
    "瑜伽垫":            {"woo_cats": ["Sports & Fitness"], "market": "DE"},
    "智能猫砂盆":         {"woo_cats": ["Pet Lovers"], "market": "US"},
    "空气炸锅":           {"woo_cats": ["Kitchen & Dining"], "market": "UK"},
    "吸尘机器人":         {"woo_cats": ["Home & Living"], "market": "JP"},
    "VC精华液":          {"woo_cats": ["Beauty & Personal Care"], "market": "US"},
    "睫毛增长液":          {"woo_cats": ["Beauty & Personal Care"], "market": "KR"},
    "儿童安全座椅":        {"woo_cats": ["Baby & Kids"], "market": "US"},
    "磁力片积木":          {"woo_cats": ["Baby & Kids", "Toys & Games"], "market": "DE"},
    "氮化镓充电器":        {"woo_cats": ["Premium Tech & Chargers"], "market": "US"},
    "无线蓝牙耳机":        {"woo_cats": ["Premium Tech & Chargers"], "market": "CN"},
    "瑜伽紧身裤":          {"woo_cats": ["Apparel", "Sports & Fitness"], "market": "AU"},
    "防晒衣":             {"woo_cats": ["Apparel", "Outdoor & Adventure"], "market": "US"},
    "宠物自动饮水机":       {"woo_cats": ["Pet Lovers"], "market": "UK"},
    "高压洗车枪":          {"woo_cats": ["Automotive"], "market": "US"},
    "人体工学椅":          {"woo_cats": ["Home & Living", "Office"], "market": "DE"},
    "桌面收纳盒":          {"woo_cats": ["Home & Living", "Office"], "market": "JP"},
    "万圣节LED装饰":       {"woo_cats": ["Seasonal", "Holiday"], "market": "US"},
    "圣诞投影灯":          {"woo_cats": ["Seasonal", "Holiday"], "market": "UK"},
}

def build_category_metrics(products: list[dict]) -> dict:
    """基于真实产品价格构建品类级 ROI/CVR/LTV 先验"""
    cat_stats = defaultdict(list)
    for p in products:
        for c in p.get("categories", []):
            cat_stats[c].append(p)

    metrics = {}
    # Dropshipping 行业基线
    base_cvr = 0.025   # 2.5% conversion rate
    base_refund = 0.04 # 4% refund rate

    for cat, prods in cat_stats.items():
        prices = [p["price"] for p in prods if p["price"] > 0]
        if not prices:
            continue
        avg_price = sum(prices) / len(prices)
        ltv = avg_price * 3.0  # dropshipping LTV = price * 3
        # ROI 估算: (selling_price - cost) / cost
        # 假设 cost ≈ price * 0.33 (3x markup), revenue = cost * 2.5 = price * 0.825
        roi = 2.5  # 行业典型 ROI
        metrics[cat] = {
            "n_products": len(prods),
            "avg_price": avg_price,
            "price_range": (min(prices), max(prices)),
            "ltv": ltv,
            "roi": roi,
            "cvr": base_cvr,
            "refund": base_refund,
        }
        print(f"  [{cat}]: {len(prods)} SKU, 价格区间 ${min(prices):.0f}-${max(prices):.0f}, "
              f"均价${avg_price:.2f}, LTV估算${ltv:.0f}")

    return dict(metrics)

# ═══════════════════════════════════════════════════════════════════
# Step 4: 用真实数据更新 World Model
# ═══════════════════════════════════════════════════════════════════

def seed_world_model(wm: WorldModel, cat_metrics: dict):
    print("\n[Step 4b] 用真实价格/LTV 数据更新 World Model 先验...")
    # WooCommerce Dropshipping 基线
    # 售价$11-$38, 成本≈售价*0.33, ROI≈(售价-成本)/成本
    woo_default = {
        "roi": 2.5, "ltv": 45.0, "cvr": 0.03, "refund_rate": 0.04
    }
    # 无 WooCommerce 对应品类时的行业估计
    industry_roi = {
        "露营帐篷": 2.1, "跑步鞋": 1.8, "瑜伽垫": 2.0, "睫毛增长液": 2.4,
        "儿童安全座椅": 1.7, "磁力片积木": 2.3, "防晒衣": 1.9,
        "高压洗车枪": 2.0, "桌面收纳盒": 1.8,
        "万圣节LED装饰": 3.5, "圣诞投影灯": 3.2,  # 季节品高ROI
        "氮化镓充电器": 2.5, "VC精华液": 3.1,
        "智能猫砂盆": 2.6, "空气炸锅": 2.2, "吸尘机器人": 1.9,
        "瑜伽紧身裤": 2.8, "宠物自动饮水机": 2.2, "人体工学椅": 2.9,
        "无线蓝牙耳机": 1.6,
    }

    seeded = 0
    for cat_name, cfg in CATEGORY_MAPPING.items():
        woo_cats = cfg.get("woo_cats", [])
        market = cfg.get("market", "US")

        # 聚合 WooCommerce 真实价格
        n_prods, price_sum, ltv = 0, 0.0, 45.0
        for wc in woo_cats:
            if wc in cat_metrics:
                m = cat_metrics[wc]
                n = m["n_products"]
                price_sum += m["avg_price"] * n
                n_prods += n
                ltv = m["ltv"]

        avg_price = price_sum / n_prods if n_prods > 0 else 0

        # ROI: WooCommerce 价格估算
        if n_prods > 0:
            roi = round(2.0 + (avg_price / 25.0) * 1.0, 1)
            roi = max(1.5, min(roi, 4.0))
        else:
            roi = industry_roi.get(cat_name, 2.0)

        # CVR: 基于品类特性
        cvr_map = {
            "VC精华液": 0.045, "睫毛增长液": 0.040, "智能猫砂盆": 0.042,
            "氮化镓充电器": 0.038, "无线蓝牙耳机": 0.030, "空气炸锅": 0.035,
            "瑜伽紧身裤": 0.040, "万圣节LED装饰": 0.055, "圣诞投影灯": 0.050,
            "宠物自动饮水机": 0.036, "人体工学椅": 0.032, "露营帐篷": 0.028,
        }
        cvr = cvr_map.get(cat_name, 0.030)

        # 退款率: 基于品类风险
        refund_map = {
            "VC精华液": 0.06, "睫毛增长液": 0.07, "空气炸锅": 0.05,
            "无线蓝牙耳机": 0.04, "智能猫砂盆": 0.03, "人体工学椅": 0.04,
            "万圣节LED装饰": 0.02, "圣诞投影灯": 0.02, "氮化镓充电器": 0.03,
        }
        refund = refund_map.get(cat_name, 0.04)

        # 注入所有指标
        for metric, value, std in [
            ("roi", roi, 0.3),
            ("cvr", cvr, 0.005),
            ("ltv", ltv, 10.0),
            ("refund_rate", refund, 0.01),
        ]:
            wm.params.update(cat_name, market, metric, value, std)
            seeded += 1

    print(f"  注入完成: {seeded} 个指标更新（{len(CATEGORY_MAPPING)}品类 × 4指标）")

# ═══════════════════════════════════════════════════════════════════
# Step 5: 20品类评分
# ═══════════════════════════════════════════════════════════════════

TEST_CATEGORIES = list(CATEGORY_MAPPING.items())

def score_category(wm, atl, cat_name: str, market: str) -> dict:
    opp_id = f"woo_{uuid.uuid4().hex[:8]}"
    pred = wm.predict(category=cat_name, market=market, opp_id=opp_id)

    roi_class = atl.classify(cat_name, market, "roi", pred.predicted_roi)
    cvr_class = atl.classify(cat_name, market, "cvr", pred.predicted_cvr)

    roi_score  = min(pred.predicted_roi / 4.0, 1.0) * 0.4
    cvr_score  = min(pred.predicted_cvr / 0.08, 1.0) * 0.3
    conf_score = pred.confidence_score * 0.2
    ref_score  = (1 - min(pred.predicted_refund_risk / 0.15, 1.0)) * 0.1
    total = roi_score + cvr_score + conf_score + ref_score

    return {
        "category": cat_name,
        "market": market,
        "roi": round(pred.predicted_roi, 2),
        "cvr": round(pred.predicted_cvr * 100, 2),
        "confidence": round(pred.confidence_score * 100, 1),
        "ltv": round(pred.predicted_ltv, 2),
        "refund": round(pred.predicted_refund_risk * 100, 2),
        "recommendation": pred.recommendation,
        "score": round(total, 3),
        "roi_level": roi_class["level"],
        "roi_percentile": roi_class["percentile"],
    }

# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  HVOS V10 × WooCommerce 真实数据管道")
    print("  SSH+VPS MySQL 直连 | WooCommerce HPOS | 真实价格数据")
    print("=" * 70)

    # ── Step 1: 产品数据 ──────────────────────────────────────
    products = fetch_woo_products()

    # 打印产品表
    print("\n  📦 WooCommerce 真实产品目录:")
    print(f"  {'产品名':<45} {'售价':>6} {'原价':>6} {'品类'}")
    print("  " + "-" * 85)
    for p in products:
        sale = "⚡" if p["sale_price"] < p["regular_price"] else "  "
        cats = ",".join(p.get("categories", [])[:2])
        print(f"  {sale}{p['post_title'][:42]:<42} ${p['price']:>5.2f} ${p['regular_price']:>5.2f}  {cats}")

    # ── Step 2: 订单数据 ──────────────────────────────────────
    order_data = fetch_woo_orders()

    # ── Step 3: 品类指标 ──────────────────────────────────────
    print("\n[Step 3] 从真实价格构建品类级指标...")
    cat_metrics = build_category_metrics(products)

    # ── Step 4: World Model ──────────────────────────────────
    print("\n[Step 4] 初始化 V10 模块并注入真实数据...")
    wm = WorldModel(
        kg_db=f"{BASE}/knowledge_graph/kg.db",
        wm_db=f"{BASE}/knowledge_graph/wm.db"
    )
    atl = AdaptiveThresholdLearner(db_path=f"{BASE}/knowledge_graph/kg.db")
    gov = PolicyGovernor(db_path=f"{BASE}/knowledge_graph/kg.db")
    causal = CausalIntelligenceEngine(kg_db=f"{BASE}/knowledge_graph/kg.db")
    print("  ✓ WorldModel + ATL + PolicyGovernor + CausalEngine")

    seed_world_model(wm, cat_metrics)

    # ── Step 5: 20品类评分 ──────────────────────────────────
    print("\n[Step 5] 20品类真实数据评分...")
    results = []
    for i, (cat, cfg) in enumerate(TEST_CATEGORIES, 1):
        mkt = cfg["market"]
        r = score_category(wm, atl, cat, mkt)
        results.append(r)
        icon = "✓" if r["recommendation"] == "INVEST" else "·"
        print(f"  [{i:02d}] {icon} {cat:<14}({mkt}) "
              f"ROI={r['roi']:.2f}x CVR={r['cvr']:.1f}% "
              f"Conf={r['confidence']:.0f}% LTV=${r['ltv']:.0f} "
              f"→ {r['recommendation']:<6} [{r['roi_level']}]")

    # ── Step 6: 汇总 ────────────────────────────────────────
    results.sort(key=lambda x: -x["score"])
    invest = [r for r in results if r["recommendation"] == "INVEST"]

    print("\n" + "=" * 70)
    print("  🏆 V10 × WooCommerce 真实数据 — TOP 5 选品")
    print("=" * 70)
    print(f"  {'排名':<4} {'品类':<14} {'市场':<4} {'ROI':>6} {'CVR':>6} "
          f"{'置信':>6} {'LTV':>6} {'评分':>5} {'等级'}")
    print("  " + "-" * 70)
    for i, r in enumerate(results[:5], 1):
        medal = ["🥇","🥈","🥉"," "," "][min(i-1,4)]
        print(f"  {medal}{i:<3} {r['category']:<13} {r['market']:<4} "
              f"{r['roi']:>5.2f}x {r['cvr']:>5.1f}% {r['confidence']:>5.0f}% "
              f"${r['ltv']:>5.0f} {r['score']:>5.3f} {r['roi_level']}")

    print(f"\n  📊 WooCommerce 店铺状态:")
    print(f"    产品总数: {len(products)} SKU")
    print(f"    订单总数: {order_data['total_orders']} (冷启动新店)")
    print(f"    总营收:   ${order_data['total_revenue']:.2f}")
    print(f"    推荐 INVEST: {len(invest)}/20 品类")

    # ── Step 7: 保存 ────────────────────────────────────────
    out = {
        "timestamp": dt.datetime.now().isoformat(),
        "woo_connection": "ssh_mysql_direct",
        "vps": VPS_HOST,
        "products_fetched": len(products),
        "orders_total": order_data["total_orders"],
        "revenue_total": order_data["total_revenue"],
        "results": results,
        "products": [
            {"id": p["ID"], "name": p["post_title"][:60], "price": p["price"],
             "regular_price": p["regular_price"], "categories": p["categories"],
             "sku": p.get("sku",""), "stock": p["stock"], "weight_kg": p["weight"]}
            for p in products
        ]
    }
    path = f"{BASE}/woo_reality_scored.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 结果已保存: {path}")

if __name__ == "__main__":
    main()
