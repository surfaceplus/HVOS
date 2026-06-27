"""
Google Trends Signal Collector
数据源：Google Trends API (pytrends)
采样频率：每 15 分钟 / 每日批量
覆盖维度：品类词 + 相关长尾词

依赖安装：
    uv pip install pytrends

API 限制：400 请求/天（Batch 模式足够）
"""

import sys
import time
from datetime import datetime, timedelta
from typing import Optional

try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False


class GoogleTrendsCollector:
    """
    Google Trends 信号采集器

    核心逻辑：
    1. 追踪品类关键词的搜索量异动
    2. 发现 Interest Surge（搜索量周环比暴增）
    3. 识别跨品类扩散信号（某词带动相关词上涨）

    阈值定义：
      - velocity > 0.3（30% 周增长）→ 触发异动
      - peak_value > 50（搜索量足够大）
      - related_rising_count > 0（有扩散）
    """

    DEFAULT_KEYWORDS = [
        "gift box", "candle", "kitchen gadget", "pet toy",
        "outdoor gear", "beauty device", "home decor",
        "fitness equipment", "kids toy", "travel accessory",
        "garden glove", "coffee grinder", "personalized gift",
        "aromatherapy", "smart watch", "wireless earbuds",
        "led strip", "yoga mat", "dog collar", "cat toy",
        "kitchen organizer", "storage box", "birthday gift",
        "wedding gift", "christmas decoration", "halloween costume",
        "party supply", "wall art", "phone case", "laptop stand",
    ]

    CATEGORY_MAP = {
        "kitchen": ["kitchen", "cooking", "gadget", "utensil", "cookware", "candle", "coffee grinder", "kitchen organizer"],
        "gift": ["gift", "present", "box", "包装礼品", "礼盒", "personalized gift", "birthday gift", "wedding gift"],
        "pet": ["pet", "dog", "cat", "animal", "toy", "dog collar", "cat toy", "pet toy"],
        "outdoor": ["outdoor", "camping", "hiking", "garden", "tent", "garden glove"],
        "beauty": ["beauty", "skincare", "cosmetic", "makeup", "aromatherapy"],
        "home": ["home decor", "decor", "furniture", "organize", "storage box", "wall art", "led strip"],
        "tech": ["smart watch", "wireless earbuds", "phone case", "laptop stand"],
        "fitness": ["fitness", "yoga", "workout", "yoga mat", "fitness equipment"],
    }

    def __init__(self, keywords: list[str] = None, lang: str = "en-US", tz: int = 360):
        """
        Args:
            keywords: 自定义关键词列表
            lang: Google Trends 语言设置
            tz: 时区偏移（360 = US EST）
        """
        try:
            from pytrends.request import TrendReq
        except ImportError:
            raise ImportError("pytrends not installed. Run: uv pip install pytrends")

        self.keywords = keywords or self.DEFAULT_KEYWORDS
        self.pytrends = TrendReq(hl=lang, tz=tz)
        self._request_count = 0

    def _rate_limit(self, min_gap_seconds: float = 5.0):
        """速率限制（Google Trends 限制约 400 req/day）"""
        if self._request_count > 0:
            time.sleep(min_gap_seconds)
        self._request_count += 1

    def get_interest_over_time(self, keyword: str, timeframe: str = "today 3-m") -> Optional[dict]:
        """
        获取关键词搜索量时间序列
        """
        self._rate_limit()

        try:
            self.pytrends.build_payload([keyword], cat=0, timeframe=timeframe)
            data = self.pytrends.interest_over_time()

            if data.empty:
                return None

            values = data[keyword].tolist()
            dates = data.index.tolist()

            if len(values) < 2:
                return None

            # 计算周环比
            weekly_velocity = 0.0
            monthly_velocity = 0.0

            if len(values) >= 7 and values[-7] > 0:
                weekly_velocity = (values[-1] - values[-7]) / values[-7]

            if len(values) >= 30 and values[-30] > 0:
                monthly_velocity = (values[-1] - values[-30]) / values[-30]

            peak_idx = values.index(max(values))
            peak_value = values[peak_idx]
            peak_date = dates[peak_idx]

            return {
                "keyword": keyword,
                "data": list(zip([str(d) for d in dates], values)),
                "peak_week": peak_date.strftime("%Y-W%W") if hasattr(peak_date, 'strftime') else str(peak_date),
                "peak_value": int(peak_value),
                "peak_date": str(peak_date),
                "current_value": int(values[-1]) if values else 0,
                "velocity_weekly": round(weekly_velocity, 4),
                "velocity_monthly": round(monthly_velocity, 4),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            print(f"[GoogleTrendsCollector] Error for '{keyword}': {e}")
            return None

    def get_related_queries(self, keyword: str, timeframe: str = "today 3-m") -> list[dict]:
        """
        获取相关查询词（发现扩散路径）
        """
        self._rate_limit()

        try:
            self.pytrends.build_payload([keyword], cat=0, timeframe=timeframe)
            related = self.pytrends.related_queries()

            rising = []
            try:
                import pandas as pd
                if keyword in related and related[keyword].get('rising') is not None:
                    df = related[keyword]['rising']
                    for _, row in df.iterrows():
                        rising.append({
                            "query": row['query'],
                            "value": int(row['value']) if pd.notna(row['value']) else 0,
                            "trend": "rising"
                        })
            except Exception:
                pass

            return rising

        except Exception as e:
            print(f"[GoogleTrendsCollector] related_queries error for '{keyword}': {e}")
            return []

    def get_interest_by_region(self, keyword: str, timeframe: str = "today 3-m") -> list[dict]:
        """
        获取关键词的地域分布
        """
        self._rate_limit()

        try:
            self.pytrends.build_payload([keyword], cat=0, timeframe=timeframe)
            data = self.pytrends.interest_by_region()

            results = []
            try:
                if hasattr(data, 'iterrows'):
                    for idx, row in data.iterrows():
                        if row[keyword] > 0:
                            results.append({
                                "geoCode": idx,
                                "geoName": idx,
                                "value": int(row[keyword])
                            })
                elif isinstance(data, dict):
                    for geo, val in data.items():
                        if isinstance(val, dict) and keyword in val and val[keyword] > 0:
                            results.append({
                                "geoCode": geo,
                                "geoName": geo,
                                "value": int(val[keyword])
                            })
            except Exception:
                pass

            return sorted(results, key=lambda x: x["value"], reverse=True)

        except Exception as e:
            print(f"[GoogleTrendsCollector] interest_by_region error for '{keyword}': {e}")
            return []

    def batch_scan(self, keywords: list[str] = None,
                   velocity_threshold: float = 0.3,
                   peak_threshold: int = 50) -> list[dict]:
        """
        批量扫描关键词，返回有异动的项
        """
        keywords = keywords or self.keywords
        signals = []

        for kw in keywords:
            try:
                trend_data = self.get_interest_over_time(kw)
                if not trend_data:
                    continue

                if (trend_data["velocity_weekly"] > velocity_threshold and
                    trend_data["peak_value"] > peak_threshold):

                    related = self.get_related_queries(kw)
                    rising = [r for r in related if r["trend"] == "rising"]

                    regions = self.get_interest_by_region(kw)
                    top_regions = regions[:5] if regions else []

                    signal = {
                        "source": "google_trends",
                        "keyword": kw,
                        "velocity_weekly": trend_data["velocity_weekly"],
                        "velocity_monthly": trend_data["velocity_monthly"],
                        "peak_value": trend_data["peak_value"],
                        "current_value": trend_data["current_value"],
                        "related_rising_count": len(rising),
                        "related_keywords": [r["query"] for r in rising[:10]],
                        "top_regions": top_regions,
                        "category": self._infer_category(kw),
                        "captured_at": trend_data["timestamp"]
                    }

                    signals.append(signal)
                    print(f"  [SIGNAL] '{kw}': velocity={trend_data['velocity_weekly']:.1%}, "
                          f"peak={trend_data['peak_value']}, rising={len(rising)}")

            except Exception as e:
                print(f"[GoogleTrendsCollector] Batch scan error for '{kw}': {e}")
                continue

        print(f"[GoogleTrendsCollector] Scan complete. {len(signals)}/{len(keywords)} "
              f"keywords triggered alerts.")
        return signals

    def _infer_category(self, keyword: str) -> str:
        """根据关键词推断品类"""
        keyword_lower = keyword.lower()
        for category, kws in self.CATEGORY_MAP.items():
            if any(kw in keyword_lower for kw in kws):
                return category
        return "general"


if __name__ == "__main__":
    print("[GoogleTrendsCollector] Running test scan...")

    collector = GoogleTrendsCollector()

    # 只测试 3 个关键词
    test_keywords = ["garden glove", "candle", "kitchen gadget"]
    results = collector.batch_scan(keywords=test_keywords, velocity_threshold=0.2)

    print(f"\n[Test] Found {len(results)} signals:")
    for r in results:
        print(f"  - {r['keyword']}: velocity={r['velocity_weekly']:.1%}, peak={r['peak_value']}")
