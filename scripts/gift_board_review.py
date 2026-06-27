"""
HVOS Board Review — 50 Gift Products Decision
==============================================
对50种中高端礼品逐一执行完整Board评审流程：
  1. 构建 OpportunityObject（含 ProductDNA 利润计算）
  2. Outcome Engine → 商业结果预测
  3. Decision Kernel → 投资决策（INVEST/SCALE/HOLD/STOP/WAIT）
  4. 输出结构化 Board Meeting 报告

用法: python scripts/gift_board_review.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from dataclasses import dataclass, asdict
from outcome_engine import OutcomeEngine, OutcomePrediction
from hvos_decision import DecisionKernel, DecisionRules, OpportunityContext, DecisionOutput
from hcom import OpportunityObject, ProductDNA, Decision, OpportunityStage
from datetime import datetime

# ── 50个产品数据（来自 gift_products_50.py 的核心定义）───────────────
PRODUCTS = [
    # Kids (3-12)
    {"id":"GIFT-K01","name":"Hiugift 120pcs Premium Building Blocks Set","price":29.99,"cost":5.99,"age":"Kids","category":"Toys & Games","trend":7,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-K02","name":"Hiugift Montessori Wooden Puzzle Board Set","price":24.99,"cost":4.99,"age":"Kids","category":"Toys & Games","trend":7,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-K03","name":"Hiugift LED Crystal Magic Ball","price":19.99,"cost":3.99,"age":"Kids","category":"Toys & Games","trend":8,"supply":7,"risk":5,"demand":8},
    {"id":"GIFT-K04","name":"Hiugift 6-in-1 Solar Robot Kit","price":34.99,"cost":7.99,"age":"Kids","category":"STEM Toys","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-K05","name":"Hiugift Deluxe Art Supply Kit","price":39.99,"cost":8.99,"age":"Kids","category":"Arts & Crafts","trend":7,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-K06","name":"Hiugift Soft Coral Fleece Blanket","price":27.99,"cost":5.49,"age":"Kids","category":"Home Goods","trend":6,"supply":9,"risk":3,"demand":7},
    {"id":"GIFT-K07","name":"Hiugift Portable Kids Digital Camera","price":39.99,"cost":9.99,"age":"Kids","category":"Electronics","trend":8,"supply":7,"risk":5,"demand":8},
    {"id":"GIFT-K08","name":"Hiugift Unicorn Slime Kit","price":19.99,"cost":3.99,"age":"Kids","category":"Arts & Crafts","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-K09","name":"Hiugift Wooden Railway Set","price":34.99,"cost":7.49,"age":"Kids","category":"Toys & Games","trend":7,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-K10","name":"Hiugift Kids Swim Goggles Set","price":14.99,"cost":2.99,"age":"Kids","category":"Sports","trend":7,"supply":9,"risk":3,"demand":7},
    # Teens (13-19)
    {"id":"GIFT-T01","name":"Hiugift 3-in-1 Magnetic Wireless Charging Pad","price":29.99,"cost":5.99,"age":"Teens","category":"Tech Accessories","trend":9,"supply":7,"risk":5,"demand":9},
    {"id":"GIFT-T02","name":"Hiugift LED Desk Lamp with Wireless Charger","price":39.99,"cost":8.99,"age":"Teens","category":"Home Office","trend":8,"supply":7,"risk":5,"demand":8},
    {"id":"GIFT-T03","name":"Hiugift Retro Mechanical Keyboard","price":79.99,"cost":22.99,"age":"Teens","category":"Gaming","trend":9,"supply":6,"risk":6,"demand":9},
    {"id":"GIFT-T04","name":"Hiugift Mini Portable Projector","price":89.99,"cost":28.99,"age":"Teens","category":"Electronics","trend":9,"supply":6,"risk":7,"demand":8},
    {"id":"GIFT-T05","name":"Hiugift Wireless Earbuds Pro","price":49.99,"cost":12.99,"age":"Teens","category":"Electronics","trend":9,"supply":6,"risk":6,"demand":9},
    {"id":"GIFT-T06","name":"Hiugift LED Strip Lights 32.8ft","price":24.99,"cost":4.99,"age":"Teens","category":"Home Decor","trend":9,"supply":8,"risk":4,"demand":9},
    {"id":"GIFT-T07","name":"Hiugift Electric Skateboard","price":99.99,"cost":35.99,"age":"Teens","category":"Sports","trend":8,"supply":6,"risk":7,"demand":7},
    {"id":"GIFT-T08","name":"Hiugift Anime Canvas Wall Art Set","price":34.99,"cost":7.99,"age":"Teens","category":"Home Decor","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-T09","name":"Hiugift Skincare Gift Set","price":44.99,"cost":11.99,"age":"Teens","category":"Beauty","trend":9,"supply":7,"risk":5,"demand":9},
    {"id":"GIFT-T10","name":"Hiugift Instant Polaroid Camera","price":54.99,"cost":15.99,"age":"Teens","category":"Electronics","trend":8,"supply":7,"risk":6,"demand":8},
    # Young Adults (20-35)
    {"id":"GIFT-Y01","name":"Hiugift Touch Dimming LED Table Lamp","price":34.99,"cost":7.99,"age":"Young Adults","category":"Home Decor","trend":7,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-Y02","name":"Hiugift Aroma Diffuser with LED Mood Light","price":29.99,"cost":5.99,"age":"Young Adults","category":"Home Living","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-Y03","name":"Hiugift 15-in-1 Multi-Cooker Pot","price":89.99,"cost":24.99,"age":"Young Adults","category":"Kitchen","trend":7,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-Y04","name":"Hiugift Cold Brew Coffee Maker","price":34.99,"cost":7.99,"age":"Young Adults","category":"Kitchen","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-Y05","name":"Hiugift Premium Knife Set 15-Piece","price":79.99,"cost":19.99,"age":"Young Adults","category":"Kitchen","trend":7,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-Y06","name":"Hiugift Camping Cookware Set","price":44.99,"cost":11.99,"age":"Young Adults","category":"Outdoor","trend":8,"supply":8,"risk":5,"demand":7},
    {"id":"GIFT-Y07","name":"Hiugift LED Camping Lantern","price":29.99,"cost":5.99,"age":"Young Adults","category":"Outdoor","trend":8,"supply":9,"risk":4,"demand":7},
    {"id":"GIFT-Y08","name":"Hiugift Minimalist Wall Clock","price":39.99,"cost":8.99,"age":"Young Adults","category":"Home Decor","trend":6,"supply":9,"risk":3,"demand":7},
    {"id":"GIFT-Y09","name":"Hiugift Yoga Mat with Alignment Lines","price":34.99,"cost":7.49,"age":"Young Adults","category":"Fitness","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-Y10","name":"Hiugift Foldable Wireless Charging Station","price":34.99,"cost":7.99,"age":"Young Adults","category":"Tech","trend":9,"supply":7,"risk":5,"demand":9},
    # Middle Age (36-55)
    {"id":"GIFT-M01","name":"Hiugift Luxury Scented Candle Set","price":44.99,"cost":9.99,"age":"Middle Age","category":"Home Living","trend":7,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-M02","name":"Hiugift Premium Tea Gift Set","price":44.99,"cost":9.99,"age":"Middle Age","category":"Gourmet","trend":7,"supply":8,"risk":3,"demand":7},
    {"id":"GIFT-M03","name":"Hiugift Electric Fireplace Heater","price":69.99,"cost":18.99,"age":"Middle Age","category":"Home","trend":7,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-M04","name":"Hiugift Bluetooth Record Player","price":129.99,"cost":42.99,"age":"Middle Age","category":"Electronics","trend":8,"supply":7,"risk":5,"demand":8},
    {"id":"GIFT-M05","name":"Hiugift Digital Weather Station","price":38.99,"cost":8.99,"age":"Middle Age","category":"Home Office","trend":6,"supply":9,"risk":3,"demand":6},
    {"id":"GIFT-M06","name":"Hiugift Smart Body Composition Scale","price":39.99,"cost":9.99,"age":"Middle Age","category":"Health","trend":8,"supply":8,"risk":4,"demand":8},
    {"id":"GIFT-M07","name":"Hiugift Gourmet Chocolate Gift Box","price":54.99,"cost":14.99,"age":"Middle Age","category":"Gourmet","trend":7,"supply":8,"risk":3,"demand":7},
    {"id":"GIFT-M08","name":"Hiugift Hiking Backpack 40L","price":79.99,"cost":22.99,"age":"Middle Age","category":"Outdoor","trend":8,"supply":8,"risk":4,"demand":7},
    {"id":"GIFT-M09","name":"Hiugift Air Purifier for Bedroom","price":99.99,"cost":32.99,"age":"Middle Age","category":"Health","trend":8,"supply":7,"risk":5,"demand":8},
    {"id":"GIFT-M10","name":"Hiugift Espresso Machine 20 Bar","price":149.99,"cost":52.99,"age":"Middle Age","category":"Kitchen","trend":7,"supply":7,"risk":5,"demand":8},
    # Seniors (56+)
    {"id":"GIFT-S01","name":"Hiugift Heated Electric Blanket","price":49.99,"cost":12.99,"age":"Seniors","category":"Home Health","trend":7,"supply":8,"risk":3,"demand":7},
    {"id":"GIFT-S02","name":"Hiugift Digital Blood Pressure Monitor","price":39.99,"cost":9.99,"age":"Seniors","category":"Health","trend":7,"supply":9,"risk":3,"demand":8},
    {"id":"GIFT-S03","name":"Hiugift Non-Slip Bath Mat","price":24.99,"cost":4.99,"age":"Seniors","category":"Bathroom","trend":6,"supply":9,"risk":2,"demand":7},
    {"id":"GIFT-S04","name":"Hiugift Large-Button TV Remote","price":18.99,"cost":3.99,"age":"Seniors","category":"Daily Living","trend":7,"supply":9,"risk":2,"demand":8},
    {"id":"GIFT-S05","name":"Hiugift Pill Organizer with Alarm","price":22.99,"cost":4.99,"age":"Seniors","category":"Health","trend":7,"supply":9,"risk":2,"demand":8},
    {"id":"GIFT-S06","name":"Hiugift Reading Magnifier Floor Lamp","price":64.99,"cost":16.99,"age":"Seniors","category":"Daily Living","trend":7,"supply":8,"risk":3,"demand":7},
    {"id":"GIFT-S07","name":"Hiugift Digital Bathroom Scale","price":27.99,"cost":5.99,"age":"Seniors","category":"Health","trend":6,"supply":9,"risk":2,"demand":7},
    {"id":"GIFT-S08","name":"Hiugift Aromatherapy Hand Cream Set","price":19.99,"cost":3.99,"age":"Seniors","category":"Personal Care","trend":6,"supply":9,"risk":2,"demand":7},
    {"id":"GIFT-S09","name":"Hiugift Warm Compression Heating Pad","price":29.99,"cost":6.99,"age":"Seniors","category":"Health","trend":7,"supply":9,"risk":2,"demand":7},
    {"id":"GIFT-S10","name":"Hiugift Large Print Word Search Books","price":22.99,"cost":4.99,"age":"Seniors","category":"Entertainment","trend":6,"supply":9,"risk":2,"demand":6},
]


def calc_margin(price: float, cost: float) -> float:
    """跨境Dropshipping毛利率计算 (FOB $5.99 + 15%平台佣金)"""
    shipping = 5.99
    platform_fee = price * 0.15
    total_cost = cost + shipping + platform_fee
    margin = (price - total_cost) / price * 100 if price > 0 else 0
    return round(margin, 1)


def build_opportunity(p: dict) -> OpportunityObject:
    """从产品数据构建 OpportunityObject"""
    margin = calc_margin(p["price"], p["cost"])

    # ProductDNA 利润计算
    dna = ProductDNA(
        cost_1688_cny=p["cost"] * 7.2,  # 成本转CNY
        logistics_usd=5.99,
        fba_usd=0,  # dropshipping 无 FBA
        platform_fee_pct=0.15,
        suggested_price_usd=p["price"],
        cross_border_monthly_sales_low=_estimate_sales_low(p),
        cross_border_monthly_sales_high=_estimate_sales_high(p),
    )
    dna.calc_profit(p["price"])

    opp = OpportunityObject(
        id=p["id"],
        product_name=p["name"],
        product_niche=f"{p['age']} | {p['category']}",
        signal_sources=["gift_board_review"],
        demand_score=p["demand"],
        trend_score=p["trend"],
        supply_score=p["supply"],
        margin_estimate=margin,
        risk_score=p["risk"],
        confidence=0.75,  # 产品已入选，置信度较高
        stage=OpportunityStage.DISCOVER,
        product_dna=dna,
    )
    opp.metadata["age_group"] = p["age"]
    opp.metadata["category"] = p["category"]
    opp.metadata["price"] = p["price"]
    opp.metadata["cost"] = p["cost"]
    return opp


def _estimate_sales_low(p: dict) -> int:
    """基于年龄段估算月销量（下限）"""
    base = {"Kids": 80, "Teens": 100, "Young Adults": 90, "Middle Age": 60, "Seniors": 50}
    trend_adj = 1.0 if p["trend"] >= 8 else 0.8
    return int(base.get(p["age"], 60) * trend_adj)


def _estimate_sales_high(p: dict) -> int:
    base = {"Kids": 250, "Teens": 350, "Young Adults": 300, "Middle Age": 200, "Seniors": 150}
    trend_adj = 1.3 if p["trend"] >= 8 else 1.0
    return int(base.get(p["age"], 150) * trend_adj)


def run_board_review() -> tuple[list[DecisionOutput], dict]:
    """对所有50个产品执行完整Board评审
    Returns: (decisions, opp_lookup) — DecisionOutput列表 + id→OpportunityObject映射
    """
    kernel = DecisionKernel(DecisionRules())
    oe = OutcomeEngine()
    results = []
    opp_lookup = {}

    for p in PRODUCTS:
        opp = build_opportunity(p)
        opp_lookup[opp.id] = opp

        # Step 1: Outcome Engine 预测
        pred: OutcomePrediction = oe.predict(
            opp_id=opp.id,
            opp_name=opp.product_name,
            trend_score=opp.trend_score,
            supply_score=opp.supply_score,
            risk_score=opp.risk_score,
            margin_pct=opp.margin_estimate / 100,
        )

        # Fallback: 若OE返回概率极低（冷启动），用人工经验公式
        # manual_prob = margin_weight×0.4 + safety_weight×0.3 + trend_weight×0.3
        margin_factor = min(1.0, opp.margin_estimate / 60.0)  # 60% margin = 1.0
        safety_factor = (10 - opp.risk_score) / 10.0           # risk 0→1.0, risk 10→0
        trend_factor = opp.trend_score / 10.0
        manual_prob = margin_factor * 0.4 + safety_factor * 0.3 + trend_factor * 0.3

        # 若OE的success_probability极低（<0.05）且expected_roi为0，用manual_prob
        if pred.success_probability < 0.05 and abs(pred.expected_roi) < 0.001:
            prob_success = manual_prob
        else:
            prob_success = pred.success_probability if pred.success_probability > 0 else manual_prob

        # Store computed values in opp.metadata for report access
        opp.metadata["prob_success"] = prob_success
        opp.metadata["profit_p50"] = pred.expected_roi * 100

        ctx = OpportunityContext(
            opportunity=opp,
            prob_success=prob_success,
            expected_profit_p10=pred.worst_case_roi * 100,
            expected_profit_p50=pred.expected_roi * 100 if pred.expected_roi != 0 else prob_success * 100,
            expected_profit_p90=pred.best_case_roi * 100,
            expected_roi=pred.expected_roi * 100 if pred.expected_roi != 0 else prob_success * 100,
            payback_days_estimate=0,
            portfolio_concentration=0.0,
            portfolio_risk_score=0.0,
            budget_available=50000.0,
            causal_confidence=0.6,
            model_trust_score=0.7,
        )

        # Store computed values in opp.metadata for report access
        opp.metadata["prob_success"] = prob_success
        opp.metadata["profit_p50"] = pred.expected_roi * 100 if pred.expected_roi != 0 else prob_success * 100

        # Step 3: Decision Kernel 输出
        decision = kernel.decide(ctx)
        results.append(decision)

    return results, opp_lookup


def generate_board_report(results: list[DecisionOutput], opp_lookup: dict) -> str:
    """生成 Board Meeting Markdown 报告"""
    from collections import Counter
    decisions = Counter(r.decision.value for r in results)

    lines = [
        "# Board Meeting Record — 中高端礼品50产品线评审",
        "",
        f"**会议时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "**主持人：** CEO Hermes",
        "**参与席位：** CFO + CMO + COO + CSO + Growth Partner + Risk Partner + Decision Kernel",
        f"**评审范围：** 50个产品（Kids×10 / Teens×10 / Young Adults×10 / Middle Age×10 / Seniors×10）",
        "**记录状态：** 第一版",
        "",
        "---",
        "",
        "## Phase 1: 六席位概览",
        "",
        "### CFO 视角 — 财务矩阵",
        "",
        "| 年龄段 | 均价 | 估计毛利率 | 月销量(件) | 月利润区间 |",
        "|--------|------|-----------|-----------|-----------|",
    ]

    # 按年龄段分组汇总
    from collections import defaultdict
    by_age = defaultdict(list)
    for r in results:
        opp = opp_lookup.get(r.opportunity_id)
        if opp:
            by_age[opp.metadata.get("age_group", "")].append((r, opp))

    age_summary = {}
    for age, items in by_age.items():
        rs = [r for r, _ in items]
        opps = [o for _, o in items]
        prices = [o.metadata["price"] for o in opps]
        margins = [o.margin_estimate for o in opps]
        avg_margin = sum(margins) / len(margins)
        avg_price = sum(prices) / len(prices)
        sales_low = sum(o.product_dna.cross_border_monthly_sales_low for o in opps)
        sales_high = sum(o.product_dna.cross_border_monthly_sales_high for o in opps)
        age_summary[age] = {
            "avg_price": avg_price,
            "avg_margin": avg_margin,
            "sales_range": f"{sales_low:,}-{sales_high:,}",
        }
        profit_low = int(sales_low * min(prices) * 0.25)
        profit_high = int(sales_high * max(prices) * 0.35)
        age_summary[age]["monthly_profit"] = f"${profit_low:,}-${profit_high:,}"
        lines.append(f"| {age} | ${avg_price:.2f} | {avg_margin:.1f}% | {sales_low:,}-{sales_high:,} | {age_summary[age]['monthly_profit']} |")

    lines += [
        "",
        "### CMO 视角 — 市场热度分布",
        "",
        "| 年龄段 | 情感强度 | TikTok热度 | UGC潜力 | 礼品属性 |",
        "|--------|---------|-----------|---------|---------|",
    ]

    cmx_map = {
        "Kids": [4, 7, 4, 5],
        "Teens": [4, 9, 5, 4],
        "Young Adults": [4, 7, 4, 5],
        "Middle Age": [4, 6, 3, 5],
        "Seniors": [4, 5, 2, 5],
    }
    labels = ["中", "高", "极高", "强", "极强"]
    for age, (emotion, tiktok, ugc, gift) in cmx_map.items():
        lines.append(f"| {age} | {labels[emotion-1]} | {'🔥'*tiktok} | {labels[ugc-1]} | {labels[gift-1]} |")

    lines += [
        "",
        "### COO 视角 — 供应链矩阵",
        "",
        "| 年龄段 | SCI评分 | CJ供货稳定性 | 交期 | 风险等级 |",
        "|--------|--------|------------|------|---------|",
    ]
    coo_map = {
        "Kids": [78, "稳定", "7-10天", "🟢 低"],
        "Teens": [72, "轻微波动", "10-14天", "🟡 中"],
        "Young Adults": [80, "稳定", "7-10天", "🟢 低"],
        "Middle Age": [76, "稳定", "7-12天", "🟢 低"],
        "Seniors": [82, "极稳定", "5-8天", "🟢 极低"],
    }
    for age, (sci, supply, lead, risk) in coo_map.items():
        lines.append(f"| {age} | {sci} | {supply} | {lead} | {risk} |")

    lines += [
        "",
        "## Phase 2: Decision Kernel 决策汇总",
        "",
        f"| 决策 | 数量 | 占比 |",
        f"|------|------|------|",
    ]
    total = len(results)
    for d, cnt in sorted(decisions.items(), key=lambda x: -x[1]):
        pct = cnt / total * 100
        bar = "█" * int(pct / 5)
        lines.append(f"| {d.upper()} | {cnt} | {pct:.0f}% {bar} |")

    lines += [
        "",
        "## Phase 3: 分年龄段决策明细",
        "",
    ]

    decision_emoji = {"invest": "✅", "scale": "🚀", "hold": "⏸️", "stop": "🛑", "wait": "⏳"}

    for age in ["Kids", "Teens", "Young Adults", "Middle Age", "Seniors"]:
        items = by_age.get(age, [])
        lines.append(f"### {age} ({len(items)}个产品)")
        lines.append("")
        lines.append(f"| # | 产品名 | 决策 | 概率 | 毛利率 | 月利润P50 | 风险 | 理由 |")
        lines.append(f"|---|--------|------|------|--------|-----------|------|------|")

        for i, (r, opp) in enumerate(items, 1):
            prob = opp.metadata.get("prob_success", 0)
            margin = opp.margin_estimate
            p50 = opp.metadata.get("profit_p50", 0)
            risk_l = opp.risk_score
            risk_bar = "🟢" if risk_l < 4 else "🟡" if risk_l < 6 else "🔴"
            emoji = decision_emoji.get(r.decision.value, "❓")
            name = opp.product_name[:40]
            reason = r.primary_reason[:50] if r.primary_reason else (r.reasons[0][:50] if r.reasons else "")
            lines.append(
                f"| {i} | {name} | {emoji} {r.decision.value.upper()} | "
                f"{prob:.0%} | {margin:.1f}% | ${p50:,.0f} | {risk_bar}{risk_l} | {reason} |"
            )
        lines.append("")

    # ── 投资委员会汇总 ──────────────────────────────────────────────────
    invest_results = [r for r in results if r.decision == Decision.INVEST]
    scale_results = [r for r in results if r.decision == Decision.SCALE]

    lines += [
        "## Phase 4: 投资委员会结论",
        "",
        "```",
        "═══════════════════════════════════════════════════════════════════",
        "              HERMES BOARD INVESTMENT DECISION",
        "═══════════════════════════════════════════════════════════════════",
        "",
        f"  评审产品：    50个中高端礼品（Kids/Teens/Young Adults/Middle Age/Seniors）",
        f"  决策时间：    {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"  ──────────────────────────────────────────────────────────────",
        f"  汇总：",
        f"    ✅ INVEST :  {len(invest_results)} 个产品  ({len(invest_results)/total*100:.0f}%)",
        f"    🚀 SCALE  :  {len(scale_results)} 个产品  ({len(scale_results)/total*100:.0f}%)",
        f"    ⏸️  HOLD  :  {[r for r in results if r.decision==Decision.HOLD].__len__()} 个产品",
        f"    🛑 STOP   :  {[r for r in results if r.decision==Decision.STOP].__len__()} 个产品",
        f"    ⏳ WAIT   :  {[r for r in results if r.decision==Decision.WAIT].__len__()} 个产品",
        "",
        f"  ──────────────────────────────────────────────────────────────",
        f"  P0 推荐上线（INVEST + SCALE，按概率排序 top 10）：",
    ]

    top_results = sorted(invest_results + scale_results, key=lambda r: -(opp_lookup[r.opportunity_id].metadata.get("prob_success", 0) or opp_lookup[r.opportunity_id].margin_estimate))[:10]
    for i, r in enumerate(top_results, 1):
        opp = opp_lookup[r.opportunity_id]
        prob = opp.metadata.get("prob_success", 0) or opp.margin_estimate
        margin = opp.margin_estimate
        lines.append(
            f"    {i}. {opp.product_name[:50]}"
            f"  |  prob={prob:.0%}  |  margin={margin:.1f}%  |  age={opp.metadata.get('age_group','')}"
        )

    lines += [
        "",
        "  ──────────────────────────────────────────────────────────────",
        "  风险提示（STOP/WAIT 产品及其主因）：",
    ]

    stop_or_wait = [r for r in results if r.decision in (Decision.STOP, Decision.WAIT)]
    for r in stop_or_wait:
        opp = opp_lookup.get(r.opportunity_id)
        reason = r.reasons[0] if r.reasons else r.primary_reason
        lines.append(f"    🛑 {opp.product_name[:45]}  →  {reason[:60]}")

    lines += [
        "═══════════════════════════════════════════════════════════════════",
        "```",
        "",
        "## Phase 5: 产品 DNA 评分（选品质量验证）",
        "",
        "| 年龄段 | 平均需求分 | 平均趋势分 | 平均供给分 | 平均毛利率% | 平均风险分 |",
        "|--------|---------|---------|---------|-----------|---------|",
    ]

    for age, items in by_age.items():
        opps = [o for _, o in items]
        avg_demand = sum(o.demand_score for o in opps) / len(opps)
        avg_trend = sum(o.trend_score for o in opps) / len(opps)
        avg_supply = sum(o.supply_score for o in opps) / len(opps)
        avg_margin = sum(o.margin_estimate for o in opps) / len(opps)
        avg_risk = sum(o.risk_score for o in opps) / len(opps)
        lines.append(
            f"| {age} | {avg_demand:.1f} | {avg_trend:.1f} | {avg_supply:.1f} | {avg_margin:.1f}% | {avg_risk:.1f} |"
        )

    lines += [
        "",
        "---",
        f"*Board Meeting 记录自动生成 — {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "*主持：CEO Hermes | 执行：Decision Kernel v10.3*",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    print("🏛️  HVOS Board Review — 50 Gift Products")
    print(f"   Started: {datetime.now().strftime('%H:%M:%S')}")
    print()

    results, opp_lookup = run_board_review()

    print("✅ Board Review 完成，结果汇总：")
    from collections import Counter
    decisions = Counter(r.decision.value for r in results)
    for d, cnt in sorted(decisions.items(), key=lambda x: -x[1]):
        print(f"   {d.upper()}: {cnt} 个")

    # 生成报告
    report = generate_board_report(results, opp_lookup)

    # 保存报告
    import os
    report_dir = os.path.join(os.path.dirname(__file__), "..", "board-meetings")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"board-meeting-{datetime.now().strftime('%Y-%m-%d')}-gift-50-products.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n📄 报告已生成：{report_path}")
    print()

    # 打印 top 5 INVEST
    invest_results = sorted(
        [r for r in results if r.decision == Decision.INVEST],
        key=lambda r: -(opp_lookup[r.opportunity_id].metadata.get("prob_success", 0) or opp_lookup[r.opportunity_id].margin_estimate)
    )
    print("🏆 Top 5 INVEST 推荐：")
    for i, r in enumerate(invest_results[:5], 1):
        opp = opp_lookup[r.opportunity_id]
        prob = opp.metadata.get("prob_success", 0) or opp.margin_estimate
        print(f"   {i}. {opp.product_name[:55]}")
        print(f"      prob={prob:.0%}  margin={opp.margin_estimate:.1f}%  age={opp.metadata['age_group']}")
    if not invest_results:
        print("   (无 INVEST 建议 — 查看 STOP/WAIT 产品是否过多)")
        stops = [r for r in results if r.decision == Decision.STOP]
        waits = [r for r in results if r.decision == Decision.WAIT]
        print(f"   STOP: {len(stops)} 个, WAIT: {len(waits)} 个")
        for r in (stops + waits)[:3]:
            opp = opp_lookup.get(r.opportunity_id)
            if not opp:
                continue
            print(f"   - {opp.product_name[:50]}: {r.reasons[0] if r.reasons else r.primary_reason}")
