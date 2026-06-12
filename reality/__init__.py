"""
HVOS Reality Layer
统一入口：读取真实世界数据 → RealityEvent → Event Bus → KG
"""

from .reality_hub import (
    RealityHub,
    RealityEvent,
    EventStore,
    EventBus,
    EventSource,
    EventType,
    EventSeverity,
    PlatformConfig,
    RealityHubConfig,
    AnomalyDetector,
    ShopifyCollector,
    MetaCollector,
    TikTokCollector,
    GoogleTrendsCollector,
    BaseCollector,
)

__all__ = [
    "RealityHub",
    "RealityEvent",
    "EventStore",
    "EventBus",
    "EventSource",
    "EventType",
    "EventSeverity",
    "PlatformConfig",
    "RealityHubConfig",
    "AnomalyDetector",
    "ShopifyCollector",
    "MetaCollector",
    "TikTokCollector",
    "GoogleTrendsCollector",
    "BaseCollector",
]
__version__ = "1.0.0"