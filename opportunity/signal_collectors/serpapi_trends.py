"""
SerpAPI Google Trends Collector
通过 SerpAPI 代理访问 Google Trends，绕过直接访问限制

依赖：pip install requests
API Key：https://serpapi.com 注册后获取
"""

import os
import time
import requests
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict


class SerpAPITrendsCollector:
    """
    通过 SerpAPI 获取 Google Trends 数据
    API 端点: https://serpapi.com/search
    参数: engine=google_trends, data_type=TIMESERIES
    """

    SERPAPI_BASE = "https://serpapi.com"
    _session = None

    def __init__(self, api_key: str = None):
        self.api_key = api_key or self._load_key()
        if self.api_key:
            print(f"[SerpAPITrendsCollector] API key loaded: {self.api_key[:8]}...")

    def _load_key(self) -> str:
        import os
        key = os.getenv("SERPAPI_API_KEY")
        if key:
            return key
        for p in [
            os.path.join(os.path.expanduser("~"), ".hermes", "serpapi_key.txt"),
            "C:\\Users\\Administrator\\.hermes\\serpapi_key.txt",
        ]:
            try:
                if os.path.exists(p):
                    content = open(p).read().strip()
                    if len(content) > 30:
                        return content
            except:
                pass
        return ""

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            })
        return self._session

    def _get(self, params: dict, timeout: int = 20) -> Optional[dict]:
        params["api_key"] = self.api_key
        url = self.SERPAPI_BASE + "/search?" + urllib.parse.urlencode(params)
        try:
            r = self.session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"[SerpAPITrendsCollector] Request error: {e}")
        return None

    def get_interest_over_time(self, keyword: str, geo: str = "US",
                              timeframe: str = "today 3-m") -> Optional[dict]:
        time.sleep(0.8)
        data = self._get({
            "q": keyword, "engine": "google_trends",
            "data_type": "TIMESERIES", "geo": geo, "time": timeframe
        })
        if not data:
            return None
        timeline = data.get("interest_over_time", {}).get("timeline_data", [])
        if not timeline:
            return None
        vals = [p["values"][0]["extracted_value"] for p in timeline if p.get("values")]
        if len(vals) < 2:
            return None
        vel_w = (vals[-1] - vals[-2]) / max(vals[-2], 1)
        vel_m = (vals[-1] - vals[-4]) / max(vals[-4], 1) if len(vals) >= 4 else 0
        peak_idx = vals.index(max(vals))
        return {
            "keyword": keyword,
            "values": vals,
            "peak_value": max(vals),
            "peak_date": timeline[peak_idx].get("date", ""),
            "current_value": vals[-1],
            "velocity_weekly": round(vel_w, 4),
            "velocity_monthly": round(vel_m, 4),
            "timestamp": datetime.now().isoformat()
        }

    def get_related_queries(self, keyword: str, geo: str = "US",
                          timeframe: str = "today 3-m") -> List[dict]:
        time.sleep(0.8)
        data = self._get({
            "q": keyword, "engine": "google_trends",
            "data_type": "RELATED_QUERIES", "geo": geo, "time": timeframe
        })
        if not data:
            return []
        rising = []
        try:
            for item in data.get("related_queries", {}).get("ranked_list", []):
                for entry in item.get("ranked_keyword", []):
                    if entry.get("trend") in ("BREAKING", "RISING"):
                        rising.append(entry.get("query", ""))
        except:
            pass
        return rising[:10]

    def batch_scan(self, keywords: list = None, geo: str = "US",
                  velocity_threshold: float = 0.1,
                  peak_threshold: int = 20) -> List[dict]:
        keywords = keywords or self.DEFAULT_KEYWORDS
        signals = []
        for kw in keywords:
            try:
                trend = self.get_interest_over_time(kw, geo=geo)
                if not trend:
                    continue
                if (trend["velocity_weekly"] > velocity_threshold or
                        trend.get("recovery_signal", 0) > 0.2) and trend["peak_value"] > peak_threshold:
                    related = self.get_related_queries(kw, geo=geo)
                    signals.append({
                        "source": "serpapi",
                        "keyword": kw,
                        "velocity_weekly": trend["velocity_weekly"],
                        "velocity": trend["velocity_weekly"],  # 评分器直接用
                        "velocity_monthly": trend["velocity_monthly"],
                        "peak_value": trend["peak_value"],
                        "current_value": trend["current_value"],
                        "related_rising_count": len(related),
                        "related_keywords": related,
                        "category": self._infer_category(kw),
                        "captured_at": trend["timestamp"]
                    })
                    print(f"  [SIGNAL] '{kw}': vel={trend['velocity_weekly']:+.1%}, peak={trend['peak_value']}")
            except Exception as e:
                print(f"[SerpAPITrendsCollector] Error for '{kw}': {e}")
        print(f"[SerpAPITrendsCollector] Done. {len(signals)}/{len(keywords)} signals.")
        return signals

    def _infer_category(self, keyword: str) -> str:
        keyword_lower = keyword.lower()
        for cat, kws in self.CATEGORY_MAP.items():
            if any(kw in keyword_lower for kw in kws):
                return cat
        return "general"

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
        "gift": ["gift", "present", "box", "personalized gift", "birthday gift", "wedding gift"],
        "pet": ["pet", "dog", "cat", "animal", "toy", "dog collar", "cat toy", "pet toy"],
        "outdoor": ["outdoor", "camping", "hiking", "garden", "tent", "garden glove"],
        "beauty": ["beauty", "skincare", "cosmetic", "makeup", "aromatherapy"],
        "home": ["home decor", "decor", "furniture", "organize", "storage box", "wall art", "led strip"],
        "tech": ["smart watch", "wireless earbuds", "phone case", "laptop stand"],
        "fitness": ["fitness", "yoga", "workout", "yoga mat", "fitness equipment"],
    }


if __name__ == "__main__":
    collector = SerpAPITrendsCollector()
    if not collector.api_key:
        print("No API key!")
    else:
        print(f"Testing with key: {collector.api_key[:8]}...")
        results = collector.batch_scan(
            keywords=["beauty device", "laptop stand", "wireless earbuds",
                      "yoga mat", "led strip", "personalized gift"],
            velocity_threshold=0.1
        )
        for r in results:
            print(f"  - {r['keyword']}: vel={r['velocity_weekly']:+.1%}")
