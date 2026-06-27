"""HVOS Reality Collector - TikTokCollector"""
from reality.enums import EventSource, EventType
from reality.models import RealityEvent, PlatformConfig
from reality.event_bus import EventBus
from reality.reality_hub import BaseCollector, RealityHubConfig

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