"""
HVOS Pricing Engine — 精确定价 x 中国电商平台扣点
来源: solo-ecom-pilot (CC-BY), 整合自一人电商运营助手
6 大平台 x 7 大类目 = 30+ 条精确扣点数据
"""

from enum import Enum


class EcommPlatform(Enum):
    TAOBAO = "淘宝"
    TMALL = "天猫"
    DOUYIN = "抖音"
    XIAOHONGSHU = "小红书"
    PDD = "拼多多"
    JD = "京东"
    AMAZON_US = "Amazon US"
    SHOPIFY = "Shopify"


PLATFORM_RATES = {
    EcommPlatform.TAOBAO:      {"min": 0.005, "max": 0.01,  "default": 0.008},
    EcommPlatform.TMALL:        {"min": 0.02,  "max": 0.05,  "default": 0.04},
    EcommPlatform.PDD:          {"min": 0.006, "max": 0.03,  "default": 0.015},
    EcommPlatform.DOUYIN:       {"min": 0.02,  "max": 0.10,  "default": 0.05},
    EcommPlatform.XIAOHONGSHU:  {"min": 0.05,  "max": 0.20,  "default": 0.10},
    EcommPlatform.JD:           {"min": 0.03,  "max": 0.08,  "default": 0.05},
    EcommPlatform.AMAZON_US:    {"min": 0.06,  "max": 0.17,  "default": 0.15},
    EcommPlatform.SHOPIFY:      {"min": 0.0,   "max": 0.0,   "default": 0.0},
}

CATEGORY_COMMISSIONS = {
    (EcommPlatform.TAOBAO, "服装鞋包"): 0.005,  (EcommPlatform.TAOBAO, "3C数码"): 0.005,
    (EcommPlatform.TAOBAO, "家居日用"): 0.005,  (EcommPlatform.TAOBAO, "美妆个护"): 0.008,
    (EcommPlatform.TAOBAO, "食品饮料"): 0.005,  (EcommPlatform.TAOBAO, "母婴玩具"): 0.005,
    (EcommPlatform.TAOBAO, "珠宝首饰"): 0.008,  (EcommPlatform.TAOBAO, "礼品盒"): 0.006,
    (EcommPlatform.TMALL, "服装鞋包"): 0.05,    (EcommPlatform.TMALL, "3C数码"): 0.03,
    (EcommPlatform.TMALL, "美妆个护"): 0.04,    (EcommPlatform.TMALL, "家居日用"): 0.03,
    (EcommPlatform.TMALL, "食品饮料"): 0.02,    (EcommPlatform.TMALL, "礼品盒"): 0.04,
    (EcommPlatform.DOUYIN, "服装鞋包"): 0.05,   (EcommPlatform.DOUYIN, "3C数码"): 0.03,
    (EcommPlatform.DOUYIN, "食品饮料"): 0.02,   (EcommPlatform.DOUYIN, "美妆个护"): 0.05,
    (EcommPlatform.DOUYIN, "珠宝首饰"): 0.08,    (EcommPlatform.DOUYIN, "家居日用"): 0.03,
    (EcommPlatform.DOUYIN, "礼品盒"): 0.04,
    (EcommPlatform.XIAOHONGSHU, "服装鞋包"): 0.10, (EcommPlatform.XIAOHONGSHU, "美妆个护"): 0.15,
    (EcommPlatform.XIAOHONGSHU, "食品饮料"): 0.05, (EcommPlatform.XIAOHONGSHU, "家居日用"): 0.10,
    (EcommPlatform.XIAOHONGSHU, "礼品盒"): 0.10,
    (EcommPlatform.PDD, "服装鞋包"): 0.01,   (EcommPlatform.PDD, "3C数码"): 0.01,
    (EcommPlatform.PDD, "食品饮料"): 0.008,  (EcommPlatform.PDD, "美妆个护"): 0.015,
    (EcommPlatform.PDD, "家居日用"): 0.008,  (EcommPlatform.PDD, "礼品盒"): 0.01,
    (EcommPlatform.JD, "服装鞋包"): 0.08,    (EcommPlatform.JD, "3C数码"): 0.03,
    (EcommPlatform.JD, "美妆个护"): 0.05,    (EcommPlatform.JD, "食品饮料"): 0.03,
    (EcommPlatform.JD, "家居日用"): 0.05,    (EcommPlatform.JD, "礼品盒"): 0.05,
    (EcommPlatform.AMAZON_US, "礼品盒"): 0.15, (EcommPlatform.AMAZON_US, "3C数码"): 0.15,
    (EcommPlatform.AMAZON_US, "家居日用"): 0.15, (EcommPlatform.AMAZON_US, "美妆个护"): 0.15,
}

