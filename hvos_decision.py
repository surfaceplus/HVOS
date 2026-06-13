"""
Decision Kernel (DK)
=====================
HVOS 统一决策中枢：所有 engine 的决策必须汇总到这里。

每个机会的决策流程：
  1. Outcome Engine 预测结果
  2. Portfolio Manager 组合分析
  3. Learning Loop 因果反馈
  4. RFE Engine 预测误差
  → 全部汇总到 Decision Kernel
  → 输出统一决策: INVEST / SCALE / HOLD / STOP / WAIT

Decision Kernel 规则（可配置）：
  INVEST  : prob > 0.65 AND risk < 5 AND margin > 25%
  SCALE   : prob > 0.70 AND 当前阶段=VALIDATE AND ROI_p50 > 20%
  HOLD    : prob > 0.5 AND (stage = SCALE OR stage = HOLD)
  STOP    : prob < 0.35 OR risk > 8 OR 回本周期 > 90天 OR 阶段超时
  WAIT    : confidence < 0.4 OR 数据不足

优先级规则：
  STOP > WAIT > HOLD > SCALE > INVEST
  即：任何 STOP 条件满足，优先 STOP
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum
import json

from hcom import (
    OpportunityObject, Decision,
    OpportunityStage, CapitalEvent, CapitalEventType
)


# ============================================================
# 决策规则配置
# ============================================================

@dataclass
class DecisionRules:
    """可配置的决策规则阈值"""
    prob_invest: float = 0.65        # 最低成功概率（可投资）
    risk_invest: float = 5.0         # 最高风险评分（可投资）
    margin_invest: float = 25.0       # 最低毛利率 %

    prob_scale: float = 0.70         # 扩量概率门槛
    roi_scale: float = 20.0           # 扩量最低 ROI %

    prob_hold: float = 0.50          # 持有概率门槛

    prob_stop: float = 0.35          # 停止概率阈值
    risk_stop: float = 8.0           # 停止风险阈值
    payback_stop: int = 180          # 停止回本周期（天）- DTC 电商180天合理

    confidence_wait: float = 0.30     # 等待置信度阈值（放宽）


# ============================================================
# Decision Input（各 engine 提供的数据）
# ============================================================

@dataclass
class OpportunityContext:
    """
    汇总所有 engine 对单个机会的输入。
    每个 engine 只负责填充自己那部分。
    """
    opportunity: OpportunityObject

    # Outcome Engine 输出
    prob_success: float = 0.0
    expected_profit_p10: float = 0.0
    expected_profit_p50: float = 0.0
    expected_profit_p90: float = 0.0
    expected_roi: float = 0.0
    payback_days_estimate: int = 0

    # Portfolio Manager 输出
    portfolio_concentration: float = 0.0   # 同品类集中度 0-1
    portfolio_risk_score: float = 0.0      # 组合层面风险
    budget_available: float = 10000.0      # 可用预算
    suggested_budget: float = 0.0         # 建议投入

    # Learning Loop 输出
    causal_confidence: float = 0.0         # 因果置信度
    similar_success_pattern: str = ""       # 相似成功案例
    failure_risk_factors: List[str] = field(default_factory=list)

    # RFE Engine 输出
    last_prediction_error: float = 0.0     # 上次预测误差 %
    model_trust_score: float = 0.5         # 模型可信度 0-1

    # 当前时间（用于超时检测）
    now: datetime = field(default_factory=datetime.now)


@dataclass
class DecisionOutput:
    """Decision Kernel 输出的决策结果"""
    opportunity_id: str
    product_name: str
    decision: Decision
    confidence: float
    priority: int                # 1-10，数字越大优先级越高

    # 决策理由
    primary_reason: str = ""
    reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)

    # 行动建议
    action: str = ""              # 具体行动描述
    allocated_budget: float = 0.0
    max_risk: float = 0.0
    expected_outcome: str = ""    # 预期结果描述
    next_review_days: int = 7     # 几天后复审

    # 元数据
    rules_triggered: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        d = {
            "opportunity_id": self.opportunity_id,
            "product_name": self.product_name,
            "decision": self.decision.value,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
            "primary_reason": self.primary_reason,
            "reasons": self.reasons,
            "risk_factors": self.risk_factors,
            "action": self.action,
            "allocated_budget": self.allocated_budget,
            "max_risk": self.max_risk,
            "expected_outcome": self.expected_outcome,
            "next_review_days": self.next_review_days,
            "rules_triggered": self.rules_triggered,
            "timestamp": self.timestamp.isoformat(),
        }
        return d


# ============================================================
# Decision Kernel
# ============================================================

class DecisionKernel:
    """
    统一决策中枢。
    使用方式：
        dk = DecisionKernel()
        ctx = OpportunityContext(opportunity=opp, prob_success=0.72, ...)
        decision = dk.decide(ctx)
    """

    def __init__(self, rules: DecisionRules = None):
        self.rules = rules or DecisionRules()

    # ============================================================
    # 决策入口
    # ============================================================

    def decide(self, ctx: OpportunityContext) -> DecisionOutput:
        """
        对单个机会做出决策。
        决策优先级（从高到低）：
          STOP > WAIT > HOLD > SCALE > INVEST
        """
        opp = ctx.opportunity
        reasons = []
        risk_factors = []
        rules_triggered = []

        # ---------- STOP 检查 ----------
        if self._is_stop(ctx, reasons, risk_factors, rules_triggered):
            return self._build_output(ctx, Decision.STOP, reasons, risk_factors, rules_triggered)

        # ---------- WAIT 检查 ----------
        if self._is_wait(ctx, reasons, rules_triggered):
            return self._build_output(ctx, Decision.WAIT, reasons, risk_factors, rules_triggered)

        # ---------- SCALE 检查 ----------
        if self._is_scale(ctx, reasons, rules_triggered):
            return self._build_output(ctx, Decision.SCALE, reasons, risk_factors, rules_triggered)

        # ---------- HOLD 检查 ----------
        if self._is_hold(ctx, reasons, rules_triggered):
            return self._build_output(ctx, Decision.HOLD, reasons, risk_factors, rules_triggered)

        # ---------- INVEST ----------
        reasons.append(f"prob={ctx.prob_success:.2f}, risk={opp.risk_score:.1f}, margin={opp.margin_estimate:.1f}%")
        rules_triggered.append("INVEST")
        return self._build_output(ctx, Decision.INVEST, reasons, risk_factors, rules_triggered)

    # ============================================================
    # 批量决策
    # ============================================================

    def decide_batch(self, contexts: List[OpportunityContext]) -> List[DecisionOutput]:
        """对多个机会批量决策"""
        results = [self.decide(ctx) for ctx in contexts]
        # 按优先级排序
        return sorted(results, key=lambda r: -r.priority)

    # ============================================================
    # 决策规则
    # ============================================================

    def _is_stop(
        self, ctx: OpportunityContext,
        reasons: List[str], risk_factors: List[str],
        rules_triggered: List[str]
    ) -> bool:
        opp = ctx.opportunity
        stop_conditions = []

        if ctx.prob_success < self.rules.prob_stop:
            stop_conditions.append(f"prob({ctx.prob_success:.2f}) < {self.rules.prob_stop}")
        if opp.risk_score > self.rules.risk_stop:
            stop_conditions.append(f"risk({opp.risk_score:.1f}) > {self.rules.risk_stop}")
        if ctx.payback_days_estimate > self.rules.payback_stop > 0:
            stop_conditions.append(f"payback({ctx.payback_days_estimate}d) > {self.rules.payback_stop}d")
        if ctx.portfolio_concentration > 0.8:
            stop_conditions.append(f"concentration({ctx.portfolio_concentration:.2f}) > 0.8 (品类过于集中)")
        if ctx.failure_risk_factors:
            stop_conditions.append(f"failure risks: {', '.join(ctx.failure_risk_factors[:2])}")

        if stop_conditions:
            reasons.append("STOP conditions met: " + "; ".join(stop_conditions))
            risk_factors.extend(stop_conditions)
            rules_triggered.append("STOP")
            return True
        return False

    def _is_wait(
        self, ctx: OpportunityContext,
        reasons: List[str], rules_triggered: List[str]
    ) -> bool:
        opp = ctx.opportunity
        wait_conditions = []

        if opp.confidence < self.rules.confidence_wait:
            wait_conditions.append(f"confidence({opp.confidence:.2f}) < {self.rules.confidence_wait}")
        if ctx.prob_success < 0.4:
            wait_conditions.append(f"数据不足，prob={ctx.prob_success:.2f}")

        if wait_conditions:
            reasons.append("WAIT: " + "; ".join(wait_conditions))
            rules_triggered.append("WAIT")
            return True
        return False

    def _is_scale(
        self, ctx: OpportunityContext,
        reasons: List[str], rules_triggered: List[str]
    ) -> bool:
        opp = ctx.opportunity
        scale_conditions = []

        if ctx.prob_success >= self.rules.prob_scale:
            scale_conditions.append(f"prob({ctx.prob_success:.2f}) >= {self.rules.prob_scale}")
        if ctx.expected_roi >= self.rules.roi_scale:
            scale_conditions.append(f"ROI({ctx.expected_roi:.1f}%) >= {self.rules.roi_scale}%")
        if opp.stage == OpportunityStage.VALIDATE:
            scale_conditions.append("stage=VALIDATE")

        if len(scale_conditions) >= 2:
            reasons.append("SCALE: " + "; ".join(scale_conditions))
            rules_triggered.append("SCALE")
            return True
        return False

    def _is_hold(
        self, ctx: OpportunityContext,
        reasons: List[str], rules_triggered: List[str]
    ) -> bool:
        opp = ctx.opportunity
        if ctx.prob_success >= self.rules.prob_hold and opp.stage in (
            OpportunityStage.SCALE, OpportunityStage.HOLD
        ):
            reasons.append(
                f"HOLD: prob={ctx.prob_success:.2f} >= {self.rules.prob_hold}, "
                f"stage={opp.stage.value}"
            )
            rules_triggered.append("HOLD")
            return True
        return False

    # ============================================================
    # 输出构建
    # ============================================================

    def _build_output(
        self, ctx: OpportunityContext,
        decision: Decision,
        reasons: List[str], risk_factors: List[str],
        rules_triggered: List[str]
    ) -> DecisionOutput:
        opp = ctx.opportunity

        # 优先级
        priority_map = {Decision.STOP: 10, Decision.WAIT: 8, Decision.HOLD: 6,
                        Decision.SCALE: 4, Decision.INVEST: 2, Decision.WAIT: 1}
        priority = priority_map.get(decision, 0)

        # 行动建议
        action, allocated_budget, next_review = self._get_action_and_budget(ctx, decision)

        # 预期结果描述
        if decision == Decision.INVEST:
            expected = f"P50 profit: ${ctx.expected_profit_p50:,.0f} / 90d"
        elif decision == Decision.SCALE:
            expected = f"Scale to ${ctx.suggested_budget or ctx.budget_available * 0.3:,.0f}, ROI: {ctx.expected_roi:.0f}%"
        elif decision == Decision.STOP:
            expected = "Cut losses, reallocate budget"
        elif decision == Decision.WAIT:
            expected = "Monitor for 7 days, re-evaluate"
        else:
            expected = f"Maintain position, review in {next_review} days"

        return DecisionOutput(
            opportunity_id=opp.id,
            product_name=opp.product_name,
            decision=decision,
            confidence=opp.confidence,
            priority=priority,
            primary_reason=reasons[0] if reasons else "",
            reasons=reasons,
            risk_factors=risk_factors,
            action=action,
            allocated_budget=allocated_budget,
            max_risk=opp.risk_score,
            expected_outcome=expected,
            next_review_days=next_review,
            rules_triggered=rules_triggered,
        )

    def _get_action_and_budget(
        self, ctx: OpportunityContext, decision: Decision
    ) -> Tuple[str, float, int]:
        """
        根据决策类型确定具体行动和预算分配。
        """
        opp = ctx.opportunity
        stage = opp.stage

        if decision == Decision.INVEST:
            # 发现阶段：测试预算
            if stage == OpportunityStage.DISCOVER:
                budget = min(500, ctx.budget_available * 0.05)
                return f"启动小规模测试（${budget:.0f}）", budget, 7
            # 验证阶段：确认后加仓
            budget = min(1500, ctx.budget_available * 0.15)
            return f"投入验证（${budget:.0f}）", budget, 14

        elif decision == Decision.SCALE:
            budget = min(
                ctx.budget_available * 0.30,
                ctx.suggested_budget or 3000
            )
            return f"扩大投入（${budget:.0f}），进入 SCALE 阶段", budget, 7

        elif decision == Decision.HOLD:
            return "维持现状，关注市场信号变化", 0, 14

        elif decision == Decision.STOP:
            return f"立即停止，释放预算", 0, 0

        elif decision == Decision.WAIT:
            return "等待更多信息，减少暴露", 0, 7

        return "无特定行动", 0, 7

    # ============================================================
    # 决策日志
    # ============================================================

    def export_decisions(self, decisions: List[DecisionOutput]) -> str:
        return json.dumps(
            [d.to_dict() for d in decisions],
            ensure_ascii=False, indent=2
        )

    def get_invest_decisions(self, decisions: List[DecisionOutput]) -> List[DecisionOutput]:
        return [d for d in decisions if d.decision == Decision.INVEST]

    def get_scale_decisions(self, decisions: List[DecisionOutput]) -> List[DecisionOutput]:
        return [d for d in decisions if d.decision == Decision.SCALE]

    def get_stop_decisions(self, decisions: List[DecisionOutput]) -> List[DecisionOutput]:
        return [d for d in decisions if d.decision == Decision.STOP]


# ============================================================
# 便捷入口函数
# ============================================================

def decide_opportunity(opp: OpportunityObject, **kwargs) -> DecisionOutput:
    """快速决策：传入 OpportunityObject 和额外参数"""
    ctx = OpportunityContext(opportunity=opp, **kwargs)
    dk = DecisionKernel()
    return dk.decide(ctx)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    from hcom import new_opportunity, OpportunityStage, Decision

    dk = DecisionKernel()

    test_cases = [
        # (名称, 阶段, prob, risk, confidence, margin, stage)
        ("宠物手套", OpportunityStage.VALIDATE, 0.72, 3.5, 0.75, 38.0),
        ("智能园艺灯", OpportunityStage.DISCOVER, 0.55, 4.0, 0.45, 28.0),
        ("折叠旅行杯", OpportunityStage.SCALE, 0.68, 5.5, 0.70, 22.0),
        ("濒死品类A", OpportunityStage.VALIDATE, 0.28, 8.5, 0.60, 15.0),
    ]

    print("=" * 60)
    print("DECISION KERNEL TEST")
    print("=" * 60)
    for name, stage, prob, risk, conf, margin in test_cases:
        opp = new_opportunity(name)
        opp.stage = stage
        opp.risk_score = risk
        opp.confidence = conf
        opp.margin_estimate = margin

        ctx = OpportunityContext(
            opportunity=opp,
            prob_success=prob,
            expected_roi=margin * prob,
            payback_days_estimate=30 if prob > 0.5 else 120,
        )
        result = dk.decide(ctx)
        print(f"\n[{name}] stage={stage.value}")
        print(f"  Decision: {result.decision.value} (priority={result.priority})")
        print(f"  Reason: {result.primary_reason}")
        print(f"  Action: {result.action}")
        print(f"  Expected: {result.expected_outcome}")
