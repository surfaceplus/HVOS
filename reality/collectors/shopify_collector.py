"""HVOS Reality Collector - ShopifyCollector"""
from reality.enums import EventSource, EventType
from reality.models import RealityEvent, PlatformConfig
from reality.event_bus import EventBus
from reality.reality_hub import BaseCollector, RealityHubConfig

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