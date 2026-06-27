"""HVOS Reality Collector - WCOrdersCollector"""
from reality.enums import EventSource, EventType
from reality.models import RealityEvent, PlatformConfig
from reality.event_bus import EventBus
from reality.reality_hub import BaseCollector, RealityHubConfig

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