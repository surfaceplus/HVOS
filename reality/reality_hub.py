"""
HVOS Reality Hub — 真实数据统一入口
=====================================
统一收集 Shopify / Meta / TikTok / Google Trends 的真实运营数据，
标准化为 RealityEvent，发布到 Event Bus，持久化到 Event Store。

Author: HVOS X Reality Layer
Version: 1.0.0
"""

from __future__ import annotations

import json
import hashlib
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

# HVOS V10 Multi-Platform Bridge imports
from .amazon_collector import search_categories as amazon_search_cat, collect_market_intel as amazon_collect_intel
from .collector_1688 import search_products as alibaba_search, research_keywords as alibaba_research

class EventSource(Enum):
    """事件来源平台"""
    SHOPIFY = "shopify"
    WOO = "woo"           # WooCommerce
    META = "meta"
    TIKTOK = "tiktok"
    GOOGLE = "google"
    AMAZON = "amazon"
    ALIBABA = "alibaba_1688"
    MANUAL = "manual"


class EventType(Enum):
    """事件类型"""
    ORDER_PLACED = "order_placed"
    ORDER_REFUNDED = "order_refunded"
    REVENUE_SPIKE = "revenue_spike"
    REVENUE_DROP = "revenue_drop"
    AOV_CHANGE = "aov_change"
    CVR_CHANGE = "cvr_change"
    REFUND_RATE_SPIKE = "refund_rate_spike"
    AD_SPEND_CHANGE = "ad_spend_change"
    CPA_SPIKE = "cpa_spike"
    CPA_DROP = "cpa_drop"
    ROAS_CHANGE = "roas_change"
    CTR_CHANGE = "ctr_change"
    CPM_CHANGE = "cpm_change"
    TREND_SPIKE = "trend_spike"
    TREND_DROP = "trend_drop"
    ANOMALY_DETECTED = "anomaly_detected"
    OPPORTUNITY_DETECTED = "opportunity_detected"
    ALERT = "alert"


class EventSeverity(Enum):
    """事件严重程度"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    OPPORTUNITY = "opportunity"


@dataclass
class RealityEvent:
    """
    统一 Reality Event 数据模型
    所有平台数据最终标准化为此结构
    """
    #身份字段
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    source: EventSource = EventSource.MANUAL
    event_type: EventType = EventType.ORDER_PLACED
    severity: EventSeverity = EventSeverity.INFO

    # 时间字段
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    window_start: Optional[str] = None
    window_end: Optional[str] = None

    # 业务标识
    platform_store_id: Optional[str] = None
    product_sku: Optional[str] = None
    campaign_id: Optional[str] = None
    adset_id: Optional[str] = None
    ad_id: Optional[str] = None

    # 核心指标（统一命名）
    metric_name: str = ""
    metric_value: float = 0.0
    metric_unit: str = ""
    metric_delta_pct: float = 0.0  # 环比变化 %

    # 上下文
    previous_value: float = 0.0
    baseline_value: float = 0.0 # 30天均值
    threshold_triggered: float = 0.0  # 触发阈值

    # 原始数据（保留引用）
    raw_data: dict = field(default_factory=dict)

    # 标签（用于 KG 关联）
    tags: list[str] = field(default_factory=list)
    category: Optional[str] = None
    market: Optional[str] = None

    # 元数据
    confidence: float = 1.0
    processed_at: Optional[str] = None

    def __post_init__(self):
        if self.processed_at is None:
            self.processed_at = datetime.now(timezone.utc).isoformat()
        if isinstance(self.source, str):
            self.source = EventSource(self.source)
        if isinstance(self.event_type, str):
            self.event_type = EventType(self.event_type)
        if isinstance(self.severity, str):
            self.severity = EventSeverity(self.severity)

    def to_dict(self) -> dict:
        d = asdict(self)
        # 序列化时转换 enum 为字符串
        if isinstance(d.get("source"), EventSource):
            d["source"] = d["source"].value
        if isinstance(d.get("event_type"), EventType):
            d["event_type"] = d["event_type"].value
        if isinstance(d.get("severity"), EventSeverity):
            d["severity"] = d["severity"].value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @property
    def kg_node_id(self) -> str:
        """生成 KG节点 ID"""
        return f"reality_{self.source.value}_{self.event_type.value}_{self.event_id}"

    @property
    def is_anomaly(self) -> bool:
        """判断是否为异常事件"""
        return self.severity in (EventSeverity.CRITICAL, EventSeverity.WARNING)

    @property
    def delta_abs(self) -> float:
        """绝对变化量"""
        return self.metric_value - self.previous_value

    def sign(self) -> str:
        """变化方向"""
        if self.metric_delta_pct > 0:
            return "↑"
        elif self.metric_delta_pct < 0:
            return "↓"
        return "→"


# ─────────────────────────────────────────────────────────────────────────────
# 配置管理
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlatformConfig:
    """平台配置"""
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    ad_account_id: str = ""
    store_url: str = ""
    shop_id: str = ""
    account_id: str = ""  # Meta / TikTok account
    #告警阈值
    anomaly_threshold_pct: float = 20.0  # 变化超过20%触发告警
    check_interval_minutes: int = 60


@dataclass
class RealityHubConfig:
    """Reality Hub 全局配置"""
    shopify: PlatformConfig = field(default_factory=PlatformConfig)
    woo: PlatformConfig = field(default_factory=PlatformConfig)
    meta: PlatformConfig = field(default_factory=PlatformConfig)
    tiktok: PlatformConfig = field(default_factory=PlatformConfig)
    google: PlatformConfig = field(default_factory=PlatformConfig)
    amazon: PlatformConfig = field(default_factory=PlatformConfig)
    alibaba: PlatformConfig = field(default_factory=PlatformConfig)

    # 全局设置
    event_store_path: str = "reality/events.db"
    event_bus_enabled: bool = True
    kg_update_enabled: bool = True
    alert_enabled: bool = True
    log_level: str = "INFO"

    #聚合窗口
    aggregation_window_minutes: int = 60

    @classmethod
    def from_dict(cls, data: dict) -> "RealityHubConfig":
        def _platform(d: dict) -> PlatformConfig:
            return PlatformConfig(
                enabled=d.get("enabled", False),
                api_key=d.get("api_key", ""),
                api_secret=d.get("api_secret", ""),
                access_token=d.get("access_token", ""),
                ad_account_id=d.get("ad_account_id", ""),
                store_url=d.get("store_url", ""),
                shop_id=d.get("shop_id", ""),
                account_id=d.get("account_id", ""),
                anomaly_threshold_pct=d.get("anomaly_threshold_pct", 20.0),
                check_interval_minutes=d.get("check_interval_minutes", 60),
            )
        return cls(
            shopify=_platform(data.get("shopify", {})),
            woo=_platform(data.get("woo", {})),
            meta=_platform(data.get("meta", {})),
            tiktok=_platform(data.get("tiktok", {})),
            google=_platform(data.get("google", {})),
            event_store_path=data.get("event_store_path", "reality/events.db"),
            event_bus_enabled=data.get("event_bus_enabled", True),
            kg_update_enabled=data.get("kg_update_enabled", True),
            alert_enabled=data.get("alert_enabled", True),
            log_level=data.get("log_level", "INFO"),
            aggregation_window_minutes=data.get("aggregation_window_minutes", 60),
        )

    @classmethod
    def from_file(cls, path: str) -> "RealityHubConfig":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_file(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# 异常检测引擎
# ─────────────────────────────────────────────────────────────────────────────

class AnomalyDetector:
    """
