"""HVOS Reality Collector - MetaCollector"""
from reality.enums import EventSource, EventType
from reality.models import RealityEvent, PlatformConfig
from reality.event_bus import EventBus
from reality.reality_hub import BaseCollector, RealityHubConfig

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