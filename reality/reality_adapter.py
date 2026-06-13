"""
HVOS Reality Adapter Framework
===============================
统一适配器接口：WooCommerce / Shopify / Meta / TikTok / Amazon

核心理念：
  新增数据源时，Write a new adapter, don't modify core logic.

Stage 1.5: Reality Layer

Author: HVOS X Reality Layer
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any, Literal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 统一响应模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AdapterOrders:
    """统一订单数据结构"""
    total_count: int           # 订单总数
    total_revenue: float       # 总收入
    total_cost: float          # 总成本（如果可获取）
    avg_order_value: float     # AOV
    currency: str = "USD"

    # 按状态分解
    completed_count: int = 0
    completed_revenue: float = 0.0
    refunded_count: int = 0
    refunded_amount: float = 0.0

    # 详细订单列表
    orders: list[dict] = field(default_factory=list)

    # 时间窗口
    window_start: str = ""
    window_end: str = ""

    # 原始响应（调试用）
    raw_response: Optional[dict] = None

    def to_reality_metrics(self) -> dict:
        """转换为 RealityEvent 可用的指标字典"""
        return {
            "total_orders": self.total_count,
            "total_revenue": self.total_revenue,
            "aov": self.avg_order_value,
            "completed_orders": self.completed_count,
            "completed_revenue": self.completed_revenue,
            "refunded_orders": self.refunded_count,
            "refunded_amount": self.refunded_amount,
            "currency": self.currency,
            "window_start": self.window_start,
            "window_end": self.window_end,
        }


@dataclass
class AdapterMetrics:
    """统一指标数据结构（广告/流量指标）"""
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    conversions: int = 0
    revenue: float = 0.0

    # 计算指标
    ctr: float = 0.0       # Click-through rate
    cvr: float = 0.0       # Conversion rate
    cpc: float = 0.0       # Cost per click
    cpa: float = 0.0       # Cost per acquisition
    roas: float = 0.0      # Return on ad spend

    platform: str = ""
    campaign_id: Optional[str] = None
    adset_id: Optional[str] = None
    ad_id: Optional[str] = None

    currency: str = "USD"
    window_start: str = ""
    window_end: str = ""

    raw_response: Optional[dict] = None

    def compute_rates(self):
        """计算衍生指标"""
        if self.impressions > 0:
            self.ctr = self.clicks / self.impressions
        if self.clicks > 0:
            self.cpc = self.spend / self.clicks
        if self.conversions > 0:
            self.cpa = self.spend / self.conversions
        if self.spend > 0:
            self.roas = self.revenue / self.spend
        if self.clicks > 0:
            self.cvr = self.conversions / self.clicks
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Base Adapter — 抽象基类
# ─────────────────────────────────────────────────────────────────────────────

class BaseRealityAdapter(ABC):
    """
    Reality Adapter 抽象基类

    所有平台适配器必须实现：
    - fetch_orders()     → AdapterOrders
    - fetch_metrics()   → AdapterMetrics
    - test_connection() → bool

    可选实现：
    - fetch_products()  → 产品列表
    - fetch_ad_campaigns() → 广告系列
    """

    VERSION = "1.0.0"
    platform_name: str = "base"

    def __init__(self, config: dict):
        """
        Args:
            config: 平台配置，包含：
                - api_key / api_secret
                - store_url / shop_name
                - access_token
                等平台特定参数
        """
        self.config = config
        self._connected = False

    # ─────────────────────────────────────────────────────────────────────
    # 必须实现的方法
    # ─────────────────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_orders(
        self,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        status_filter: Optional[list[str]] = None,
    ) -> AdapterOrders:
        """
        获取订单数据

        Args:
            window_start: ISO 格式起始时间
            window_end: ISO 格式结束时间
            status_filter: 状态过滤，如 ["completed", "processing"]

        Returns:
            AdapterOrders: 统一格式订单数据
        """
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """
        测试连接是否正常

        Returns:
            bool: 连接是否成功
        """
        ...

    # ─────────────────────────────────────────────────────────────────────
    # 可选实现的方法（提供默认实现）
    # ─────────────────────────────────────────────────────────────────────

    def fetch_metrics(
        self,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ) -> AdapterMetrics:
        """
        获取广告/流量指标（默认返回空，需要子类覆盖）

        Returns:
            AdapterMetrics: 统一格式指标数据
        """
        return AdapterMetrics(platform=self.platform_name)

    def fetch_products(
        self,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取产品列表（默认返回空列表，需要子类覆盖）

        Returns:
            list[dict]: 产品列表
        """
        return []

    def get_platform_name(self) -> str:
        return self.platform_name

    def is_connected(self) -> bool:
        return self._connected

    # ─────────────────────────────────────────────────────────────────────
    # 通用工具方法
    # ─────────────────────────────────────────────────────────────────────

    def _iso_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_window(self, days: int = 30) -> tuple[str, str]:
        """返回默认时间窗口"""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        return start.isoformat(), now.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce Adapter
