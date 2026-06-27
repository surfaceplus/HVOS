"""
Alert Dispatcher — 机会预警推送

支持渠道：
1. 微信（WeChat）- 推送 H5 报告
2. Knowledge Graph - 创建 Opportunity 节点 + 关系
3. Cron Job - 定时任务通知

注意：iLink Bot API 是会话驱动的，send 必须先有 context_token（从用户发给 Bot 的消息获取）
所以 WeChat 推送策略：
  方案 A：用户接受"等明天 06:00 cron"方案（Cron job 投递在 Gateway 收到用户消息后自动送达）
  方案 B：直接发 H5 文件路径，用户可随时查看
  方案 C：创建本地 cron job，下次触发时送达
"""

import os
import json
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class OpportunityAlert:
    """机会预警数据结构"""
    opportunity_id: str
    opportunity_name: str
    alpha_score: float
    recommendation: str
    key_signals: List[str]
    channels: List[str]
    created_at: str
    category: str = ""
    velocity: float = 0.0
    breadth: float = 0.0
    days_to_window: int = 999


class AlertDispatcher:
    """
    Alert 分发器

    推送逻辑：
    1. STRONG_BUY（≥75分）→ 立即推送微信 + 创建 KG 节点
    2. BUY（60-74分）→ KG 节点 + 等待 Board Meeting
    3. WATCH（45-59分）→ 仅写入 KG，不推送
    4. SKIP（<45分）→ 不写入
    """

    RECOMMENDATION_CHANNELS = {
        "STRONG_BUY": ["wechat", "kg"],
        "BUY": ["kg", "cron"],
        "WATCH": ["kg"],
        "SKIP": []
    }

    def __init__(self,
                 report_dir: str = None,
                 kg_db_path: str = None):
        """
        Args:
            report_dir: H5 报告保存目录
            kg_db_path: KG 数据库路径
        """
        self.report_dir = report_dir or r"C:\Users\Administrator\AppData\Local\hermes\hvos\opportunity\reports"
        self.kg_db_path = kg_db_path or r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph\kg.db"
        os.makedirs(self.report_dir, exist_ok=True)

    def dispatch(self, opportunity) -> dict:
        """
        根据机会评级自动分发

        Args:
            opportunity: Opportunity 对象

        Returns:
            {"status": "dispatched", "channels": [...], "results": {...}}
        """
        recommendation = opportunity.recommendation
        channels = self.RECOMMENDATION_CHANNELS.get(recommendation, [])

        if not channels:
            return {"status": "no_dispatch", "reason": f"SKIP recommendation"}

        results = {}
        for channel in channels:
            if channel == "wechat":
                results["wechat"] = self._send_wechat_alert(opportunity)
            elif channel == "kg":
                results["kg"] = self._persist_to_kg(opportunity)
            elif channel == "cron":
                results["cron"] = self._queue_for_cron(opportunity)

        return {
            "status": "dispatched",
            "recommendation": recommendation,
            "channels": channels,
            "results": results,
            "dispatched_at": datetime.now().isoformat()
        }

    def send_alert(self, opportunity, channels: List[str]) -> dict:
        """
        手动指定渠道发送预警

        Args:
            opportunity: Opportunity 对象
            channels: 手动指定的渠道列表

        Returns:
            {"status": "sent", "channels": ["wechat", "kg"]}
        """
        alert = OpportunityAlert(
            opportunity_id=opportunity.opp_id,
            opportunity_name=opportunity.name,
            alpha_score=opportunity.alpha_score,
            recommendation=opportunity.recommendation,
            key_signals=[s.get("source", "unknown") for s in opportunity.signals]
                         if hasattr(opportunity, 'signals') else [],
            channels=channels,
            created_at=opportunity.created_at if hasattr(opportunity, 'created_at') else datetime.now().isoformat(),
            category=opportunity.category if hasattr(opportunity, 'category') else "",
            velocity=getattr(opportunity, 'velocity', 0),
            breadth=getattr(opportunity, 'breadth', 0),
            days_to_window=getattr(opportunity, 'days_to_window', 999)
        )

        results = {}
        for channel in channels:
            if channel == "wechat":
                results["wechat"] = self._send_wechat_alert(opportunity)
            elif channel == "kg":
                results["kg"] = self._persist_to_kg(opportunity)

        return {"status": "dispatched", "results": results}

    def _send_wechat_alert(self, opportunity) -> dict:
        """
        发送微信预警（H5 报告格式）

        策略：
        1. 生成 H5 报告文件
        2. 文件存入本地，路径记录到 Cron Job 队列
        3. 下次 Cron Job 触发时送达用户

        Returns:
            {"report_path": "...", "cron_queued": True}
        """
        # 生成 H5 报告
        html_content = self._generate_alert_html(opportunity)

        # 保存 H5 文件
        safe_name = opportunity.name.replace(' ', '_').replace('/', '_')[:40]
        filename = f"opp_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        filepath = os.path.join(self.report_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        # 写入 Cron 队列
        cron_queue_path = os.path.join(self.report_dir, "wechat_dispatch_queue.json")
        queue = []
        if os.path.exists(cron_queue_path):
            try:
                with open(cron_queue_path, "r", encoding="utf-8") as f:
                    queue = json.load(f)
            except:
                queue = []

        queue.append({
            "report_path": filepath,
            "opportunity_name": opportunity.name,
            "alpha_score": opportunity.alpha_score,
            "recommendation": opportunity.recommendation,
            "queued_at": datetime.now().isoformat()
        })

        with open(cron_queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)

        print(f"[AlertDispatcher] WeChat alert queued: {opportunity.name} "
              f"(Score: {opportunity.alpha_score})")

        return {
            "report_path": filepath,
            "cron_queued": True,
            "queue_size": len(queue)
        }

    def _generate_alert_html(self, opportunity) -> str:
        """生成 Opportunity Alert H5 页面"""
        recommendation_colors = {
            "STRONG_BUY": "#00C853",
            "BUY": "#4CAF50",
            "WATCH": "#FFC107",
            "SKIP": "#F44336"
        }
        color = recommendation_colors.get(opportunity.recommendation, "#9E9E9E")

        # 从 opportunity 对象获取各因子
        velocity = getattr(opportunity, 'velocity', 0)
        breadth = getattr(opportunity, 'breadth', 0)
        depth = getattr(opportunity, 'depth', 0)
        gap = getattr(opportunity, 'competition_gap', 0)
        seasonal = getattr(opportunity, 'seasonal_fit', 0)
        days_to = getattr(opportunity, 'days_to_window', 999)
        window = getattr(opportunity, 'seasonal_window', '无季节性窗口')
        category = getattr(opportunity, 'category', 'general')

        signals = getattr(opportunity, 'signals', [])
        signal_sources = list(set(s.get("source", "unknown") for s in signals))

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HVOS Opportunity Alert — {opportunity.name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0a0a0a; color: #fff; min-height: 100vh; padding: 16px; }}
        .container {{ max-width: 480px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e);
                   border-radius: 16px; padding: 24px; margin-bottom: 16px; }}
        .badge {{ display: inline-block; padding: 6px 16px; border-radius: 20px;
                  background: {color}; color: #fff; font-size: 13px; font-weight: 600;
                  margin-bottom: 12px; }}
        .score {{ font-size: 64px; font-weight: 800; color: {color}; line-height: 1; }}
        .score-label {{ color: #888; font-size: 12px; margin-top: 4px; }}
        .title {{ font-size: 20px; font-weight: 700; margin: 16px 0 4px; }}
        .subtitle {{ color: #888; font-size: 13px; }}
        .section {{ background: #1a1a1a; border-radius: 12px; padding: 20px; margin-bottom: 12px; }}
        .section-title {{ font-size: 11px; color: #666; text-transform: uppercase;
                         letter-spacing: 1px; margin-bottom: 12px; }}
        .signal-tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .signal-tag {{ padding: 4px 10px; background: #2a2a2a; border-radius: 6px;
                       font-size: 11px; color: #aaa; }}
        .signal-tag.active {{ background: #1a3a2a; color: #4CAF50; border: 1px solid #4CAF50; }}
        .metric-row {{ display: flex; justify-content: space-between; padding: 10px 0;
                       border-bottom: 1px solid #222; }}
        .metric-row:last-child {{ border-bottom: none; }}
        .metric-label {{ color: #888; font-size: 13px; }}
        .metric-value {{ font-weight: 600; font-size: 14px; }}
        .bar {{ height: 6px; background: #333; border-radius: 3px; margin-top: 4px; overflow: hidden; }}
        .bar-fill {{ height: 100%; background: {color}; border-radius: 3px; }}
        .window-badge {{ display: inline-block; padding: 4px 12px; background: #2a2a2a;
                         border-radius: 8px; font-size: 12px; margin-top: 8px; }}
        .footer {{ text-align: center; padding: 20px; color: #444; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span class="badge">{opportunity.recommendation}</span>
            <div class="score">{opportunity.alpha_score:.0f}</div>
            <div class="score-label">Alpha Score</div>
            <div class="title">{opportunity.name}</div>
            <div class="subtitle">品类：{category} · {len(signal_sources)} 个信号源</div>
        </div>

        <div class="section">
            <div class="section-title">信号来源</div>
            <div class="signal-tags">
                {" ".join(f'<span class="signal-tag active">{s}</span>' for s in signal_sources)}
            </div>
        </div>

        <div class="section">
            <div class="section-title">评分明细</div>
            <div class="metric-row">
                <span class="metric-label">Signal Velocity</span>
                <span class="metric-value">{velocity:.0f}</span>
            </div>
            <div class="bar"><div class="bar-fill" style="width:{velocity}%"></div></div>

            <div class="metric-row" style="margin-top:12px">
                <span class="metric-label">Signal Breadth</span>
                <span class="metric-value">{breadth:.0f}</span>
            </div>
            <div class="bar"><div class="bar-fill" style="width:{breadth}%"></div></div>

            <div class="metric-row" style="margin-top:12px">
                <span class="metric-label">Supply Depth</span>
                <span class="metric-value">{depth:.0f}</span>
            </div>
            <div class="bar"><div class="bar-fill" style="width:{depth}%"></div></div>

            <div class="metric-row" style="margin-top:12px">
                <span class="metric-label">Competition Gap</span>
                <span class="metric-value">{gap:.0f}</span>
            </div>
            <div class="bar"><div class="bar-fill" style="width:{gap}%"></div></div>

            <div class="metric-row" style="margin-top:12px">
                <span class="metric-label">Seasonal Fit</span>
                <span class="metric-value">{seasonal:.0f}</span>
            </div>
            <div class="bar"><div class="bar-fill" style="width:{seasonal}%"></div></div>
        </div>

        <div class="section">
            <div class="section-title">季节性窗口</div>
            <span class="window-badge">{window}</span>
            <div style="margin-top:8px; color:#666; font-size:12px;">
                距窗口 {"{:.0f}天" if days_to < 999 else "未知"}
            </div>
        </div>

        <div class="footer">
            <div>HVOS Opportunity Engine V10</div>
            <div style="margin-top:4px">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
        </div>
    </div>
</body>
</html>
"""
        return html

    def _persist_to_kg(self, opportunity) -> dict:
        """
        将 Opportunity 写入 Knowledge Graph
        使用 KGIntegration 封装模块
        """
        try:
            from kg_integration import KGIntegration
            kg = KGIntegration()

            # 写入 Opportunity 节点
            node_id = kg.write_opportunity(opportunity)

            # 写入各信号
            if hasattr(opportunity, 'signals'):
                for signal in opportunity.signals:
                    kg.write_opportunity_signal(opportunity, signal)

            print(f"[AlertDispatcher] KG node created: {opportunity.opp_id}")
            return {"status": "kg_node_created", "node_id": node_id}

        except Exception as e:
            print(f"[AlertDispatcher] KG write failed: {e}")
            return {"status": "kg_write_failed", "error": str(e)}

    def _queue_for_cron(self, opportunity) -> dict:
        """将机会加入 Cron Job 队列，等待下次触发送达"""
        cron_queue_path = os.path.join(self.report_dir, "cron_dispatch_queue.json")
        queue = []
        if os.path.exists(cron_queue_path):
            try:
                with open(cron_queue_path, "r", encoding="utf-8") as f:
                    queue = json.load(f)
            except:
                queue = []

        queue.append({
            "opportunity_id": opportunity.opp_id,
            "opportunity_name": opportunity.name,
            "alpha_score": opportunity.alpha_score,
            "recommendation": opportunity.recommendation,
            "queued_at": datetime.now().isoformat()
        })

        with open(cron_queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)

        return {"status": "queued", "queue_size": len(queue)}


if __name__ == "__main__":
    # 简单测试
    from dataclasses import dataclass

    @dataclass
    class MockOpportunity:
        opp_id: str = "opp_test_001"
        name: str = "Garden Glove"
        category: str = "outdoor"
        alpha_score: float = 78.5
        recommendation: str = "STRONG_BUY"
        velocity: float = 72.0
        breadth: float = 60.0
        depth: float = 55.0
        competition_gap: float = 68.0
        seasonal_fit: float = 100.0
        days_to_window: int = 45
        seasonal_window: str = "父亲节"
        created_at: str = ""
        signals: list = None

        def __post_init__(self):
            if self.created_at == "":
                self.created_at = datetime.now().isoformat()
            if self.signals is None:
                self.signals = []

    dispatcher = AlertDispatcher()
    opp = MockOpportunity()

    result = dispatcher.dispatch(opp)
    print(f"Dispatch result: {result['status']}")
    print(f"Channels: {result.get('channels', [])}")
