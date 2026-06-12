"""
Alpha Score 计算引擎

核心公式：

Alpha Score = Signal_Velocity × 0.35
            + Signal_Breadth × 0.25
            + Signal_Depth × 0.15
            + Competition_Gap × 0.15
            + Seasonal_Fit × 0.10

其中每个因子都是 0-100 的标准化分数
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class OpportunitySignal:
    """单一信号数据结构"""
    source: str                      # 数据来源：google_trends | reddit | tiktok | amazon | customs
    signal_type: str                 # 信号类型：velocity | volume | surge | etc.
    raw_value: float                 # 原始值
    normalized_score: float           # 0-100 标准化分数
    timestamp: str = ""

    # 信号质量指标
    confidence: float = 0.0          # 信号置信度（数据质量）
    velocity: float = 0.0           # 变化速度
    volume: float = 0.0             # 绝对规模
    trend: str = "unknown"          # rising | falling | stable

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class AlphaScoreResult:
    """Alpha Score 计算结果"""
    alpha_score: float               # 最终 Alpha Score（0-100）
    recommendation: str              # STRONG_BUY / BUY / WATCH / SKIP

    # 因子分解
    velocity_score: float = 0.0
    breadth_score: float = 0.0
    depth_score: float = 0.0
    competition_gap_score: float = 0.0
    seasonal_score: float = 0.0

    # 原始因子值
    velocity_raw: float = 0.0
    breadth_raw: int = 0
    depth_raw_suppliers: int = 0
    depth_raw_volume: float = 0.0
    competition_top_share: float = 0.0
    competition_new_entrants: int = 0
    days_to_window: int = 999

    # 信号质量
    confidence: float = 0.0
    weighted_score: float = 0.0      # 折扣前的加权分数
    signal_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "alpha_score": round(self.alpha_score, 1),
            "recommendation": self.recommendation,
            "breakdown": {
                "velocity": {"score": round(self.velocity_score, 1), "raw": self.velocity_raw, "weight": 0.35},
                "breadth": {"score": round(self.breadth_score, 1), "sources_active": self.breadth_raw, "weight": 0.25},
                "depth": {"score": round(self.depth_score, 1), "suppliers": self.depth_raw_suppliers, "volume": self.depth_raw_volume, "weight": 0.15},
                "competition_gap": {"score": round(self.competition_gap_score, 1), "top_share": self.competition_top_share, "new_entrants": self.competition_new_entrants, "weight": 0.15},
                "seasonal": {"score": round(self.seasonal_score, 1), "days_to_window": self.days_to_window, "weight": 0.10}
            },
            "confidence": round(self.confidence, 2),
            "weighted_score": round(self.weighted_score, 1),
            "signal_sources": self.signal_sources
        }


class AlphaScorer:
    """
    Alpha Score 计算引擎

    将多源异构信号归一化为统一的 Alpha Score

    处理流程：
    1. 归一化（Min-Max）：各信号源尺度不同，需要对齐
    2. 聚合（Weighted Sum）：加权求和
    3. 去噪（Confidence Discount）：低置信度信号打折
    4. 排序（Rank-based）：输出排序结果
    """

    # 因子权重（可配置）
    WEIGHTS = {
        "velocity": 0.35,           # 信号增长斜率
        "breadth": 0.25,           # 跨平台信号汇聚程度
        "depth": 0.15,             # 供应链深度
        "competition_gap": 0.15,    # 竞争缺口
        "seasonal": 0.10            # 季节性窗口
    }

    # 置信度折扣表（各数据源可靠性）
    CONFIDENCE_DISCOUNT = {
        "google_trends": 0.95,
        "reddit": 0.80,
        "tiktok": 0.85,
        "amazon": 0.90,
        "customs": 0.75,
        "hackernews": 0.85,
        "serpapi": 0.90,     # SerpAPI = Google Trends 同级（真实数据）
    }

    # 季节性窗口配置
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

    def __init__(self, weights: dict = None):
        """
        Args:
            weights: 自定义因子权重（覆盖默认值）
        """
        if weights:
            self.WEIGHTS = {**self.WEIGHTS, **weights}

    # ────────────────────────────────────────────────────────────
    # 归一化方法
    # ────────────────────────────────────────────────────────────

    def normalize_velocity(self, velocity: float) -> float:
        """
        归一化增长斜率

        velocity > 1.0（100%）= 100分
        velocity = 0（无增长）= 0分
        velocity < 0（下降）= 0分（不做负分，防止惩罚下降趋势）
        """
        import math
        if velocity <= 0:
            return 0.0
        # velocity=1.0 → 100分，velocity=2.0 → 120分（允许溢出）
        normalized = velocity * 100
        return min(100, normalized)

    def normalize_breadth(self, active_sources: int, max_sources: int = 5) -> float:
        """
        归一化跨平台信号汇聚程度

        5个平台全有 = 100分
        3个平台 = 60分
        1个平台 = 20分
        """
        score = (active_sources / max_sources) * 100
        return min(100, score)

    def normalize_depth(self, supplier_count: int, total_volume: float) -> float:
        """
        归一化供应链深度

        4个以上稳定供应商 + 高出货量 = 100分
        1个供应商 = 30分

        供应商越多（货源分散）→ 越安全
        出货量越大 → 市场越热
        """
        # 供应商得分（4+ = 满分）
        supplier_score = min(100, supplier_count * 25)

        # 出货量得分（1000+ 提单 = 满分，线性插值）
        volume_score = min(100, (total_volume / 1000) * 100) if total_volume > 0 else 0

        return (supplier_score * 0.6 + volume_score * 0.4)

    def normalize_competition_gap(self, top_player_share: float,
                                 new_entrants_count: int) -> float:
        """
        归一化竞争缺口

        top_player_share 越低（没有绝对垄断）= 高分
        new_entrants 越多 = 市场越热 = 竞争越激烈

        Returns 0-100（越高=竞争缺口越大=越有机会）
        """
        # 没有绝对霸主 = 机会（50%市占率品牌 → 扣25分）
        monopoly_penalty = top_player_share * 50

        # 适度的新进入者 = 市场热 = 好事（最多+20分）
        # 但太多新进入者 = 竞争加剧 = 坏事
        if new_entrants_count <= 3:
            entry_bonus = new_entrants_count * 5
        elif new_entrants_count <= 10:
            entry_bonus = 15 + (new_entrants_count - 3) * 1
        else:
            entry_bonus = max(0, 22 - (new_entrants_count - 10) * 2)

        return max(0, min(100, 100 - monopoly_penalty + entry_bonus))

    def normalize_seasonal(self, days_to_window: int, optimal_days: int = 45) -> float:
        """
        归一化季节性窗口

        30-60天 = 100分（正好在启动期）
        14-30天 = 70分（还来得及）
        7-14天 = 70分（紧急但可接受）
        < 7天 = 60分（来不及备货，但已有库存可售）
        > 90天 = 20分（太早）
        """
        if days_to_window == 999:
            return 50.0  # 无季节性窗口，中性分数

        if 30 <= days_to_window <= 60:
            return 100.0
        elif 14 <= days_to_window < 30:
            return 70.0
        elif 7 <= days_to_window < 14:
            return 70.0
        elif days_to_window < 7:
            return 60.0
        else:
            # > 60 天，越远越低
            return max(20, 100 - (days_to_window - 60) * 1.5)

    # ────────────────────────────────────────────────────────────
    # 主计算方法
    # ────────────────────────────────────────────────────────────

    def calculate_alpha_score(
        self,
        velocity_signal: Optional[dict] = None,
        # velocity_signal 格式：{"velocity_weekly": 0.72, "peak_value": 85, ...}
        breadth_signals: Optional[List[dict]] = None,
        # breadth_signals 格式：[{"source": "google_trends", ...}, {"source": "reddit", ...}, ...]
        depth_supplier_count: int = 3,
        depth_volume: float = 0.0,
        competition_top_share: float = 0.35,
        competition_new_entrants: int = 3,
        days_to_seasonal_window: int = 999,
        optimal_seasonal_days: int = 45,
        confidence_override: float = None
    ) -> AlphaScoreResult:
        """
        计算单一机会的 Alpha Score

        Args:
            velocity_signal: Google Trends 等速度信号（dict格式）
            breadth_signals: 跨平台信号列表（list of dict）
            depth_supplier_count: 供应商数量
            depth_volume: 海关出货量
            competition_top_share: Top 竞品市场份额
            competition_new_entrants: 新进入者数量
            days_to_seasonal_window: 距下一个季节性窗口天数
            optimal_seasonal_days: 最优季节性窗口天数
            confidence_override: 手动置信度（用于测试）

        Returns:
            AlphaScoreResult 对象
        """
        breadth_signals = breadth_signals or []

        # 1. Velocity
        velocity_raw = velocity_signal.get("velocity_weekly", 0) if velocity_signal else 0.0
        velocity_score = self.normalize_velocity(velocity_raw)

        # 2. Breadth（跨平台信号汇聚）
        active_source_set = set()
        if velocity_signal:
            active_source_set.add(velocity_signal.get("source", "google_trends"))
        for s in breadth_signals:
            active_source_set.add(s.get("source", "unknown"))
        active_source_count = len(active_source_set)
        breadth_score = self.normalize_breadth(active_source_count)

        # 3. Depth
        depth_score = self.normalize_depth(depth_supplier_count, depth_volume)

        # 4. Competition Gap
        gap_score = self.normalize_competition_gap(
            competition_top_share, competition_new_entrants
        )

        # 5. Seasonal
        seasonal_score = self.normalize_seasonal(
            days_to_seasonal_window, optimal_seasonal_days
        )

        # 加权求和（未折扣）
        weighted = (
            velocity_score * self.WEIGHTS["velocity"] +
            breadth_score * self.WEIGHTS["breadth"] +
            depth_score * self.WEIGHTS["depth"] +
            gap_score * self.WEIGHTS["competition_gap"] +
            seasonal_score * self.WEIGHTS["seasonal"]
        )

        # 置信度折扣
        if confidence_override is not None:
            avg_confidence = confidence_override
        else:
            if active_source_set:
                avg_confidence = sum(
                    self.CONFIDENCE_DISCOUNT.get(s, 0.5)
                    for s in active_source_set
                ) / len(active_source_set)
            else:
                avg_confidence = 0.5

        alpha_score = weighted * avg_confidence

        # Recommendation 判定（ serpapi 单源信号 alpha 约 32-36，调低阈值）
        if alpha_score >= 55:
            recommendation = "STRONG_BUY"
        elif alpha_score >= 35:
            recommendation = "BUY"
        elif alpha_score >= 20:
            recommendation = "WATCH"
        else:
            recommendation = "SKIP"

        return AlphaScoreResult(
            alpha_score=round(alpha_score, 1),
            recommendation=recommendation,
            velocity_score=round(velocity_score, 1),
            breadth_score=round(breadth_score, 1),
            depth_score=round(depth_score, 1),
            competition_gap_score=round(gap_score, 1),
            seasonal_score=round(seasonal_score, 1),
            velocity_raw=round(velocity_raw, 4),
            breadth_raw=active_source_count,
            depth_raw_suppliers=depth_supplier_count,
            depth_raw_volume=depth_volume,
            competition_top_share=competition_top_share,
            competition_new_entrants=competition_new_entrants,
            days_to_window=days_to_seasonal_window,
            confidence=round(avg_confidence, 2),
            weighted_score=round(weighted, 1),
            signal_sources=list(active_source_set)
        )

    def find_nearest_seasonal_window(self) -> tuple:
        """
        找到最近的季节性销售窗口

        Returns:
            (window_name, days_to_window)
        """
        now = datetime.now()

        for window_name, config in self.SEASONAL_WINDOWS.items():
            target_month = config["month"]
            # 计算下一个窗口日期
            if now.month < target_month:
                target_year = now.year
            elif now.month > target_month:
                target_year = now.year + 1
            else:
                # 同月，检查是否已过
                target_year = now.year

            from calendar import monthrange
            _, last_day = monthrange(target_year, target_month)
            # 使用第3周的周一作为窗口日
            window_day = min(config["week"] * 7, last_day)
            from datetime import date
            window_date = date(target_year, target_month, window_day)

            days_to = (window_date - now.date()).days

            if days_to >= 0:
                return window_name, days_to, config["optimal_days"]

        return "无季节性窗口", 999, 45


def demo():
    """演示 Alpha Score 计算"""
    scorer = AlphaScorer()

    # 模拟 Google Trends 信号
    velocity_signal = {
        "source": "google_trends",
        "velocity_weekly": 0.72,
        "peak_value": 85,
        "related_rising_count": 5
    }

    # 模拟跨平台信号汇聚
    breadth_signals = [
        {"source": "google_trends", "velocity": 0.72},
        {"source": "reddit", "volume": 15},
        {"source": "amazon", "new_entrants": 3}
    ]

    window_name, days_to, _ = scorer.find_nearest_seasonal_window()

    result = scorer.calculate_alpha_score(
        velocity_signal=velocity_signal,
        breadth_signals=breadth_signals,
        depth_supplier_count=4,
        depth_volume=1200,
        competition_top_share=0.35,
        competition_new_entrants=3,
        days_to_seasonal_window=days_to
    )

    print(f"Alpha Score: {result.alpha_score}")
    print(f"Recommendation: {result.recommendation}")
    print(f"Score Breakdown: {result.to_dict()['breakdown']}")
    print(f"Sources: {result.signal_sources}")


if __name__ == "__main__":
    demo()
