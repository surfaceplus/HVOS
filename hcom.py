"""
HVOS Core Object Model (HCOM)
==============================
统一对象模型：HVOS 所有 engine 必须围绕这三种对象运转。

OpportunityObject  - 机会对象
CapitalEvent       - 资金事件
MarketSignal       - 市场信号

所有 engine 的输入/输出必须使用这些类型。
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List
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

    def to_dict(self) -> dict:
        d = {
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
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityObject":
        d["signals"] = [MarketSignal.from_dict(s) for s in d.get("signals", [])]
        d["capital_events"] = [CapitalEvent.from_dict(e) for e in d.get("capital_events", [])]
        d["stage"] = OpportunityStage(d.get("stage", "discover"))
        d["current_decision"] = Decision(d.get("current_decision", "wait"))
        for ts_field in ["created_at", "updated_at", "stage_changed_at"]:
            if isinstance(d.get(ts_field), str):
                d[ts_field] = datetime.fromisoformat(d[ts_field])
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


def new_capital_event(
    event_type: CapitalEventType, amount: float,
    source: str = "", linked_opportunity: str = ""
) -> CapitalEvent:
    return CapitalEvent(
        event_type=event_type, amount=amount,
        source=source, linked_opportunity=linked_opportunity
    )


def new_market_signal(
    platform: SignalPlatform, strength: float, velocity: float,
    direction: str, trend_phase: TrendPhase
) -> MarketSignal:
    return MarketSignal(
        platform=platform, strength=strength, velocity=velocity,
        direction=direction, trend_phase=trend_phase
    )


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
    opp.update_decision(Decision.INVEST, "高分 + 趋势向上 + 置信度高")
    print("=== OpportunityObject Test ===")
    print(f"ID: {opp.id}")
    print(f"Weighted Score: {opp.weighted_score:.2f}")
    print(f"ROI Estimate: {opp.roi_estimate:.1f}%")
    print(f"Is Worth Investing: {opp.is_worth_investing}")
    print(f"Decision: {opp.current_decision.value}")
    print(opp.to_json()[:600])
