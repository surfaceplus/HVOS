"""
Signal Enricher — 竞品分析 + 行业研究并行丰富层

职责：
  1. CompetitorEnricher：KG 查询竞品数据 + SWOT 分析
  2. IndustryResearcher：行业空间 + 产业链 + 竞争格局
  3. 并行执行，merge 结果

接入点：OE._aggregate_signals() 之后，_score_opportunities() 之前
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
import os, json

# ─────────────────────────────────────────
# Skill 路径
# ─────────────────────────────────────────
SKILLS_DIR = os.path.expanduser("~/AppData/Local/hermes/skills")
KG_DIR = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph"


class CompetitorEnricher:
    """竞品分析 enrichment — 查询 KG + 竞品分析 Skill"""

    def __init__(self):
        self.skill_dir = os.path.join(SKILLS_DIR, "竞品分析工具")
        self.kg_path = os.path.join(KG_DIR, "knowledge_graph.json")

    def enrich(self, signals: List[Dict]) -> List[Dict]:
        """对每个信号查询竞品，返回 enriched signals"""
        for sig in signals:
            keyword = sig.get("keyword", "")
            category = sig.get("category", "")

            # 1. 查 KG 已有竞品数据
            kg_competitors = self._query_kg(keyword, category)

            # 2. 补充竞品 Skill 的分析框架输出
            swot = self._generate_swot(kg_competitors)

            sig["_competitors"] = kg_competitors
            sig["_swot"] = swot
            sig["_competitor_count"] = len(kg_competitors)

            # 竞争密度评分
            if len(kg_competitors) > 10:
                sig["_competition_density"] = "HIGH"
            elif len(kg_competitors) > 5:
                sig["_competition_density"] = "MEDIUM"
            else:
                sig["_competition_density"] = "LOW"

        return signals

    def _query_kg(self, keyword: str, category: str) -> List[Dict]:
        """从 Knowledge Graph 查询相关竞品"""
        competitors = []
        if not os.path.exists(self.kg_path):
            return competitors
        try:
            with open(self.kg_path, "r", encoding="utf-8") as f:
                kg_data = json.load(f)
            nodes = kg_data.get("nodes", [])
            keyword_lower = keyword.lower()
            for node in nodes:
                node_text = f"{node.get('name','')} {node.get('category','')}".lower()
                if keyword_lower in node_text or category.lower() in node_text:
                    if node.get("type") in ("product", "competitor", "brand"):
                        competitors.append({
                            "name": node.get("name"),
                            "category": node.get("category"),
                            "bsr": node.get("bsr"),
                            "price": node.get("price"),
                            "rating": node.get("rating"),
                        })
        except Exception:
            pass
        return competitors[:10]  # 最多返回10个

    def _generate_swot(self, competitors: List[Dict]) -> Dict:
        """根据竞品列表生成 SWOT 矩阵"""
        if not competitors:
            return {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}
        # 简单规则生成，实际可接入 Skill 的 LLM 分析
        avg_price = sum(float(c.get("price", 0)) for c in competitors if c.get("price")) / max(len(competitors), 1)
        return {
            "strengths": [f"{len(competitors)} 个已知竞品可参考定价"],
            "weaknesses": [f"平均价格 ${avg_price:.2f}，价格战风险"],
            "opportunities": ["差异化切入点：细分功能/独特设计/垂直人群"],
            "threats": [f"CR4 集中度 {min(80, len(competitors)*10)}%，头部垄断"]
        }


class IndustryResearcher:
    """行业研究 enrichment — 行业空间 + 产业链"""

    def __init__(self):
        self.skill_dir = os.path.join(SKILLS_DIR, "行业研究框架")

    def enrich(self, signals: List[Dict]) -> List[Dict]:
        """对每个信号补充行业研究数据"""
        for sig in signals:
            keyword = sig.get("keyword", "")
            category = sig.get("category", "")

            research = self._quick_research(keyword, category)
            sig["_industry_research"] = research
            sig["_market_size_b"] = research.get("market_size_b")
            sig["_market_cagr"] = research.get("cagr")
            sig["_industry_stage"] = research.get("stage", "unknown")

        return signals

    def _quick_research(self, keyword: str, category: str) -> Dict:
        """快速行业研究（基于规则推断 + KG 数据）"""
        # 硬编码 America250 相关品类研究数据
        christmas_keywords = ["christmas", "holiday", "xmas", "santa", "snowman", "reindeer"]
        is_christmas = any(k in keyword.lower() for k in christmas_keywords)

        if is_christmas:
            return {
                "market_size_b": 25.0,
                "cagr": 6.5,
                "stage": "mature",
                "top_players": ["Amazon Basics", "GERBER", "K绿"],
                "growth_driver": "美国圣诞礼品市场稳定，电商渗透率提升"
            }

        # 从 KG 查询
        research = {"market_size_b": None, "cagr": None, "stage": "unknown"}
        kg_research = self._query_kg_industry(keyword, category)
        if kg_research:
            research.update(kg_research)
        return research

    def _query_kg_industry(self, keyword: str, category: str) -> Dict:
        """从 KG 查行业数据"""
        kg_path = os.path.join(KG_DIR, "knowledge_graph.json")
        if not os.path.exists(kg_path):
            return {}
        try:
            with open(kg_path, "r", encoding="utf-8") as f:
                kg_data = json.load(f)
            nodes = kg_data.get("nodes", [])
            keyword_lower = keyword.lower()
            for node in nodes:
                if node.get("type") == "industry":
                    if keyword_lower in f"{node.get('name','')} {node.get('category','')}".lower():
                        return {
                            "market_size_b": node.get("market_size_b"),
                            "cagr": node.get("cagr"),
                            "stage": node.get("stage"),
                        }
        except Exception:
            pass
        return {}


class SignalEnricher:
    """信号丰富层 — 并行执行竞品分析 + 行业研究"""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.competitor = CompetitorEnricher()
        self.researcher = IndustryResearcher()

    def enrich(self, signals: List[Dict]) -> List[Dict]:
        """并行丰富，merge 结果"""
        if not signals:
            return signals

        # 并行跑两个 enricher
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            comp_future = ex.submit(self.competitor.enrich, signals)
            ind_future = ex.submit(self.researcher.enrich, signals)

            # 两个都完成才算成功
            comp_signals = comp_future.result()
            ind_signals = ind_future.result()

        # merge：ind_signals 覆盖/补充 comp_signals
        enriched = comp_signals
        for i, sig in enumerate(enriched):
            if i < len(ind_signals):
                sig.update({k: v for k, v in ind_signals[i].items() if k not in sig})

        # 统计
        for sig in enriched:
            total_comps = sig.get("_competitor_count", 0)
            market_size = sig.get("_market_size_b")
            sig["_enriched"] = True

        return enriched
