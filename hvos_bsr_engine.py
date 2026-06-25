"""
HVOS BSR Sales Intelligence Engine
====================================
融合自 ecommerce-product-picker 的 BSR 销量转换模型

核心能力：
  1. Amazon BSR → 月销量区间转换
  2. AliExpress 上升榜趋势修正
  3. 小红书/TikTok 社交热度信号注入
  4. 1688 成本 + FBA + 平台费 → 利润计算

使用方式：
  python hvos_bsr_engine.py --bsr 500 --cost 18 --price 22.9
  python hvos_bsr_engine.py --tiktok 1800000 --xhs 30000 --price 25.0
"""

import argparse
import math
from typing import Tuple, Optional


# ─────────────────────────────────────────────────────────────────────────────
# BSR → 月销量转换（Amazon 类别特定模型）
# 来源：ecommerce-product-picker v4
# ─────────────────────────────────────────────────────────────────────────────

BSR_TIER_TABLE = [
    # (bsr_upper, low_monthly, high_monthly, confidence)
    (100,      2000,  5000,  "high"),
    (500,      1000,  3000,  "high"),
    (1000,     500,   2000,  "high"),
    (3000,     200,   800,   "medium"),
    (5000,     100,   400,   "medium"),
    (10000,    50,    200,   "Medium"),
    (20000,    20,    100,   "Low"),
    (50000,    5,     50,    "low"),
    (99999999, 1,     20,    "low"),
]


