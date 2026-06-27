"""
Opportunity Engine — 主调度器

核心职责：
1. 协调所有 Signal Collector 的采集
2. 汇总多源信号 → Alpha Score 计算
3. 去重 + 排序 + 机会合并
4. 输出每日 TOP 50 Emerging Opportunities
5. 自动触发 Alert

采集频率：
  - Google Trends: 每 15 分钟
  - Reddit: 每小时
  - TikTok: 每日
  - Amazon New Releases: 每日
  - 完整扫描（所有数据源）: 每日 06:00

文件结构：
  opportunity/
  ├── __init__.py
  ├── opportunity_engine.py      ← 主引擎
  ├── alpha_scorer.py            ← Alpha Score 计算
  ├── opportunity_ranker.py       ← 排序去重
  ├── alert_dispatcher.py         ← 推送分发
  ├── signal_collectors/
  │   ├── google_trends.py
  │   ├── reddit_scraper.py
  │   ├── amazon_releases.py
  │   └── customs_data.py
  └── reports/                    ← H5 报告输出目录
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, date
from typing import Optional, List, Dict
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────
# 模块路径设置
# ──────────────────────────────────────────────────────────────
HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
OPP_DIR = os.path.join(HVOS_ROOT, "opportunity")
KG_DIR = os.path.join(HVOS_ROOT, "knowledge_graph")
DATA_DIR = os.path.join(HVOS_ROOT, "data")

# 添加到 Python path
for _p in [OPP_DIR, KG_DIR, HVOS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 新增模块
from signal_collectors.industry_recon_scanner import IndustryReconScanner
from signal_filter import SignalFilter
from signal_enricher import SignalEnricher


# ──────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────
@dataclass
class Opportunity:
    """机会数据结构"""
    opp_id: str = ""
    name: str = ""
    category: str = "general"

    # Alpha Score
    alpha_score: float = 0.0
    recommendation: str = "WATCH"

    # 评分因子
    velocity: float = 0.0
    breadth: float = 0.0
    depth: float = 0.0
    competition_gap: float = 0.0
    seasonal_fit: float = 0.0

    # 置信度
    confidence: float = 0.5
    weighted_score: float = 0.0

    # 信号
    signals: List[Dict] = field(default_factory=list)
    signal_count: int = 0

    # 市场信息
    seasonal_window: str = ""
    days_to_window: int = 999
    related_keywords: List[str] = field(default_factory=list)

    # 状态
    status: str = "discovered"   # discovered | under_review | approved | rejected | executed
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at


# ──────────────────────────────────────────────────────────────
# 季节性窗口
# ──────────────────────────────────────────────────────────────
SEASONAL_WINDOWS = {
    "父亲节": {"month": 6, "week": 3, "optimal_days": 45},
    "美国独立日": {"month": 7, "week": 4, "optimal_days": 60},
    "Back to School": {"month": 8, "week": 1, "optimal_days": 60},
    "Labor Day": {"month": 9, "week": 1, "optimal_days": 30},
    "万圣节": {"month": 10, "week": 4, "optimal_days": 45},
    "感恩节/黑五": {"month": 11, "week": 4, "optimal_days": 60},
    "圣诞": {"month": 12, "week": 4, "optimal_days": 90},
    "新年": {"month": 1, "week": 1, "optimal_days": 30},
    "情人节": {"month": 2, "week": 2, "optimal_days": 45},
    "母亲节": {"month": 5, "week": 2, "optimal_days": 45},
}

CATEGORY_KEYWORDS = {
    "kitchen": ["kitchen", "cooking", "gadget", "utensil", "cookware", "candle", "coffee grinder", "kitchen organizer"],
    "gift": ["gift", "present", "box", "包装礼品", "personalized gift", "birthday gift", "wedding gift"],
    "pet": ["pet", "dog", "cat", "animal", "dog collar", "cat toy", "pet toy"],
    "outdoor": ["outdoor", "camping", "hiking", "garden", "tent", "garden glove"],
    "beauty": ["beauty", "skincare", "cosmetic", "makeup", "aromatherapy"],
    "home": ["home decor", "decor", "furniture", "organize", "storage box", "wall art", "led strip"],
    "tech": ["smart watch", "wireless earbuds", "phone case", "laptop stand", "fitness tracker"],
    "fitness": ["fitness", "yoga", "workout", "yoga mat", "fitness equipment"],
}

DEFAULT_TRACKED_KEYWORDS = [
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


# ──────────────────────────────────────────────────────────────
# 主引擎
# ──────────────────────────────────────────────────────────────
class OpportunityEngine:
    """
    Opportunity Engine 主引擎

    使用方式：

    # 初始化（每日 06:00 完整扫描）
    engine = OpportunityEngine()
    results = engine.run_full_scan()

    # 获取 TOP 50
    top50 = engine.get_top_opportunities(limit=50)

    # 获取特定品类的机会
    kitchen_opps = engine.get_by_category("kitchen")

    # 手动触发单品类扫描
    engine.scan_category("gift")
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._opportunities: List[Opportunity] = []
        self._last_scan_time: str = ""
        self._scan_lock = threading.Lock()

        # 初始化各模块
        self._init_collectors()
        self._init_scorer()
        self._init_ranker()
        self._init_dispatcher()

        # 季节性配置
        self.seasonal_windows = SEASONAL_WINDOWS

    def _init_collectors(self):
        """初始化采集器（按优先级排序）"""
        self.collectors = {}
        self._network_available = self._check_network_health()

        # 1. SerpAPI（优先，比直接访问 Google 更稳定）
        try:
            from signal_collectors.serpapi_trends import SerpAPITrendsCollector
            serpapi_collector = SerpAPITrendsCollector()
            if serpapi_collector.api_key:
                self.collectors["serpapi"] = serpapi_collector
                print(f"[OpportunityEngine] SerpAPITrendsCollector initialized (key: {serpapi_collector.api_key[:8]}...)")
            else:
                print("[OpportunityEngine] SerpAPITrendsCollector skipped: No API key")
        except ImportError as e:
            print(f"[OpportunityEngine] SerpAPITrendsCollector not available: {e}")

        # 2. Google Trends（仅在网络通时启用，避免阻塞）
        if self._network_available and self._is_google_trends_reachable():
            try:
                from signal_collectors.google_trends import GoogleTrendsCollector
                self.collectors["google_trends"] = GoogleTrendsCollector(
                    keywords=self.config.get("tracked_keywords", DEFAULT_TRACKED_KEYWORDS)
                )
                print("[OpportunityEngine] GoogleTrendsCollector initialized")
            except ImportError as e:
                print(f"[OpportunityEngine] GoogleTrendsCollector not available: {e}")
        else:
            print("[OpportunityEngine] GoogleTrendsCollector skipped: trends.google.com unreachable")

        # 3. Reddit
        try:
            from signal_collectors.reddit_scraper import RedditSignalCollector
            self.collectors["reddit"] = RedditSignalCollector(
                client_id=self.config.get("reddit_client_id"),
                client_secret=self.config.get("reddit_client_secret")
            )
            print(f"[OpportunityEngine] RedditSignalCollector initialized (available={self.collectors['reddit'].is_available})")
        except ImportError as e:
            print(f"[OpportunityEngine] RedditSignalCollector not available: {e}")

        # 4. Amazon
        try:
            from signal_collectors.amazon_releases import AmazonNewReleasesScanner
            self.collectors["amazon"] = AmazonNewReleasesScanner()
            print("[OpportunityEngine] AmazonNewReleasesScanner initialized")
        except ImportError as e:
            print(f"[OpportunityEngine] AmazonNewReleasesScanner not available: {e}")

        # 5. Hacker News（DTC 创业者社区，无需认证）
        try:
            from signal_collectors.hackernews_collector import HackerNewsCollector
            self.collectors["hackernews"] = HackerNewsCollector()
            print("[OpportunityEngine] HackerNewsCollector initialized")
        except ImportError as e:
            print(f"[OpportunityEngine] HackerNewsCollector not available: {e}")

        # 6. 行业侦察·天眼（消费品/硬科技/服务三路由产业链分析）
        try:
            self.collectors["industry_recon"] = IndustryReconScanner()
            print("[OpportunityEngine] IndustryReconScanner initialized")
        except Exception as e:
            print(f"[OpportunityEngine] IndustryReconScanner not available: {e}")

    def _check_network_health(self) -> bool:
        """快速检测网络连通性"""
        import socket
        try:
            socket.setdefaulttimeout(2)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
            print("[OpportunityEngine] Network health: OK")
            return True
        except Exception:
            print("[OpportunityEngine] Network health: UNREACHABLE (will skip blocked sources)")
            return False

    def _is_google_trends_reachable(self, timeout_seconds: int = 3) -> bool:
        """检测 Google Trends API 是否可达（快速探针）"""
        import socket
        try:
            socket.setdefaulttimeout(timeout_seconds)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("trends.google.com", 443))
            print("[OpportunityEngine] Google Trends: reachable")
            return True
        except Exception:
            print("[OpportunityEngine] Google Trends: unreachable (will skip)")
            return False

    def _init_scorer(self):
        """初始化 Alpha Scorer"""
        from alpha_scorer import AlphaScorer
        self.scorer = AlphaScorer(
            weights=self.config.get("scorer_weights")
        )
    def _init_ranker(self):
        """初始化 Ranker"""
        from opportunity_ranker import OpportunityRanker
        self.ranker = OpportunityRanker(
            min_score_for_listing=self.config.get("min_score", 25.0)
        )

    def _init_dispatcher(self):
        """初始化 Alert Dispatcher"""
        from alert_dispatcher import AlertDispatcher
        self.dispatcher = AlertDispatcher(
            report_dir=os.path.join(OPP_DIR, "reports"),
            kg_db_path=os.path.join(KG_DIR, "kg.db")
        )

    # ──────────────────────────────────────────────────────────
    # 公开 API
    # ──────────────────────────────────────────────────────────

    def run_full_scan(self) -> dict:
        """
        完整扫描：所有数据源 → 汇总 → 评分 → 排序

        Returns:
            {
                "scan_id": "scan_202606110600",
                "scanned_at": "2026-06-11T06:00:00",
                "opportunities_found": 127,
                "top_opportunities": [Opportunity, ...],
                "alerts_triggered": 3
            }
        """
        scan_id = f"scan_{datetime.now().strftime('%Y%m%d%H%M')}"
        print(f"\n[OpportunityEngine] [{scan_id}] Starting full scan...")

        # Step 1: 并行采集所有数据源
        print(f"[OpportunityEngine] Collecting signals...")
        signals = self._collect_all_signals()
        print(f"[OpportunityEngine] Collected {len(signals)} raw signals")

        # Step 2: 信号过滤（AI数据驱动师 电商指标过滤）
        print(f"[OpportunityEngine] Filtering signals (AI电商指标)...")
        from signal_filter import SignalFilter
        signal_filter = SignalFilter()
        filtered_signals = signal_filter.apply(signals)
        filter_stats = signal_filter.get_filter_stats()
        print(f"[OpportunityEngine] Filter: {filter_stats['passed']}/{filter_stats['total']} passed "
              f"({filter_stats['rejected']} rejected)")

        # Step 2b: 补充季节性信息
        filtered_signals = signal_filter.enrich_seasonal_info(filtered_signals)

        # Step 3: 信号丰富（竞品分析 + 行业研究框架 并行）
        print(f"[OpportunityEngine] Enriching signals (竞品分析 + 行业研究)...")
        from signal_enricher import SignalEnricher
        enricher = SignalEnricher()
        enriched_signals = enricher.enrich(filtered_signals)
        enriched_count = sum(1 for s in enriched_signals if s.get("_enriched"))
        print(f"[OpportunityEngine] Enriched: {enriched_count}/{len(enriched_signals)} signals enriched")

        # Step 4: 信号汇聚（按产品/品类分组）
        print(f"[OpportunityEngine] Aggregating signals...")
        aggregated = self._aggregate_signals(enriched_signals)
        print(f"[OpportunityEngine] Aggregated into {len(aggregated)} opportunity clusters")

        # Step 5: Alpha Score 计算
        print(f"[OpportunityEngine] Calculating Alpha Scores...")
        scored = self._score_opportunities(aggregated)
        print(f"[OpportunityEngine] Scored {len(scored)} opportunities")

        # Step 4: 排序 + 去重
        print(f"[OpportunityEngine] Ranking and deduplicating...")
        ranked = self.ranker.rank(scored)
        self._opportunities = ranked

        # Step 5: 触发 Alert
        alerts = self._dispatch_alerts(ranked[:10])

        self._last_scan_time = datetime.now().isoformat()

        print(f"[OpportunityEngine] [{scan_id}] Scan complete.")
        print(f"  Opportunities found: {len(ranked)}")
        print(f"  Alerts triggered: {len(alerts)}")

        return {
            "scan_id": scan_id,
            "scanned_at": self._last_scan_time,
            "opportunities_found": len(ranked),
            "top_opportunities": ranked[:10],
            "alerts_triggered": len(alerts)
        }

    def scan_category(self, category: str) -> List[Opportunity]:
        """
        手动触发单品类增量扫描（快速响应）

        用于：用户在 Board Meeting 中对某品类感兴趣时，快速获取最新信号
        """
        print(f"[OpportunityEngine] Scanning category: {category}")

        signals = []

        # Google Trends 扫描
        if "google_trends" in self.collectors:
            try:
                kw_list = CATEGORY_KEYWORDS.get(category, [category])
                gt_signals = self.collectors["google_trends"].batch_scan(
                    keywords=kw_list, velocity_threshold=0.2
                )
                signals.extend(gt_signals)
            except Exception as e:
                print(f"[OpportunityEngine] GoogleTrends scan error: {e}")

        # 汇聚 + 评分
        aggregated = self._aggregate_signals(signals)
        scored = self._score_opportunities(aggregated)
        ranked = self.ranker.rank(scored)

        return ranked

    def get_top_opportunities(self, limit: int = 50,
                             recommendation: str = None,
                             category: str = None) -> List:
        """
        获取 TOP N 机会（默认 TOP 50）
        """
        if not self._opportunities:
            self.run_full_scan()

        opps = self._opportunities

        if recommendation:
            opps = [o for o in opps if o.recommendation == recommendation]

        if category:
            opps = [o for o in opps if o.category == category]

        return opps[:limit]

    def get_by_category(self, category: str) -> List:
        """按品类筛选机会"""
        return self.get_top_opportunities(limit=100, category=category)

    def generate_report(self, limit: int = 50) -> str:
        """生成文本格式的机会报告"""
        return self.ranker.generate_report(self._opportunities, limit=limit)

    def get_stats(self) -> dict:
        """获取扫描统计"""
        if not self._opportunities:
            return {"status": "not_scanned"}

        rec_counts = {}
        cat_counts = {}
        total_signals = 0

        for opp in self._opportunities:
            rec_counts[opp.recommendation] = rec_counts.get(opp.recommendation, 0) + 1
            cat_counts[opp.category] = cat_counts.get(opp.category, 0) + 1
            total_signals += opp.signal_count

        return {
            "total_opportunities": len(self._opportunities),
            "last_scan_time": self._last_scan_time,
            "recommendation_distribution": rec_counts,
            "category_distribution": cat_counts,
            "total_signals_collected": total_signals,
            "avg_alpha_score": round(sum(o.alpha_score for o in self._opportunities) / len(self._opportunities), 1)
        }

    # ──────────────────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────────────────

    def _collect_all_signals(self) -> List[Dict]:
        """
        并行采集所有数据源
        使用线程池避免阻塞
        """
        all_signals = []
        errors = []

        def collect_serpapi():
            try:
                if "serpapi" in self.collectors:
                    return self.collectors["serpapi"].batch_scan() or []
                return []
            except Exception as e:
                errors.append(f"SerpAPI: {e}")
                return []

        def collect_google():
            try:
                if "google_trends" in self.collectors:
                    return self.collectors["google_trends"].batch_scan() or []
                return []
            except Exception as e:
                errors.append(f"GoogleTrends: {e}")
                return []

        def collect_reddit():
            try:
                if self.collectors.get("reddit") and self.collectors["reddit"].is_available:
                    return self.collectors["reddit"].batch_scan(hours=48) or []
                return []
            except Exception as e:
                errors.append(f"Reddit: {e}")
                return []

        def collect_hackernews():
            try:
                if "hackernews" in self.collectors:
                    hn_signals = self.collectors["hackernews"].batch_scan(hours=72) or []
                    # HN 信号转换：故事 → 机会格式
                    signals = []
                    for s in hn_signals:
                        categories = s.get("matched_categories", [])
                        for cat in categories:
                            signals.append({
                                "source": "hackernews",
                                "category": cat,
                                "product": s.get("title", ""),
                                "story_score": s.get("score", 0),
                                "comments": s.get("comments", 0),
                                "url": s.get("url", ""),
                                "hn_url": s.get("hn_url", ""),
                                "captured_at": datetime.now().isoformat()
                            })
                    return signals
                return []
            except Exception as e:
                errors.append(f"HackerNews: {e}")
                return []

        def collect_amazon():
            try:
                if "amazon" in self.collectors:
                    amazon_results = self.collectors["amazon"].batch_scan() or []
                    signals = []
                    for r in amazon_results:
                        if "products" in r:
                            for p in r.get("products", [])[:20]:
                                signals.append({
                                    "source": "amazon",
                                    "category": r.get("category", "general"),
                                    "product": p.get("title", ""),
                                    "brand": p.get("brand", ""),
                                    "rank": p.get("rank", 0),
                                    "rating": p.get("rating", 0),
                                    "captured_at": datetime.now().isoformat()
                                })
                    return signals
                return []
            except Exception as e:
                errors.append(f"Amazon: {e}")
                return []

        def collect_industry_recon():
            try:
                if "industry_recon" in self.collectors:
                    return self.collectors["industry_recon"].batch_scan() or []
                return []
            except Exception as e:
                errors.append(f"IndustryRecon: {e}")
                return []

        # 并行执行
        threads = []
        results = {}

        for name, fn in [
            ("serpapi", collect_serpapi),
            ("google", collect_google),
            ("reddit", collect_reddit),
            ("hackernews", collect_hackernews),
            ("amazon", collect_amazon),
            ("industry_recon", collect_industry_recon)
        ]:
            t = threading.Thread(target=lambda n, f: results.update({n: f()}), args=(name, fn))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=90)

        for name in ["serpapi", "google", "reddit", "amazon"]:
            signals = results.get(name, [])
            if signals:
                all_signals.extend(signals)
            elif not signals and name == "hackernews":
                # HN 采集中但未完成，跳过（HN 是最后才加入的）
                pass

        # HackerNews 单独同步调用（6秒，快速可靠）
        if not all_signals:
            # 仅当其他数据源全为空时，用 HN 补充
            try:
                if "hackernews" in self.collectors:
                    print("[OpportunityEngine] Supplementing with HackerNews...")
                    hn_signals = self.collectors["hackernews"].batch_scan(hours=72) or []
                    signals = []
                    for s in hn_signals:
                        for cat in s.get("matched_categories", []):
                            signals.append({
                                "source": "hackernews",
                                "category": cat,
                                "product": s.get("title", ""),
                                "story_score": s.get("score", 0),
                                "comments": s.get("comments", 0),
                                "url": s.get("url", ""),
                                "hn_url": s.get("hn_url", ""),
                                "captured_at": datetime.now().isoformat()
                            })
                    all_signals.extend(signals)
                    print(f"[OpportunityEngine] HackerNews补充: {len(signals)} 个信号")
                    # HN 信号注入 velocity（故事分数 → 速度代理）
                    # HN story_score > 200 = velocity 0.4, > 100 = 0.2, 其他 = 0.1
                    for sig in signals:
                        story_score = sig.get("story_score", 0)
                        if story_score > 200:
                            sig["velocity"] = 0.4
                        elif story_score > 100:
                            sig["velocity"] = 0.2
                        else:
                            sig["velocity"] = 0.1
                            # HN story_score 高 = 社区热度 → 给季节性加分
                            sig["seasonal_bonus"] = 30 if story_score > 150 else 0
            except Exception as e:
                print(f"[OpportunityEngine] HackerNews补充失败: {e}")

        # SerpAPI 补充（HackerNews之后，真实 Google Trends 数据）
        if not all_signals:
            try:
                if "serpapi" in self.collectors and self.collectors["serpapi"].api_key:
                    print("[OpportunityEngine] Supplementing with SerpAPI (Google Trends)...")
                    serpapi_signals = self.collectors["serpapi"].batch_scan() or []
                    for s in serpapi_signals:
                        s["velocity"] = s.get("velocity_weekly", 0)
                    all_signals.extend(serpapi_signals)
                    print(f"[OpportunityEngine] SerpAPI补充: {len(serpapi_signals)} 个信号")
            except Exception as e:
                print(f"[OpportunityEngine] SerpAPI补充失败: {e}")

        # 如果所有真实数据源都失败，使用模拟数据（演示模式）
        if not all_signals:
            print("[OpportunityEngine] All real sources failed. Using demo data.")
            all_signals = self._generate_demo_signals()

        if errors:
            print(f"[OpportunityEngine] Collector errors: {errors}")

        return all_signals

    def _generate_demo_signals(self) -> List[Dict]:
        """
        生成演示用模拟信号（当所有数据源不可用时使用）
        用于演示和测试完整流程
        """
        return [
            {
                "source": "google_trends",
                "keyword": "garden glove",
                "velocity_weekly": 0.72,
                "velocity_monthly": 0.45,
                "peak_value": 85,
                "current_value": 72,
                "related_rising_count": 5,
                "related_keywords": ["gardening gloves", "work gloves", "latex gloves"],
                "top_regions": [{"geo": "US", "value": 100}],
                "category": "outdoor",
                "captured_at": datetime.now().isoformat()
            },
            {
                "source": "reddit",
                "subreddit": "dropshipping",
                "category": "kitchen",
                "post_count": 15,
                "volume_spike": True,
                "captured_at": datetime.now().isoformat()
            },
            {
                "source": "amazon",
                "category": "gift",
                "product": "Personalized Gift Box",
                "rank": 3,
                "rating": 4.7,
                "captured_at": datetime.now().isoformat()
            }
        ]

    def _aggregate_signals(self, signals: List[Dict]) -> Dict[str, Dict]:
        """
        将原始信号按产品/品类关键词汇聚

        Returns:
            {
                "garden_glove": {
                    "keyword": "garden glove",
                    "signals": [...],
                    "sources_active": 3,
                    "supplier_count": 4,
                    "shipment_volume": 1200
                },
                ...
            }
        """
        aggregated = {}

        for signal in signals:
            source = signal.get("source", "unknown")

            if source == "google_trends":
                keyword = signal.get("keyword", "")
                if not keyword:
                    continue
                if keyword not in aggregated:
                    aggregated[keyword] = {
                        "keyword": keyword,
                        "signals": [],
                        "category": signal.get("category", self._infer_category(keyword)),
                        "supplier_count": 3,
                        "shipment_volume": 0
                    }
                aggregated[keyword]["signals"].append(signal)

            elif source == "serpapi":
                # SerpAPI 信号：和 google_trends 同样处理
                keyword = signal.get("keyword", "")
                if not keyword:
                    continue
                if keyword not in aggregated:
                    aggregated[keyword] = {
                        "keyword": keyword,
                        "signals": [],
                        "category": signal.get("category", self._infer_category(keyword)),
                        "supplier_count": 3,
                        "shipment_volume": 0
                    }
                aggregated[keyword]["signals"].append(signal)

            elif source == "hackernews":
                # HN 信号：使用产品名称作为关键词
                product = signal.get("product", "")
                category = signal.get("category", "general")
                key = product[:40] if product else category
                if not key:
                    continue
                if key not in aggregated:
                    aggregated[key] = {
                        "keyword": key,
                        "signals": [],
                        "category": category,
                        "supplier_count": 2,
                        "shipment_volume": 0
                    }
                aggregated[key]["signals"].append(signal)

            elif source == "reddit":
                category = signal.get("category", "general")
                if category not in aggregated:
                    aggregated[category] = {
                        "keyword": category,
                        "signals": [],
                        "category": category,
                        "supplier_count": 2,
                        "shipment_volume": 0
                    }
                aggregated[category]["signals"].append(signal)

            elif source == "amazon":
                product = signal.get("product", "")
                category = signal.get("category", "general")
                key = product[:30] if product else category
                if key not in aggregated:
                    aggregated[key] = {
                        "keyword": key,
                        "signals": [],
                        "category": category,
                        "supplier_count": 2,
                        "shipment_volume": 0
                    }
                aggregated[key]["signals"].append(signal)

        # 统计各聚合的活跃信号源
        for key, data in aggregated.items():
            sources = set(s.get("source", "unknown") for s in data["signals"])
            data["sources_active"] = len(sources)

        return aggregated

    def _score_opportunities(self, aggregated: Dict[str, Dict]) -> List[Opportunity]:
        """
        对汇聚后的机会进行 Alpha Score 计算
        """
        scored_opportunities = []

        for keyword, data in aggregated.items():
            signals = data["signals"]
            sources_active = data.get("sources_active", len(signals))

            # 提取 Google Trends 速度信号
            velocity_signal = next(
                (s for s in signals if s.get("source") == "google_trends"), None
            )

            # HN 信号velocity注入：从信号dict中取
            if not velocity_signal:
                for s in signals:
                    if s.get("source") == "hackernews" and "velocity" in s:
                        velocity_signal = {
                            "source": "hackernews",
                            "velocity_weekly": s["velocity"],
                            "peak_value": s.get("story_score", 100),
                            "related_rising_count": 1
                        }
                        break
                    elif s.get("source") == "serpapi" and "velocity" in s:
                        velocity_signal = {
                            "source": "serpapi",
                            "velocity_weekly": s["velocity"],
                            "peak_value": s.get("peak_value", 50),
                            "related_rising_count": s.get("related_rising_count", 0)
                        }
                        break

            # 计算季节性
            seasonal = self._calculate_seasonal_fit(keyword)

            # Alpha Score 计算
            result = self.scorer.calculate_alpha_score(
                velocity_signal=velocity_signal,
                breadth_signals=signals,
                depth_supplier_count=data.get("supplier_count", 3),
                depth_volume=data.get("shipment_volume", 0),
                competition_top_share=0.35,  # 默认值
                competition_new_entrants=sources_active,
                days_to_seasonal_window=seasonal["days_to_window"]
            )

            # 构建 Opportunity 对象
            opp = Opportunity(
                opp_id=f"opp_{self._sanitize_id(keyword)}_{datetime.now().strftime('%Y%m%d%H%M')}",
                name=keyword.title(),
                category=data.get("category", self._infer_category(keyword)),
                alpha_score=result.alpha_score,
                recommendation=result.recommendation,
                velocity=result.velocity_score,
                breadth=result.breadth_score,
                depth=result.depth_score,
                competition_gap=result.competition_gap_score,
                seasonal_fit=result.seasonal_score,
                confidence=result.confidence,
                weighted_score=result.weighted_score,
                signals=signals,
                signal_count=sources_active,
                seasonal_window=seasonal["window_name"],
                days_to_window=seasonal["days_to_window"],
                related_keywords=velocity_signal.get("related_keywords", []) if velocity_signal else []
            )

            scored_opportunities.append(opp)

        return scored_opportunities

    def _dispatch_alerts(self, top_opportunities: List) -> List[dict]:
        """对 TOP 机会触发 Alert"""
        alerts = []

        for opp in top_opportunities:
            if opp.recommendation in ("STRONG_BUY", "BUY") and opp.alpha_score >= 35:
                try:
                    alert_result = self.dispatcher.dispatch(opp)
                    alerts.append(alert_result)
                except Exception as e:
                    print(f"[OpportunityEngine] Alert dispatch error for {opp.name}: {e}")

        return alerts

    def _calculate_seasonal_fit(self, keyword: str) -> Dict:
        """
        计算某关键词与当前季节性窗口的匹配度
        """
        now = date.today()

        for window_name, config in self.seasonal_windows.items():
            target_month = config["month"]

            # 计算下一个窗口日期
            if now.month < target_month:
                target_year = now.year
            elif now.month > target_month:
                target_year = now.year + 1
            else:
                # 同月：检查是否已过窗口期
                target_year = now.year

            from calendar import monthrange
            _, last_day = monthrange(target_year, target_month)
            window_day = min(config["week"] * 7, last_day)
            window_date = date(target_year, target_month, window_day)

            days_to = (window_date - now).days

            if 0 <= days_to <= config["optimal_days"] + 30:
                return {
                    "window_name": window_name,
                    "days_to_window": days_to,
                    "optimal_days": config["optimal_days"]
                }

        return {"window_name": "无季节性窗口", "days_to_window": 999, "optimal_days": 45}

    def _infer_category(self, keyword: str) -> str:
        """根据关键词推断品类"""
        keyword_lower = keyword.lower()
        for category, kws in CATEGORY_KEYWORDS.items():
            if any(kw in keyword_lower for kw in kws):
                return category
        return "general"

    def _sanitize_id(self, text: str) -> str:
        """将文本转换为安全的 ID"""
        import re
        text = text.lower()
        text = re.sub(r'[^a-z0-9]', '_', text)
        text = re.sub(r'_+', '_', text)
        return text[:30]