# ─────────────────────────────────────────────────────────────────────────────

class WooAdapter(BaseRealityAdapter):
    """
    WooCommerce 适配器

    配置参数：
        store_url: WooCommerce REST API 基础 URL
                   例如：https://your-store.com/wp-json/wc/v3
        consumer_key: WooCommerce REST API Consumer Key
        consumer_secret: WooCommerce REST API Consumer Secret
        table_prefix: WP 数据库表前缀，默认 wp_0dd69b_

    数据库直连配置（绕过 REST API 401 Bug）：
        host: MySQL host
        port: MySQL port
        database: 数据库名
        user: 数据库用户
        password: 数据库密码
    """

    platform_name = "woo"

    def __init__(self, config: dict):
        super().__init__(config)
        self.store_url = config.get("store_url", "")
        self.consumer_key = config.get("consumer_key", "")
        self.consumer_secret = config.get("consumer_secret", "")
        self.table_prefix = config.get("table_prefix", "wp_0dd69b_")

        # 数据库直连配置（可选，用于绕过 REST API Bug）
        self.db_config = {
            "host": config.get("host", "YOUR_VPS_IP"),
            "port": config.get("port", 3306),
            "database": config.get("database", "YOUR_MYSQL_DATABASE"),
            "user": config.get("user", "YOUR_MYSQL_DATABASE"),
            "password": config.get("password", ""),
        }

        self._mysql_conn = None

    # ─────────────────────────────────────────────────────────────────────
    # 必须实现
    # ─────────────────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """测试 WooCommerce 连接"""
        try:
            # 尝试直连 MySQL
            import mysql.connector
            conn = mysql.connector.connect(**self.db_config)
            conn.close()
            self._connected = True
            return True
        except ImportError:
            # 没有 mysql-connector-python，尝试 REST API
            try:
                import urllib.request
                url = f"{self.store_url}/orders?per_page=1"
                import base64
                credentials = f"{self.consumer_key}:{self.consumer_secret}"
                encoded = base64.b64encode(credentials.encode()).decode()
                req = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Basic {encoded}"}
                )
                urllib.request.urlopen(req, timeout=10)
                self._connected = True
                return True
            except Exception as e:
                logger.error(f"WooCommerce connection failed: {e}")
                self._connected = False
                return False
        except Exception as e:
            logger.error(f"WooCommerce connection failed: {e}")
            self._connected = False
            return False

    def fetch_orders(
        self,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        status_filter: Optional[list[str]] = None,
    ) -> AdapterOrders:
        """
        获取 WooCommerce 订单（直连 MySQL，绕过 REST API Bug）

        使用 WooCommerce HPOS 表：wc_orders
        """
        if status_filter is None:
            status_filter = ["completed", "processing", "on-hold"]

        w_start = window_start or self._default_window(30)[0]
        w_end = window_end or self._iso_now()

        try:
            import mysql.connector
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor(dictionary=True)

            # HPOS 模式：wc_orders 表
            status_placeholders = ",".join(["%s"] * len(status_filter))
            query = f"""
                SELECT
                    id,
                    status,
                    total,
                    total_tax,
                    currency,
                    date_created,
                    billing_email,
                    payment_method
                FROM {self.table_prefix}wc_orders
                WHERE date_created >= %s
                  AND date_created <= %s
                  AND status IN ({status_placeholders})
                ORDER BY date_created DESC
            """
            cursor.execute(query, [w_start, w_end] + status_filter)
            rows = cursor.fetchall()

            total_revenue = 0.0
            total_cost = 0.0
            completed_revenue = 0.0
            refunded_amount = 0.0
            orders_list = []

            for row in rows:
                order_total = float(row["total"] or 0)
                status = row["status"]

                orders_list.append({
                    "id": str(row["id"]),
                    "status": status,
                    "total": order_total,
                    "currency": row["currency"] or "USD",
                    "date_created": str(row["date_created"]),
                    "billing_email": row["billing_email"],
                    "payment_method": row["payment_method"],
                })

                if status == "completed":
                    completed_revenue += order_total

                if status not in ["refunded", "cancelled", "failed"]:
                    total_revenue += order_total
                elif status == "refunded":
                    refunded_amount += order_total

            cursor.close()
            conn.close()

            return AdapterOrders(
                total_count=len(rows),
                total_revenue=round(total_revenue, 2),
                total_cost=round(total_cost, 2),
                avg_order_value=round(total_revenue / len(rows), 2) if rows else 0.0,
                completed_count=len([r for r in rows if r["status"] == "completed"]),
                completed_revenue=round(completed_revenue, 2),
                refunded_count=len([r for r in rows if r["status"] == "refunded"]),
                refunded_amount=round(refunded_amount, 2),
                currency="USD",
                orders=orders_list,
                window_start=w_start,
                window_end=w_end,
            )

        except ImportError:
            logger.error("mysql-connector-python not installed")
            return AdapterOrders(total_count=0, total_revenue=0.0)
        except Exception as e:
            logger.error(f"Failed to fetch WooCommerce orders: {e}")
            return AdapterOrders(total_count=0, total_revenue=0.0)

    # ─────────────────────────────────────────────────────────────────────
    # 可选实现
    # ─────────────────────────────────────────────────────────────────────

    def fetch_products(self, limit: int = 100) -> list[dict]:
        """获取 WooCommerce 产品列表"""
        try:
            import mysql.connector
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor(dictionary=True)

            query = f"""
                SELECT
                    p.ID,
                    p.post_title,
                    pm.meta_value AS sku
                FROM {self.table_prefix}posts p
                LEFT JOIN {self.table_prefix}postmeta pm
                    ON p.ID = pm.post_id AND pm.meta_key = '_sku'
                WHERE p.post_type = 'product'
                  AND p.post_status = 'publish'
                LIMIT %s
            """
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

            cursor.close()
            conn.close()

            return [
                {"id": str(r["ID"]), "name": r["post_title"], "sku": r["sku"] or ""}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to fetch WooCommerce products: {e}")
            return []


# ─────────────────────────────────────────────────────────────────────────────
# Shopify Adapter (Skeleton — Stage 2 实现)
# ─────────────────────────────────────────────────────────────────────────────

class ShopifyAdapter(BaseRealityAdapter):
    """
    Shopify 适配器

    配置参数：
        shop_name: Shopify 店铺名（如 mystore）
        access_token: Shopify Admin API Access Token
        api_version: API 版本，默认 "2024-01"
    """

    platform_name = "shopify"

    def __init__(self, config: dict):
        super().__init__(config)
        self.shop_name = config.get("shop_name", "")
        self.access_token = config.get("access_token", "")
        self.api_version = config.get("api_version", "2024-01")
        self.base_url = f"https://{self.shop_name}.myshopify.com/admin/api/{self.api_version}"

    def test_connection(self) -> bool:
        try:
            import urllib.request
            url = f"{self.base_url}/shop.json"
            req = urllib.request.Request(
                url,
                headers={
                    "X-Shopify-Access-Token": self.access_token,
                    "Content-Type": "application/json",
                }
            )
            urllib.request.urlopen(req, timeout=10)
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Shopify connection failed: {e}")
            self._connected = False
            return False

    def fetch_orders(
        self,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        status_filter: Optional[list[str]] = None,
    ) -> AdapterOrders:
        """获取 Shopify 订单"""
        if status_filter is None:
            status_filter = ["any"]

        w_start = window_start or self._default_window(30)[0]
        w_end = window_end or self._iso_now()

        try:
            import urllib.request
            import json

            status_param = "any" if "any" in status_filter else ",".join(status_filter)
            url = (
                f"{self.base_url}/orders.json"
                f"?status={status_param}"
                f"&created_at_min={w_start}"
                f"&created_at_max={w_end}"
                f"&fields=id,name,total_price,currency,financial_status,created_at"
            )
            req = urllib.request.Request(
                url,
                headers={"X-Shopify-Access-Token": self.access_token}
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())

            orders = data.get("orders", [])
            total_revenue = sum(float(o["total_price"]) for o in orders
                                if o["financial_status"] != "refunded")
            refunded = sum(float(o["total_price"]) for o in orders
                           if o["financial_status"] == "refunded")

            return AdapterOrders(
                total_count=len(orders),
                total_revenue=round(total_revenue, 2),
                total_cost=0.0,
                avg_order_value=round(total_revenue / len(orders), 2) if orders else 0.0,
                completed_count=len([o for o in orders if o["financial_status"] == "paid"]),
                completed_revenue=round(total_revenue, 2),
                refunded_count=len([o for o in orders if o["financial_status"] == "refunded"]),
                refunded_amount=round(refunded, 2),
                orders=[{
                    "id": str(o["id"]),
                    "status": o["financial_status"],
                    "total": float(o["total_price"]),
                    "currency": o["currency"],
                    "date_created": o["created_at"],
                } for o in orders],
                window_start=w_start,
                window_end=w_end,
            )
        except Exception as e:
            logger.error(f"Failed to fetch Shopify orders: {e}")
            return AdapterOrders(total_count=0, total_revenue=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Meta Adapter (Skeleton — Stage 2 实现)
# ─────────────────────────────────────────────────────────────────────────────

class MetaAdapter(BaseRealityAdapter):
    """
    Meta (Facebook/Instagram) Ads 适配器

    配置参数：
        ad_account_id: Facebook Ad Account ID（如 act_123456789）
        access_token: Facebook Marketing API Access Token
    """

    platform_name = "meta"

    def __init__(self, config: dict):
        super().__init__(config)
        self.ad_account_id = config.get("ad_account_id", "")
        self.access_token = config.get("access_token", "")
        self.graph_url = "https://graph.facebook.com/v19.0"

    def test_connection(self) -> bool:
        try:
            import urllib.request
            url = f"{self.graph_url}/me?access_token={self.access_token}"
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=10)
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Meta connection failed: {e}")
            self._connected = False
            return False

    def fetch_metrics(
        self,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ) -> AdapterMetrics:
        """获取 Meta 广告指标"""
        w_start = window_start or self._default_window(7)[0]
        w_end = window_end or self._iso_now()

        try:
            import urllib.request
            import json

            fields = "impressions,clicks,spend,actions,action_values"
            url = (
                f"{self.graph_url}/act_{self.ad_account_id}/insights"
                f"?time_range={{'since':'{w_start[:10]}','until':'{w_end[:10]}'}}"
                f"&fields={fields}"
                f"&access_token={self.access_token}"
            )
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())

            data = data.get("data", [{}])[0] if data.get("data") else {}

            metrics = AdapterMetrics(
                impressions=int(data.get("impressions", 0)),
                clicks=int(data.get("clicks", 0)),
                spend=float(data.get("spend", 0)),
                conversions=0,  # 需要从 actions 解析
                revenue=0.0,    # 需要从 action_values 解析
                platform="meta",
                window_start=w_start,
                window_end=w_end,
            )
            return metrics.compute_rates()

        except Exception as e:
            logger.error(f"Failed to fetch Meta metrics: {e}")
            return AdapterMetrics(platform="meta")


