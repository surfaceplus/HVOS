"""
HVOS Core Object Model (HCOM)
==============================
统一对象模型：HVOS 所有 engine 必须围绕这三种对象运转。


OpportunityObject  - 机会对象
CapitalEvent       - 资金事件
MarketSignal       - 市场信号

所有 engine 的输入/输出必须使用这些类型。

V10.1 (2026-06-25):
  融合 ecommerce-product-picker 技能:
  - BSR 销量转换模型字段
  - 社交热度字段（TikTok/XHS）
  - 1688 供应链成本字段
  - ProductDNA 利润计算
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple
from datetime import datetime
from enum import Enum
import uuid
import json


class SignalPlatform(str, Enum):
    TIKTOK = "tiktok"
    AMAZON = "amazon"
    META = "meta"
    GOOGLE = "google"
    REDDIT = "reddit"
    HACKERNEWS = "hackernews"
    XIAOHONGSHU = "xiaohongshu"
    ALIEXPRESS = "aliexpress"
    P1688 = "1688"


class TrendPhase(str, Enum):
    EMERGING = "emerging"
    PEAK = "peak"
    DECLINING = "declining"
    SATURATED = "saturated"


class OpportunityStage(str, Enum):
    DISCOVER = "discover"
    VALIDATE = "validate"
    SCALE = "scale"
    HOLD = "hold"
    STOP = "stop"


class CapitalEventType(str, Enum):
    AD_SPEND = "ad_spend"
    INVENTORY = "inventory"
    PROFIT = "profit"
    LOSS = "loss"
    REFUND = "refund"
    REVENUE = "revenue"
    CAC = "cac"
    ROI = "roi"


class Decision(str, Enum):
    INVEST = "invest"
    SCALE = "scale"
    HOLD = "hold"
    STOP = "stop"
    WAIT = "wait"


@dataclass
class MarketSignal:
    platform: SignalPlatform
    strength: float
    velocity: float
    direction: str
    trend_phase: TrendPhase
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: dict = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["trend_phase"] = self.trend_phase.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MarketSignal":
        d["platform"] = SignalPlatform(d["platform"])
        d["trend_phase"] = TrendPhase(d["trend_phase"])
        return cls(**d)


@dataclass
class CapitalEvent:
    event_type: CapitalEventType
    amount: float
    currency: str = "USD"
    linked_opportunity: str = ""
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    notes: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: dict = field(default_factory=dict)

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    @property
    def abs_amount(self) -> float:
        return abs(self.amount)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CapitalEvent":
        d["event_type"] = CapitalEventType(d["event_type"])
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────────────
# V10.1 新增：ProductDNA — 来自电商选品技能的销量/利润基因数据
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProductDNA:
    """
    ProductDNA — 产品基因数据
    融合自 ecommerce-product-picker 的 BSR 销量转换模型 + 1688 成本建模
    """
    # 销量预估（国内）
    domestic_monthly_sales_low: int = 0
    domestic_monthly_sales_high: int = 0
    domestic_sales_ref: str = ""

    # 销量预估（跨境 Amazon BSR）
    cross_border_monthly_sales_low: int = 0
    cross_border_monthly_sales_high: int = 0
    bsr_rank: int = 0

    # 社交热度
    xiaohongshu_notes: int = 0
    xiaohongshu_avg_likes: int = 0
    tiktok_views: int = 0
    tiktok_viral: str = "unknown"

    # 供应链成本（1688）
    cost_1688_cny: float = 0.0
    logistics_usd: float = 3.5
    fba_usd: float = 6.5
    platform_fee_pct: float = 0.15

    # 利润计算结果
    total_cost_usd: float = 0.0
    suggested_price_usd: float = 0.0
    gross_margin_pct: float = 0.0
    monthly_profit_low: float = 0.0
    monthly_profit_high: float = 0.0

    # 链接
    amazon_link: str = ""
    aliexpress_link: str = ""

    def to_dict(self) -> dict:
        return {
            "domestic_monthly_sales": f"{self.domestic_monthly_sales_low:,}-{self.domestic_monthly_sales_high:,}",
            "domestic_sales_ref": self.domestic_sales_ref,
            "cross_border_monthly_sales": f"{self.cross_border_monthly_sales_low:,}-{self.cross_border_monthly_sales_high:,}",
            "bsr_rank": self.bsr_rank,
            "xiaohongshu": {"notes": self.xiaohongshu_notes, "avg_likes": self.xiaohongshu_avg_likes},
            "tiktok": {"views": self.tiktok_views, "viral": self.tiktok_viral},
            "cost_1688_cny": self.cost_1688_cny,
            "total_cost_usd": round(self.total_cost_usd, 2),
            "suggested_price_usd": round(self.suggested_price_usd, 2),
            "gross_margin_pct": round(self.gross_margin_pct, 1),
            "monthly_profit": f"${self.monthly_profit_low:,.0f}-${self.monthly_profit_high:,.0f}",
            "amazon_link": self.amazon_link,
        }

    def calc_profit(self, price_usd: float, fx: float = 7.2) -> Tuple[float, float]:
        """
        跨境利润计算
        fx: USD/CNY 汇率，默认7.2
        返回 (total_cost_usd, gross_margin_pct)
        """
        self.suggested_price_usd = price_usd
        self.total_cost_usd = (self.cost_1688_cny / fx) + self.logistics_usd + self.fba_usd + (price_usd * self.platform_fee_pct)
        self.gross_margin_pct = (price_usd - self.total_cost_usd) / price_usd * 100 if price_usd > 0 else 0
        profit_per_unit = price_usd - self.total_cost_usd
        self.monthly_profit_low = profit_per_unit * self.cross_border_monthly_sales_low
        self.monthly_profit_high = profit_per_unit * self.cross_border_monthly_sales_high
        return self.total_cost_usd, self.gross_margin_pct


@dataclass
class OpportunityObject:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    product_name: str = ""
    product_niche: str = ""
    signal_sources: List[str] = field(default_factory=list)

    demand_score: float = 0.0
    trend_score: float = 0.0
    supply_score: float = 0.0
    margin_estimate: float = 0.0
    risk_score: float = 0.0
    confidence: float = 0.0

    signals: List[MarketSignal] = field(default_factory=list)
    capital_events: List[CapitalEvent] = field(default_factory=list)
    stage: OpportunityStage = OpportunityStage.DISCOVER

    outcome_p10: float = 0.0
    outcome_p50: float = 0.0
    outcome_p90: float = 0.0
    probability_of_success: float = 0.0

    # V10.1 ProductDNA
    product_dna: ProductDNA = field(default_factory=ProductDNA)

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    stage_changed_at: datetime = field(default_factory=datetime.now)

    current_decision: Decision = Decision.WAIT
    decision_reason: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def is_worth_investing(self) -> bool:
        return (
            self.confidence > 0.5 and
            self.probability_of_success > 0.4 and
            self.risk_score < 7.0 and
            self.margin_estimate > 20.0
        )

    @property
    def weighted_score(self) -> float:
        return (
            self.demand_score * 0.30 +
            self.trend_score * 0.25 +
            self.supply_score * 0.15 +
            (10 - self.risk_score) * 0.20 +
            self.confidence * 0.10
        )

    @property
    def roi_estimate(self) -> float:
        return self.margin_estimate * self.probability_of_success

    @property
    def days_in_stage(self) -> int:
        return (datetime.now() - self.stage_changed_at).days

    def update_signals(self, signal: MarketSignal):
        self.signals.append(signal)
        self.updated_at = datetime.now()

    def add_capital_event(self, event: CapitalEvent):
        event.linked_opportunity = self.id
        self.capital_events.append(event)
        self.updated_at = datetime.now()

    def transition_to(self, new_stage: OpportunityStage, reason: str = ""):
        if new_stage != self.stage:
            self.stage = new_stage
            self.stage_changed_at = datetime.now()
            self.updated_at = datetime.now()
            if reason:
                self.decision_reason = reason

    def update_decision(self, decision: Decision, reason: str = ""):
        self.current_decision = decision
        if reason:
            self.decision_reason = reason
        self.updated_at = datetime.now()

    def apply_outcome_prediction(self, p10: float, p50: float, p90: float, prob: float):
        self.outcome_p10 = p10
        self.outcome_p50 = p50
        self.outcome_p90 = p90
        self.probability_of_success = prob
        self.updated_at = datetime.now()

    def apply_product_dna(self, dna: ProductDNA):
        """从电商选品数据填充 ProductDNA"""
        self.product_dna = dna
        if dna.gross_margin_pct > 0 and self.margin_estimate == 0:
            self.margin_estimate = dna.gross_margin_pct
        self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_name": self.product_name,
            "product_niche": self.product_niche,
            "signal_sources": self.signal_sources,
            "demand_score": self.demand_score,
            "trend_score": self.trend_score,
            "supply_score": self.supply_score,
            "margin_estimate": self.margin_estimate,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "signals": [s.to_dict() for s in self.signals],
            "capital_events": [e.to_dict() for e in self.capital_events],
            "stage": self.stage.value,
            "outcome_p10": self.outcome_p10,
            "outcome_p50": self.outcome_p50,
            "outcome_p90": self.outcome_p90,
            "probability_of_success": self.probability_of_success,
            "product_dna": self.product_dna.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "stage_changed_at": self.stage_changed_at.isoformat(),
            "current_decision": self.current_decision.value,
            "decision_reason": self.decision_reason,
            "metadata": self.metadata,
            "is_worth_investing": self.is_worth_investing,
            "weighted_score": round(self.weighted_score, 2),
            "roi_estimate": round(self.roi_estimate, 2),
            "days_in_stage": self.days_in_stage,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityObject":
        d["signals"] = [MarketSignal.from_dict(s) for s in d.get("signals", [])]
        d["capital_events"] = [CapitalEvent.from_dict(e) for e in d.get("capital_events", [])]
        d["stage"] = OpportunityStage(d.get("stage", "discover"))
        d["current_decision"] = Decision(d.get("current_decision", "wait"))
        if "product_dna" in d and isinstance(d["product_dna"], dict):
            pd = d["product_dna"]
            d["product_dna"] = ProductDNA(
                domestic_monthly_sales_low=pd.get("domestic_monthly_sales_low", 0),
                domestic_monthly_sales_high=pd.get("domestic_monthly_sales_high", 0),
                domestic_sales_ref=pd.get("domestic_sales_ref", ""),
                cross_border_monthly_sales_low=pd.get("cross_border_monthly_sales_low", 0),
                cross_border_monthly_sales_high=pd.get("cross_border_monthly_sales_high", 0),
                bsr_rank=pd.get("bsr_rank", 0),
                xiaohongshu_notes=pd.get("xiaohongshu_notes", 0),
                xiaohongshu_avg_likes=pd.get("xiaohongshu_avg_likes", 0),
                tiktok_views=pd.get("tiktok_views", 0),
                tiktok_viral=pd.get("tiktok_viral", "unknown"),
                cost_1688_cny=pd.get("cost_1688_cny", 0.0),
                logistics_usd=pd.get("logistics_usd", 3.5),
                fba_usd=pd.get("fba_usd", 6.5),
                platform_fee_pct=pd.get("platform_fee_pct", 0.15),
                total_cost_usd=pd.get("total_cost_usd", 0.0),
                suggested_price_usd=pd.get("suggested_price_usd", 0.0),
                gross_margin_pct=pd.get("gross_margin_pct", 0.0),
                monthly_profit_low=pd.get("monthly_profit_low", 0.0),
                monthly_profit_high=pd.get("monthly_profit_high", 0.0),
                amazon_link=pd.get("amazon_link", ""),
                aliexpress_link=pd.get("aliexpress_link", ""),
            )
        for ts in ["created_at", "updated_at", "stage_changed_at"]:
            if isinstance(d.get(ts), str):
                d[ts] = datetime.fromisoformat(d[ts])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SystemDecision:
    opportunity_id: str
    decision: Decision
    confidence: float
    reason: str
    priority: int = 0
    allocated_budget: float = 0.0
    max_risk: float = 0.0
    scenario: str = "base"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


def new_opportunity(product_name: str, niche: str = "") -> OpportunityObject:
    return OpportunityObject(product_name=product_name, product_niche=niche)


def new_capital_event(event_type: CapitalEventType, amount: float,
                      source: str = "", linked_opportunity: str = "") -> CapitalEvent:
    return CapitalEvent(event_type=event_type, amount=amount,
                        source=source, linked_opportunity=linked_opportunity)


def new_market_signal(platform: SignalPlatform, strength: float, velocity: float,
                      direction: str, trend_phase: TrendPhase) -> MarketSignal:
    return MarketSignal(platform=platform, strength=strength, velocity=velocity,
                        direction=direction, trend_phase=trend_phase)


def new_product_dna(domestic_low=0, domestic_high=0, cb_low=0, cb_high=0,
                    cost_cny=0.0, logistics_usd=3.5, fba_usd=6.5,
                    platform_pct=0.15, xhs_notes=0, tiktok_views=0,
                    bsr=0, selling_price=0.0) -> ProductDNA:
    """工厂函数：从选品数据构造 ProductDNA"""
    dna = ProductDNA(
        domestic_monthly_sales_low=domestic_low,
        domestic_monthly_sales_high=domestic_high,
        cross_border_monthly_sales_low=cb_low,
        cross_border_monthly_sales_high=cb_high,
        cost_1688_cny=cost_cny,
        logistics_usd=logistics_usd,
        fba_usd=fba_usd,
        platform_fee_pct=platform_pct,
        xiaohongshu_notes=xhs_notes,
        tiktok_views=tiktok_views,
        bsr_rank=bsr,
    )
    if selling_price > 0:
        dna.calc_profit(selling_price)
    return dna


if __name__ == "__main__":
    opp = new_opportunity("宠物手套", "pet_grooming")
    opp.demand_score = 7.5
    opp.trend_score = 8.0
    opp.supply_score = 5.0
    opp.risk_score = 4.0
    opp.confidence = 0.72
    opp.margin_estimate = 35.0
    opp.probability_of_success = 0.68
    opp.stage = OpportunityStage.VALIDATE
    opp.update_decision(Decision.INVEST, "高分+趋势向上+置信度高")

    # V10.1 ProductDNA
    dna = new_product_dna(
        domestic_low=15000, domestic_high=25000,
        cb_low=8000, cb_high=15000,
        cost_cny=18.0, logistics_usd=5.5, fba_usd=6.5,
        platform_pct=0.15, xhs_notes=30000,
        tiktok_views=1800000, bsr=500,
        selling_price=22.9
    )
    opp.apply_product_dna(dna)

    print("=== HVOS HCOM V10.1 Test ===")
    print(f"ProductDNA 月利润: {opp.product_dna.to_dict()['monthly_profit']}")
    print(f"毛利率: {opp.product_dna.gross_margin_pct:.1f}%")
    print(f"总成本: ${opp.product_dna.total_cost_usd:.2f}")
    print(f"Draft ROI: {opp.roi_estimate:.1f}%")