# ──────────────────────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS Opportunity Engine")
    parser.add_argument("--action", default="scan", choices=["scan", "stats", "report"])
    parser.add_argument("--category", default=None, help="Scan specific category")
    parser.add_argument("--limit", type=int, default=50, help="TOP N limit")
    parser.add_argument("--recommendation", default=None, help="Filter by recommendation")
    parser.add_argument("--config", default=None, help="Config JSON file")

    args = parser.parse_args()

    config = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, "r") as f:
            config = json.load(f)

    engine = OpportunityEngine(config=config)

    if args.action == "scan":
        if args.category:
            print(f"[OpportunityEngine] Scanning category: {args.category}")
            results = engine.scan_category(args.category)
            print(f"Found {len(results)} opportunities")
            for o in results[:10]:
                print(f"  {o.alpha_score:.1f} | {o.recommendation:<12} | {o.name}")
        else:
            results = engine.run_full_scan()
            print(f"\n[Results]")
            print(f"  Total opportunities: {results['opportunities_found']}")
            print(f"  Alerts triggered: {results['alerts_triggered']}")
            print(f"\n{engine.generate_report(limit=args.limit)}")

    elif args.action == "stats":
        stats = engine.get_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))

    elif args.action == "report":
        print(engine.generate_report(limit=args.limit))
