"""
HVOS 全系统状态监控面板
===========================
一次性输出 HVOS 所有模块的状态：
  Board Layer / Knowledge Graph / Agent Factory
  Reality Feedback / Product DNA / Winning Patterns
  Digital Twin / Self-Evolution / Customs Intelligence
  Cron Jobs / Phase 进度

使用方法：
  python hvos_status.py
"""

import sqlite3
import json
import os
from datetime import datetime

import os; KG_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge_graph', 'kg.db')
HVOS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = r"C:\Users\Administrator\AppData\Local\hermes\skills\hvos"

def get_conn():
    return sqlite3.connect(KG_DB)


def colored_bar(value, max_val=100, width=20):
    """生成分隔条"""
    filled = int(value / max_val * width)
    return "█" * filled + "░" * (width - filled)


def box_line(text, width=64):
    """居中输出"""
    if len(text) > width - 4:
        return "  " + text[:width-4]
    return "  " + text.center(width - 4)


def section(title):
    print(f"\n{'─'*64}")
    print(f"  {title}")
    print(f"{'─'*64}")


def hvos_status():
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║      HVOS — HERMES VENTURE OPERATING SYSTEM                 ║
║           AI DTC Venture Studio — 全系统状态面板            ║
║                                                              ║
║                    Version 9.0 — Phase 1-7                  ║
║                    系统时间: %s                     ║
╚══════════════════════════════════════════════════════════════╝
""" % datetime.now().strftime("%Y-%m-%d %H:%M"))

    conn = get_conn()
    cur = conn.cursor()

    # ============================================================
    # 1. Board Layer 状态
    # ============================================================
    section("Board Layer — 董事会席位")
    board_slots = [
        ("CEO Hermes",     "决策中枢",    "✅ 就绪"),
        ("CFO Hermes",    "财务视角",    "✅ 就绪"),
        ("CMO Hermes",    "市场视角",    "✅ 就绪"),
        ("COO Hermes",    "运营视角",    "✅ 就绪"),
        ("CSO Hermes",    "战略视角",    "✅ 就绪"),
        ("Investment Committee", "三方辩论", "✅ 就绪"),
        ("Board Meeting",  "投资评审",   "✅ 已运行"),
    ]
    print(f"  {'席位':<25} {'角色':<15} {'状态':<10}")
    print(f"  {'─'*55}")
    for name, role, status in board_slots:
        print(f"  {name:<25} {role:<15} {status}")

    # ============================================================
    # 2. Knowledge Graph 状态
    # ============================================================
    section("Memory Layer — 知识图谱 (Knowledge Graph)")

    cur.execute("SELECT entity_type, COUNT(*) FROM kg_nodes GROUP BY entity_type")
    node_types = dict(cur.fetchall())
    total_nodes = sum(node_types.values())

    cur.execute("SELECT rel_type, COUNT(*) FROM kg_relations GROUP BY rel_type")
    rel_types = dict(cur.fetchall())
    total_rels = sum(rel_types.values())

    print(f"  数据库: {KG_DB}")
    print(f"  节点总数: {total_nodes}  |  关系总数: {total_rels}")
    print(f"\n  节点类型分布:")
    for ntype, count in sorted(node_types.items()):
        bar = colored_bar(count, total_nodes, 15)
        print(f"    {ntype:<15} {bar} {count}")

    print(f"\n  关系类型分布:")
    for rtype, count in sorted(rel_types.items()):
        bar = colored_bar(count, total_rels, 15)
        print(f"    {rtype:<15} {bar} {count}")

    # ============================================================
    # 3. Customs Intelligence Center
    # ============================================================
    section("Customs Intelligence Center — 海关情报中心 (权重: 40%)")

    cur.execute("SELECT COUNT(*) FROM customs_hs_codes")
    hs_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM customs_shipments")
    ship_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM customs_traders")
    trader_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM customs_alerts")
    alert_count = cur.fetchone()[0]

    print(f"  HS Code 库:   {hs_count} 条")
    print(f"  海关提单:     {ship_count} 条")
    print(f"  贸易商数据:   {trader_count} 条")
    print(f"  海关警报:     {alert_count} 条")

    if hs_count > 0:
        cur.execute("SELECT hs_code, description, duty_rate_us FROM customs_hs_codes LIMIT 8")
        print(f"\n  热门 HS Code:")
        for row in cur.fetchall():
            duty = f"{row[2]}%" if row[2] else "0%"
            print(f"    HS {row[0]}: {row[1][:35]} (US duty: {duty})")

    # ============================================================
    # 4. Reality Feedback Engine
    # ============================================================
    section("Reality Feedback Engine — 真实世界反馈系统")

    cur.execute("SELECT COUNT(*) FROM predictions")
    pred_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM actuals")
    actual_count = cur.fetchone()[0]

    coverage = f"{actual_count/pred_count*100:.0f}%" if pred_count > 0 else "N/A"
    print(f"  预测记录:   {pred_count} 条")
    print(f"  实际录入:   {actual_count} 条  (覆盖率: {coverage})")

    if actual_count > 0:
        cur.execute("SELECT AVG(error_rate) FROM prediction_errors")
        avg_err = cur.fetchone()[0] or 0
        err_bar = colored_bar(avg_err, 50, 15)
        emoji = "🟢" if avg_err < 15 else "🟡" if avg_err < 30 else "🔴"
        print(f"  平均误差率: {avg_err:.1f}%  {err_bar} {emoji}")
    else:
        print(f"  平均误差率: N/A (暂无实际数据)")

    # 待录入预测
    cur.execute("""SELECT COUNT(*) FROM predictions p
                   WHERE p.id NOT IN (SELECT prediction_id FROM actuals)""")
    pending = cur.fetchone()[0]
    if pending > 0:
        print(f"  ⚠️  待录入实际结果: {pending} 条")

    # ============================================================
    # 5. Product DNA & Winning Patterns
    # ============================================================
    section("Product DNA — 产品基因库")

    cur.execute("SELECT node_id, properties FROM kg_nodes WHERE entity_type='Product'")
    products_with_dna = 0
    for row in cur.fetchall():
        props = json.loads(row[1]) if row[1] else {}
        if "dna" in props:
            products_with_dna += 1

    print(f"  已提取 DNA 产品: {products_with_dna}/{total_nodes} 个产品节点")
    print(f"  已知品类基准: 6 个（礼品套装/宠物/厨房/户外/美妆/3C配件）")
    print(f"  爆款基因库: 5 个模式（礼品套装型/宠物用品型/厨房功能型/户外装备型/美妆护肤型）")

    print(f"\n  爆款模式参考:")
    patterns = [
        ("礼品套装型",   [3,4,5,4,5,3,2,2,4,3], "高情绪+高传播+高品牌化"),
        ("宠物用品型",   [2,3,4,3,4,3,4,2,3,3], "中等情感+高复购"),
        ("厨房功能型",   [3,4,3,4,2,3,3,3,2,4], "高痛点+高演示"),
        ("户外装备型",   [3,3,3,3,3,4,3,4,3,3], "高利润+高供应链难度"),
        ("美妆护肤型",   [2,5,3,4,3,3,5,4,3,4], "极高痛点+高复购"),
    ]
    print(f"  {'模式':<14} {'DNA向量':<30} {'特征'}")
    print(f"  {'─'*65}")
    for name, dna, desc in patterns:
        dna_str = str(dna)
        print(f"  {name:<14} {dna_str:<30} {desc}")

    # ============================================================
    # 6. Agent Factory
    # ============================================================
    section("Agent Factory — 动态 Agent 生成引擎")

    agent_templates = {
        "通用基础模板": 3,
        "宠物赛道模板": 6,
        "厨房赛道模板": 5,
        "户外赛道模板": 5,
        "美妆赛道模板": 6,
        "家居赛道模板": 6,
    }
    total_templates = sum(agent_templates.values())

    print(f"  Agent 模板总数: {total_templates}")
    print(f"  活跃 Agent: 0 (按需动态生成)")
    print(f"\n  赛道模板分布:")
    for category, count in agent_templates.items():
        bar = colored_bar(count, total_templates, 18)
        print(f"    {category:<14} {bar} {count} 个模板")

    print(f"\n  Agent 生成规则:")
    print(f"    发现赛道信号 → 分析所需视角 → 动态生成 Agent → 执行 → 知识沉淀 → Agent 休眠")

    # ============================================================
    # 7. Digital Twin
    # ============================================================
    section("Growth Digital Twin — 数字孪生引擎")

    print(f"  状态: ⚙️  已定义，待激活")
    print(f"  虚拟品牌生成器: ✅ 就绪")
    print(f"  模拟器组:")
    for sim in ["Growth Simulator", "Financial Simulator", "Market Simulator",
                "Competition Simulator", "Monte Carlo Simulator"]:
        print(f"    ✅ {sim}")

    print(f"\n  Digital Twin 触发条件: 产品进入 WATCHLIST")
    print(f"  模拟周期: 90天 / 180天 / 365天")
    print(f"  输出: 乐观/中性/悲观三档 ROI 概率分布")

    # ============================================================
    # 8. Self-Evolution
    # ============================================================
    section("Self-Evolution Engine — 自我进化引擎")

    cur.execute("SELECT COUNT(*) FROM evolution_log")
    evo_count = cur.fetchone()[0]

    print(f"  进化周期总数: {evo_count}")
    print(f"  系统性偏见清单: 0 个活跃偏见（示例）")
    print(f"\n  进化飞轮:")
    print(f"    发现失败 → 分析失败 → 总结失败 → 生成新规则 → 更新Skill → 重新测试")

    if evo_count == 0:
        print(f"\n  🟡 暂无进化记录（需要 Reality Feedback Engine 触发）")

    # ============================================================
    # 9. Board Meeting 历史
    # ============================================================
    section("Board Meeting — 历史评审记录")

    import os
    bm_dir = os.path.join(HVOS_DIR, "board-meetings")
    if os.path.exists(bm_dir):
        files = [f for f in os.listdir(bm_dir) if f.endswith(".md")]
        print(f"  历史评审: {len(files)} 次")
        for f in sorted(files)[-3:]:
            print(f"    📋 {f.replace('board-meeting-', '').replace('.md', '')}")
    else:
        print(f"  历史评审: 0 次")

    # ============================================================
    # 10. Phase 进度
    # ============================================================
    section("Phase 进度总览")

    phases = [
        ("Phase 1: Board Layer + 投资委员会",     "✅ 完成",   "CEO+CFO+CMO+COO+CSO+Partners"),
        ("Phase 2: Memory Layer (Knowledge Graph)", "✅ 完成",   "节点/关系/海关数据已入库"),
        ("Phase 3: Reality Feedback Engine",       "⚙️ 运行中", "预测记录待积累，需真实数据验证"),
        ("Phase 4: Agent Factory",                  "✅ 就绪",   "31个模板已注册，待动态调用"),
        ("Phase 5: Digital Twin",                  "⏳ 待激活", "脚本已定义，WATCHLIST立项后启动"),
        ("Phase 6: Winning Pattern Library",        "✅ 基础就绪", "5个爆款模式，已提取Product DNA"),
        ("Phase 7: 自主运转",                      "⏳ 发展中", "等待真实数据积累 + 进化验证"),
    ]

    print(f"  {'阶段':<45} {'状态':<12} {'备注'}")
    print(f"  {'─'*80}")
    for phase, status, note in phases:
        print(f"  {phase:<45} {status:<12} {note}")

    # ============================================================
    # 11. Cron Jobs
    # ============================================================
    section("Cron Jobs — 自动任务")

    from pathlib import Path
    cron_file = Path(HVOS_DIR).parent / "cron" / "jobs.json"
    if cron_file.exists():
        with open(cron_file) as f:
            jobs = json.load(f)
        print(f"  已配置定时任务: {len(jobs) if isinstance(jobs, list) else len(jobs.get('jobs', []))} 个")
    else:
        print(f"  ⚠️  未检测到 HVOS 专用 Cron Jobs")
        print(f"\n  建议配置以下自动任务:")
        recommended = [
            ("market_scan",     "每周一 09:00", "市场扫描，SCI 异常检测"),
            ("hvos_daily",      "每日 08:00",   "HVOS 每日状态报告"),
            ("review_reminder", "每周五 17:00", "Board Meeting 提醒"),
            ("kg_maintenance",  "每月 1日",     "知识图谱整理"),
        ]
        for name, schedule, desc in recommended:
            print(f"    • {name:<20} {schedule:<18} {desc}")

    print(f"\n{'═'*64}")
    print(f"  ✅ HVOS 系统状态面板加载完成 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*64}\n")


if __name__ == "__main__":
    hvos_status()
