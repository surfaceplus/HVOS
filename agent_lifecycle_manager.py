#!/usr/bin/env python3
"""
HVOS V10.3 — Agent Lifecycle Manager
======================================
真正的Agent生命周期管理：
  - 注册模板（来自SkillHub）
  - Agent生成（按需）

当前注册模板来源：
  - 内置：HVOS Agent Factory (31模板)
  - SkillHub：
    * cross-border-ecommerce-product-analysis  → 跨境电商选品Agent
    * ecommerce-product-selector                → 多平台选品Agent
    * cross-border-copywriter                   → 跨境文案Agent
    * data-analysis-plus                         → 数据分析Agent
    * one-person-company-plus                    → 运营管理Agent
    * anysearch                                  → 搜索信号Agent
    * topnews                                    → 舆情监控Agent
    * global-biblio-base                         → 文献/专利查询Agent
    * processon-diagramgen                       → 图表生成Agent
    * ppt-generator-skill                        → PPT报告Agent
"""

from __future__ import annotations
import uuid
import datetime as dt
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.expanduser("~/AppData/Local/hermes/skills")
OUTPUT_DIR = f"{BASE}/pipeline_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════
# Agent 模板注册表
# ═══════════════════════════════════════════════════════════════════

AGENT_TEMPLATES = {
    # ── 内置 HVOS 模板 ──
    "market_agent": {
        "name": "Market Agent",
        "source": "hvos_builtin",
        "category": "通用",
        "description": "市场规模/增速/季节性分析",
        "trigger": "任何赛道触发",
        "skill_ref": "commerce-intelligence",
    },
    "trend_agent": {
        "name": "Trend Agent",
        "source": "hvos_builtin",
        "category": "通用",
        "description": "趋势信号/爆款识别",
        "trigger": "任何赛道触发",
        "skill_ref": "commerce-intelligence",
    },
    "competitive_agent": {
        "name": "Competitive Agent",
        "source": "hvos_builtin",
        "category": "通用",
        "description": "竞争格局/价格带/BSR",
        "trigger": "任何赛道触发",
        "skill_ref": "commerce-intelligence",
    },

    # ── SkillHub 新增模板 ──
    "cross_border_selection_agent": {
        "name": "跨境电商选品 Agent",
        "source": "skillhub",
        "category": "选品",
        "slug": "cross-border-ecommerce-product-analysis",
        "skill_path": f"{SKILLS_DIR}/cross-border-ecommerce-product-analysis",
        "description": "自动爬取跨境电商榜单、利润计算、侵权排查、竞品分析、选品报告",
        "capabilities": ["榜单分析", "利润计算", "侵权排查", "竞品分析", "选品报告"],
        "trigger": "跨境选品/亚马逊/Temu/TikTok选品",
    },
    "multi_platform_selection_agent": {
        "name": "多平台选品 Agent",
        "source": "skillhub",
        "category": "选品",
        "slug": "ecommerce-product-selector",
        "skill_path": f"{SKILLS_DIR}/ecommerce-product-selector",
        "description": "淘宝/京东/拼多多/抖音/Amazon多平台爆款筛选",
        "capabilities": ["多平台比价", "热销榜", "趋势分析"],
        "trigger": "国内电商选品/淘宝/京东/拼多多选品",
    },
    "cross_border_copy_agent": {
        "name": "跨境文案 Agent",
        "source": "skillhub",
        "category": "内容",
        "slug": "cross-border-copywriter",
        "skill_path": f"{SKILLS_DIR}/cross-border-copywriter",
        "description": "跨境电商爆款商品文案生成",
        "capabilities": ["Listing优化", "A+内容", "社交文案"],
        "trigger": "跨境文案/商品描述/Landing Page",
    },
    "data_analysis_agent": {
        "name": "数据分析 Agent",
        "source": "skillhub",
        "category": "分析",
        "slug": "data-analysis-plus",
        "skill_path": f"{SKILLS_DIR}/data-analysis-plus",
        "description": "全球多平台数据采集/整合/ROI分析/趋势可视化",
        "capabilities": ["数据采集", "ROI分析", "趋势预测", "可视化报表"],
        "trigger": "数据报告/舆情监控/ROI分析/市场趋势",
    },
    "one_person_company_agent": {
        "name": "运营管理 Agent",
        "source": "skillhub",
        "category": "运营",
        "slug": "one-person-company-plus",
        "skill_path": f"{SKILLS_DIR}/one-person-company-plus",
        "description": "一人公司全能运营：内容/商业/产品/客服/提效5大模块",
        "capabilities": ["内容创作", "品牌营销", "PRD编写", "客服话术", "周报月报"],
        "trigger": "运营管理/内容创作/品牌营销/周报月报",
    },
    "search_signal_agent": {
        "name": "搜索信号 Agent",
        "source": "skillhub",
        "category": "情报",
        "slug": "anysearch",
        "skill_path": f"{SKILLS_DIR}/anysearch",
        "description": "实时搜索引擎，支持Web/垂直领域/批量搜索",
        "capabilities": ["实时搜索", "垂直搜索", "批量搜索"],
        "trigger": "实时搜索/市场调研/竞品情报",
    },
    "sentiment_monitor_agent": {
        "name": "舆情监控 Agent",
        "source": "skillhub",
        "category": "情报",
        "slug": "topnews",
        "skill_path": f"{SKILLS_DIR}/topnews",
        "description": "股票舆情/实时大事/财经快讯监控",
        "capabilities": ["实时舆情", "新闻监控", "风险预警"],
        "trigger": "舆情监控/实时新闻/竞品异动",
    },
    "patent_search_agent": {
        "name": "专利查询 Agent",
        "source": "skillhub",
        "category": "合规",
        "slug": "global-biblio-base",
        "skill_path": f"{SKILLS_DIR}/global-biblio-base",
        "description": "全球12亿文献知识库，8000万中文期刊可下载",
        "capabilities": ["文献检索", "专利查询", "合规检查"],
        "trigger": "专利查询/合规检查/文献检索",
    },
    "diagram_agent": {
        "name": "图表生成 Agent",
        "source": "skillhub",
        "category": "可视化",
        "slug": "processon-diagramgen",
        "skill_path": f"{SKILLS_DIR}/processon-diagramgen",
        "description": "流程图/泳道图/时序图/架构图/ER图一键生成",
        "capabilities": ["流程图", "架构图", "供应链图", "可视化"],
        "trigger": "流程图/架构图/供应链可视化/Board报告",
    },
    "ppt_report_agent": {
        "name": "PPT报告 Agent",
        "source": "skillhub",
        "category": "报告",
        "slug": "ppt-generator-skill",
        "skill_path": f"{SKILLS_DIR}/ppt-generator-skill",
        "description": "智能PPT生成，支持多行业/多语言",
        "capabilities": ["PPT生成", "Board报告", "投资者演示"],
        "trigger": "PPT生成/Board Meeting报告/投资者演示",
    },
}

