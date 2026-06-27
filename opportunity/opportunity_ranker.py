"""
Opportunity Ranker — 机会排序与去重

核心职责：
1. 对同类机会去重（多个信号指向同一个产品）
2. 多维度排序（Alpha Score 为主，辅以其他维度）
3. 生成 TOP 50 列表
4. 发现机会冲突（两个同类机会，一个 BUY 一个 SKIP）
"""

import re
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class RankedOpportunity:
    """排序后的机会对象"""
    opp_id: str
    name: str
    category: str
    alpha_score: float
    recommendation: str
    velocity: float = 0.0
    breadth: float = 0.0
    depth: float = 0.0
    competition_gap: float = 0.0
    seasonal_fit: float = 0.0
    confidence: float = 0.0
    signal_count: int = 0
    signals: list = field(default_factory=list)
    seasonal_window: str = ""
    days_to_window: int = 999
    is_duplicated: bool = False
    duplicate_of: str = ""

    def __hash__(self):
        return hash(self.opp_id)


class OpportunityRanker:
    """
    机会排序器

    排序逻辑：
    1. Alpha Score 降序
    2. 同分：confidence 降序
    3. 同分：velocity 降序

    去重逻辑：
    1. 关键词相似度去重（garden glove ≈ garden gloves）
    2. 品类内只保留最高分
    """

    def __init__(self, min_score_for_listing: float = 45.0):
        """
        Args:
            min_score_for_listing: Alpha Score 最低阈值（低于此分数不进入列表）
        """
        self.min_score = min_score_for_listing

    def rank(self, opportunities: list, limit: int = 50) -> List[RankedOpportunity]:
        """
        排序 + 去重

        Args:
            opportunities: 已评分的 Opportunity 列表
            limit: 返回数量上限

        Returns:
            去重 + 排序后的 TOP N 列表
        """
        if not opportunities:
            return []

        # Step 1: 过滤低分
        filtered = [o for o in opportunities
                   if getattr(o, 'alpha_score', 0) >= self.min_score]

        if not filtered:
            return []

        # Step 2: 转换为 RankedOpportunity
        ranked = [self._to_ranked(o) for o in filtered]

        # Step 3: 去重
        deduped = self._deduplicate(ranked)

        # Step 4: 排序
        sorted_opps = sorted(
            deduped,
            key=lambda o: (
                -o.alpha_score,
                -o.confidence,
                -o.velocity,
                -o.signal_count
            )
        )

        # Step 5: 限制数量
        return sorted_opps[:limit]

    def _to_ranked(self, opportunity) -> RankedOpportunity:
        """将任意 Opportunity 对象转换为 RankedOpportunity"""
        return RankedOpportunity(
            opp_id=getattr(opportunity, 'opp_id', 'unknown'),
            name=getattr(opportunity, 'name', 'Unknown'),
            category=getattr(opportunity, 'category', 'general'),
            alpha_score=getattr(opportunity, 'alpha_score', 0),
            recommendation=getattr(opportunity, 'recommendation', 'WATCH'),
            velocity=getattr(opportunity, 'velocity', 0),
            breadth=getattr(opportunity, 'breadth', 0),
            depth=getattr(opportunity, 'depth', 0),
            competition_gap=getattr(opportunity, 'competition_gap', 0),
            seasonal_fit=getattr(opportunity, 'seasonal_fit', 0),
            confidence=getattr(opportunity, 'confidence', 0.5),
            signal_count=len(getattr(opportunity, 'signals', [])),
            signals=getattr(opportunity, 'signals', []),
            seasonal_window=getattr(opportunity, 'seasonal_window', ''),
            days_to_window=getattr(opportunity, 'days_to_window', 999)
        )

    def _deduplicate(self, opportunities: List[RankedOpportunity]) -> List[RankedOpportunity]:
        """
        去重：合并指向同一产品的多个信号

        方法：
        1. 提取产品名称根关键词
        2. 计算相似度（简单：编辑距离 + 包含关系）
        3. 相似度高 → 合并为一条（保留最高分）
        """
        if not opportunities:
            return []

        unique_map = {}  # root_keyword -> RankedOpportunity

        for opp in opportunities:
            root = self._extract_root_keyword(opp.name)

            if root in unique_map:
                # 合并：保留分数更高的
                existing = unique_map[root]
                if opp.alpha_score > existing.alpha_score:
                    unique_map[root] = opp
                    existing.is_duplicated = True
                    existing.duplicate_of = opp.opp_id
                    opp.is_duplicated = False
                else:
                    opp.is_duplicated = True
                    opp.duplicate_of = existing.opp_id
            else:
                unique_map[root] = opp

        return list(unique_map.values())

    def _extract_root_keyword(self, name: str) -> str:
        """
        提取产品根关键词

        处理规则：
        1. 移除复数（s/es）
        2. 移除空格和特殊字符
        3. 转小写
        """
        if not name:
            return ""

        # 转小写
        name = name.lower()

        # 移除常见产品描述词
        patterns_to_remove = [
            r'\bfor\s+\w+',      # "glove for gardening"
            r'\bwith\s+\w+',     # "candle with holder"
            r'\bnew\s+',         # "new design"
            r'\bbest\s+',        # "best selling"
            r'\bhot\s+',         # "hot sale"
            r'\b2024\b',         # 年份
            r'\b2025\b',
            r'\b2026\b',
        ]

        for pattern in patterns_to_remove:
            name = re.sub(pattern, '', name)

        # 移除复数
        name = re.sub(r'(s|es)$', '', name)

        # 移除特殊字符
        name = re.sub(r'[^a-z0-9]', '', name)

        return name.strip()

    def get_top_opportunities(self,
                            opportunities: list,
                            recommendation: str = None,
                            category: str = None,
                            limit: int = 10) -> List[RankedOpportunity]:
        """
        获取 TOP 机会，支持过滤

        Args:
            opportunities: 机会列表
            recommendation: 按评级过滤（STRONG_BUY/BUY/WATCH）
            category: 按品类过滤
            limit: 返回数量
        """
        ranked = self.rank(opportunities, limit=100)  # 先取足够多

        if recommendation:
            ranked = [o for o in ranked if o.recommendation == recommendation]

        if category:
            ranked = [o for o in ranked if o.category == category]

        return ranked[:limit]

    def generate_report(self, opportunities: list, limit: int = 50) -> str:
        """
        生成文本格式的机会报告（用于终端输出）

        Returns:
            多行文本报告
        """
        ranked = self.rank(opportunities, limit=limit)

        if not ranked:
            return "No opportunities found."

        lines = []
        lines.append("=" * 70)
        lines.append(f"{'Rank':<5} {'Product':<30} {'Category':<10} {'Score':<6} {'Signal':<5} {'Window':<15}")
        lines.append("=" * 70)

        for i, opp in enumerate(ranked, 1):
            window_str = f"{opp.seasonal_window} ({opp.days_to_window}d)" if opp.seasonal_window else "无"
            lines.append(
                f"{i:<5} {opp.name[:28]:<30} {opp.category:<10} "
                f"{opp.alpha_score:<6.1f} {opp.signal_count:<5} {window_str:<15}"
            )

        lines.append("=" * 70)
        lines.append(f"Total: {len(ranked)} opportunities")

        # 统计
        rec_counts = {}
        for opp in ranked:
            rec_counts[opp.recommendation] = rec_counts.get(opp.recommendation, 0) + 1

        lines.append(f"STRONG_BUY: {rec_counts.get('STRONG_BUY', 0)} | "
                     f"BUY: {rec_counts.get('BUY', 0)} | "
                     f"WATCH: {rec_counts.get('WATCH', 0)}")

        return "\n".join(lines)


if __name__ == "__main__":
    # 简单测试
    from dataclasses import dataclass

    @dataclass
    class MockOpportunity:
        opp_id: str
        name: str
        category: str
        alpha_score: float
        recommendation: str
        velocity: float = 0.0
        breadth: float = 0.0
        depth: float = 0.0
        competition_gap: float = 0.0
        seasonal_fit: float = 0.0
        confidence: float = 0.8
        signal_count: int = 1
        signals: list = None
        seasonal_window: str = ""
        days_to_window: int = 999

        def __post_init__(self):
            if self.signals is None:
                self.signals = []

    opportunities = [
        MockOpportunity("1", "Garden Gloves", "outdoor", 78, "STRONG_BUY", velocity=72),
        MockOpportunity("2", "Garden Glove", "outdoor", 75, "BUY", velocity=70),
        MockOpportunity("3", "Coffee Grinder", "kitchen", 82, "STRONG_BUY", velocity=65),
        MockOpportunity("4", "Pet Toy", "pet", 55, "WATCH", velocity=30),
        MockOpportunity("5", "Smart Watch", "tech", 68, "BUY", velocity=55),
    ]

    ranker = OpportunityRanker()
    ranked = ranker.rank(opportunities)

    print(ranker.generate_report(opportunities))