简单异常检测器
    基于标准差的离群点检测
    """

    def __init__(self, threshold_pct: float = 20.0):
        self.threshold_pct = threshold_pct
        self.history: dict[str, list[float]] = {}

    def record(self, metric_name: str, value: float) -> tuple[bool, float, float]:
        """
       记录指标值，返回 (is_anomaly, z_score, baseline)
        baseline = 30天均值（若无足够数据，用滑动均值）
        """
        if metric_name not in self.history:
            self.history[metric_name] = []

        self.history[metric_name].append(value)
        #保留最近30个数据点
        if len(self.history[metric_name]) > 30:
            self.history[metric_name] = self.history[metric_name][-30:]

        values = self.history[metric_name]
        if len(values) < 3:
            return False, 0.0, value

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = variance ** 0.5

        if std == 0:
            return False, 0.0, mean

        z_score = (value - mean) / std
        is_anomaly = abs(z_score) > 2 or abs(value - mean) / mean * 100 > self.threshold_pct

        return is_anomaly, z_score, mean

    def clear(self):
        self.history.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 事件存储（SQLite）
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3

class EventStore:
    """
    SQLite持久化事件存储
    轻量级实现，支持查询和聚合
    """

    def __init__(self, db_path: str = "reality/events.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os_imported = __import__("os")
        os_imported.makedirs(os_imported.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                window_start TEXT,
                window_end TEXT,
                platform_store_id TEXT,
                product_sku TEXT,
                campaign_id TEXT,
                adset_id TEXT,
                ad_id TEXT,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                metric_unit TEXT,
                metric_delta_pct REAL,
                previous_value REAL,
                baseline_value REAL,
                threshold_triggered REAL,
                raw_data TEXT,
                tags TEXT,
                category TEXT,
                market TEXT,
                confidence REAL,
                processed_at TEXT,
                created_at TEXT DEFAULT (datetime('now', 'utc'))
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_source_time
            ON events(source, timestamp)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type_time
            ON events(event_type, timestamp)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_metric
            ON events(metric_name, timestamp)
        """)
        conn.commit()
        conn.close()

    def save(self, event: RealityEvent) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO events (
                    event_id, source, event_type, severity, timestamp,
                    window_start, window_end, platform_store_id, product_sku,
                    campaign_id, adset_id, ad_id, metric_name, metric_value,
                    metric_unit, metric_delta_pct, previous_value, baseline_value,
                    threshold_triggered, raw_data, tags, category, market,
                    confidence, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.source.value,
                event.event_type.value,
                event.severity.value,
                event.timestamp,
                event.window_start,
                event.window_end,
                event.platform_store_id,
                event.product_sku,
                event.campaign_id,
                event.adset_id,
                event.ad_id,
                event.metric_name,
                event.metric_value,
                event.metric_unit,
                event.metric_delta_pct,
                event.previous_value,
                event.baseline_value,
                event.threshold_triggered,
                json.dumps(event.raw_data, default=str),
                json.dumps(event.tags),
                event.category,
                event.market,
                event.confidence,
                event.processed_at,
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"EventStore.save failed: {e}")
            return False

    def query(
        self,
        source: Optional[EventSource] = None,
        event_type: Optional[EventType] = None,
        metric_name: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> list[RealityEvent]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        conditions = []
        params = []

        if source:
            conditions.append("source = ?")
            params.append(source.value)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type.value)
        if metric_name:
            conditions.append("metric_name = ?")
            params.append(metric_name)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = " AND ".join(conditions) if conditions else "1=1"
        query_sql = f"""
            SELECT * FROM events
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        rows = c.execute(query_sql, params).fetchall()
        conn.close()

        events = []
        for row in rows:
            d = dict(row)
            d["raw_data"] = json.loads(d.get("raw_data", "{}"))
            d["tags"] = json.loads(d.get("tags", "[]"))
            d.pop("created_at", None)
            events.append(RealityEvent(**d))
        return events

    def recent_events(self, hours: int = 24, source: Optional[EventSource] = None) -> list[RealityEvent]:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        return self.query(source=source, since=since)

    def count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM events")
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_latest_value(self, metric_name: str, source: EventSource) -> Optional[float]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        row = c.execute("""
            SELECT metric_value FROM events
            WHERE metric_name = ? AND source = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (metric_name, source.value)).fetchone()
        conn.close()
        return row[0] if row else None

    def clear_all(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM events")
        conn.commit()
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Event Bus（内存发布订阅）
# ─────────────────────────────────────────────────────────────────────────────

class EventBus:
    """
轻量级内存事件总线
    支持订阅/发布模式
    """

    def __init__(self):
        self._subscribers: dict[str, list[callable]] = {}
        self._event_log: list[RealityEvent] = []

    def subscribe(self, event_type: EventType, handler: callable):
        key = event_type.value
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type.value}")

    def subscribe_all(self, handler: callable):
        """订阅所有事件"""
        for et in EventType:
            self.subscribe(et, handler)

    def publish(self, event: RealityEvent) -> int:
        """
        发布事件到总线
        返回被处理的订阅者数量
        """
        self._event_log.append(event)
        # 只保留最近1000个
        if len(self._event_log) > 1000:
            self._event_log = self._event_log[-1000:]

        key = event.event_type.value
        handlers = self._subscribers.get(key, [])
        for h in handlers:
            try:
                h(event)
            except Exception as e:
                logger.error(f"EventBus handler {h.__name__} failed: {e}")

        # 也通知 wildcard订阅者
        for h in self._subscribers.get("*", []):
            try:
                h(event)
            except Exception as e:
                logger.error(f"EventBus wildcard handler {h.__name__} failed: {e}")

        return len(handlers)

    def get_recent(self, count: int = 50) -> list[RealityEvent]:
        return self._event_log[-count:]

    def clear_log(self):
        self._event_log.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 平台数据收集器基类
# ─────────────────────────────────────────────────────────────────────────────

from abc import ABC, abstractmethod
import requests


