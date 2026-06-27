"""
HVOS Event → CausaMem 事件捕获桥接
====================================
将 HVOS Event Bus 的事件实时同步到 CausaMem L0 raw_events 表。

实现 EventBus 的持久化：将纯内存 _event_log 变为 CausaMem 因果记忆。

Stage 1.5 Integration

Author: HVOS X × CausaMem
Version: 1.0.0
"""

from __future__ import annotations

import os
import sys
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Any

logger = logging.getLogger(__name__)

# CausaMem 桥接路径
HVOSC_BRIDGE = os.path.join(
    os.path.dirname(__file__), "hvosc_bridge.py"
)
sys.path.insert(0, os.path.dirname(__file__))

try:
    from hvosc_bridge import CausaMemEventCapture
    CAUSAMEM_AVAILABLE = True
except ImportError:
    CAUSAMEM_AVAILABLE = False
    logger.warning("CausaMem bridge not available, event capture disabled")


# ─────────────────────────────────────────────────────────────────────────────
# HVOS Event Types → CausaMem 映射
# ─────────────────────────────────────────────────────────────────────────────

HVOS_EVENT_TYPE_MAP = {
    # 投资决策类
    "INVESTMENT_DECISION": "DECISION",
    "INVESTMENT_REVIEW": "DECISION",
    "BOARD_VOTE": "DECISION",
    "CAPITAL_ALLOCATION": "DECISION",
    # 市场信号类
    "MARKET_SIGNAL": "INSIGHT",
    "COMPETITOR_ALERT": "INSIGHT",
    "TREND_DETECTED": "INSIGHT",
    "PRICE_CHANGE": "INSIGHT",
    # 运营事件类
    "ORDER_COMPLETED": "CHANGE",
    "REFUND_ISSUED": "CHANGE",
    "CAMPAIGN_LAUNCHED": "CHANGE",
    "CAMPAIGN_ENDED": "CHANGE",
    # 预测/评估类
    "ROI_PREDICTED": "INSIGHT",
    "ALPHA_SCORED": "INSIGHT",
    "PATTERN_DETECTED": "INSIGHT",
    # 异常类
    "ERROR": "BUG",
    "FAILURE_DETECTED": "BUG",
    "COMPLIANCE_ISSUE": "BUG",
}


