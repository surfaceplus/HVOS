"""
Reddit Signal Collector
数据源：Reddit API (PRAW) 或 RapidAPI Reddit API
采样频率：每小时扫描目标 Subreddit
覆盖范围：Dropshipping / Entrepreneur / SmallBusiness / AmazonSeller

依赖安装：
    pip install praw

环境变量：
    REDDIT_CLIENT_ID
    REDDIT_CLIENT_SECRET
    REDDIT_USER_AGENT
"""

import os
import re
import time
from datetime import datetime, timedelta
from collections import Counter
from typing import Optional

try:
    import praw
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False


class RedditSignalCollector:
    """
    Reddit 社区信号采集器

    核心逻辑：
    1. 扫描目标 Subreddit 的热帖
    2. 提取产品/品类关键词（NLP 预处理）
    3. 检测"某个品类的讨论量暴涨"
    4. 识别玩家正在卖什么（先行指标）

    信号类型：
      - Volume Spike：某品类讨论量周环比暴涨
      - Mentions Surge：提及次数突然增加
      - Sentiment Shift：负面→正面（口碑爆发）
    """

    TARGET_SUBREDDITS = [
        "dropshipping",        # 独立站 dropshipper 讨论
        "Entrepreneur",         # 创业讨论
        "smallbusiness",       # 小生意讨论
        "AmazonSeller",        # Amazon 卖家
        "FulfillmentByAmazon", # FBA 讨论
        "ecommerce",            # 电商综合
    ]

    # 品类关键词映射
    CATEGORY_KEYWORDS = {
        "kitchen": ["kitchen", "cooking", "gadget", "utensil", "cookware", "candle", "coffee grinder"],
        "gift": ["gift", "present", "包装礼品", "gift box", "礼盒", "personalized gift"],
        "pet": ["pet", "dog", "cat", "animal", "dog collar", "cat toy", "pet toy"],
        "outdoor": ["outdoor", "camping", "hiking", "garden", "tent", "garden glove"],
        "beauty": ["beauty", "skincare", "cosmetic", "makeup", "aromatherapy"],
        "home": ["home decor", "decor", "furniture", "organize", "storage box", "wall art", "led strip"],
        "tech": ["smart watch", "wireless earbuds", "phone case", "laptop stand", "fitness tracker"],
        "fitness": ["fitness", "yoga", "workout", "yoga mat", "fitness equipment"],
    }

    # 停用词（高频但无意义）
    STOPWORDS = {
        'the', 'is', 'at', 'which', 'on', 'a', 'an', 'and', 'or',
        'for', 'to', 'of', 'in', 'with', 'i', 'you', 'it', 'this',
        'that', 'be', 'are', 'was', 'have', 'has', 'had', 'not',
        'my', 'your', 'our', 'their', 'its', 'im', "i'm", 'get',
        'got', 'like', 'just', 'would', 'could', 'should', 'will',
        'been', 'being', 'doing', 'does', 'did', 'what', 'how',
        'when', 'where', 'why', 'can', 'cant', "can't", 'dont', "don't"
    }

    def __init__(self,
                 client_id: str = None,
                 client_secret: str = None,
                 user_agent: str = None):
        """
        Args:
            client_id: Reddit API Client ID（优先从环境变量读取）
            client_secret: Reddit API Client Secret
            user_agent: User Agent 字符串
        """
        self.client_id = client_id or os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = user_agent or os.getenv(
            "REDDIT_USER_AGENT",
            "HVOS Opportunity Engine/1.0 (by /u/hvos_team)"
        )

        self.reddit = None
        if PRAW_AVAILABLE and self.client_id and self.client_secret:
            try:
                self.reddit = praw.Reddit(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    user_agent=self.user_agent
                )
                # 验证连接
                self.reddit.user.me()
            except Exception as e:
                print(f"[RedditCollector] Reddit API connection failed: {e}")
                self.reddit = None
        else:
            if not PRAW_AVAILABLE:
                print("[RedditCollector] praw not installed. Run: pip install praw")
            else:
                print("[RedditCollector] Reddit credentials not set. "
                      "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars.")

    @property
    def is_available(self) -> bool:
        return self.reddit is not None

    def extract_keywords_from_text(self, title: str, selftext: str = "") -> list[str]:
        """
        从帖子中提取产品/品类关键词

        方法：
        1. 移除 URL 和特殊字符
        2. 分词 + 移除停用词
        3. 匹配已知品类关键词
        """
        text = (title + " " + selftext).lower()

        # 移除 URL
        text = re.sub(r'http\S+', '', text)
        # 移除特殊字符，保留字母和空格
        text = re.sub(r'[^a-z\s]', ' ', text)

        words = text.split()
        words = [w.strip() for w in words if w.strip() and len(w) > 3 and w not in self.STOPWORDS]

        # 匹配品类关键词
        matched = set()
        text_combined = ' '.join(words)

        for category, kws in self.CATEGORY_KEYWORDS.items():
            for kw in kws:
                if kw in text_combined:
                    matched.add(category)
                    break

        return list(matched)

    def scan_subreddit(self, subreddit_name: str, hours: int = 48,
                      post_limit: int = 100) -> Optional[dict]:
        """
        扫描指定 Subreddit 最近 N 小时的帖子

        Args:
            subreddit_name: Subreddit 名称（不含 r/）
            hours: 回溯时间窗口（小时）
            post_limit: 最多扫描帖子数

        Returns:
            {
                "subreddit": "dropshipping",
                "posts_scanned": 50,
                "category_counts": {"kitchen": 12, "gift": 8},
                "top_posts": [{"title": "...", "score": 500, "categories": [...]}],
                "volume_spike": False,
                "volume_ratio": 1.2,
                "captured_at": "..."
            }
        """
        if not self.is_available:
            return None

        subreddit = self.reddit.subreddit(subreddit_name)
        cutoff = datetime.now() - timedelta(hours=hours)

        posts = []
        try:
            for post in subreddit.new(limit=post_limit):
                post_time = datetime.fromtimestamp(post.created_utc)
                if post_time < cutoff:
                    break

                categories = self.extract_keywords_from_text(post.title, post.selftext)
                if categories:
                    posts.append({
                        "id": post.id,
                        "title": post.title[:100],
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "categories": categories,
                        "url": f"https://reddit.com{post.permalink}",
                        "created_utc": post.created_utc,
                        "created_time": post_time.isoformat()
                    })
        except Exception as e:
            print(f"[RedditCollector] Error scanning r/{subreddit_name}: {e}")
            return None

        # 品类计数
        all_categories = [c for p in posts for c in p["categories"]]
        category_counts = dict(Counter(all_categories))

        # 估算 Volume Spike（当前窗口 vs 历史窗口）
        # 如果有历史数据可以做对比，简化版：只看帖子数量是否异常高
        # 这里用活跃帖子数 vs 阈值
        estimated_daily_posts = len(posts) / (hours / 24)
        volume_ratio = estimated_daily_posts / 20  # 假设每天20帖为基准
        volume_spike = volume_ratio > 2.0

        return {
            "subreddit": subreddit_name,
            "posts_scanned": len(posts),
            "category_counts": category_counts,
            "top_posts": sorted(posts, key=lambda x: x["score"], reverse=True)[:5],
            "volume_spike": volume_spike,
            "volume_ratio": round(volume_ratio, 2),
            "captured_at": datetime.now().isoformat()
        }

    def batch_scan(self, hours: int = 48) -> list[dict]:
        """
        批量扫描所有目标 Subreddit，返回有信号的内容

        Returns:
            [
                {
                    "source": "reddit",
                    "subreddit": "dropshipping",
                    "category": "kitchen",
                    "post_count_48h": 12,
                    "top_posts": [...],
                    "volume_spike": True,
                    "captured_at": "..."
                },
                ...
            ]
        """
        all_signals = []

        for sr in self.TARGET_SUBREDDITS:
            try:
                result = self.scan_subreddit(sr, hours=hours)
                if not result or result["posts_scanned"] == 0:
                    continue

                # 为每个品类生成独立信号
                for category, count in result["category_counts"].items():
                    if count >= 3:  # 至少 3 帖才生成信号
                        signal = {
                            "source": "reddit",
                            "subreddit": sr,
                            "category": category,
                            "post_count": count,
                            "total_posts_scanned": result["posts_scanned"],
                            "top_posts": [p for p in result["top_posts"]
                                         if category in p["categories"]][:3],
                            "volume_spike": result["volume_spike"],
                            "volume_ratio": result["volume_ratio"],
                            "captured_at": result["captured_at"]
                        }
                        all_signals.append(signal)

                time.sleep(1)  # 避免触发 Reddit API 限流

            except Exception as e:
                print(f"[RedditCollector] Error in batch scan for r/{sr}: {e}")
                continue

        return all_signals

    def get_trending_keywords(self, subreddit_name: str = "dropshipping",
                              limit: int = 20) -> list[dict]:
        """
        获取某 Subreddit 当前热词（从标题中提取高频词）

        Returns:
            [{"keyword": "shopify", "count": 45}, {"keyword": "aliexpress", "count": 32}, ...]
        """
        if not self.is_available:
            return []

        subreddit = self.reddit.subreddit(subreddit_name)
        word_counts = Counter()

        try:
            for post in subreddit.hot(limit=limit):
                text = (post.title + " " + (post.selftext or "")).lower()
                text = re.sub(r'http\S+', '', text)
                text = re.sub(r'[^a-z\s]', ' ', text)
                words = [w.strip() for w in text.split()
                        if len(w) > 3 and w not in self.STOPWORDS]
                word_counts.update(words)
        except Exception as e:
            print(f"[RedditCollector] Error getting trending keywords: {e}")
            return []

        return [
            {"keyword": word, "count": count}
            for word, count in word_counts.most_common(limit)
        ]


if __name__ == "__main__":
    import os
    # 测试（需要设置环境变量）
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDDIT_CLIENT_SECRET")

    collector = RedditSignalCollector(
        client_id=client_id,
        client_secret=client_secret
    )

    if collector.is_available:
        print("[RedditCollector] Connected successfully")
        signals = collector.batch_scan(hours=24)
        print(f"Found {len(signals)} category signals")
        for s in signals[:5]:
            print(f"  - r/{s['subreddit']} | {s['category']}: {s['post_count']} posts")
    else:
        print("[RedditCollector] Not configured. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars.")
