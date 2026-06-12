"""
HVOS Portfolio Manager — Reality Event 消费者
==============================================
消费 Event Bus 中的 RealityEvent，更新 KG（Knowledge Graph）
并生成 Board-ready 的 Portfolio 状态报告

功能：
1. 订阅 Event Bus
2. 消费 RealityEvent → 更新 KG 节点
3. 维护 Portfolio 状态（每品类盈亏/趋势）
4. 生成 Board 报告
5. 微信推送异常事件
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

from .reality_hub import (
    RealityEvent,
    EventSource,
    EventType,
    EventSeverity,
    EventBus,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio Item — 持仓单品
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PortfolioItem:
    """组合持仓单品"""
    sku: str
    product_name: str
    category: str
    platform: str

    # 实时状态（从 RealityEvent 更新）
    revenue_7d: float = 0.0
    revenue_delta_pct: float = 0.0
    orders_7d: int = 0
    orders_delta_pct: float = 0.0
    aov: float = 0.0
    aov_delta_pct: float = 0.0
    refund_rate: float = 0.0
    refund_delta_pct: float = 0.0

    # 广告数据
    ad_spend_7d: float = 0.0
    roas: float = 0.0
    cpa: float = 0.0
    ctr: float = 0.0

    # Google Trends
    trend_score: float = 0.0
    trend_delta_pct: float = 0.0

    # 计算字段
    net_profit_rate: float = 0.0  # 估算净利率
    health_score: float = 0.0  # 0-100

    # 时间戳
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_health(self) -> float:
        """
        计算健康分 0-100
        综合：趋势/营收增长/利润率/退款率
        """
        score = 50.0

        # 趋势加分（最高+20）
        if self.trend_delta_pct > 0:
            score += min(20, self.trend_delta_pct / 5)

        # 营收增长（最高+15）
        if self.revenue_delta_pct > 0:
            score += min(15, self.revenue_delta_pct / 10)

        # 退款率扣分（最多-20）
        if self.refund_rate > 10:
            score -= 20
        elif self.refund_rate > 5:
            score -= 10
        elif self.refund_rate > 2:
            score -= 5

        # ROAS 加分（最高+15）
        if self.roas > 3:
            score += 15
        elif self.roas > 2:
            score += 10
        elif self.roas > 1:
            score += 5

        # 广告效率（最多-10）
        if self.cpa > 30:
            score -= 10
        elif self.cpa > 20:
            score -= 5

        self.health_score = max(0, min(100, score))
        return self.health_score

    def to_dict(self) -> dict:
        d = asdict(self)
        d["health_score"] = self.compute_health()
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio Manager
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioManager:
    """
    Portfolio Manager — RealityEvent 消费者 + KG 更新器
    订阅 EventBus，消费事件，维护 Portfolio 状态
    """

    def __init__(self, event_bus: EventBus, kg_path: str = "knowledge-graph/kg.db"):
        self.event_bus = event_bus
        self.kg_path = kg_path

        # 内存中的 Portfolio 状态
        self.portfolio: dict[str, PortfolioItem] = {}

        # 注册订阅
        self.event_bus.subscribe_all(self.on_event)

        # 统计
        self.stats = {
            "events_processed": 0,
            "kg_updates": 0,
            "anomalies_alerted": 0,
            "last_run": None,
        }

    def on_event(self, event: RealityEvent):
        """EventBus 回调：处理每个 RealityEvent"""
        try:
            self._process_event(event)
            self.stats["events_processed"] += 1
            self.stats["last_run"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            logger.error(f"PortfolioManager.on_event failed: {e}")

    def _process_event(self, event: RealityEvent):
        """处理单个事件"""
        # 1. 更新 KG
        self._update_kg(event)

        # 2. 更新 Portfolio 内存状态
        self._update_portfolio(event)

        # 3. 异常告警
        if event.is_anomaly and event.severity in (EventSeverity.CRITICAL, EventSeverity.WARNING):
            self._alert(event)

    def _update_kg(self, event: RealityEvent):
        """更新 Knowledge Graph — 写入 kg_nodes / kg_relations 表（正确 schema）"""
        try:
            conn = sqlite3.connect(self.kg_path)
            c = conn.cursor()

            node_id = event.kg_node_id
            now = datetime.now(timezone.utc).isoformat()
            properties = {
                "metric_name": event.metric_name,
                "metric_value": event.metric_value,
                "metric_delta_pct": event.metric_delta_pct,
                "metric_unit": event.metric_unit,
                "severity": event.severity.value,
                "tags": event.tags or [],
                "category": event.category,
                "market": event.market,
                "confidence": event.confidence,
                "product_sku": event.product_sku,
                "campaign_id": event.campaign_id,
            }

            # 写入 kg_nodes（正确 schema）
            c.execute("""
                INSERT OR REPLACE INTO kg_nodes (
                    node_id, entity_type, name, properties,
                    created_at, updated_at, source_event_id, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                node_id,
                "RealityEvent",
                f"{event.source.value}:{event.event_type.value}",
                json.dumps(properties, default=str),
                now,         # created_at
                now,         # updated_at
                event.event_id,
                event.confidence or 0.5,
            ))

            # 写入 kg_relations（正确 schema）：事件 → 产品 SKU
            if event.product_sku:
                sku_node_id = f"product_{event.product_sku}"
                rel_id = f"rel_{node_id}_{event.product_sku}"
                c.execute("""
                    INSERT OR REPLACE INTO kg_relations (
                        relation_id, from_node, to_node, rel_type, properties,
                        created_at, source_event_id, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rel_id,
                    node_id,
                    sku_node_id,
                    "RELATES_TO",
                    json.dumps({
                        "source": event.source.value,
                        "event_type": event.event_type.value,
                    }),
                    now,
                    event.event_id,
                    event.confidence or 0.5,
                ))

            conn.commit()
            conn.close()
            self.stats["kg_updates"] += 1
        except Exception as e:
            logger.warning(f"KG update failed: {e}")

    def _update_portfolio(self, event: RealityEvent):
        """更新内存 Portfolio 状态"""
        if not event.product_sku:
            return

        sku = event.product_sku

        # 初始化或更新 PortfolioItem
        if sku not in self.portfolio:
            self.portfolio[sku] = PortfolioItem(
                sku=sku,
                product_name=event.raw_data.get("product_name", sku),
                category=event.category or "unknown",
                platform=event.source.value,
            )

        item = self.portfolio[sku]

        # 根据 metric_name 更新对应字段
        if event.metric_name == "shopify_revenue_daily":
            item.revenue_7d = event.metric_value
            item.revenue_delta_pct = event.metric_delta_pct
        elif event.metric_name == "shopify_orders_daily":
            item.orders_7d = int(event.metric_value)
            item.orders_delta_pct = event.metric_delta_pct
        elif event.metric_name == "shopify_aov":
            item.aov = event.metric_value
            item.aov_delta_pct = event.metric_delta_pct
        elif event.metric_name == "shopify_refund_rate":
            item.refund_rate = event.metric_value
            item.refund_delta_pct = event.metric_delta_pct
        elif event.metric_name in ("meta_roas", "tiktok_roas"):
            item.roas = event.metric_value
        elif event.metric_name in ("meta_spend_daily", "tiktok_spend_daily"):
            item.ad_spend_7d = event.metric_value
        elif event.metric_name in ("meta_cpa", "tiktok_cpa"):
            item.cpa = event.metric_value
        elif event.metric_name in ("meta_ctr",):
            item.ctr = event.metric_value
        elif event.metric_name.startswith("google_trend_"):
            item.trend_score = event.metric_value
            item.trend_delta_pct = event.metric_delta_pct

        item.last_updated = datetime.now(timezone.utc).isoformat()

    def _alert(self, event: RealityEvent):
        """异常告警"""
        self.stats["anomalies_alerted"] += 1
        logger.warning(
            f"[ALERT] {event.severity.value.upper()} | {event.source.value} | "
            f"{event.metric_name}={event.metric_value}{event.metric_unit} "
            f"({event.sign()}{abs(event.metric_delta_pct):.1f}% vs baseline {event.baseline_value:.2f})"
        )

    def get_portfolio_summary(self) -> dict:
        """生成 Portfolio 汇总报告"""
        items = list(self.portfolio.values())
        total = len(items)

        healthy = len([i for i in items if i.compute_health() >= 70])
        warning = len([i for i in items if 40 <= i.compute_health() < 70])
        critical = len([i for i in items if i.compute_health() < 40])

        total_revenue = sum(i.revenue_7d for i in items)
        total_spend = sum(i.ad_spend_7d for i in items)

        return {
            "total_items": total,
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "total_revenue_7d": total_revenue,
            "total_ad_spend_7d": total_spend,
            "estimated_roas": (total_revenue / total_spend) if total_spend > 0 else 0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def get_board_report(self) -> dict:
        """
        生成 Board-ready 报告
        用于微信推送
        """
        summary = self.get_portfolio_summary()
        items = sorted(self.portfolio.values(), key=lambda i: i.compute_health(), reverse=True)

        anomalies = [
            e for e in self.event_bus.get_recent(100)
            if e.is_anomaly and e.severity in (EventSeverity.CRITICAL, EventSeverity.WARNING)
        ]

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "Portfolio Board Report",
            "summary": summary,
            "top_performers": [
                {
                    "sku": i.sku,
                    "health": round(i.compute_health(), 1),
                    "revenue_7d": round(i.revenue_7d, 2),
                    "roas": round(i.roas, 2),
                    "trend": f"{'↑' if i.trend_delta_pct > 0 else '↓' if i.trend_delta_pct < 0 else '→'}{abs(i.trend_delta_pct):.1f}%",
                    "refund_rate": f"{i.refund_rate:.1f}%",
                }
                for i in items[:5]
            ],
            "anomalies": [
                {
                    "source": e.source.value,
                    "metric": e.metric_name,
                    "value": f"{e.metric_value:.2f}{e.metric_unit}",
                    "delta": f"{e.sign()}{abs(e.metric_delta_pct):.1f}%",
                    "severity": e.severity.value,
                }
                for e in anomalies[:5]
            ],
        }
        return report

    def sync_from_event_store(self, event_store):
        """从 EventStore 恢复 Portfolio 状态（启动时调用）"""
        events = event_store.recent_events(hours=24 * 7)  # 最近7天
        for event in events:
            self._update_portfolio(event)
        logger.info(f"Portfolio synced from {len(events)} historical events")

    def export_portfolio_json(self, path: str = "reality/portfolio.json"):
        """导出 Portfolio JSON"""
        os_imported = __import__("os")
        os_imported.makedirs(os_imported.path.dirname(path) or ".", exist_ok=True)
        data = {
            "summary": self.get_portfolio_summary(),
            "items": [i.to_dict() for i in self.portfolio.values()],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return path


# ─────────────────────────────────────────────────────────────────────────────
# Reality Bridge — 桥接 Reality Hub 和 Portfolio Manager
# ─────────────────────────────────────────────────────────────────────────────

import os
from pathlib import Path

# HVOS 根目录（本模块所在目录的父目录）
_HVOS_ROOT = Path(__file__).resolve().parent.parent

class RealityBridge:
    """
    Reality Bridge — 统一协调 RealityHub + EventBus + PortfolioManager
    提供一站式启动接口
    """

    def __init__(self, config_path: Optional[str] = None):
        from .reality_hub import RealityHub, RealityHubConfig

        if config_path:
            self.config = RealityHubConfig.from_file(config_path)
        else:
            self.config = RealityHubConfig()

        # 初始化 Hub
        self.hub = RealityHub(config=self.config)

        # 初始化 Portfolio Manager — 使用绝对路径
        kg_db = _HVOS_ROOT / "knowledge-graph" / "kg.db"
        self.portfolio_manager = PortfolioManager(
            event_bus=self.hub.event_bus,
            kg_path=str(kg_db),
        )

        # 从历史事件恢复 Portfolio 状态
        self.portfolio_manager.sync_from_event_store(self.hub.event_store)

    def run_cycle(self) -> dict:
        """
        执行一个完整的 Reality 循环
        1. collect() → 收集数据
        2. 发布事件到 EventBus
        3. PortfolioManager 消费事件
        4. 生成 Board 报告
        """
        # Step 1: 收集数据
        collect_results = self.hub.collect()

        # Step 2: 同步到 KG
        sync_results = self.hub.sync()

        # Step 3: 生成 Portfolio 报告
        portfolio_summary = self.portfolio_manager.get_portfolio_summary()
        board_report = self.portfolio_manager.get_board_report()

        return {
            "collect": collect_results,
            "sync": sync_results,
            "portfolio": portfolio_summary,
            "board_report": board_report,
        }

    def get_board_report(self) -> dict:
        return self.portfolio_manager.get_board_report()

    def health_check(self) -> dict:
        return {
            "hub_health": self.hub.health_check(),
            "portfolio_items": len(self.portfolio_manager.portfolio),
            "kg_updates": self.portfolio_manager.stats["kg_updates"],
            "events_in_bus": len(self.hub.event_bus.get_recent()),
        }


def main():
    import argparse, os

    parser = argparse.ArgumentParser(description="HVOS Portfolio Manager")
    parser.add_argument("--config", default="reality_config.json")
    parser.add_argument("--action", default="run", choices=["run", "report", "export", "status"])
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = args.config if os.path.exists(args.config) else None
    bridge = RealityBridge(config_path=config_path)

    if args.action == "run":
        result = bridge.run_cycle()
        print(json.dumps(result, indent=2, default=str))

    elif args.action == "report":
        report = bridge.get_board_report()
        print(json.dumps(report, indent=2, default=str))

    elif args.action == "export":
        path = bridge.portfolio_manager.export_portfolio_json()
        print(f"Portfolio exported to {path}")

    elif args.action == "status":
        status = bridge.health_check()
        print(json.dumps(status, indent=2, default=str))


if __name__ == "__main__":
    main()