class EventCaptureBridge:
    """
    HVOS EventBus → CausaMem L0 事件桥接器

    用法：
        bridge = EventCaptureBridge()

        # 在 EventBus 的 publish() 方法中调用
        bridge.capture(
            session_id="hvos_main",
            event=event,   # RealityEvent 对象
            raw_event=event_data,  # dict
        )

        # 或者直接调用
        bridge.capture_decision(
            session_id="hvos_main",
            decision="投资 opp_watch_001 $2000",
            reason="ROI 2.3x，供应链稳定",
            opp_id="opp_watch_001",
            investment_amount=2000,
        )
    """

    def __init__(self, async_capture: bool = True):
        """
        Args:
            async_capture: True=异步写入（不阻塞 EventBus），False=同步写入
        """
        self.async_capture = async_capture
        self._capture = CausaMemEventCapture() if CAUSAMEM_AVAILABLE else None
        self._lock = threading.Lock()

    def capture(
        self,
        session_id: str,
        event: Any,
        raw_event: Optional[dict] = None,
    ) -> Optional[int]:
        """
        将 HVOS RealityEvent 写入 CausaMem L0

        Args:
            session_id: HVOS 会话 ID
            event: RealityEvent 对象
            raw_event: 原始事件 dict（如果 event 不可序列化）

        Returns:
            int: CausaMem raw_event ID，失败返回 None
        """
        if not self._capture:
            return None

        # 提取事件内容
        if hasattr(event, "__dict__"):
            event_dict = {
                k: v for k, v in event.__dict__.items()
                if not k.startswith("_")
            }
        else:
            event_dict = raw_event or {}

        event_type = event_dict.get("event_type", "UNKNOWN")
        content = self._summarize_event(event_dict)
        metadata = {
            "hvos_event_type": event_type,
            "causamem_type": HVOS_EVENT_TYPE_MAP.get(event_type, "INSIGHT"),
            "event_dict": event_dict,
        }

        if self.async_capture:
            # 异步写入，不阻塞 EventBus
            thread = threading.Thread(
                target=self._do_capture,
                args=(session_id, content, event_type, metadata),
                daemon=True,
            )
            thread.start()
            return None
        else:
            return self._do_capture(session_id, content, event_type, metadata)

    def _do_capture(
        self,
        session_id: str,
        content: str,
        event_type: str,
        metadata: dict,
    ) -> Optional[int]:
        """实际执行捕获"""
        try:
            with self._lock:
                event_id = self._capture.capture_hvos_event(
                    session_id=session_id,
                    role="system",
                    content=content,
                    source=f"hvos_{event_type.lower()}",
                    metadata=metadata,
                )
            logger.info(f"[EventCaptureBridge] Captured {event_type} → {event_id}")
            return event_id
        except Exception as e:
            logger.error(f"[EventCaptureBridge] Failed to capture: {e}")
            return None

    def capture_decision(
        self,
        session_id: str,
        decision: str,
        reason: str,
        outcome: Optional[str] = None,
        opp_id: Optional[str] = None,
        investment_amount: Optional[float] = None,
    ) -> Optional[int]:
        """捕获投资决策（结构化）"""
        if not self._capture:
            return None

        try:
            return self._capture.capture_decision(
                session_id=session_id,
                decision=decision,
                reason=reason,
                outcome=outcome,
                opp_id=opp_id,
                investment_amount=investment_amount,
            )
        except Exception as e:
            logger.error(f"[EventCaptureBridge] Failed to capture decision: {e}")
            return None

    def capture_signal(
        self,
        session_id: str,
        signal_type: str,
        content: str,
        source: str,
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
    ) -> Optional[int]:
        """捕获市场信号"""
        if not self._capture:
            return None

        try:
            return self._capture.capture_signal(
                session_id=session_id,
                signal_type=signal_type,
                content=content,
                source=source,
                metric_name=metric_name,
                metric_value=metric_value,
            )
        except Exception as e:
            logger.error(f"[EventCaptureBridge] Failed to capture signal: {e}")
            return None

    @staticmethod
    def _summarize_event(event_dict: dict) -> str:
        """将事件字典压缩为单行摘要"""
        event_type = event_dict.get("event_type", "UNKNOWN")
        parts = [f"[{event_type}]"]

        # 关键字段提取
        for key in ["opp_id", "sku", "brand", "signal_type", "metric_name",
                    "decision", "amount", "roi", "predicted_roi", "actual_roi",
                    "error", "message"]:
            if key in event_dict and event_dict[key]:
                val = event_dict[key]
                if isinstance(val, float):
                    val = f"{val:.2f}"
                parts.append(f"{key}={val}")

        return " ".join(parts)[:500]


# ─────────────────────────────────────────────────────────────────────────────
# 自动注入到 EventBus（猴子补丁）
# ─────────────────────────────────────────────────────────────────────────────

_original_publish = None


def patch_eventbus():
    """
    给 HVOS EventBus 自动打猴子补丁：将所有事件同步到 CausaMem

    调用一次即可。以后所有 EventBus.publish() 调用都会自动写入 CausaMem L0。
    """
    global _original_publish

    try:
        from reality.reality_hub import EventBus
    except ImportError as e:
        logger.warning(f"Cannot patch EventBus: {e}")
        return False

    if _original_publish is not None:
        logger.warning("EventBus already patched")
        return False

    _original_publish = EventBus.publish
    bridge = EventCaptureBridge(async_capture=True)

    def patched_publish(self, event):
        """先执行原逻辑，再异步写入 CausaMem"""
        result = _original_publish(self, event)
        try:
            bridge.capture(
                session_id=getattr(self, "_session_id", "default"),
                event=event,
            )
        except Exception as e:
            logger.error(f"EventCaptureBridge error: {e}")
        return result

    EventBus.publish = patched_publish
    logger.info("[EventCaptureBridge] EventBus patched successfully")
    return True


def unpatch_eventbus():
    """卸载猴子补丁"""
    global _original_publish
    if _original_publish is None:
        return
    try:
        from reality.reality_hub import EventBus
        EventBus.publish = _original_publish
        _original_publish = None
        logger.info("[EventCaptureBridge] EventBus unpatched")
    except ImportError:
        pass