# ─────────────────────────────────────────────────────────────────────────────
# TikTok Adapter (Skeleton — Stage 2 实现)
# ─────────────────────────────────────────────────────────────────────────────

class TikTokAdapter(BaseRealityAdapter):
    """TikTok Ads 适配器（Skeleton）"""
    platform_name = "tiktok"

    def __init__(self, config: dict):
        super().__init__(config)

    def test_connection(self) -> bool:
        # TODO: 实现 TikTok API 连接测试
        self._connected = False
        return False

    def fetch_orders(self, **kwargs) -> AdapterOrders:
        return AdapterOrders(total_count=0, total_revenue=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Amazon Adapter (Skeleton — Stage 2 实现)
# ─────────────────────────────────────────────────────────────────────────────

class AmazonAdapter(BaseRealityAdapter):
    """Amazon Seller Central 适配器（Skeleton）"""
    platform_name = "amazon"

    def __init__(self, config: dict):
        super().__init__(config)

    def test_connection(self) -> bool:
        # TODO: 实现 Amazon SP-API 连接测试
        self._connected = False
        return False

    def fetch_orders(self, **kwargs) -> AdapterOrders:
        return AdapterOrders(total_count=0, total_revenue=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Adapter Factory
# ─────────────────────────────────────────────────────────────────────────────

ADAPTER_REGISTRY: dict[str, type[BaseRealityAdapter]] = {
    "woo": WooAdapter,
    "shopify": ShopifyAdapter,
    "meta": MetaAdapter,
    "tiktok": TikTokAdapter,
    "amazon": AmazonAdapter,
}


def create_adapter(platform: str, config: dict) -> BaseRealityAdapter:
    """
    工厂函数：根据平台类型创建适配器

    Args:
        platform: 平台名（woo/shopify/meta/tiktok/amazon）
        config: 平台配置

    Returns:
        BaseRealityAdapter: 适配器实例

    Raises:
        ValueError: 不支持的平台
    """
    platform = platform.lower()
    if platform not in ADAPTER_REGISTRY:
        raise ValueError(
            f"Unsupported platform: {platform}. "
            f"Available: {list(ADAPTER_REGISTRY.keys())}"
        )
    return ADAPTER_REGISTRY[platform](config)


# ─────────────────────────────────────────────────────────────────────────────
# RealityHub 集成
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_revenue(window_days: int = 30) -> dict[str, AdapterOrders]:
    """
    从所有已配置平台获取收入数据

    读取 reality_config.json 获取已配置的平台列表

    Returns:
        dict[str, AdapterOrders]: 平台名 → 订单数据
    """
    import os
    import json

    hvos_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(hvos_root, "reality_config.json")

    if not os.path.exists(config_path):
        logger.warning(f"reality_config.json not found at {config_path}")
        return {}

    with open(config_path, "r") as f:
        config = json.load(f)

    results = {}
    platforms = config.get("platforms", {})

    for platform, cfg in platforms.items():
        if not cfg.get("enabled", False):
            continue

        try:
            adapter = create_adapter(platform, cfg)
            if adapter.test_connection():
                orders = adapter.fetch_orders(
                    window_start=cfg.get("window_start"),
                    window_end=cfg.get("window_end"),
                )
                results[platform] = orders
                logger.info(f"[{platform}] Fetched {orders.total_count} orders, ${orders.total_revenue:.2f}")
            else:
                logger.warning(f"[{platform}] Connection test failed")
        except Exception as e:
            logger.error(f"[{platform}] Failed: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HVOS Reality Adapter CLI")
    parser.add_argument("--platform", required=True,
                        choices=["woo", "shopify", "meta", "tiktok", "amazon"])
    parser.add_argument("--action", required=True,
                        choices=["test", "orders", "metrics", "products"])
    parser.add_argument("--config", help="Path to platform config JSON")
    args = parser.parse_args()

    # 加载配置
    if args.config:
        import json
        with open(args.config) as f:
            cfg = json.load(f)
    else:
        cfg = {}

    adapter = create_adapter(args.platform, cfg)

    if args.action == "test":
        ok = adapter.test_connection()
        print(f"Connection {'✅ OK' if ok else '❌ FAILED'}")
        return

    elif args.action == "orders":
        orders = adapter.fetch_orders()
        print(json.dumps(orders.to_reality_metrics(), indent=2, default=str))

    elif args.action == "metrics":
        metrics = adapter.fetch_metrics()
        print(json.dumps(asdict(metrics), indent=2, default=str))

    elif args.action == "products":
        products = adapter.fetch_products()
        print(json.dumps(products, indent=2, default=str))


if __name__ == "__main__":
    from datetime import timedelta
    main()