class BaseCollector(ABC):
    """平台收集器基类"""

    def __init__(self, config: PlatformConfig, event_store: EventStore, event_bus: EventBus, anomaly_detector: AnomalyDetector):
        self.config = config
        self.event_store = event_store
        self.event_bus = event_bus
        self.anomaly_detector = anomaly_detector
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HVOS-RealityHub/1.0",
            "Accept": "application/json",
        })

    @abstractmethod
    def collect(self) -> list[RealityEvent]:
        """收集数据并返回事件列表"""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass

    def _create_event(
        self,
        event_type: EventType,
        severity: EventSeverity,
        metric_name: str,
        metric_value: float,
        metric_unit: str = "",
        tags: Optional[list[str]] = None,
        **kwargs,
    ) -> RealityEvent:
        """创建并发布事件"""
        is_anomaly, z_score, baseline = self.anomaly_detector.record(metric_name, metric_value)

        if is_anomaly and severity == EventSeverity.INFO:
            severity = EventSeverity.WARNING

        # 从 kwargs 中提取独立参数，避免重复传参
        metric_delta_pct = kwargs.pop("metric_delta_pct", 0.0)
        previous_value = kwargs.pop("previous_value", 0.0)
        category = kwargs.pop("category", None)
        market = kwargs.pop("market", "US")
        confidence = kwargs.pop("confidence", 1.0)
        raw_data = kwargs.pop("raw_data", {})
        # 剩余 kwargs 全部传入 raw_data
        if kwargs:
            raw_data = {**raw_data, **kwargs}

        event = RealityEvent(
            source=self._source_type(),
            event_type=event_type,
            severity=severity,
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            metric_delta_pct=metric_delta_pct,
            previous_value=previous_value,
            baseline_value=baseline,
            threshold_triggered=self.config.anomaly_threshold_pct,
            raw_data=raw_data,
            tags=tags or [],
            category=category,
            market=market,
            confidence=confidence,
        )
        return event

    def _source_type(self) -> EventSource:
        return EventSource.MANUAL

    def _safe_request(self, method: str, url: str, **kwargs) -> Optional[dict]:
        """安全的 HTTP 请求"""
        try:
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                logger.warning(f"API认证失败: {url}")
            elif resp.status_code == 429:
                logger.warning(f"API限频: {url}")
            else:
                logger.warning(f"API请求失败 [{resp.status_code}]: {url}")
        except requests.exceptions.Timeout:
            logger.warning(f"API超时: {url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"API请求异常: {e}")
        return None

    def save_and_publish(self, event: RealityEvent) -> bool:
        """保存到 EventStore 并发布到 EventBus"""
        saved = self.event_store.save(event)
        if saved and self.config.enabled:
            self.event_bus.publish(event)
        return saved


# ─────────────────────────────────────────────────────────────────────────────
# Shopify收集器
# ─────────────────────────────────────────────────────────────────────────────

class ShopifyCollector(BaseCollector):
    """
    Shopify Admin API 收集器
   读取：Orders / Revenue / AOV / Refund Rate / CVR
    """

    API_VERSION = "2024-01"

    def _source_type(self) -> EventSource:
        return EventSource.SHOPIFY

    @property
    def base_url(self) -> str:
        return f"{self.config.store_url}/admin/api/{self.API_VERSION}"

    def _headers(self) -> dict:
        return {"X-Shopify-Access-Token": self.config.access_token}

    def health_check(self) -> bool:
        if not self.config.enabled or not self.config.access_token:
            return False
        url = f"{self.base_url}/shop.json"
        data = self._safe_request("GET", url, headers=self._headers())
        return data is not None

    def collect(self) -> list[RealityEvent]:
        """收集 Shopify 核心指标"""
        events = []
        if not self.config.enabled:
            return events

        #1. 收集订单数据
        events.extend(self._collect_orders())

        # 2. 收集营收数据
        events.extend(self._collect_revenue())

        # 3. 收集 Refund Rate
        events.extend(self._collect_refund_rate())

        return events

    def _collect_orders(self) -> list[RealityEvent]:
        """收集订单量"""
        events = []
        # 最近7天订单
        created_min = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{self.base_url}/orders.json?status=any&created_at_min={created_min}&limit=250"
        data = self._safe_request("GET", url, headers=self._headers())
        if not data or "orders" not in data:
            return events

        orders = data["orders"]
        today = datetime.now(timezone.utc).date()
        today_orders = [o for o in orders if datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")).date() == today]
        yesterday_orders = [o for o in orders if (datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")).date() == today - timedelta(days=1))]

        today_count = len(today_orders)
        yesterday_count = len(yesterday_orders)
        prev_count = self.event_store.get_latest_value("shopify_orders_daily", EventSource.SHOPIFY) or today_count

        delta_pct = ((today_count - prev_count) / prev_count * 100) if prev_count > 0 else 0.0

        event = self._create_event(
            event_type=EventType.ORDER_PLACED,
            severity=EventSeverity.INFO,
            metric_name="shopify_orders_daily",
            metric_value=float(today_count),
            metric_unit="orders",
            metric_delta_pct=delta_pct,
            previous_value=prev_count,
            raw_data={"orders_today": today_count, "orders_yesterday": yesterday_count, "total_7d": len(orders)},
            tags=["shopify", "orders", "daily"],
            category="orders",
        )
        self.save_and_publish(event)
        events.append(event)
        return events

    def _collect_revenue(self) -> list[RealityEvent]:
        """收集营收数据"""
        events = []
        created_min = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{self.base_url}/orders.json?status=any&created_at_min={created_min}&limit=250&fields=id,total_price,created_at,currency"
        data = self._safe_request("GET", url, headers=self._headers())
        if not data or "orders" not in data:
            return events

        orders = data["orders"]
        today = datetime.now(timezone.utc).date()
        today_revenue = sum(
            float(o["total_price"])
            for o in orders
            if datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")).date() == today
            and o.get("currency") == "USD"
        )
        yesterday_revenue = sum(
            float(o["total_price"])
            for o in orders
            if datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")).date() == today - timedelta(days=1)
            and o.get("currency") == "USD"
        )

        prev_revenue = self.event_store.get_latest_value("shopify_revenue_daily", EventSource.SHOPIFY) or today_revenue
        delta_pct = ((today_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0.0

        # AOV
        today_count = len([o for o in orders if datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")).date() == today])
        aov = today_revenue / today_count if today_count > 0 else 0.0
        prev_aov = self.event_store.get_latest_value("shopify_aov", EventSource.SHOPIFY) or aov
        aov_delta = ((aov - prev_aov) / prev_aov * 100) if prev_aov > 0 else 0.0

        # Revenu事件
        event_type = EventType.REVENUE_SPIKE if delta_pct > 10 else (EventType.REVENUE_DROP if delta_pct < -10 else EventType.ORDER_PLACED)
        event = self._create_event(
            event_type=event_type,
            severity=EventSeverity.INFO,
            metric_name="shopify_revenue_daily",
            metric_value=today_revenue,
            metric_unit="USD",
            metric_delta_pct=delta_pct,
            previous_value=prev_revenue,
            raw_data={"revenue_today": today_revenue, "revenue_yesterday": yesterday_revenue},
            tags=["shopify", "revenue", "daily"],
            category="revenue",
        )
        self.save_and_publish(event)
        events.append(event)

        # AOV事件
        aov_event = self._create_event(
            event_type=EventType.AOV_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="shopify_aov",
            metric_value=aov,
            metric_unit="USD",
            metric_delta_pct=aov_delta,
            previous_value=prev_aov,
            raw_data={"aov": aov, "order_count": today_count},
            tags=["shopify", "aov", "daily"],
            category="aov",
        )
        self.save_and_publish(aov_event)
        events.append(aov_event)
        return events

    def _collect_refund_rate(self) -> list[RealityEvent]:
        """收集退款率"""
        events = []
        # 统计最近30天退款订单
        created_min = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{self.base_url}/orders.json?status=any&created_at_min={created_min}&limit=250&fields=id,total_price,refunded_at,financial_status"
        data = self._safe_request("GET", url, headers=self._headers())
        if not data or "orders" not in data:
            return events

        orders = data["orders"]
        total_orders = len(orders)
        refunded_orders = len([o for o in orders if o.get("refunded_at")])
        refund_rate = (refunded_orders / total_orders * 100) if total_orders > 0 else 0.0

        prev_rate = self.event_store.get_latest_value("shopify_refund_rate", EventSource.SHOPIFY) or refund_rate
        delta_pct = ((refund_rate - prev_rate) / prev_rate * 100) if prev_rate > 0 else 0.0

        severity = EventSeverity.CRITICAL if refund_rate > 10 else (EventSeverity.WARNING if refund_rate > 5 else EventSeverity.INFO)
        if abs(delta_pct) > 20:
            severity = EventSeverity.WARNING

        event = self._create_event(
            event_type=EventType.REFUND_RATE_SPIKE,
            severity=severity,
            metric_name="shopify_refund_rate",
            metric_value=refund_rate,
            metric_unit="%",
            metric_delta_pct=delta_pct,
            previous_value=prev_rate,
            raw_data={"refunded_orders": refunded_orders, "total_orders": total_orders},
            tags=["shopify", "refund", "30d"],
            category="refund",
        )
        self.save_and_publish(event)
        events.append(event)
        return events


# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce 数据库直连收集器（绕过 REST API 认证问题）
# ─────────────────────────────────────────────────────────────────────────────

class WCOrdersCollector(BaseCollector):
    """
    WooCommerce 订单收集器 — 直连 MySQL 数据库
    读取：订单数 / 营收 / AOV / 退款率（从 wc_orders 表）
    适用于 REST API 认证失败的情况
    """

    def _source_type(self) -> EventSource:
        return EventSource.WOO

    def health_check(self) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                self.config.shop_id,  # shop_id 临时用作 VPS IP
                username='root',
                password=self.config.access_token,  # access_token 临时用作 SSH 密码
                timeout=10
            )
            client.close()
            return True
        except Exception:
            return False

    def collect(self) -> list[RealityEvent]:
        events = []
        if not self.config.enabled:
            return events

        events.extend(self._collect_orders())
        events.extend(self._collect_revenue())
        return events

    def _ssh_query(self, query: str) -> list:
        """执行 SSH + MySQL 查询（修复版）"""
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.config.shop_id,
            username='root',
            password=self.config.access_token,
            timeout=10
        )
        # 直接通过 stdin 发送 SQL，避免 shell 引号转义问题
        cmd = f"mysql -u {self.config.api_key} -p'{self.config.api_secret}' {self.config.store_url}"
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=False)
        stdin.write(query + ';' + '\n')
        stdin.flush()
        stdin.channel.shutdown_write()
        result = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        client.close()

        if err and 'ERROR' in err:
            logger.warning(f"MySQL error: {err[:200]}")
        lines = [l for l in result.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            return []
        headers = [h.strip() for h in lines[0].split('\t')]
        rows = []
        for line in lines[1:]:
            vals = [v.strip() for v in line.split('\t')]
            rows.append(dict(zip(headers, vals)))
        return rows

    def _collect_orders(self) -> list[RealityEvent]:
        events = []
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        # 查询今天和昨天的订单数
        query = (
            f"SELECT DATE(date_created_gmt) as order_date, COUNT(*) as cnt "
            f"FROM wp_0dd69b_wc_orders "
            f"WHERE type='shop_order' AND status NOT IN ('trash') "
            f"AND date_created_gmt >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) "
            f"GROUP BY DATE(date_created_gmt)"
        )
        rows = self._ssh_query(query)
        if not rows:
            return events

        date_cnt = {datetime.strptime(r['order_date'], '%Y-%m-%d').date(): int(r['cnt']) for r in rows}
        today_count = date_cnt.get(today, 0)
        yesterday_count = date_cnt.get(yesterday, 0)
        total_7d = sum(date_cnt.values())

        prev_count = self.event_store.get_latest_value("woo_orders_daily", EventSource.WOO) or today_count
        delta_pct = ((today_count - prev_count) / prev_count * 100) if prev_count > 0 else 0.0

        event = self._create_event(
            event_type=EventType.ORDER_PLACED,
            severity=EventSeverity.INFO,
            metric_name="woo_orders_daily",
            metric_value=float(today_count),
            metric_unit="orders",
            metric_delta_pct=delta_pct,
            previous_value=prev_count,
            raw_data={
                "orders_today": today_count,
                "orders_yesterday": yesterday_count,
                "total_7d": total_7d,
            },
            tags=["woo", "orders", "daily", "db_direct"],
            category="orders",
        )
        self.save_and_publish(event)
        events.append(event)
        return events

    def _collect_revenue(self) -> list[RealityEvent]:
        events = []
        today = datetime.now(timezone.utc).date()

        query = (
            f"SELECT DATE(date_created_gmt) as order_date, "
            f"SUM(total_amount) as revenue, COUNT(*) as cnt, currency "
            f"FROM wp_0dd69b_wc_orders "
            f"WHERE type='shop_order' AND status NOT IN ('trash','refunded') "
            f"AND date_created_gmt >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) "
            f"GROUP BY DATE(date_created_gmt), currency"
        )
        rows = self._ssh_query(query)
        if not rows:
            return events

        date_data = {}
        for r in rows:
            d = datetime.strptime(r['order_date'], '%Y-%m-%d').date()
            revenue = float(r['revenue'] or 0)
            cnt = int(r['cnt'])
            currency = r.get('currency', 'USD')
            if currency == 'USD':
                if d not in date_data:
                    date_data[d] = {'revenue': 0, 'cnt': 0}
                date_data[d]['revenue'] += revenue
                date_data[d]['cnt'] += cnt

        today_revenue = date_data.get(today, {}).get('revenue', 0)
        today_count = date_data.get(today, {}).get('cnt', 0)
        aov = today_revenue / today_count if today_count > 0 else 0.0

        prev_revenue = self.event_store.get_latest_value("woo_revenue_daily", EventSource.WOO) or today_revenue
        delta_pct = ((today_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0.0
        prev_aov = self.event_store.get_latest_value("woo_aov", EventSource.WOO) or aov
        aov_delta = ((aov - prev_aov) / prev_aov * 100) if prev_aov > 0 else 0.0

        event_type = EventType.REVENUE_SPIKE if delta_pct > 10 else (EventType.REVENUE_DROP if delta_pct < -10 else EventType.ORDER_PLACED)
        revenue_event = self._create_event(
            event_type=event_type,
            severity=EventSeverity.INFO,
            metric_name="woo_revenue_daily",
            metric_value=today_revenue,
            metric_unit="USD",
            metric_delta_pct=delta_pct,
            previous_value=prev_revenue,
            raw_data={"revenue_today": today_revenue},
            tags=["woo", "revenue", "daily", "db_direct"],
            category="revenue",
        )
        self.save_and_publish(revenue_event)
        events.append(revenue_event)

        aov_event = self._create_event(
            event_type=EventType.AOV_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="woo_aov",
            metric_value=aov,
            metric_unit="USD",
            metric_delta_pct=aov_delta,
            previous_value=prev_aov,
            raw_data={"aov": aov, "order_count": today_count},
            tags=["woo", "aov", "daily", "db_direct"],
            category="aov",
        )
        self.save_and_publish(aov_event)
        events.append(aov_event)
        return events


# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce REST API 收集器（your-store.com 专用）
# ─────────────────────────────────────────────────────────────────────────────

class WooCommerceCollector(BaseCollector):
    """
    WooCommerce REST API 收集器（your-store.com 专用）
    读取：订单数 / 营收 / AOV / 退款率
    Auth: Consumer Key + Consumer Secret（URL参数）
    """

    API_VERSION = "v3"

    def _source_type(self) -> EventSource:
        return EventSource.WOO

    @property
    def base_url(self) -> str:
        return f"{self.config.store_url}/wp-json/wc/{self.API_VERSION}"

    def _auth_params(self) -> dict:
        """WooCommerce 认证参数"""
        return {
            "consumer_key": self.config.api_key,
            "consumer_secret": self.config.api_secret,
        }

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def health_check(self) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        url = f"{self.base_url}/system_status"
        data = self._safe_request("GET", url, params=self._auth_params())
        return data is not None

    def collect(self) -> list[RealityEvent]:
        events = []
        if not self.config.enabled or not self.config.api_key:
            return events

        events.extend(self._collect_orders())
        events.extend(self._collect_revenue())
        events.extend(self._collect_refund_rate())
        return events

    def _collect_orders(self) -> list[RealityEvent]:
        """收集每日订单数"""
        events = []
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        # WooCommerce: after 参数用 ISO8601
        after = (today - timedelta(days=7)).isoformat() + "T00:00:00Z"
        params = {
            **self._auth_params(),
            "after": after,
            "per_page": 100,
            "status": "any",
        }
        url = f"{self.base_url}/orders"
        data = self._safe_request("GET", url, params=params)
        if not data or isinstance(data, dict):
            # WooCommerce 返回 error JSON 时是 dict
            logger.warning(f"WooCommerce orders API error: {data}")
            return events

        orders = data
        today_orders = [
            o for o in orders
            if datetime.fromisoformat(o["date_created"].replace("Z", "+00:00")).date() == today
        ]
        yesterday_orders = [
            o for o in orders
            if datetime.fromisoformat(o["date_created"].replace("Z", "+00:00")).date() == yesterday
        ]

        today_count = len(today_orders)
        yesterday_count = len(yesterday_orders)
        prev_count = self.event_store.get_latest_value("woo_orders_daily", EventSource.WOO) or today_count
        delta_pct = ((today_count - prev_count) / prev_count * 100) if prev_count > 0 else 0.0

        event = self._create_event(
            event_type=EventType.ORDER_PLACED,
            severity=EventSeverity.INFO,
            metric_name="woo_orders_daily",
            metric_value=float(today_count),
            metric_unit="orders",
            metric_delta_pct=delta_pct,
            previous_value=prev_count,
            raw_data={
                "orders_today": today_count,
                "orders_yesterday": yesterday_count,
                "total_7d": len(orders),
            },
            tags=["woo", "orders", "daily"],
            category="orders",
        )
        self.save_and_publish(event)
        events.append(event)
        return events

    def _collect_revenue(self) -> list[RealityEvent]:
        """收集营收和 AOV"""
        events = []
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        after = (today - timedelta(days=7)).isoformat() + "T00:00:00Z"
        params = {
            **self._auth_params(),
            "after": after,
            "per_page": 100,
            "status": "any",
        }
        url = f"{self.base_url}/orders"
        data = self._safe_request("GET", url, params=params)
        if not data or isinstance(data, dict):
            return events

        orders = data
        today_orders = [
            o for o in orders
            if datetime.fromisoformat(o["date_created"].replace("Z", "+00:00")).date() == today
        ]
        yesterday_orders = [
            o for o in orders
            if datetime.fromisoformat(o["date_created"].replace("Z", "+00:00")).date() == yesterday
        ]

        def order_total_usd(o) -> float:
            # 过滤 USD 订单
            if o.get("currency", "USD") != "USD":
                return 0.0
            return float(o.get("total", "0"))

        today_revenue = sum(order_total_usd(o) for o in today_orders)
        yesterday_revenue = sum(order_total_usd(o) for o in yesterday_orders)

        prev_revenue = self.event_store.get_latest_value("woo_revenue_daily", EventSource.WOO) or today_revenue
        delta_pct = ((today_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0.0

        today_count = len(today_orders)
        aov = today_revenue / today_count if today_count > 0 else 0.0
        prev_aov = self.event_store.get_latest_value("woo_aov", EventSource.WOO) or aov
        aov_delta = ((aov - prev_aov) / prev_aov * 100) if prev_aov > 0 else 0.0

        event_type = EventType.REVENUE_SPIKE if delta_pct > 10 else (EventType.REVENUE_DROP if delta_pct < -10 else EventType.ORDER_PLACED)
        revenue_event = self._create_event(
            event_type=event_type,
            severity=EventSeverity.INFO,
            metric_name="woo_revenue_daily",
            metric_value=today_revenue,
            metric_unit="USD",
            metric_delta_pct=delta_pct,
            previous_value=prev_revenue,
            raw_data={"revenue_today": today_revenue, "revenue_yesterday": yesterday_revenue},
            tags=["woo", "revenue", "daily"],
            category="revenue",
        )
        self.save_and_publish(revenue_event)
        events.append(revenue_event)

        aov_event = self._create_event(
            event_type=EventType.AOV_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="woo_aov",
            metric_value=aov,
            metric_unit="USD",
            metric_delta_pct=aov_delta,
            previous_value=prev_aov,
            raw_data={"aov": aov, "order_count": today_count},
            tags=["woo", "aov", "daily"],
            category="aov",
        )
        self.save_and_publish(aov_event)
        events.append(aov_event)
        return events

    def _collect_refund_rate(self) -> list[RealityEvent]:
        """收集退款率（最近30天）"""
        events = []
        today = datetime.now(timezone.utc).date()
        days_30_ago = today - timedelta(days=30)

        after = days_30_ago.isoformat() + "T00:00:00Z"
        params = {
            **self._auth_params(),
            "after": after,
            "per_page": 100,
            "status": "any",
        }
        url = f"{self.base_url}/orders"
        data = self._safe_request("GET", url, params=params)
        if not data or isinstance(data, dict):
            return events

        orders = data
        total_orders = len(orders)
        # WooCommerce: refunded orders have status "refunded"
        refunded_orders = len([o for o in orders if o.get("status") == "refunded"])
        refund_rate = (refunded_orders / total_orders * 100) if total_orders > 0 else 0.0

        prev_rate = self.event_store.get_latest_value("woo_refund_rate", EventSource.WOO) or refund_rate
        delta_pct = ((refund_rate - prev_rate) / prev_rate * 100) if prev_rate > 0 else 0.0

        severity = EventSeverity.CRITICAL if refund_rate > 10 else (EventSeverity.WARNING if refund_rate > 5 else EventSeverity.INFO)
        if abs(delta_pct) > 20:
            severity = EventSeverity.WARNING

        event = self._create_event(
            event_type=EventType.REFUND_RATE_SPIKE,
            severity=severity,
            metric_name="woo_refund_rate",
            metric_value=refund_rate,
            metric_unit="%",
            metric_delta_pct=delta_pct,
            previous_value=prev_rate,
            raw_data={"refunded_orders": refunded_orders, "total_orders": total_orders},
            tags=["woo", "refund", "30d"],
            category="refund",
        )
        self.save_and_publish(event)
        events.append(event)
        return events


# ─────────────────────────────────────────────────────────────────────────────
# Meta 收集器
# ─────────────────────────────────────────────────────────────────────────────

class MetaCollector(BaseCollector):
    """
    Meta Marketing API 收集器
    读取：CPA / CPM / CTR / ROAS
    """

    API_VERSION = "v21.0"

    def _source_type(self) -> EventSource:
        return EventSource.META

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.API_VERSION}"

    def _params(self) -> dict:
        return {
            "access_token": self.config.access_token,
        }

    def health_check(self) -> bool:
        if not self.config.enabled or not self.config.access_token:
            return False
        url = f"{self.base_url}/me"
        data = self._safe_request("GET", url, params=self._params())
        return data is not None

    def collect(self) -> list[RealityEvent]:
        events = []
        if not self.config.enabled or not self.config.ad_account_id:
            return events

        events.extend(self._collect_ad_metrics())
        return events

    def _collect_ad_metrics(self) -> list[RealityEvent]:
        """收集广告系列指标"""
        events = []

        # 获取广告账户下的广告系列
        url = f"{self.base_url}/act_{self.config.ad_account_id}/campaigns"
        params = {
            **self._params(),
            "fields": "id,name,campaign_id,objective",
            "limit": 50,
        }
        data = self._safe_request("GET", url, params=params)
        if not data or "data" not in data:
            return events

        for campaign in data["data"][:10]:  # 最多10个
            campaign_id = campaign["id"]
            campaign_events = self._collect_campaign_insights(campaign)
            events.extend(campaign_events)

        return events

    def _collect_campaign_insights(self, campaign: dict) -> list[RealityEvent]:
        """收集单个广告系列的洞察数据"""
        events = []
        campaign_id = campaign["id"]

        # 过去7天数据
        url = f"{self.base_url}/{campaign_id}/insights"
        params = {
            **self._params(),
            "fields": "spend,impressions,clicks,ctr,cpc,roas,cpm,actions,action_values",
            "time_range": json.dumps({"since": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"), "until": datetime.now(timezone.utc).strftime("%Y-%m-%d")}),
            "level": "campaign",
        }
        data = self._safe_request("GET", url, params=params)
        if not data or "data" not in data or not data["data"]:
            return events

        insight = data["data"][0]

        spend = float(insight.get("spend", 0) or 0)
        impressions = int(insight.get("impressions", 0) or 0)
        clicks = int(insight.get("clicks", 0) or 0)
        ctr = float(insight.get("ctr", 0) or 0)
        cpc = float(insight.get("cpc", 0) or 0)
        roas = float(insight.get("roas", 0) or 0)
        cpm = float(insight.get("cpm", 0) or 0)

        # Spend 事件
        prev_spend = self.event_store.get_latest_value("meta_spend_daily", EventSource.META) or spend
        delta_pct = ((spend - prev_spend) / prev_spend * 100) if prev_spend > 0 else 0.0
        spend_event = self._create_event(
            event_type=EventType.AD_SPEND_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="meta_spend_daily",
            metric_value=spend,
            metric_unit="USD",
            metric_delta_pct=delta_pct,
            previous_value=prev_spend,
            campaign_id=campaign_id,
            raw_data=insight,
            tags=["meta", "ad_spend", "campaign"],
            category="ads",
        )
        self.save_and_publish(spend_event)
        events.append(spend_event)

        # ROAS 事件
        prev_roas = self.event_store.get_latest_value("meta_roas", EventSource.META) or roas
        roas_delta = ((roas - prev_roas) / prev_roas * 100) if prev_roas > 0 else 0.0
        roas_event = self._create_event(
            event_type=EventType.ROAS_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="meta_roas",
            metric_value=roas,
            metric_unit="x",
            metric_delta_pct=roas_delta,
            previous_value=prev_roas,
            campaign_id=campaign_id,
            raw_data=insight,
            tags=["meta", "roas", "campaign"],
            category="ads",
        )
        self.save_and_publish(roas_event)
        events.append(roas_event)

        # CPA (通过 actions 计算)
        conversions = 0
        if "actions" in insight:
            for a in insight["actions"]:
                if a.get("action_type") in ["purchase", "lead", "complete_registration"]:
                    conversions += int(a.get("value", 0))
        cpa = spend / conversions if conversions > 0 else 0.0
        prev_cpa = self.event_store.get_latest_value("meta_cpa", EventSource.META) or cpa
        cpa_delta = ((cpa - prev_cpa) / prev_cpa * 100) if prev_cpa > 0 else 0.0
        cpa_event = self._create_event(
            event_type=EventType.CPA_SPIKE if cpa_delta > 10 else EventType.CPA_DROP,
            severity=EventSeverity.WARNING if cpa_delta > 20 else EventSeverity.INFO,
            metric_name="meta_cpa",
            metric_value=cpa,
            metric_unit="USD",
            metric_delta_pct=cpa_delta,
            previous_value=prev_cpa,
            campaign_id=campaign_id,
            raw_data={"conversions": conversions, "spend": spend},
            tags=["meta", "cpa", "campaign"],
            category="ads",
        )
        self.save_and_publish(cpa_event)
        events.append(cpa_event)

        # CTR 事件
        prev_ctr = self.event_store.get_latest_value("meta_ctr", EventSource.META) or ctr
        ctr_delta = ((ctr - prev_ctr) / prev_ctr * 100) if prev_ctr > 0 else 0.0
        ctr_event = self._create_event(
            event_type=EventType.CTR_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="meta_ctr",
            metric_value=ctr,
            metric_unit="%",
            metric_delta_pct=ctr_delta,
            previous_value=prev_ctr,
            campaign_id=campaign_id,
            raw_data=insight,
            tags=["meta", "ctr", "campaign"],
            category="ads",
        )
        self.save_and_publish(ctr_event)
        events.append(ctr_event)

        return events


# ─────────────────────────────────────────────────────────────────────────────
# TikTok 收集器
# ─────────────────────────────────────────────────────────────────────────────

class TikTokCollector(BaseCollector):
    """
    TikTok Business API 收集器
    读取：Views / CTR / CPA / ROAS
    """

    API_VERSION = "v1.3"

    def _source_type(self) -> EventSource:
        return EventSource.TIKTOK

    @property
    def base_url(self) -> str:
        return f"https://business-api.tiktok.com/portal/api/{self.API_VERSION}"

    def _headers(self) -> dict:
        return {"Access-Token": self.config.access_token}

    def health_check(self) -> bool:
        if not self.config.enabled or not self.config.access_token:
            return False
        url = f"{self.base_url}/advertiser/info"
        data = self._safe_request("GET", url, headers=self._headers())
        return data is not None

    def collect(self) -> list[RealityEvent]:
        events = []
        if not self.config.enabled or not self.config.ad_account_id:
            return events

        events.extend(self._collect_video_metrics())
        return events

    def _collect_video_metrics(self) -> list[RealityEvent]:
        """收集视频广告指标"""
        events = []

        # 获取广告账户信息
        url = f"{self.base_url}/advertiser/info"
        params = {"advertiser_ids": json.dumps([self.config.ad_account_id])}
        data = self._safe_request("GET", url, headers=self._headers(), params=params)
        if not data:
            return events

        # 获取广告系列
        url = f"{self.base_url}/campaign/list"
        params = {
            "advertiser_id": self.config.ad_account_id,
            "page_size": 20,
        }
        data = self._safe_request("GET", url, headers=self._headers(), params=params)
        if not data or "data" not in data:
            return events

        for campaign in data["data"].get("list", [])[:10]:
            campaign_events = self._collect_tiktok_campaign_insights(campaign)
            events.extend(campaign_events)

        return events

    def _collect_tiktok_campaign_insights(self, campaign: dict) -> list[RealityEvent]:
        """收集 TikTok 广告系列洞察"""
        events = []
        campaign_id = campaign.get("campaign_id", "")

        url = f"{self.base_url}/report/campaign/get"
        params = {
            "advertiser_id": self.config.ad_account_id,
            "campaign_ids": json.dumps([campaign_id]),
            "fields": json.dumps(["spend", "impressions", "clicks", "ctr", "video_views", "cpc", "cpm", "conversion", "cost_per_conversion"]),
            "start_date": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"),
            "end_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        data = self._safe_request("GET", url, headers=self._headers(), params=params)
        if not data or "data" not in data:
            return events

        metrics = data["data"]
        spend = float(metrics.get("spend", 0) or 0)
        impressions = int(metrics.get("impressions", 0) or 0)
        clicks = int(metrics.get("clicks", 0) or 0)
        ctr = float(metrics.get("ctr", 0) or 0)
        video_views = int(metrics.get("video_views", 0) or 0)
        cpc = float(metrics.get("cpc", 0) or 0)
        conversions = int(metrics.get("conversion", 0) or 0)
        cpa = float(metrics.get("cost_per_conversion", 0) or 0)

        # Spend
        prev_spend = self.event_store.get_latest_value("tiktok_spend_daily", EventSource.TIKTOK) or spend
        delta_pct = ((spend - prev_spend) / prev_spend * 100) if prev_spend > 0 else 0.0
        spend_event = self._create_event(
            event_type=EventType.AD_SPEND_CHANGE,
            severity=EventSeverity.INFO,
            metric_name="tiktok_spend_daily",
            metric_value=spend,
            metric_unit="USD",
            metric_delta_pct=delta_pct,
            previous_value=prev_spend,
            campaign_id=campaign_id,
            raw_data=metrics,
            tags=["tiktok", "ad_spend", "campaign"],
            category="ads",
        )
        self.save_and_publish(spend_event)
        events.append(spend_event)

        # Views
        prev_views = self.event_store.get_latest_value("tiktok_video_views", EventSource.TIKTOK) or video_views
        views_delta = ((video_views - prev_views) / prev_views * 100) if prev_views > 0 else 0.0
        views_event = self._create_event(
            event_type=EventType.TREND_SPIKE if views_delta > 50 else EventType.ORDER_PLACED,
            severity=EventSeverity.OPPORTUNITY if views_delta > 50 else EventSeverity.INFO,
            metric_name="tiktok_video_views",
            metric_value=video_views,
            metric_unit="views",
            metric_delta_pct=views_delta,
            previous_value=prev_views,
            campaign_id=campaign_id,
            raw_data=metrics,
            tags=["tiktok", "views", "video"],
            category="video",
        )
        self.save_and_publish(views_event)
        events.append(views_event)

        # CPA
        prev_cpa = self.event_store.get_latest_value("tiktok_cpa", EventSource.TIKTOK) or cpa
        cpa_delta = ((cpa - prev_cpa) / prev_cpa * 100) if prev_cpa > 0 else 0.0
        cpa_event = self._create_event(
            event_type=EventType.CPA_SPIKE if cpa_delta > 10 else EventType.CPA_DROP,
            severity=EventSeverity.WARNING if cpa_delta > 20 else EventSeverity.INFO,
            metric_name="tiktok_cpa",
            metric_value=cpa,
            metric_unit="USD",
            metric_delta_pct=cpa_delta,
            previous_value=prev_cpa,
            campaign_id=campaign_id,
            raw_data={"conversions": conversions, "spend": spend},
            tags=["tiktok", "cpa", "campaign"],
            category="ads",
        )
        self.save_and_publish(cpa_event)
        events.append(cpa_event)

        return events


# ─────────────────────────────────────────────────────────────────────────────
# Google Trends 收集器
# ─────────────────────────────────────────────────────────────────────────────

class GoogleTrendsCollector(BaseCollector):
    """
    Google Trends 收集器
    读取：Search Trend / SEO Traffic 相关性
    使用 pytrends 或 SerpAPI
    """

    def _source_type(self) -> EventSource:
        return EventSource.GOOGLE

    def health_check(self) -> bool:
        if not self.config.enabled:
            return False
        return True

    def collect(self) -> list[RealityEvent]:
        events = []
        if not self.config.enabled:
            return events

        events.extend(self._collect_trends())
        return events

    def _collect_trends(self) -> list[RealityEvent]:
        """收集 Google Trends 数据"""
        events = []

        # 从配置文件读取要监控的关键词（api_secret 字段存储关键词列表，逗号分隔）
        keywords_raw = self.config.api_secret.strip() if self.config.api_secret else ""
        if keywords_raw:
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        else:
            # your-store.com 默认关键词（礼品相关）
            keywords = [
                "gift box", "custom gift", "Father's Day gift",
                "gift for her", "gift for him", "gift set",
                "luxury gift", "party gift", "wedding gift"
            ]
        keywords = keywords[:5]

        for keyword in keywords[:5]:  # 最多5个
            trend_value = self._fetch_trend(keyword)
            if trend_value is None:
                continue

            metric_name = f"google_trend_{keyword.replace(' ', '_').lower()}"
            prev_value = self.event_store.get_latest_value(metric_name, EventSource.GOOGLE) or trend_value
            delta_pct = ((trend_value - prev_value) / prev_value * 100) if prev_value > 0 else 0.0

            event_type = EventType.TREND_SPIKE if delta_pct > 30 else (EventType.TREND_DROP if delta_pct < -30 else EventType.ORDER_PLACED)
            severity = EventSeverity.OPPORTUNITY if delta_pct > 50 else EventSeverity.INFO

            event = self._create_event(
                event_type=event_type,
                severity=severity,
                metric_name=metric_name,
                metric_value=trend_value,
                metric_unit="interest",
                metric_delta_pct=delta_pct,
                previous_value=prev_value,
                raw_data={"keyword": keyword},
                tags=["google", "trends", keyword],
                category="seo",
            )
            self.save_and_publish(event)
            events.append(event)

        return events

    def _fetch_trend(self, keyword: str) -> Optional[float]:
        """获取关键词趋势值（0-100）"""
        try:
            # 优先使用 SerpAPI Google Trends
            if self.config.api_key and not self.config.api_key.startswith("pytrends"):
                # SerpAPI 模式
                return self._fetch_via_serpapi(keyword)
            else:
                # pytrends 模式（免费但需要代理）
                return self._fetch_via_pytrends(keyword)
        except Exception as e:
            logger.warning(f"Google Trends fetch failed for '{keyword}': {e}")
            return None

    def _fetch_via_serpapi(self, keyword: str) -> Optional[float]:
        """通过 SerpAPI 获取趋势"""
        import os
        api_key = os.environ.get("SERPAPI_KEY", self.config.api_key)
        if not api_key or api_key == "pytrends":
            return None

        url = "https://serpapi.com/search.json"
        params = {
            "q": keyword,
            "engine": "google_trends",
            "data": "TIMESERIES",
            "api_key": api_key,
        }
        data = self._safe_request("GET", url, params=params)
        if not data or "interest_over_time" not in data:
            return None

        timeline = data["interest_over_time"].get("timeline_data", [])
        if not timeline:
            return None

        # 取最后一个数据点的值
        latest = timeline[-1]
        values = latest.get("values", [])
        if not values:
            return None

        # extracted_value 是数值类型，value 可能是字符串 "18"
        entry = values[0]
        raw_val = entry.get("extracted_value") or entry.get("value",0)
        return float(raw_val)

    def _fetch_via_pytrends(self, keyword: str) -> Optional[float]:
        """通过 pytrends 获取趋势（需要代理）"""
        try:
            from pytrends.request import TrendReq
            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload([keyword], timeframe="now 7-d")
            data = pytrends.interest_over_time()
            if not data.empty:
                return float(data[keyword].iloc[-1])
        except Exception as e:
            logger.warning(f"pytrends failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Reality Hub 主入口
# ─────────────────────────────────────────────────────────────────────────────

class RealityHub:
    """
    Reality Hub — 统一入口
    ===============================
    hub.collect()      → 收集所有平台数据
    hub.sync()         → 同步到 KG
    hub.publish_events() → 发布事件到 Event Bus
    """

    def __init__(self, config: Optional[RealityHubConfig] = None, config_path: Optional[str] = None):
        if config:
            self.config = config
        elif config_path:
            self.config = RealityHubConfig.from_file(config_path)
        else:
            self.config = RealityHubConfig()

        # 核心组件
        self.event_store = EventStore(self.config.event_store_path)
        self.event_bus = EventBus()
        self.anomaly_detector = AnomalyDetector()

        # CausaMem L0 持久化：EventBus → raw_events 表（全类补丁）
        from memory.event_capture import patch_eventbus
        patch_eventbus()

        # 平台收集器
        self.shopify = ShopifyCollector(
            self.config.shopify, self.event_store, self.event_bus, self.anomaly_detector
        )
        self.wc = WCOrdersCollector(
            self.config.woo, self.event_store, self.event_bus, self.anomaly_detector
        )
        self.woo = WooCommerceCollector(
            self.config.woo, self.event_store, self.event_bus, self.anomaly_detector
        )
        self.meta = MetaCollector(
            self.config.meta, self.event_store, self.event_bus, self.anomaly_detector
        )
        self.tiktok = TikTokCollector(
            self.config.tiktok, self.event_store, self.event_bus, self.anomaly_detector
        )
        self.google = GoogleTrendsCollector(
            self.config.google, self.event_store, self.event_bus, self.anomaly_detector
        )
        # Amazon / 1688 / Shopify-spy collectors (轻量级 — 不跑 EventBus, 直接返回 JSON)
        self.amazon_enabled = self.config.amazon.enabled if hasattr(self.config, 'amazon') else False
        self.alibaba_enabled = self.config.alibaba.enabled if hasattr(self.config, 'alibaba') else False

        # 订阅者
        self._subscribers: list[callable] = []

        # 统计
        self.stats = {
            "total_events": 0,
            "last_run": None,
            "collectors_status": {},
        }

    def collect(self) -> dict:
        """
        收集所有平台数据
        返回收集结果统计
        """
        results = {}
        all_events = []

        logger.info("=== RealityHub.collect() 开始 ===")

        # Shopify
        try:
            events = self.shopify.collect()
            results["shopify"] = {"events": len(events), "status": "ok"}
            all_events.extend(events)
        except Exception as e:
            logger.error(f"Shopify collect failed: {e}")
            results["shopify"] = {"events": 0, "status": f"error: {e}"}

        # WooCommerce DB 直连（绕过 REST API）
        try:
            events = self.wc.collect()
            results["wc"] = {"events": len(events), "status": "ok"}
            all_events.extend(events)
        except Exception as e:
            logger.error(f"WooCommerce DB collect failed: {e}")
            results["wc"] = {"events": 0, "status": f"error: {e}"}

        # WooCommerce REST API（备用）
        try:
            events = self.woo.collect()
            results["woo"] = {"events": len(events), "status": "ok"}
            all_events.extend(events)
        except Exception as e:
            logger.error(f"WooCommerce collect failed: {e}")
            results["woo"] = {"events": 0, "status": f"error: {e}"}

        # Meta
        try:
            events = self.meta.collect()
            results["meta"] = {"events": len(events), "status": "ok"}
            all_events.extend(events)
        except Exception as e:
            logger.error(f"Meta collect failed: {e}")
            results["meta"] = {"events": 0, "status": f"error: {e}"}

        # TikTok
        try:
            events = self.tiktok.collect()
            results["tiktok"] = {"events": len(events), "status": "ok"}
            all_events.extend(events)
        except Exception as e:
            logger.error(f"TikTok collect failed: {e}")
            results["tiktok"] = {"events": 0, "status": f"error: {e}"}

        # Amazon Market Intelligence (APIClaw — fast categories endpoint)
        if self.amazon_enabled:
            try:
                from reality.amazon_collector import collect_market_intel as amazon_fast_collect
                amazon_events = amazon_fast_collect(keywords=["gift box", "home decor", "kitchen", "outdoor", "pet supply", "beauty", "fitness"])
                results["amazon"] = {"events": len(amazon_events), "status": "ok"}
                all_events.extend(amazon_events)
                logger.info(f"Amazon collector: {len(amazon_events)} events")
            except Exception as e:
                logger.error(f"Amazon collect failed: {e}")
                results["amazon"] = {"events": 0, "status": f"error: {e}"}
        else:
            results["amazon"] = {"events": 0, "status": "disabled"}

        # 1688 Supply Chain (Alibaba)
        if self.alibaba_enabled:
            try:
                alibaba_keywords = ["礼品盒", "gift box", "party decoration", "home decor"]
                snapshots = alibaba_research(*alibaba_keywords)
                alibaba_events = [s.to_event_dict() for s in snapshots if hasattr(s, 'to_event_dict')]
                results["alibaba"] = {"events": len(alibaba_events), "status": "ok"}
                all_events.extend(alibaba_events)
                logger.info(f"1688 collector: {len(alibaba_events)} snapshots")
            except Exception as e:
                logger.error(f"1688 collect failed: {e}")
                results["alibaba"] = {"events": 0, "status": f"error: {e}"}
        else:
            results["alibaba"] = {"events": 0, "status": "disabled"}

        # Google Trends
        try:
            events = self.google.collect()
            results["google"] = {"events": len(events), "status": "ok"}
            all_events.extend(events)
        except Exception as e:
            logger.error(f"Google collect failed: {e}")
            results["google"] = {"events": 0, "status": f"error: {e}"}

        self.stats["total_events"] += len(all_events)
        self.stats["last_run"] = datetime.now(timezone.utc).isoformat()
        self.stats["collectors_status"] = results

        logger.info(f"=== RealityHub.collect() 完成: {len(all_events)} events ===")
        return results

    def health_check(self) -> dict:
        """健康检查所有收集器"""
        return {
            "shopify": self.shopify.health_check(),
            "wc": self.wc.health_check(),
            "woo": self.woo.health_check(),
            "meta": self.meta.health_check(),
            "tiktok": self.tiktok.health_check(),
            "google": self.google.health_check(),
            "event_store_count": self.event_store.count(),
        }

    def sync(self) -> dict:
        """
        同步事件到 Knowledge Graph
        读取 Event Store 中最近24小时事件，更新 KG
        """
        events = self.event_store.recent_events(hours=24)
        synced = 0

        try:
            from ..hvos_kg_engine import KGEngine
            kg = KGEngine()
            for event in events:
                try:
                    kg.upsert_reality_event(event)
                    synced += 1
                except Exception as e:
                    logger.warning(f"KG sync failed for {event.event_id}: {e}")
        except ImportError:
            logger.warning("KGEngine not available, skipping sync")

        return {"events_checked": len(events), "synced": synced}

    def publish_events(self) -> int:
        """
        手动发布最近事件到 Event Bus
        返回发布数量
        """
        events = self.event_store.recent_events(hours=1)
        count = 0
        for event in events:
            if self.event_bus.publish(event):
                count += 1
        return count

    def subscribe(self, handler: callable):
        """订阅事件"""
        self._subscribers.append(handler)
        self.event_bus.subscribe_all(handler)

    def get_recent_events(self, hours: int = 24) -> list[RealityEvent]:
        """获取最近事件"""
        return self.event_store.recent_events(hours=hours)

    def get_anomalies(self, hours: int = 24) -> list[RealityEvent]:
        """获取最近异常事件"""
        events = self.event_store.recent_events(hours=hours)
        return [e for e in events if e.is_anomaly]

    def clear_all_events(self):
        """清空所有事件（测试用）"""
        self.event_store.clear_all()
        self.event_bus.clear_log()
        self.anomaly_detector.clear()

    def export_config_template(self, path: str = "reality_config.json"):
        """导出配置模板"""
        template = {
            "shopify": {
                "enabled": False,
                "store_url": "https://your-store.myshopify.com",
                "access_token": "YOUR_SHOPIFY_ACCESS_TOKEN",
                "anomaly_threshold_pct": 20.0,
            },
            "woo": {
                "enabled": False,
                "store_url": "https://your-store.com",
                "api_key": "YOUR_WOO_CONSUMER_KEY",
                "api_secret": "YOUR_WOO_CONSUMER_SECRET",
                "anomaly_threshold_pct": 20.0,
            },
            "meta": {
                "enabled": False,
                "ad_account_id": "act_XXXXXXXXXX",
                "access_token": "YOUR_META_ACCESS_TOKEN",
                "anomaly_threshold_pct": 20.0,
            },
            "tiktok": {
                "enabled": False,
                "ad_account_id": "YOUR_TIKTOK_AD_ACCOUNT_ID",
                "access_token": "YOUR_TIKTOK_ACCESS_TOKEN",
                "anomaly_threshold_pct": 20.0,
            },
            "google": {
                "enabled": False,
                "api_key": "YOUR_SERPAPI_KEY",
                "anomaly_threshold_pct": 30.0,
            },
            "event_store_path": "reality/events.db",
            "event_bus_enabled": True,
            "kg_update_enabled": True,
            "alert_enabled": True,
            "log_level": "INFO",
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        return path


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse, os

    parser = argparse.ArgumentParser(description="HVOS Reality Hub")
    parser.add_argument("--config", default="reality_config.json", help="配置文件路径")
    parser.add_argument("--action", default="collect", choices=["collect", "health", "export", "clear", "query"])
    parser.add_argument("--hours", type=int, default=24, help="查询最近N小时事件")
    parser.add_argument("--source", help="按来源过滤 (shopify/meta/tiktok/google)")
    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = args.config if os.path.exists(args.config) else None
    hub = RealityHub(config_path=config_path)

    if args.action == "collect":
        results = hub.collect()
        print(json.dumps(results, indent=2, default=str))
        print(f"\n总事件数: {hub.stats['total_events']}")
        print(f"最后运行: {hub.stats['last_run']}")

    elif args.action == "health":
        status = hub.health_check()
        print(json.dumps(status, indent=2, default=str))

    elif args.action == "export":
        path = hub.export_config_template(args.config)
        print(f"配置模板已导出: {path}")

    elif args.action == "clear":
        hub.clear_all_events()
        print("所有事件已清空")

    elif args.action == "query":
        source_map = {
            "shopify": EventSource.SHOPIFY,
            "meta": EventSource.META,
            "tiktok": EventSource.TIKTOK,
            "google": EventSource.GOOGLE,
        }
        source = source_map.get(args.source) if args.source else None
        events = hub.event_store.recent_events(hours=args.hours, source=source)
        print(f"最近 {args.hours}h 事件数: {len(events)}")
        for e in events:
            print(f"  [{e.source.value}] {e.event_type.value} | {e.metric_name}={e.metric_value}{e.metric_unit} ({e.sign()}{abs(e.metric_delta_pct):.1f}%)")


if __name__ == "__main__":
    main()
