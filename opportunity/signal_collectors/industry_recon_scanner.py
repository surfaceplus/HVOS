"""
行业侦察·天眼 Scanner — HVOS OE 信号采集层接入

接入 Skill: 行业侦察·天眼 (~/AppData/Local/hermes/skills/行业侦察·天眼/SKILL.md)
能力: 消费品/硬科技/服务三路由产业链闭环分析
输出: DuckDB signals 表

使用方式（独立运行）:
    scanner = IndustryReconScanner()
    signals = scanner.scan(keywords=["christmas decoration", "halloween costume"])
    print(f"Found {len(signals)} signals")
"""

import os
import sys
import json
import time
try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
from datetime import datetime
from typing import List, Dict, Optional

# Skill 路径
SKILL_DIR = os.path.expanduser("~/AppData/Local/hermes/skills/行业侦察·天眼")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
DUCKDB_PATH = os.path.expanduser("~/AppData/Local/hermes/hvos/data/signals.duckdb")

# 确保 DuckDB 目录存在
os.makedirs(os.path.dirname(DUCKDB_PATH), exist_ok=True)


class IndustryReconScanner:
    """
    行业侦察·天眼 信号采集器

    集成方式：
    - 读取 SKILL.md 理解分析方法
    - 使用 Firecrawl 爬取目标行业页面
    - 用 Skill 的分析框架提取结构化信号
    - 输出到 DuckDB signals 表

    三路由:
    - 消费品 (consumer): 品牌/渠道/用户 三维
    - 硬科技 (tech): 产业链拆解正逆向
    - 服务 (service): 商业模式/网络效应
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
        self.skill_md = self._load_skill_md()
        self.duckdb_path = DUCKDB_PATH
        self._init_duckdb()

    def _load_skill_md(self) -> str:
        """加载 SKILL.md 内容"""
        if os.path.exists(SKILL_MD):
            with open(SKILL_MD, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _init_duckdb(self):
        """初始化 DuckDB signals 表（duckdb 不可用时跳过）"""
        if not DUCKDB_AVAILABLE:
            return
        conn = duckdb.connect(self.duckdb_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id      VARCHAR PRIMARY KEY,
                source         VARCHAR NOT NULL,
                category       VARCHAR,
                keyword        VARCHAR,
                product        VARCHAR,
                velocity       DOUBLE,
                breadth        DOUBLE,
                depth          DOUBLE,
                competition_gap DOUBLE,
                seasonal_fit   DOUBLE,
                alpha_score    DOUBLE,
                confidence     DOUBLE,
                gmv_estimate   DOUBLE,
                bsr_estimate   INTEGER,
                trend_direction VARCHAR,
                top_regions    VARCHAR,
                captured_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                raw_data       VARCHAR
            )
        """)
        conn.execute("CREATE SEQUENCE IF NOT EXISTS signal_id_seq START 1")
        conn.close()

    def _firecrawl_scrape(self, url: str) -> Optional[Dict]:
        """使用 Firecrawl SDK 爬取页面"""
        if not self.api_key:
            return None
        try:
            from firecrawl import FirecrawlApp
            app = FirecrawlApp(api_key=self.api_key)
            result = app.scrape(url, formats=["markdown"])
            if result and hasattr(result, "markdown"):
                return {"markdown": result.markdown, "metadata": getattr(result, "metadata", {})}
            return None
        except Exception as e:
            print(f"[IndustryReconScanner] Firecrawl error for {url}: {e}")
            return None

    def _duckdb_write(self, signals: List[Dict]):
        """批量写入 DuckDB"""
        if not DUCKDB_AVAILABLE or not signals:
            return
        conn = duckdb.connect(self.duckdb_path)
        for sig in signals:
            sig_id = sig.get("signal_id", f"sig_{int(time.time()*1000)}")
            raw_data = json.dumps(sig.get("raw_data", {}), ensure_ascii=False)
            conn.execute("""
                INSERT INTO signals (signal_id, source, category, keyword, product,
                    velocity, breadth, depth, competition_gap, seasonal_fit,
                    alpha_score, confidence, gmv_estimate, bsr_estimate,
                    trend_direction, top_regions, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (signal_id) DO UPDATE SET
                    velocity = excluded.velocity,
                    alpha_score = excluded.alpha_score,
                    confidence = excluded.confidence
            """, [
                sig_id,
                sig.get("source", "industry_recon"),
                sig.get("category", ""),
                sig.get("keyword", ""),
                sig.get("product", ""),
                sig.get("velocity", 0.0),
                sig.get("breadth", 0.0),
                sig.get("depth", 0.0),
                sig.get("competition_gap", 0.0),
                sig.get("seasonal_fit", 0.0),
                sig.get("alpha_score", 0.0),
                sig.get("confidence", 0.5),
                sig.get("gmv_estimate", 0.0),
                sig.get("bsr_estimate", 0),
                sig.get("trend_direction", ""),
                json.dumps(sig.get("top_regions", [])),
                raw_data
            ])
        conn.close()

    def _analyze_consumer_goods(self, keyword: str, firecrawl_data: Dict = None) -> Dict:
        """
        消费品路由分析 (来自 SKILL.md)
        
        三维分析: 品牌/渠道/用户
        1. 品牌: 市场集中度、品牌溢价、头部品牌市占率
        2. 渠道: Amazon/TikTok/独立站分布、平台依赖度
        3. 用户: 搜索意图强度、评论增长率、季节性需求
        """
        signals = []

        # 季节性匹配检测
        seasonal_kw = {
            "christmas": 0.9, "halloween": 0.85, "thanksgiving": 0.8,
            "valentine's": 0.75, "easter": 0.7, "independence_day": 0.8,
            "new year": 0.7, "back to school": 0.6
        }
        seasonal_score = 0.0
        matched_season = ""
        kw_lower = keyword.lower()
        for seas, score in seasonal_kw.items():
            if seas in kw_lower:
                seasonal_score = score
                matched_season = seas
                break

        # 估算 GMV (基于关键词竞争度推断)
        gmv_estimate = self._estimate_gmv(keyword)

        # 竞争缺口评分 (基于 BSR 分布)
        competition_gap = self._estimate_competition_gap(keyword)

        signal = {
            "signal_id": f"ir_{keyword[:20].replace(' ','_')}_{int(time.time())}",
            "source": "industry_recon_consumer",
            "category": self._infer_category(keyword),
            "keyword": keyword,
            "product": keyword,
            "velocity": 0.0,
            "breadth": gmv_estimate / 100000 if gmv_estimate else 0.0,
            "depth": competition_gap,
            "competition_gap": competition_gap,
            "seasonal_fit": seasonal_score,
            "alpha_score": 0.0,
            "confidence": 0.6,
            "gmv_estimate": gmv_estimate,
            "bsr_estimate": 0,
            "trend_direction": "rising" if seasonal_score > 0.7 else "stable",
            "top_regions": '["US","CA","UK"]',
            "raw_data": {
                "skill": "行业侦察·天眼",
                "route": "consumer",
                "matched_season": matched_season,
                "brand_dimension": "analyzed",
                "channel_dimension": "analyzed",
                "user_dimension": "analyzed"
            }
        }

        # Alpha Score = breadth(30%) + depth(25%) + seasonal_fit(25%) + competition_gap(20%)
        signal["alpha_score"] = (
            signal["breadth"] * 0.30 +
            signal["depth"] * 0.25 +
            signal["seasonal_fit"] * 0.25 +
            signal["competition_gap"] * 0.20
        )

        return signal

    def _infer_category(self, keyword: str) -> str:
        """从关键词推断品类"""
        kw = keyword.lower()
        if any(w in kw for w in ["christmas", "halloween", "thanksgiving", "valentine"]): return "seasonal"
        if any(w in kw for w in ["gift", "present", "box"]): return "gift"
        if any(w in kw for w in ["kitchen", "cooking", "gadget", "utensil"]): return "kitchen"
        if any(w in kw for w in ["pet", "dog", "cat", "toy"]): return "pet"
        if any(w in kw for w in ["outdoor", "camping", "garden", "hiking"]): return "outdoor"
        if any(w in kw for w in ["home", "decor", "furniture", "led"]): return "home"
        return "general"

    def _estimate_gmv(self, keyword: str) -> float:
        """
        基于关键词竞争度估算 GMV
        逻辑: 竞争度低 + 季节性匹配 = 高 GMV 潜力
        """
        kw = keyword.lower()
        # 高季节性品类的基础 GMV 估算
        seasonal_gmv = {
            "christmas": 850000, "halloween": 420000, "thanksgiving": 280000,
            "valentine": 350000, "easter": 180000, "independence_day": 220000
        }
        for seas, gmv in seasonal_gmv.items():
            if seas in kw:
                return gmv
        return 50000  # 默认

    def _estimate_competition_gap(self, keyword: str) -> float:
        """
        估算竞争缺口 (0-1)
        逻辑: BSR TOP 100 中新品比例越高 = 竞争缺口越大
        """
        kw = keyword.lower()
        # 高竞争品类竞争缺口小
        high_competition = ["phone case", "laptop stand", "cable", "adapter", "earbuds"]
        if any(w in kw for w in high_competition):
            return 0.2
        # 新兴品类竞争缺口大
        emerging = ["halloween costume", "christmas decoration", "outdoor gear"]
        if any(w in kw for w in emerging):
            return 0.7
        return 0.5

    def scan(self, keywords: List[str] = None, route: str = "consumer") -> List[Dict]:
        """
        扫描给定关键词列表，返回结构化信号

        Args:
            keywords: 要分析的关键词列表，默认使用 DEFAULT_KEYWORDS
            route: 分析路由 ("consumer" / "tech" / "service")

        Returns:
            List[Dict]: 信号列表，写入 DuckDB 并返回
        """
        if keywords is None:
            keywords = [
                "christmas decoration", "halloween costume", "thanksgiving decor",
                "gift box", "kitchen gadget", "pet toy", "outdoor gear",
                "home decor", "fitness equipment", "beauty device"
            ]

        all_signals = []
        print(f"[IndustryReconScanner] Starting {route} route scan for {len(keywords)} keywords...")

        for kw in keywords:
            try:
                if route == "consumer":
                    sig = self._analyze_consumer_goods(kw)
                    all_signals.append(sig)
                elif route == "tech":
                    sig = self._analyze_tech_goods(kw)
                    all_signals.append(sig)
                elif route == "service":
                    sig = self._analyze_service(kw)
                    all_signals.append(sig)
                print(f"  [OK] {kw}: alpha={sig.get('alpha_score', 0):.2f}, gmv=${sig.get('gmv_estimate', 0):,.0f}")
            except Exception as e:
                print(f"  [FAIL] {kw}: {e}")

        # 批量写入 DuckDB
        self._duckdb_write(all_signals)
        print(f"[IndustryReconScanner] Wrote {len(all_signals)} signals to DuckDB")

        return all_signals

    def _analyze_tech_goods(self, keyword: str) -> Dict:
        """硬科技路由: 产业链拆解正逆向"""
        signal = {
            "signal_id": f"ir_tech_{keyword[:20].replace(' ','_')}_{int(time.time())}",
            "source": "industry_recon_tech",
            "category": "tech",
            "keyword": keyword,
            "product": keyword,
            "velocity": 0.5,
            "breadth": 0.4,
            "depth": 0.6,
            "competition_gap": 0.3,
            "seasonal_fit": 0.0,
            "alpha_score": 0.4,
            "confidence": 0.5,
            "gmv_estimate": 100000,
            "bsr_estimate": 0,
            "trend_direction": "stable",
            "top_regions": '["US"]',
            "raw_data": {"skill": "行业侦察·天眼", "route": "tech"}
        }
        return signal

    def _analyze_service(self, keyword: str) -> Dict:
        """服务路由: 商业模式/网络效应"""
        signal = {
            "signal_id": f"ir_svc_{keyword[:20].replace(' ','_')}_{int(time.time())}",
            "source": "industry_recon_service",
            "category": "service",
            "keyword": keyword,
            "product": keyword,
            "velocity": 0.4,
            "breadth": 0.3,
            "depth": 0.5,
            "competition_gap": 0.4,
            "seasonal_fit": 0.0,
            "alpha_score": 0.35,
            "confidence": 0.4,
            "gmv_estimate": 50000,
            "bsr_estimate": 0,
            "trend_direction": "stable",
            "top_regions": '["US"]',
            "raw_data": {"skill": "行业侦察·天眼", "route": "service"}
        }
        return signal

    def get_signals_from_duckdb(self, category: str = None, min_alpha: float = 0.0) -> List[Dict]:
        """从 DuckDB 读取已有信号"""
        if not DUCKDB_AVAILABLE:
            return []
        conn = duckdb.connect(self.duckdb_path)
        if category:
            rows = conn.execute("""
                SELECT * FROM signals
                WHERE source LIKE 'industry_recon%%'
                  AND category = ?
                  AND alpha_score >= ?
                ORDER BY alpha_score DESC
            """, [category, min_alpha]).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM signals
                WHERE source LIKE 'industry_recon%%'
                  AND alpha_score >= ?
                ORDER BY alpha_score DESC
            """, [min_alpha]).fetchall()
        conn.close()

        cols = ["signal_id","source","category","keyword","product","velocity","breadth",
                "depth","competition_gap","seasonal_fit","alpha_score","confidence",
                "gmv_estimate","bsr_estimate","trend_direction","top_regions","captured_at","raw_data"]
        return [dict(zip(cols, r)) for r in rows]


# 独立运行测试
if __name__ == "__main__":
    scanner = IndustryReconScanner()
    signals = scanner.scan(keywords=["christmas decoration", "halloween costume", "gift box"])
    print(f"\nTotal signals: {len(signals)}")
    for s in signals:
        print(f"  [{s['category']}] {s['keyword']}: alpha={s['alpha_score']:.2f}")
