"""HVOS Reality Collector - WooCommerceCollector"""
from reality.enums import EventSource, EventType
from reality.models import RealityEvent, PlatformConfig
from reality.event_bus import EventBus
from reality.reality_hub import BaseCollector, RealityHubConfig

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