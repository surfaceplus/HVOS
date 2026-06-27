"""Generate consolidated TOP5 H5 opportunity report"""
import json
from datetime import datetime

opportunities = [
    {"name": "Show Hn: Homebrew 6.0.0", "alpha_score": 37.1, "recommendation": "BUY", "category": "home", "seasonal_window": "父亲节", "days_to": 9, "signals": "HackerNews"},
    {"name": "Show Hn: Extend Ui – Open-Source Ui Kit", "alpha_score": 37.1, "recommendation": "BUY", "category": "beauty", "seasonal_window": "父亲节", "days_to": 9, "signals": "HackerNews"},
    {"name": "Petition To Withdraw Canada'S Bill C-22", "alpha_score": 37.1, "recommendation": "BUY", "category": "pet", "seasonal_window": "父亲节", "days_to": 9, "signals": "HackerNews"},
    {"name": "Show Hn: Gravity – Interactive Solar-Sys", "alpha_score": 37.1, "recommendation": "BUY", "category": "pet", "seasonal_window": "父亲节", "days_to": 9, "signals": "HackerNews"},
]

rec_colors = {"STRONG_BUY": "#00C853", "BUY": "#4CAF50", "WATCH": "#FFC107", "SKIP": "#F44336"}
now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
ts_str = datetime.now().strftime('%Y%m%d_%H%M')

opp_rows = ""
for i, o in enumerate(opportunities):
    color = rec_colors.get(o["recommendation"], "#9E9E9E")
    opp_rows += f"""
        <div class="opp-card">
            <div class="opp-header">
                <span class="opp-rank">#{i+1}</span>
                <span class="opp-badge" style="background:{color}">{o["recommendation"]}</span>
                <span class="opp-score" style="color:{color}">{o["alpha_score"]:.0f}</span>
            </div>
            <div class="opp-name">{o["name"]}</div>
            <div class="opp-meta">
                <span class="meta-tag">{o["category"]}</span>
                <span class="meta-tag">{o["signals"]}</span>
                <span class="meta-tag seasonal">{o["seasonal_window"]} ({o["days_to"]}d)</span>
            </div>
        </div>"""

html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HVOS TOP 机会报告 — {ts_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0a0a0a; color: #fff; min-height: 100vh; padding: 16px; }}
        .container {{ max-width: 480px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e);
                   border-radius: 16px; padding: 24px; margin-bottom: 16px; text-align: center; }}
        .header-title {{ font-size: 11px; color: #666; text-transform: uppercase;
                        letter-spacing: 2px; margin-bottom: 8px; }}
        .header-main {{ font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 4px; }}
        .header-sub {{ color: #666; font-size: 12px; }}
        .summary-row {{ display: flex; gap: 12px; margin-top: 16px; }}
        .summary-box {{ flex: 1; background: rgba(255,255,255,0.05); border-radius: 10px;
                       padding: 12px; text-align: center; }}
        .summary-num {{ font-size: 28px; font-weight: 800; color: #4CAF50; }}
        .summary-label {{ font-size: 10px; color: #666; margin-top: 2px; text-transform: uppercase; }}
        .opp-card {{ background: #1a1a1a; border-radius: 12px; padding: 16px; margin-bottom: 10px;
                    border-left: 3px solid #4CAF50; }}
        .opp-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
        .opp-rank {{ font-size: 12px; color: #666; font-weight: 600; }}
        .opp-badge {{ padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600;
                      color: #fff; }}
        .opp-score {{ font-size: 20px; font-weight: 800; margin-left: auto; }}
        .opp-name {{ font-size: 14px; font-weight: 600; margin-bottom: 8px; line-height: 1.3; }}
        .opp-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .meta-tag {{ padding: 3px 8px; background: #2a2a2a; border-radius: 6px;
                     font-size: 10px; color: #888; }}
        .meta-tag.seasonal {{ background: #2a1a1a; color: #FF8C00; border: 1px solid #FF8C00; }}
        .section {{ margin-top: 16px; }}
        .section-title {{ font-size: 11px; color: #444; text-transform: uppercase;
                         letter-spacing: 1px; margin-bottom: 10px; padding-left: 4px; }}
        .note-box {{ background: #1a1a1a; border-radius: 10px; padding: 14px; margin-top: 12px; }}
        .note-text {{ font-size: 11px; color: #666; line-height: 1.6; }}
        .footer {{ text-align: center; padding: 24px; color: #333; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-title">HVOS Opportunity Engine V10</div>
            <div class="header-main">TOP 机会报告</div>
            <div class="header-sub">{now_str} · 父亲节窗口 (9天后)</div>
            <div class="summary-row">
                <div class="summary-box">
                    <div class="summary-num">4</div>
                    <div class="summary-label">BUY 信号</div>
                </div>
                <div class="summary-box">
                    <div class="summary-num">37.1</div>
                    <div class="summary-label">平均 Alpha</div>
                </div>
                <div class="summary-box">
                    <div class="summary-num">HN</div>
                    <div class="summary-label">主信号源</div>
                </div>
            </div>
        </div>
        <div class="section">
            <div class="section-title">BUY 信号 · Alpha Score 排序</div>
            {opp_rows}
        </div>
        <div class="note-box">
            <div class="note-text">
                ⚠️ 注意：以上机会均来自 HackerNews（科技新闻平台），
                关键词匹配产生的 DTC 信号误报率较高（已验证 ~100% 误报）。
                建议结合 SerpAPI Google Trends 数据源进行二次验证。
                <br/><br/>
                📌 数据源状态：Google Trends 直连 ❌ | SerpAPI ✅ | Reddit ❌ | Amazon ❌
            </div>
        </div>
        <div class="footer">
            <div>HVOS V10 Opportunity Engine</div>
            <div style="margin-top:4px">{now_str}</div>
            <div style="margin-top:4px; color:#222">Cron: 511a2b9291bd · 每天 06:00</div>
        </div>
    </div>
</body>
</html>"""

report_dir = "C:/Users/Administrator/AppData/Local/hermes/hvos/opportunity/reports"
report_path = f"{report_dir}/opp_TOP5_{ts_str}.html"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"REPORT_PATH:{report_path}")

# Update wechat_dispatch_queue
queue_path = f"{report_dir}/wechat_dispatch_queue.json"
try:
    with open(queue_path, "r", encoding="utf-8") as f:
        wechat_queue = json.load(f)
except:
    wechat_queue = []

wechat_queue.append({
    "report_path": report_path,
    "opportunity_name": f"HVOS TOP5 报告 {ts_str}",
    "alpha_score": 37.1,
    "recommendation": "BUY",
    "queued_at": datetime.now().isoformat()
})

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(wechat_queue, f, ensure_ascii=False, indent=2)

print(f"wechat_queue_size:{len(wechat_queue)}")
print(f"queued_at:{wechat_queue[-1]['queued_at']}")