# ═══════════════════════════════════════════════════════════════════
# 赛道 × Agent 映射
# ═══════════════════════════════════════════════════════════════════

# 每个赛道触发时自动生成的Agent组合
TRACK_AGENT_MAP = {
    "seasonal_gifts": {
        "name": "季节性礼品赛道",
        "agents": [
            "cross_border_selection_agent",  # 选品分析
            "cross_border_copy_agent",       # 文案生成
            "data_analysis_agent",           # 数据分析
            "ppt_report_agent",              # 报告输出
        ],
    },
    "pet_supplies": {
        "name": "宠物用品赛道",
        "agents": [
            "cross_border_selection_agent",
            "data_analysis_agent",
            "diagram_agent",                 # 供应链图
        ],
    },
    "kitchen_dining": {
        "name": "厨房餐饮赛道",
        "agents": [
            "multi_platform_selection_agent",
            "data_analysis_agent",
            "patent_search_agent",           # 专利合规
        ],
    },
    "cross_border_general": {
        "name": "跨境通用",
        "agents": [
            "cross_border_selection_agent",
            "cross_border_copy_agent",
            "search_signal_agent",           # 实时信号
            "sentiment_monitor_agent",        # 舆情监控
            "data_analysis_agent",
            "diagram_agent",
        ],
    },
    "board_meeting": {
        "name": "董事会评审",
        "agents": [
            "data_analysis_agent",
            "one_person_company_agent",      # 运营报告
            "diagram_agent",                 # 可视化
            "ppt_report_agent",              # 演示报告
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════
# Agent 生命周期
# ═══════════════════════════════════════════════════════════════════

LIFECYCLE_DB = f"{OUTPUT_DIR}/agent_lifecycle.json"

def _load_lifecycle() -> dict:
    if os.path.exists(LIFECYCLE_DB):
        with open(LIFECYCLE_DB) as f:
            return json.load(f)
    return {"agents": {}, "history": []}

def _save_lifecycle(data: dict):
    with open(LIFECYCLE_DB, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def spawn_agent(track: str, context: str = "") -> dict:
    """按赛道生成Agent实例"""
    if track not in TRACK_AGENT_MAP:
        return {"error": f"Unknown track: {track}"}

    track_cfg = TRACK_AGENT_MAP[track]
    agent_ids = []
    for agent_key in track_cfg["agents"]:
        if agent_key not in AGENT_TEMPLATES:
            continue
        tmpl = AGENT_TEMPLATES[agent_key]
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        record = {
            "id": agent_id,
            "template": agent_key,
            "name": tmpl["name"],
            "source": tmpl["source"],
            "track": track,
            "status": "active",
            "spawned_at": dt.datetime.now().isoformat(),
            "context": context[:100],
            "skill_slug": tmpl.get("slug", ""),
            "skill_path": tmpl.get("skill_path", ""),
        }
        agent_ids.append(agent_id)

        # 持久化
        lc = _load_lifecycle()
        lc["agents"][agent_id] = record
        lc["history"].append({
            "event": "spawn",
            "agent_id": agent_id,
            "template": agent_key,
            "track": track,
            "timestamp": dt.datetime.now().isoformat(),
        })
        _save_lifecycle(lc)

    return {
        "track": track,
        "track_name": track_cfg["name"],
        "agents_spawned": len(agent_ids),
        "agent_ids": agent_ids,
        "agents": [{
            "id": aid,
            "name": AGENT_TEMPLATES[a_key]["name"],
            "skill_slug": AGENT_TEMPLATES[a_key].get("slug", ""),
        } for a_key, aid in zip(track_cfg["agents"], agent_ids)
          if a_key in AGENT_TEMPLATES],
    }

def hibernate_agent(agent_id: str):
    """休眠Agent"""
    lc = _load_lifecycle()
    if agent_id in lc["agents"]:
        lc["agents"][agent_id]["status"] = "hibernated"
        lc["agents"][agent_id]["hibernated_at"] = dt.datetime.now().isoformat()
        lc["history"].append({
            "event": "hibernate", "agent_id": agent_id,
            "timestamp": dt.datetime.now().isoformat(),
        })
        _save_lifecycle(lc)
        return {"status": "hibernated", "agent_id": agent_id}
    return {"error": "Agent not found"}

def get_active_agents() -> list[dict]:
    """获取活跃Agent列表"""
    lc = _load_lifecycle()
    return [a for a in lc["agents"].values() if a["status"] == "active"]

def get_status() -> dict:
    """获取Agent Factory状态"""
    lc = _load_lifecycle()
    agents = lc["agents"]
    active = sum(1 for a in agents.values() if a["status"] == "active")
    hibernated = sum(1 for a in agents.values() if a["status"] == "hibernated")
    return {
        "total_templates": len(AGENT_TEMPLATES),
        "builtin_templates": sum(1 for t in AGENT_TEMPLATES.values() if t["source"] == "hvos_builtin"),
        "skillhub_templates": sum(1 for t in AGENT_TEMPLATES.values() if t["source"] == "skillhub"),
        "total_tracks": len(TRACK_AGENT_MAP),
        "active_agents": active,
        "hibernated_agents": hibernated,
        "total_spawned": len(lc.get("history", [])),
        "tracks": list(TRACK_AGENT_MAP.keys()),
    }


# ═══════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════

def print_status():
    s = get_status()
    print("=" * 60)
    print("  HVOS Agent Factory — 状态报告")
    print("=" * 60)
    print(f"  📋 模板总数:      {s['total_templates']}")
    print(f"     ├─ HVOS内置:   {s['builtin_templates']}")
    print(f"     └─ SkillHub:   {s['skillhub_templates']}")
    print(f"  🎯 赛道定义:       {s['total_tracks']}")
    print(f"  🤖 活跃Agent:      {s['active_agents']}")
    print(f"  💤 休眠Agent:      {s['hibernated_agents']}")
    print(f"  📊 历史Agent数:    {s['total_spawned']}")
    print()
    print("  📌 赛道列表:")
    for tid, tinfo in TRACK_AGENT_MAP.items():
        agents = [AGENT_TEMPLATES[ak]["name"] for ak in tinfo["agents"] if ak in AGENT_TEMPLATES]
        print(f"    [{tid}] {tinfo['name']}: {', '.join(agents)}")
    print()
    print("  📌 Agent 模板（SkillHub源）:")
    for k, t in AGENT_TEMPLATES.items():
        if t["source"] == "skillhub":
            print(f"    {t['name']:20s} slug={t.get('slug','')}")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "status":
            print_status()
        elif cmd == "spawn" and len(sys.argv) > 2:
            result = spawn_agent(sys.argv[2])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif cmd == "hibernate" and len(sys.argv) > 2:
            result = hibernate_agent(sys.argv[2])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif cmd == "active":
            agents = get_active_agents()
            print(json.dumps(agents, ensure_ascii=False, indent=2))
        else:
            print(f"Usage: {sys.argv[0]} [status|spawn <track>|hibernate <id>|active]")
    else:
        print_status()
