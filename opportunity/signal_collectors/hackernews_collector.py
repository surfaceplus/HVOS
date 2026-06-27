"""
Hacker News Signal Collector
数据源：Hacker News Firebase API（完全公开，无需认证）
采样频率：每小时

HN 数据反映：
- 科技创业者圈子的热点讨论
- 新工具/新产品的早期曝光
- DTC 相关的技术和营销趋势

信号类型：
  - Top Story Surge：某话题的 HN 分数暴涨
  - New Show HN：某产品首次出现在 Show HN（早期产品信号）
  - Comment Spike：某话题评论数暴涨
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict


class HackerNewsCollector:
    """
    Hacker News 数据采集器

    API 端点：
      - Top Stories: https://hacker-news.firebaseio.com/v0/topstories.json
      - Item: https://hacker-news.firebaseio.com/v0/item/{id}.json
      - User: https://hacker-news.firebaseio.com/v0/user/{id}.json

    无需认证，公开可用
    """

    HN_API = "https://hacker-news.firebaseio.com/v0"
    SESSION = requests.Session()
    SESSION.headers.update({
        "User-Agent": "HVOS Opportunity Engine/1.0"
    })

    # DTC 相关关键词（过滤信号）
    DTC_KEYWORDS = {
        "kitchen": ["kitchen", "cook", "candle", "coffee", "gadget", "utensil"],
        "gift": ["gift", "present", "custom", "personalized", "box"],
        "pet": ["pet", "dog", "cat", "animal", "toy"],
        "outdoor": ["outdoor", "camping", "hiking", "garden", "tent"],
        "beauty": ["beauty", "skin", "cosmetic", "makeup"],
        "home": ["home", "decor", "furniture", "organize", "storage"],
        "ecommerce": ["shopify", "etsy", "amazon fba", "dropship", "ecommerce", " DTC"],
        "marketing": ["tiktok", "instagram", "pinterest", "facebook ads", "marketing", "seo"],
        "product": ["product", "launch", "crowdfunding", "kickstarter", "indiegogo"],
    }

    def __init__(self, max_stories: int = 30):
        """
        Args:
            max_stories: 每次扫描的最多故事数（HN API 有 500 热门，取前 N）
        """
        self.max_stories = max_stories
        self._story_cache = []

    def _fetch_json(self, endpoint: str, timeout: int = 8) -> Optional[dict]:
        try:
            r = self.SESSION.get(f"{self.HN_API}/{endpoint}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def get_top_stories(self, limit: int = 30) -> List[dict]:
        """获取热门故事"""
        import concurrent.futures

        story_ids = self._fetch_json("topstories.json")
        if not story_ids:
            return []

        ids_to_fetch = story_ids[:limit]

        def fetch_story(story_id):
            return self._fetch_json(f"item/{story_id}.json")

        stories = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_story, sid): sid for sid in ids_to_fetch}
            for future in concurrent.futures.as_completed(futures, timeout=20):
                try:
                    story = future.result()
                    if story and story.get("type") == "story" and story.get("title"):
                        stories.append(story)
                except Exception:
                    pass

        # 按分数排序
        stories.sort(key=lambda x: x.get("score", 0), reverse=True)
        return stories[:limit]

    def get_show_hn_stories(self, hours: int = 72, limit: int = 20) -> List[dict]:
        """获取 Show HN 故事（新产品首次曝光）"""
        import concurrent.futures

        story_ids = self._fetch_json("topstories.json")
        if not story_ids:
            return []

        cutoff = datetime.now() - timedelta(hours=hours)

        # 先预取所有故事 ID（批量减少等待时间）
        def fetch_item(story_id):
            return self._fetch_json(f"item/{story_id}.json")

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(fetch_item, sid): sid for sid in story_ids[:200]}
            for future in concurrent.futures.as_completed(futures, timeout=25):
                try:
                    story = future.result()
                    if story and story.get("type") == "story":
                        time_val = story.get("time", 0)
                        if time_val:
                            story_time = datetime.fromtimestamp(time_val)
                            if story_time >= cutoff:
                                results[story.get("id")] = story
                except Exception:
                    pass

        # 过滤 Show HN
        stories = []
        for story in results.values():
            title = story.get("title", "").lower()
            if "show hn:" in title:
                stories.append(story)

        stories.sort(key=lambda x: x.get("score", 0), reverse=True)
        return stories[:limit]

    def filter_dtc_signals(self, stories: List[dict]) -> List[dict]:
        """
        过滤出与 DTC 相关的机会信号

        Returns:
            [{"source": "hackernews", "story": {...}, "matched_categories": [...], ...}
        """
        signals = []

        for story in stories:
            title = story.get("title", "").lower()
            text = (story.get("text") or "").lower()
            combined = title + " " + text

            matched = set()
            for category, keywords in self.DTC_KEYWORDS.items():
                for kw in keywords:
                    if kw in combined:
                        matched.add(category)
                        break

            if matched:
                score = story.get("score", 0)
                comments = story.get("descendants", 0)

                signals.append({
                    "source": "hackernews",
                    "story_id": story.get("id"),
                    "title": story.get("title"),
                    "url": story.get("url") or f"https://news.ycombinator.com/item?id={story.get('id')}",
                    "hn_url": f"https://news.ycombinator.com/item?id={story.get('id')}",
                    "score": score,
                    "comments": comments,
                    "matched_categories": list(matched),
                    "by": story.get("by", ""),
                    "time": datetime.fromtimestamp(story["time"]).isoformat() if story.get("time") else "",
                    "captured_at": datetime.now().isoformat()
                })

        # 按分数排序
        signals.sort(key=lambda x: x["score"], reverse=True)
        return signals

    def scan_dtc_opportunities(self, hours: int = 168) -> List[dict]:
        """
        主扫描方法：获取 HN DTC 相关机会信号

        Args:
            hours: 回溯时间窗口（默认 7 天）

        Returns:
            [{"source": "hackernews", "keyword": "...", "opportunity_score": 85, ...}, ...]
        """
        print("[HackerNewsCollector] Fetching top stories...")
        top_stories = self.get_top_stories(limit=self.max_stories)

        print(f"[HackerNewsCollector] Fetching Show HN (last {hours}h)...")
        show_hn = self.get_show_hn_stories(hours=hours)

        all_stories = top_stories + show_hn

        print(f"[HackerNewsCollector] Filtering DTC signals from {len(all_stories)} stories...")
        signals = self.filter_dtc_signals(all_stories)

        print(f"[HackerNewsCollector] Found {len(signals)} DTC signals")
        return signals

    def batch_scan(self, hours: int = 168) -> List[dict]:
        """批量扫描接口（统一采集器接口）"""
        return self.scan_dtc_opportunities(hours=hours)


if __name__ == "__main__":
    collector = HackerNewsCollector()
    signals = collector.batch_scan(hours=72)

    print(f"\nFound {len(signals)} DTC signals:")
    for s in signals[:10]:
        print(f"  [{s['score']:>4} pts] [{', '.join(s['matched_categories'])}] {s['title'][:60]}")
