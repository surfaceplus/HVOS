"""
SystemStateManager (SSM)
=========================
HVOS 全局状态机：管理所有 OpportunityObject 的生命周期状态。

每个机会必须处于以下阶段之一：
  DISCOVER  → VALIDATE → SCALE → HOLD
                              ↘ STOP ↙

SSM 是系统的"大脑"，记录：
- 当前有哪些机会在运行
- 每个机会处于什么阶段
- 阶段停留时间（超时自动告警）
- 全局资源占用（总预算、总风险敞口）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import json

# 导入 HCOM
from hcom import OpportunityObject, OpportunityStage, Decision


class AlertLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class StageAlert:
    alert_id: str
    opportunity_id: str
    opportunity_name: str
    level: AlertLevel
    message: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class GlobalStats:
    total_opportunities: int = 0
    by_stage: dict = field(default_factory=dict)
    total_budget_allocated: float = 0.0
    total_risk_exposure: float = 0.0
    avg_confidence: float = 0.0
    avg_probability: float = 0.0


class SystemStateManager:
    """
    全局状态机：管理所有机会的生命周期。

    使用方式：
        ssm = SystemStateManager()
        ssm.register(opp)
        ssm.transition("abc123", OpportunityStage.SCALE, "趋势确认，上调")
        print(ssm.get_board_summary())
    """

    def __init__(self, db_path: str = ""):
        self.opportunities: Dict[str, OpportunityObject] = {}
        self.alerts: List[StageAlert] = []
        self.db_path = db_path

        # 超时阈值（天）
        self.STAGE_TIMEOUT = {
            OpportunityStage.DISCOVER: 3,    # 发现阶段最多3天
            OpportunityStage.VALIDATE: 14,   # 验证阶段最多14天
            OpportunityStage.SCALE: 30,     # 扩量阶段最多30天
            OpportunityStage.HOLD: 90,      # 持有阶段最多90天
        }

        # 最大同时运行机会数
        self.MAX_CONCURRENT = 10

    # ============================================================
    # 核心操作
    # ============================================================

    def register(self, opp: OpportunityObject) -> bool:
        """
        注册新机会到状态机。
        如果 ID 已存在则更新，不重复注册。
        """
        self.opportunities[opp.id] = opp
        return True

    def get(self, opp_id: str) -> Optional[OpportunityObject]:
        return self.opportunities.get(opp_id)

    def get_all(self) -> List[OpportunityObject]:
        return list(self.opportunities.values())

    def get_by_stage(self, stage: OpportunityStage) -> List[OpportunityObject]:
        return [o for o in self.opportunities.values() if o.stage == stage]

    def get_active_opportunities(self) -> List[OpportunityObject]:
        """获取所有非 STOP/HOLD 的活跃机会"""
        return [
            o for o in self.opportunities.values()
            if o.stage not in (OpportunityStage.STOP, OpportunityStage.HOLD)
        ]

    def transition(
        self, opp_id: str, new_stage: OpportunityStage,
        reason: str = "", force: bool = False
    ) -> bool:
        """
        将机会转换到新阶段。
        force=True 跳过警告检查。
        """
        opp = self.opportunities.get(opp_id)
        if not opp:
            return False

        old_stage = opp.stage
        opp.transition_to(new_stage, reason)

        # 阶段超时检查
        if not force:
            self._check_stage_timeout(opp)

        self._add_alert(opp, AlertLevel.INFO,
            f"Stage: {old_stage.value} -> {new_stage.value}" +
            (f" | {reason}" if reason else ""))
        return True

    def update_decision(self, opp_id: str, decision: Decision, reason: str = ""):
        """更新机会的决策"""
        opp = self.opportunities.get(opp_id)
        if opp:
            opp.update_decision(decision, reason)

    def remove(self, opp_id: str):
        """从状态机移除机会"""
        if opp_id in self.opportunities:
            del self.opportunities[opp_id]

    # ============================================================
    # 超时与告警
    # ============================================================

    def _check_stage_timeout(self, opp: OpportunityObject):
        """检查阶段是否超时"""
        threshold = self.STAGE_TIMEOUT.get(opp.stage, 30)
        days = opp.days_in_stage
        if days > threshold:
            self._add_alert(opp, AlertLevel.WARN,
                f"阶段超时：已停留 {days} 天（阈值 {threshold} 天）")
        if days > threshold * 2:
            self._add_alert(opp, AlertLevel.CRITICAL,
                f"严重超时：已停留 {days} 天，建议 STOP")
            # 自动建议停止
            opp.update_decision(Decision.STOP, f"超时 {days} 天未完成")

    def _add_alert(self, opp: OpportunityObject, level: AlertLevel, message: str):
        alert = StageAlert(
            alert_id=f"alert_{len(self.alerts)+1}",
            opportunity_id=opp.id,
            opportunity_name=opp.product_name,
            level=level,
            message=message,
        )
        self.alerts.append(alert)
        # 只保留最近100条告警
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

    def get_active_alerts(self, level: AlertLevel = None) -> List[StageAlert]:
        if level:
            return [a for a in self.alerts if a.level == level]
        return self.alerts[-20:]  # 最近20条

    def get_critical_alerts(self) -> List[StageAlert]:
        return self.get_active_alerts(AlertLevel.CRITICAL)

    # ============================================================
    # 全局统计
    # ============================================================

    def get_global_stats(self) -> GlobalStats:
        """获取全局统计数据"""
        all_opps = self.get_all()
        if not all_opps:
            return GlobalStats()

        by_stage = {}
        for stage in OpportunityStage:
            by_stage[stage.value] = len([o for o in all_opps if o.stage == stage])

        # 加权平均（统计所有机会，不只是活跃的）
        avg_confidence = sum(o.confidence for o in all_opps) / max(len(all_opps), 1)
        avg_prob = sum(o.probability_of_success for o in all_opps) / max(len(all_opps), 1)

        return GlobalStats(
            total_opportunities=len(all_opps),
            by_stage=by_stage,
            total_budget_allocated=sum(o.metadata.get("allocated_budget", 0) for o in all_opps),
            total_risk_exposure=sum(o.risk_score * o.metadata.get("allocated_budget", 1000) / 10 for o in all_opps),
            avg_confidence=round(avg_confidence, 3),
            avg_probability=round(avg_prob, 3),
        )

    # ============================================================
    # Board Report 视图
    # ============================================================

    def get_board_summary(self) -> dict:
        """Board meeting 级别的汇总"""
        stats = self.get_global_stats()
        critical = self.get_critical_alerts()
        warns = self.get_active_alerts(AlertLevel.WARN)

        return {
            "generated_at": datetime.now().isoformat(),
            "total_opportunities": stats.total_opportunities,
            "active_opportunities": len(self.get_active_opportunities()),
            "by_stage": stats.by_stage,
            "avg_confidence": stats.avg_confidence,
            "avg_probability": stats.avg_probability,
            "critical_alerts": [
                {"opportunity": a.opportunity_name, "message": a.message}
                for a in critical
            ],
            "warn_alerts": [
                {"opportunity": a.opportunity_name, "message": a.message}
                for a in warns
            ],
        }

    def get_board_summary_text(self) -> str:
        """Board meeting 文本格式"""
        summary = self.get_board_summary()
        lines = [
            "=" * 50,
            "HVOS BOARD SUMMARY",
            "=" * 50,
            f"Total Opportunities: {summary['total_opportunities']}",
            f"Active: {summary['active_opportunities']}",
            "",
            "By Stage:",
        ]
        for stage, count in summary["by_stage"].items():
            lines.append(f"  {stage}: {count}")
        lines += [
            "",
            f"Avg Confidence: {summary['avg_confidence']:.2f}",
            f"Avg Success Prob: {summary['avg_probability']:.2f}",
        ]
        if summary["critical_alerts"]:
            lines.append("")
            lines.append("CRITICAL ALERTS:")
            for a in summary["critical_alerts"]:
                lines.append(f"  [!] {a['opportunity']}: {a['message']}")
        if summary["warn_alerts"]:
            lines.append("")
            lines.append("WARNINGS:")
            for a in summary["warn_alerts"]:
                lines.append(f"  [W] {a['opportunity']}: {a['message']}")
        return "\n".join(lines)

    # ============================================================
    # 持久化
    # ============================================================

    def save(self, path: str = ""):
        """保存状态到 JSON 文件"""
        if not path:
            path = self.db_path
        if not path:
            path = "hvos_state.json"

        data = {
            "saved_at": datetime.now().isoformat(),
            "opportunities": [o.to_dict() for o in self.opportunities.values()],
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "opportunity_id": a.opportunity_id,
                    "opportunity_name": a.opportunity_name,
                    "level": a.level.value,
                    "message": a.message,
                    "timestamp": a.timestamp.isoformat(),
                }
                for a in self.alerts
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str = ""):
        """从 JSON 文件加载状态"""
        if not path:
            path = self.db_path
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return

        from hcom import OpportunityObject
        self.opportunities = {
            o["id"]: OpportunityObject.from_dict(o)
            for o in data.get("opportunities", [])
        }
        self.alerts = [
            StageAlert(
                alert_id=a["alert_id"],
                opportunity_id=a["opportunity_id"],
                opportunity_name=a["opportunity_name"],
                level=AlertLevel(a["level"]),
                message=a["message"],
                timestamp=datetime.fromisoformat(a["timestamp"]),
            )
            for a in data.get("alerts", [])
        ]

    def export_opportunities_json(self) -> str:
        """导出所有机会为 JSON 字符串"""
        return json.dumps(
            [o.to_dict() for o in self.opportunities.values()],
            ensure_ascii=False, indent=2
        )


if __name__ == "__main__":
    from hcom import new_opportunity, OpportunityStage, Decision, SignalPlatform, TrendPhase, new_market_signal

    ssm = SystemStateManager()

    # 模拟3个机会
    for name, niche, stage in [
        ("宠物手套", "pet_grooming", OpportunityStage.VALIDATE),
        ("智能园艺灯", "garden_tools", OpportunityStage.DISCOVER),
        ("折叠旅行杯", "travel_accessories", OpportunityStage.SCALE),
    ]:
        opp = new_opportunity(name, niche)
        opp.stage = stage
        opp.demand_score = 7.0
        opp.trend_score = 8.0
        opp.risk_score = 4.0
        opp.confidence = 0.72
        opp.probability_of_success = 0.65
        opp.margin_estimate = 32.0
        opp.update_decision(Decision.INVEST, "初步评估通过")
        ssm.register(opp)

    print(ssm.get_board_summary_text())
    print()
    print("Active Alerts:", len(ssm.get_active_alerts()))
