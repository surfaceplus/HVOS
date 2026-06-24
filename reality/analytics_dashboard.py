"""
HVOS 运营诊断 × 合规检查
来源: solo-ecom-pilot (CC-BY), 整合自一人电商运营助手
合并: AnalyticsDashboard + AdComplianceChecker
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional


# ── 广告法违禁词库 ──────────────────────────────────────────────────────────

PROHIBITED_WORDS = {
    "绝对化用语": [
        "最","最佳","最好","最优","最强","最大","最高","最低",
        "最便宜","最先进","最流行","最受欢迎","最安全",
        "第一","唯一","首个","首选","首款","第一品牌","销量第一",
        "排名第一","顶级","极品","绝版","终极",
        "全网首发","全国首发","世界级","国家级","驰名",
    ],
    "权威性误导": [
        "国家免检","质量免检","免检产品","特供","专供","指定","推荐品牌",
    ],
    "虚假承诺": [
        "100%有效","100%有效","永久","包治百病","绝对有效","无效退款",
        "零风险","无副作用","药到病除","立竿见影","一用就灵","万能",
    ],
    "夸大功效": [
        "速效","神效","奇效","特效","强效","高效",
        "彻底清除","根除","完全","绝对安全",
    ],
    "伪科学": [
        "科学证明","医学认证","临床证明","权威认证","经XX机构认证",
    ],
    "诱导消费": [
        "马上抢","仅剩X件","不买后悔","错过再等一年",
        "最后一天","限时秒杀","抢疯了",
    ],
    "价格违规": [
        "原价","特价","跳楼价","白菜价","亏本甩卖",
    ],
}

REPLACEMENT_SUGGESTIONS = {
    "最": "优选/人气之选",
    "第一": "领先/前列",
    "唯一": "独特/专属",
    "100%有效": "显著改善",
    "永久": "持久/长效",
    "国家级": "品牌自研/匠心打造",
    "原价": "日常价(需有真实交易记录)",
    "无效退款": "不满意可退换",
    "全网首发": "品牌首发",
}


class AdComplianceChecker:
    """
    广告法合规检查器 — 内容输出前必检

    使用:
        checker = AdComplianceChecker()
        result = checker.check_text("全网销量第一！100%有效！")
    """

    def __init__(self, wordlist_path: Optional[str] = None):
        self.prohibited_words = dict(PROHIBITED_WORDS)
        if wordlist_path and os.path.isfile(wordlist_path):
            with open(wordlist_path, "r", encoding="utf-8") as f:
                custom = json.load(f)
                self.prohibited_words.update(custom)

    def check_text(self, text: str) -> dict:
        if not text:
            return {"is_compliant": True, "violations": [], "compliance_score": 100.0, "fixed_text": ""}

        fixed = text
        violations = []
        found = set()

        for category, words in self.prohibited_words.items():
            for word in words:
                if word in text and word not in found:
                    violations.append({
                        "word": word,
                        "category": category,
                        "suggestion": REPLACEMENT_SUGGESTIONS.get(word, "建议删除或替换"),
                    })
                    found.add(word)
                    repl = REPLACEMENT_SUGGESTIONS.get(word, "[" + word + "]")
                    if word in fixed:
                        fixed = fixed.replace(word, repl, 1)

        score = max(0.0, 100.0 - len(violations) * 10)
        return {
            "is_compliant": len(violations) == 0,
            "violations": violations,
            "compliance_score": score,
            "fixed_text": fixed,
        }

    def check_compliance_report(self, text: str) -> str:
        result = self.check_text(text)
        sb = []
        sb.append("=" * 50)
        sb.append("广告法合规检查报告")
        sb.append("=" * 50)
        sb.append("合规分数: " + str(result["compliance_score"]) + "/100")
        sb.append("违规词数: " + str(len(result["violations"])))
        if result["violations"]:
            sb.append("")
            sb.append("违规项:")
            for v in result["violations"]:
                sb.append("  [x] [" + v["category"] + "] " + v["word"])
                sb.append("      建议: " + v["suggestion"])
        else:
            sb.append("无违规词")
        if result["fixed_text"] and result["fixed_text"] != text:
            sb.append("")
            sb.append("修改后版本:")
            sb.append(result["fixed_text"])
        return "\n".join(sb)


class AnalyticsDashboard:
    """
    运营数据诊断 — 8 大核心指标健康检查

    使用:
        dash = AnalyticsDashboard()
        report = dash.diagnose(cvr=0.012, refund_rate=0.08, roi=1.2)
        print(dash.print_diagnosis(**kwargs))
    """

    METRICS = [
        {"name": "转化率",     "key": "cvr",           "unit": "%",  "good": lambda v: v >= 0.03, "warn": lambda v: v >= 0.02, "good_val": ">=3%",  "direction": "越高越好"},
        {"name": "客单价",     "key": "aov",            "unit": "元", "good": lambda v: v >= 80,   "warn": lambda v: v >= 50,   "good_val": ">=80元", "direction": "绝对值"},
        {"name": "退款率",     "key": "refund_rate",    "unit": "%",  "good": lambda v: v <= 0.05, "warn": lambda v: v <= 0.08, "good_val": "<=5%",  "direction": "越低越好"},
        {"name": "复购率",     "key": "repurchase_rate","unit": "%",  "good": lambda v: v >= 0.15, "warn": lambda v: v >= 0.10, "good_val": ">=15%", "direction": "越高越好"},
        {"name": "ROI",        "key": "roi",            "unit": "x",  "good": lambda v: v >= 3.0,  "warn": lambda v: v >= 2.0,  "good_val": ">=3x",  "direction": "越高越好"},
        {"name": "好评率",     "key": "rating_rate",    "unit": "%",  "good": lambda v: v >= 0.95, "warn": lambda v: v >= 0.90, "good_val": ">=95%", "direction": "越高越好"},
        {"name": "客服响应时间","key": "response_time", "unit": "秒", "good": lambda v: v <= 30,    "warn": lambda v: v <= 60,   "good_val": "<=30秒", "direction": "越低越好"},
        {"name": "DSR评分",    "key": "dsr",            "unit": "分", "good": lambda v: v >= 4.7,  "warn": lambda v: v >= 4.5,  "good_val": ">=4.7", "direction": "越高越好"},
    ]

    SUGGESTIONS = {
        "转化率":     {"warning": "优化标题和主图，检查价格竞争力",         "danger": "检查商品是否精准触达目标人群"},
        "客单价":     {"warning": "搭配销售或满减活动引导加购",              "danger": "检查产品定位和目标客群"},
        "退款率":     {"warning": "检查产品描述与实物差异",                  "danger": "优先排查质量/描述问题"},
        "复购率":     {"warning": "建立会员体系或老客优惠",                  "danger": "加强客户运营和复购引导"},
        "ROI":        {"warning": "优化投放人群和素材",                      "danger": "暂停低效渠道，重新审视选品"},
        "好评率":     {"warning": "主动回访客户，改进服务",                  "danger": "排查差评原因，优先解决产品/服务问题"},
        "客服响应时间":{"warning": "设置自动回复和快捷话术",                  "danger": "增加客服人手或使用机器人"},
        "DSR评分":    {"warning": "改善物流或描述相符度",                    "danger": "逐一排查描述/服务/物流三维度"},
    }

    def diagnose(self, **kwargs) -> dict:
        results = []
        warnings = []
        for m in self.METRICS:
            val = kwargs.get(m["key"])
            if val is None:
                results.append({"name": m["name"], "value": None, "status": "unknown", "emoji": "⚪", "good_val": m["good_val"], "suggestion": "缺少数据"})
                continue
            # 百分数归一化
            if m["unit"] == "%" and val > 1:
                val = val / 100.0
            if m["good"](val):
                status, emoji = "good", "🟢"
            elif m["warn"](val):
                status, emoji = "warning", "🟡"
            else:
                status, emoji = "danger", "🔴"
                warnings.append(m["name"])
            if m["unit"] == "%":
                display = str(round(val * 100, 1)) + "%"
            elif m["unit"] == "x":
                display = str(round(val, 2)) + "x"
            elif m["unit"] == "分":
                display = str(round(val, 1))
            elif m["unit"] == "秒":
                display = str(round(val, 0)) + "秒"
            else:
                display = str(val) + m["unit"]
            results.append({
                "name": m["name"],
                "value": display,
                "status": status,
                "emoji": emoji,
                "good_val": m["good_val"],
                "direction": m["direction"],
                "suggestion": self.SUGGESTIONS.get(m["name"], {}).get(status, ""),
            })
        todos = [("优先处理 " + w + " 异常") for w in warnings] or ["所有指标正常"]
        summary = {
            "total": len(results),
            "good": sum(1 for r in results if r["status"] == "good"),
            "warning": sum(1 for r in results if r["status"] == "warning"),
            "danger": sum(1 for r in results if r["status"] == "danger"),
        }
        return {"summary": summary, "metrics": results, "todos": todos, "diagnosis_time": datetime.now(timezone.utc).isoformat()}

    def print_diagnosis(self, **kwargs) -> str:
        result = self.diagnose(**kwargs)
        s = []
        s.append("=" * 50)
        s.append("运营数据诊断报告")
        s.append("=" * 50)
        s.append("健康度: " + str(result["summary"]["good"]) + "/" + str(result["summary"]["total"]) + "  🟢 " + str(result["summary"]["warning"]) + " 🟡 " + str(result["summary"]["danger"]) + " 🔴")
        s.append("")
        for m in result["metrics"]:
            s.append(m["emoji"] + " " + m["name"] + ": " + (m["value"] or "N/A") + " (健康值: " + m["good_val"] + ")")
            s.append("   建议: " + m["suggestion"])
        s.append("")
        s.append("今日待办:")
        for t in result["todos"]:
            s.append("  " + t)
        return "\n".join(s)