def bsr_to_monthly_sales(bsr: int, aliexpress_trending_pct: float = 0.0) -> dict:
    """
    BSR → 月销量区间转换
    aliexpress_trending_pct: AliExpress 上升修正（0.0-1.0），默认0
    返回 dict: {low, high, confidence, base_sales}
    """
    low, high, confidence = 1, 20, "low"
    for ceiling, tier_low, tier_high, conf in BSR_TIER_TABLE:
        if bsr <= ceiling:
            low, high, confidence = tier_low, tier_high, conf
            break

    # AliExpress 趋势修正：上升 +20-50%
    modifier = 1.0 + (aliexpress_trending_pct * 0.3)
    low = int(low * modifier)
    high = int(high * modifier)

    return {
        "low": low,
        "high": high,
        "confidence": confidence,
        "base_bsr": bsr,
        "aliexpress_modifier": modifier,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 国内月销量参考（淘宝/天猫/京东热榜 + 直播数据）
# ─────────────────────────────────────────────────────────────────────────────

def domestic_sales_ref(taobao_rank_notes: str = "", live_gmv_factor: float = 1.0) -> Tuple[int, int]:
    """
    国内月销量估算
    taobao_rank_notes: 热榜位置说明（如"热销 Top50"）
    live_gmv_factor: 直播GMV放大因子（1.0=无直播，1.5=头部主播）
    """
    base_low, base_high = 10000, 30000
    if "Top10" in taobao_rank_notes:
        base_low, base_high = 20000, 50000
    elif "Top50" in taobao_rank_notes:
        base_low, base_high = 10000, 30000
    elif "Top100" in taobao_rank_notes:
        base_low, base_high = 5000, 15000

    low = int(base_low * live_gmv_factor)
    high = int(base_high * live_gmv_factor)
    return low, high


# ─────────────────────────────────────────────────────────────────────────────
# 社交热度评分（TikTok + 小红书）
# ─────────────────────────────────────────────────────────────────────────────

TIKTOK_VIRAL_TABLE = [
    (1000000, "high",   1.3),
    (500000,  "medium", 1.1),
    (100000,  "low",    1.0),
    (0,       "none",   0.8),
]

XHS_NOTES_TABLE = [
    (50000, 1.2),
    (10000, 1.1),
    (1000,  1.0),
    (0,     0.9),
]


def social_heat_score(tiktok_views: int, xhs_notes: int, xhs_avg_likes: int) -> dict:
    """
    社交热度综合评分
    返回 dict: {score_0_100, tiktok_viral, xhs_factor, combined_signal}
    """
    # TikTok
    tiktok_viral = "none"
    tiktok_factor = 1.0
    for threshold, label, factor in TIKTOK_VIRAL_TABLE:
        if tiktok_views >= threshold:
            tiktok_viral = label
            tiktok_factor = factor
            break

    # 小红书
    xhs_factor = 1.0
    for threshold, factor in XHS_NOTES_TABLE:
        if xhs_notes >= threshold:
            xhs_factor = factor
            break

    # XHS 点赞质量修正
    if xhs_avg_likes >= 5000:
        xhs_factor *= 1.2
    elif xhs_avg_likes >= 1000:
        xhs_factor *= 1.1

    combined = tiktok_factor * xhs_factor

    # 归一化到 0-100 评分
    raw_score = combined * 40  # base 40, max ~104
    score = min(100, int(raw_score))

    return {
        "score": score,
        "tiktok_viral": tiktok_viral,
        "tiktok_factor": tiktok_factor,
        "xhs_factor": xhs_factor,
        "combined_signal": round(combined, 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 跨境利润计算（1688 采购 + FBA + Amazon 平台费）
# ─────────────────────────────────────────────────────────────────────────────

def calc_cross_border_profit(
    cost_cny: float,
    price_usd: float,
    weight_lb: float = 2.0,
    logistics_usd: float = 3.5,
    fba_base: float = 6.5,
    fba_per_lb: float = 0.25,
    platform_pct: float = 0.15,
    fx: float = 7.2,
) -> dict:
    """
    跨境 Amazon 利润计算
    成本 = 1688采购价 + 物流 + FBA履行费 + 平台佣金
    利润 = 售价 - 成本
    """
    fba_cost = fba_base + (weight_lb * fba_per_lb)
    cost_cny_usd = cost_cny / fx
    total_cost = cost_cny_usd + logistics_usd + fba_cost + (price_usd * platform_pct)

    profit_per_unit = price_usd - total_cost
    gross_margin = (profit_per_unit / price_usd * 100) if price_usd > 0 else 0

    return {
        "cost_1688_cny": cost_cny,
        "cost_1688_usd": round(cost_cny_usd, 2),
        "logistics_usd": logistics_usd,
        "fba_cost_usd": round(fba_cost, 2),
        "platform_fee_usd": round(price_usd * platform_pct, 2),
        "total_cost_usd": round(total_cost, 2),
        "profit_per_unit_usd": round(profit_per_unit, 2),
        "gross_margin_pct": round(gross_margin, 1),
        "fx_rate": fx,
    }


def monthly_profit_estimate(
    price_usd: float,
    cost_cny: float,
    monthly_sales_low: int,
    monthly_sales_high: int,
    weight_lb: float = 2.0,
    logistics_usd: float = 3.5,
    fba_base: float = 6.5,
    platform_pct: float = 0.15,
    fx: float = 7.2,
) -> dict:
    """月利润区间估算"""
    cost_breakdown = calc_cross_border_profit(
        cost_cny, price_usd, weight_lb, logistics_usd, fba_base, 0.25, platform_pct, fx
    )
    profit_per_unit = cost_breakdown["profit_per_unit_usd"]

    return {
        "profit_per_unit": round(profit_per_unit, 2),
        "monthly_sales_range": f"{monthly_sales_low:,}-{monthly_sales_high:,}",
        "monthly_profit_low": round(profit_per_unit * monthly_sales_low, 0),
        "monthly_profit_high": round(profit_per_unit * monthly_sales_high, 0),
        "monthly_profit_range": f"${profit_per_unit * monthly_sales_low:,.0f}-${profit_per_unit * monthly_sales_high:,.0f}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 综合选品报告
# ─────────────────────────────────────────────────────────────────────────────

def full_selection_report(
    product_name: str,
    bsr: int,
    cost_cny: float,
    price_usd: float,
    weight_lb: float = 2.0,
    tiktok_views: int = 0,
    xhs_notes: int = 0,
    xhs_avg_likes: int = 0,
    taobao_ref: str = "",
    live_factor: float = 1.0,
    aliexpress_trend: float = 0.0,
    logistics_usd: float = 3.5,
    fba_base: float = 6.5,
    platform_pct: float = 0.15,
    fx: float = 7.2,
) -> dict:
    """生成完整选品报告"""
    # 1. BSR 销量转换
    bsr_data = bsr_to_monthly_sales(bsr, aliexpress_trend)

    # 2. 国内月销参考
    dom_low, dom_high = domestic_sales_ref(taobao_ref, live_factor)

    # 3. 社交热度
    social = social_heat_score(tiktok_views, xhs_notes, xhs_avg_likes)

    # 4. 利润计算
    profit = monthly_profit_estimate(
        price_usd, cost_cny,
        bsr_data["low"], bsr_data["high"],
        weight_lb, logistics_usd, fba_base, platform_pct, fx
    )

    # 5. 综合跨境潜力评分
    social_score = social["score"]
    bsr_conf_map = {"high": 100, "Medium": 70, "medium": 70, "Low": 50, "low": 50}
    bsr_conf_score = bsr_conf_map.get(bsr_data["confidence"], 50)
    margin_score = min(100, profit["profit_per_unit"] / price_usd * 200) if price_usd > 0 else 0

    # 热度权重：社交30 + BSR转化30 + 毛利40
    cross_border_potential = int(
        social_score * 0.30 + bsr_conf_score * 0.30 + margin_score * 0.40
    )

    return {
        "product_name": product_name,
        "recommendation": "强烈推荐" if cross_border_potential >= 80 else
                          "推荐" if cross_border_potential >= 60 else
                          "谨慎" if cross_border_potential >= 40 else "不建议",
        "cross_border_potential": cross_border_potential,
        "bsr_conversion": bsr_data,
        "domestic_sales_estimate": {"low": dom_low, "high": dom_high, "ref": taobao_ref},
        "social_heat": social,
        "cost_breakdown": profit,
        "suggested_price_usd": price_usd,
        "suggested_price_cny": round(price_usd * fx, 0),
        "gross_margin_pct": profit["profit_per_unit"] / price_usd * 100 if price_usd > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HVOS BSR Sales Intelligence Engine")
    parser.add_argument("--product", default="宠物美容手套", help="产品名称")
    parser.add_argument("--bsr", type=int, default=500, help="Amazon BSR排名")
    parser.add_argument("--cost", type=float, default=18.0, help="1688采购价(元)")
    parser.add_argument("--price", type=float, default=22.9, help="建议售价(USD)")
    parser.add_argument("--weight", type=float, default=2.0, help="重量(lb)")
    parser.add_argument("--tiktok", type=int, default=0, help="TikTok观看量")
    parser.add_argument("--xhs", type=int, default=0, help="小红书笔记数")
    parser.add_argument("--xhs_likes", type=int, default=0, help="小红书平均点赞")
    parser.add_argument("--aliexpress_trend", type=float, default=0.0, help="AliExpress上升趋势(0-1)")
    parser.add_argument("--logistics", type=float, default=3.5, help="物流费USD")
    parser.add_argument("--fba", type=float, default=6.5, help="FBA基础费USD")
    parser.add_argument("--fx", type=float, default=7.2, help="USD/CNY汇率")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    report = full_selection_report(
        product_name=args.product,
        bsr=args.bsr,
        cost_cny=args.cost,
        price_usd=args.price,
        weight_lb=args.weight,
        tiktok_views=args.tiktok,
        xhs_notes=args.xhs,
        xhs_avg_likes=args.xhs_likes,
        aliexpress_trend=args.aliexpress_trend,
        logistics_usd=args.logistics,
        fba_base=args.fba,
        fx=args.fx,
    )

    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        r = report
        print("=" * 60)
        print(f"  HVOS BSR 选品报告")
        print("=" * 60)
        print(f"  产品: {r['product_name']}")
        print(f"  跨境潜力: {r['cross_border_potential']}/100  [{r['recommendation']}]")
        print()
        print(f"  【BSR 销量转换】")
        print(f"    BSR排名: {r['bsr_conversion']['base_bsr']}")
        print(f"    月销量区间: {r['bsr_conversion']['low']:,}-{r['bsr_conversion']['high']:,} 件")
        print(f"    置信度: {r['bsr_conversion']['confidence']}")
        print()
        print(f"  【国内月销参考】")
        d = r['domestic_sales_estimate']
        print(f"    区间: {d['low']:,}-{d['high']:,} 件")
        if d['ref']:
            print(f"    参考: {d['ref']}")
        print()
        print(f"  【社交热度】")
        s = r['social_heat']
        print(f"    综合热度评分: {s['score']}/100")
        print(f"    TikTok: {s['tiktok_viral']} (x{s['tiktok_factor']})")
        print(f"    小红书: x{s['xhs_factor']}")
        print()
        print(f"  【利润计算】")
        p = r['cost_breakdown']
        print(f"    1688采购: ¥{p['cost_1688_cny']} = ${p['cost_1688_usd']}")
        print(f"    物流: ${p['logistics_usd']}  FBA: ${p['fba_cost_usd']}  平台费: ${p['platform_fee_usd']}")
        print(f"    总成本: ${p['total_cost_usd']}  售价: ${r['suggested_price_usd']}")
        print(f"    毛利率: {r['gross_margin_pct']:.1f}%")
        print(f"    月利润区间: {p['monthly_profit_range']}")
        print("=" * 60)
