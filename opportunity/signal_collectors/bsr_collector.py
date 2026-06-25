"""
BSR Signal Collector
====================
V10.1 新增：从 Amazon BSR 信号中提取销量区间 + 社交热度

注入到 OpportunityEngine 的采集器体系。

使用 BSR 排名直接调用 hvos_bsr_engine 的 bsr_to_monthly_sales()，
将市场信号转换为可量化的销量预估，填充 ProductDNA。
"""

import sys
import os
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, r"C:\Users\Administrator\HVOS")

try:
    from hvos_bsr_engine import bsr_to_monthly_sales, social_heat_score, calc_cross_border_profit
    HAS_BSR_ENGINE = True
except ImportError:
    HAS_BSR_ENGINE = False


class BSRSignalCollector:
    """
    BSR 信号采集器
    将 Amazon BSR 排名 + TikTok/XHS 热度转换为结构化销量信号
    """

    def __init__(self):
        self.name = "bsr_collector"
        self.platform = "amazon_bsr"

    def collect(self, keyword: str, bsr: int = 0,
                tiktok_views: int = 0, xhs_notes: int = 0,
                xhs_avg_likes: int = 0, aliexpress_trend: float = 0.0) -> Dict:
        """
        采集 BSR + 社交信号，返回结构化信号字典
        """
        result = {
            "source": "bsr_collector",
            "keyword": keyword,
            "collected_at": datetime.now().isoformat(),
            "has_bsr_engine": HAS_BSR_ENGINE,
        }

        if not HAS_BSR_ENGINE:
            result["status"] = "bsr_engine_not_available"
            return result

        # BSR → 月销量
        bsr_data = bsr_to_monthly_sales(bsr, aliexpress_trend)
        result["bsr"] = bsr
        result["monthly_sales_low"] = bsr_data["low"]
        result["monthly_sales_high"] = bsr_data["high"]
        result["bsr_confidence"] = bsr_data["confidence"]

        # 社交热度
        social = social_heat_score(tiktok_views, xhs_notes, xhs_avg_likes)
        result["social_score"] = social["score"]
        result["tiktok_viral"] = social["tiktok_viral"]
        result["tiktok_factor"] = social["tiktok_factor"]
        result["xhs_factor"] = social["xhs_factor"]

        # 综合信号强度
        bsr_conf_map = {"high": 1.0, "Medium": 0.7, "medium": 0.7, "Low": 0.5, "low": 0.5}
        bsr_conf = bsr_conf_map.get(bsr_data["confidence"], 0.5)
        result["combined_signal"] = round(bsr_conf * 0.5 + social["score"] / 100 * 0.5, 3)

        return result

    def batch_collect(self, signals: List[Dict]) -> List[Dict]:
        """
        批量采集：输入 [{keyword, bsr, tiktok_views, xhs_notes, ...}, ...]
        """
        return [self.collect(**s) for s in signals]


if __name__ == "__main__":
    collector = BSRSignalCollector()

    test_signals = [
        {
            "keyword": "pet grooming gloves",
            "bsr": 500,
            "tiktok_views": 1800000,
            "xhs_notes": 30000,
            "xhs_avg_likes": 4500,
            "aliexpress_trend": 0.3,
        },
        {
            "keyword": "smart garden light",
            "bsr": 8000,
            "tiktok_views": 500000,
            "xhs_notes": 5000,
            "xhs_avg_likes": 800,
            "aliexpress_trend": 0.0,
        },
    ]

    results = collector.batch_collect(test_signals)
    import json
    print(json.dumps(results, ensure_ascii=False, indent=2))