CATEGORY_ALIASES = {
    "服装鞋包": ["服装","鞋","包","服饰","女装","男装","童装","鞋子","箱包"],
    "3C数码":   ["数码","手机","电脑","耳机","充电器","数码配件","3c"],
    "美妆个护": ["美妆","化妆品","护肤品","个护","面膜","口红","洗护"],
    "食品饮料": ["食品","饮料","零食","茶叶","咖啡","保健品"],
    "家居日用": ["家居","日用品","家纺","厨具","收纳","清洁"],
    "母婴玩具": ["母婴","玩具","婴儿","童装","奶粉","纸尿裤"],
    "珠宝首饰": ["珠宝","首饰","黄金","银饰","钻石","手表"],
    "礼品盒":   ["礼品","礼盒","gift box","gift set","礼盒套装","生日礼物","节日礼品"],
}


class PricingEngine:
    """
    HVOS 定价引擎 — 精确到平台 x 类目的科学定价

    使用:
        result = PricingEngine.calculate_price(cost=50, platform="天猫", category="服装鞋包", target_margin=0.40)
        print(result["pricing_tiers"]["recommended"]["price"])
    """

    @staticmethod
    def _resolve_platform(p: str) -> EcommPlatform:
        p = p.strip().lower()
        m = {
            "淘宝": EcommPlatform.TAOBAO, "taobao": EcommPlatform.TAOBAO,
            "天猫": EcommPlatform.TMALL, "tmall": EcommPlatform.TMALL,
            "抖音": EcommPlatform.DOUYIN, "douyin": EcommPlatform.DOUYIN,
            "小红书": EcommPlatform.XIAOHONGSHU, "xhs": EcommPlatform.XIAOHONGSHU,
            "拼多多": EcommPlatform.PDD, "pdd": EcommPlatform.PDD, "pinduoduo": EcommPlatform.PDD,
            "京东": EcommPlatform.JD, "jd": EcommPlatform.JD,
            "amazon": EcommPlatform.AMAZON_US,
            "shopify": EcommPlatform.SHOPIFY,
        }
        for k, v in m.items():
            if k in p:
                return v
        return EcommPlatform.TAOBAO

    @staticmethod
    def _resolve_category(c: str) -> str:
        c = c.strip().lower()
        for std, aliases in CATEGORY_ALIASES.items():
            if c in aliases or c == std:
                return std
        return c if c else "通用"

    @staticmethod
    def get_rate(platform: EcommPlatform, category: str = None, custom_rate: float = None) -> float:
        if custom_rate is not None:
            return custom_rate
        if category:
            cat = PricingEngine._resolve_category(category)
            key = (platform, cat)
            if key in CATEGORY_COMMISSIONS:
                return CATEGORY_COMMISSIONS[key]
        return PLATFORM_RATES[platform]["default"]

    @staticmethod
    def calculate_price(
        cost: float,
        platform: str,
        category: str = None,
        target_margin: float = 0.40,
        marketing_reserve: float = 0.08,
        return_rate: float = 0.03,
        custom_rate: float = None,
    ) -> dict:
        ec = PricingEngine._resolve_platform(platform)
        rate = PricingEngine.get_rate(ec, category, custom_rate)
        packaging = cost * 0.06
        logistics = cost * 0.05
        total_cost = (cost + packaging + logistics) * (1 + return_rate)

        def net_margin(price):
            gross = price - total_cost
            net = gross - (price * rate) - (price * marketing_reserve)
            return net / price if price > 0 else 0

        tiers = {}
        for label, margin_adj in [("conservative", -0.05), ("recommended", 0.0), ("aggressive", 0.05)]:
            margin = target_margin + margin_adj
            denom = 1 - rate - marketing_reserve - margin
            if denom <= 0:
                price = total_cost * 999  # invalid
            else:
                price = total_cost / denom
            nm = net_margin(price)
            tiers[label] = {
                "price": round(price, 2),
                "gross_margin": str(round(margin * 100, 1)) + "%",
                "net_margin": str(round(nm * 100, 1)) + "%",
            }

        warnings = []
        if tiers["aggressive"]["net_margin"].startswith("-"):
            warnings.append("激进定价低于成本价")
        if float(tiers["recommended"]["net_margin"].replace("%","")) > 70:
            warnings.append("高利润率需有真实成本支撑")

        return {
            "platform": ec.value,
            "category": category or "通用",
            "rate_used": str(round(rate * 100, 1)) + "%",
            "cost_breakdown": {
                "product_cost": cost,
                "packaging": round(packaging, 2),
                "logistics": round(logistics, 2),
                "total_cost": round(total_cost, 2),
            },
            "pricing_tiers": tiers,
            "compliance_warnings": warnings,
        }

    @staticmethod
    def simulate_profit_table(cost: float, platform: str, category: str = None) -> list:
        ec = PricingEngine._resolve_platform(platform)
        rate = PricingEngine.get_rate(ec, category)
        packaging = cost * 0.06
        logistics = cost * 0.05
        total_cost = cost + packaging + logistics
        rows = []
        for markup in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
            price = total_cost * (1 + markup)
            net = price - total_cost - (price * rate) - (price * 0.08)
            rows.append({
                "markup": str(int(markup * 100)) + "%",
                "price": round(price, 2),
                "net_margin": str(round(net / price * 100, 1)) + "%" if price > 0 else "N/A",
                "net_profit": round(net, 2),
            })
        return rows
