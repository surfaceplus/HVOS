"""
HVOS 核心引擎 — 商业知识图谱 CRUD API
========================================
知识图谱是 HVOS 的长期记忆资产。
每次分析自动沉淀节点和关系，驱动图谱持续成长。

使用方法：
  python hvos_kg_engine.py --action update_product --name "个性化礼品套装" --category "礼品" --price_tier 3 --dna "3,4,5,4,5,3,2,2,4,3"
  python hvos_kg_engine.py --action query --type Product
  python hvos_kg_engine.py --action status
"""

import sqlite3
import json
import os
import uuid
import sys
from datetime import datetime
from math import sqrt

# ============================================================
# 配置
# ============================================================
HVOS_ROOT = os.path.dirname(os.path.abspath(__file__))
KG_DB = os.path.join(HVOS_ROOT, "knowledge_graph", "kg.db")

# ============================================================
# 数据库连接
# ============================================================
def get_conn():
    return sqlite3.connect(KG_DB)

# ============================================================
# 节点操作
# ============================================================

def kg_update_product(name, category, price_tier=3, dna=None, status="watchlist", extra_props=None):
    """
    更新或创建产品节点
    """
    conn = get_conn()
    cur = conn.cursor()
    node_id = f"prod_{name[:20].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    props = {
        "name": name,
        "category": category,
        "price_tier": price_tier,
        "status": status,
    }
    if dna:
        dna_list = [int(x.strip()) for x in dna.split(",")]
        props["dna"] = {
            "price_tier": dna_list[0],
            "pain_point_intensity": dna_list[1],
            "emotion_intensity": dna_list[2],
            "demo_effectiveness": dna_list[3],
            "viral_potential": dna_list[4],
            "profit_margin": dna_list[5],
            "repurchase_rate": dna_list[6],
            "supply_difficulty": dna_list[7],
            "brandability": dna_list[8],
            "competition_level": dna_list[9],
        }
    if extra_props:
        props.update(extra_props)

    # 检查是否已存在同名产品 — 用 JSON_EXTRACT 精确匹配
    cur.execute("SELECT id FROM nodes WHERE type='Product' AND JSON_EXTRACT(properties, '$.name') = ?", (name,))
    existing = cur.fetchone()
    if existing:
        node_id = existing[0]
        cur.execute("UPDATE nodes SET properties=?, updated_at=? WHERE id=?", 
                    (json.dumps(props, ensure_ascii=False), datetime.now().isoformat(), node_id))
        action = "updated"
    else:
        cur.execute("INSERT INTO nodes (id, type, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (node_id, "Product", json.dumps(props, ensure_ascii=False), 
                     datetime.now().isoformat(), datetime.now().isoformat()))
        action = "created"

    conn.commit()
    print(f"[KG] Product '{name}' {action}. ID: {node_id}")
    return node_id


def kg_add_category(name, parent=None, seasonality=None, key_holidays=None, extra_props=None):
    """创建或更新品类节点"""
    conn = get_conn()
    cur = conn.cursor()
    node_id = f"cat_{name[:20].replace(' ', '_')}"
    props = {"name": name}
    if parent: props["parent"] = parent
    if seasonality: props["seasonality"] = seasonality
    if key_holidays: props["key_holidays"] = key_holidays
    if extra_props: props.update(extra_props)

    cur.execute("SELECT id FROM nodes WHERE id=?", (node_id,))
    if cur.fetchone():
        cur.execute("UPDATE nodes SET properties=?, updated_at=? WHERE id=?",
                    (json.dumps(props, ensure_ascii=False), datetime.now().isoformat(), node_id))
        action = "updated"
    else:
        cur.execute("INSERT INTO nodes (id, type, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (node_id, "Category", json.dumps(props, ensure_ascii=False),
                     datetime.now().isoformat(), datetime.now().isoformat()))
        action = "created"

    conn.commit()
    print(f"[KG] Category '{name}' {action}. ID: {node_id}")
    return node_id


def kg_add_hscode(code, description, duty_rate_us=0.0, duty_rate_eu=0.0, duty_rate_uk=0.0, category=None):
    """添加 HS Code 节点"""
    conn = get_conn()
    cur = conn.cursor()
    node_id = f"hsc_{code.replace('.', '')}"
    props = {
        "code": code,
        "description": description,
        "duty_rate_us": duty_rate_us,
        "duty_rate_eu": duty_rate_eu,
        "duty_rate_uk": duty_rate_uk,
    }
    if category: props["category"] = category

    cur.execute("SELECT id FROM nodes WHERE id=?", (node_id,))
    if cur.fetchone():
        cur.execute("UPDATE nodes SET properties=?, updated_at=? WHERE id=?",
                    (json.dumps(props, ensure_ascii=False), datetime.now().isoformat(), node_id))
    else:
        cur.execute("INSERT INTO nodes (id, type, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (node_id, "HSCode", json.dumps(props, ensure_ascii=False),
                     datetime.now().isoformat(), datetime.now().isoformat()))

    conn.commit()
    print(f"[KG] HSCode '{code}' registered. ID: {node_id}")
    return node_id


def kg_link_nodes(from_id, rel_type, to_id, properties=None):
    """连接两个节点"""
    conn = get_conn()
    cur = conn.cursor()
    rel_id = str(uuid.uuid4())
    props_str = json.dumps(properties, ensure_ascii=False) if properties else "{}"
    cur.execute("INSERT INTO relations (from_id, rel_type, to_id, properties, created_at) VALUES (?, ?, ?, ?, ?)",
                (from_id, rel_type, to_id, props_str, datetime.now().isoformat()))
    conn.commit()
    print(f"[KG] Link: {from_id} --[{rel_type}]--> {to_id}")
    return rel_id


def kg_query(query_type=None, filters=None):
    """
    查询知识图谱
    """
    conn = get_conn()
    cur = conn.cursor()

    if query_type == "Product":
        if filters and "category" in filters:
            cur.execute("""SELECT id, type, properties FROM nodes 
                           WHERE type='Product' AND properties LIKE ?""", 
                        (f'%"{filters["category"]}"%',))
        else:
            cur.execute("SELECT id, type, properties FROM nodes WHERE type='Product'")
    elif query_type == "Category":
        cur.execute("SELECT id, type, properties FROM nodes WHERE type='Category'")
    elif query_type == "HSCode":
        cur.execute("SELECT id, type, properties FROM nodes WHERE type='HSCode'")
    else:
        cur.execute("SELECT id, type, properties FROM nodes")

    results = []
    for row in cur.fetchall():
        props = json.loads(row[2]) if row[2] else {}
        results.append({"id": row[0], "type": row[1], **props})

    return results


def kg_status():
    """打印知识图谱状态"""
    conn = get_conn()
    cur = conn.cursor()

    print("\n" + "="*60)
    print("  HVOS 知识图谱 — SYSTEM STATUS")
    print("="*60)

    # 节点统计
    cur.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type")
    type_counts = dict(cur.fetchall())
    total_nodes = sum(type_counts.values())
    print(f"\n  节点总数：{total_nodes}")
    for t, c in type_counts.items():
        print(f"    {t}: {c}")

    # 关系统计
    cur.execute("SELECT rel_type, COUNT(*) FROM relations GROUP BY rel_type")
    rel_counts = dict(cur.fetchall())
    total_rels = sum(rel_counts.values())
    print(f"\n  关系总数：{total_rels}")
    for r, c in rel_counts.items():
        print(f"    {r}: {c}")

    # 海关数据
    cur.execute("SELECT COUNT(*) FROM customs_hs_codes")
    hs_count = cur.fetchone()[0]
    print(f"\n  海关 HS Code：{hs_count} 条")

    # 预测记录
    cur.execute("SELECT COUNT(*) FROM predictions")
    pred_count = cur.fetchone()[0]
    print(f"  预测记录：{pred_count} 条")

    # 最近更新
    cur.execute("SELECT updated_at FROM nodes ORDER BY updated_at DESC LIMIT 1")
    last = cur.fetchone()
    print(f"\n  最后更新：{last[0] if last else '无'}")
    print("\n" + "="*60)
    return {"nodes": total_nodes, "relations": total_rels, "hs_codes": hs_count, "predictions": pred_count}


def kg_init_sample_data():
    """初始化示例数据（演示用）"""
    print("\n[KG] 初始化示例数据...")

    # 添加更多 HS Codes
    hs_codes = [
        ("9505.10", "圣诞节装饰用品", 0.0, 0.0, "Holiday", "Gift/Party"),
        ("9505.21", "化装舞会用品", 0.0, 0.0, "Party", "Costume"),
        ("9505.90", "其他派对用品", 0.0, 0.0, "Party", "Party"),
        ("7323.99", "钢铁制家用炊具", 2.8, 1.7, "Kitchen", "Cookware"),
        ("7615.10", "铝制餐具/厨房用具", 3.4, 2.7, "Kitchen", "Kitchenware"),
        ("3924.10", "塑料餐具/厨房用具", 3.4, 2.7, "Kitchen", "Kitchenware"),
        ("8210.00", "手动食品加工机械", 4.6, 2.7, "Kitchen", "Appliance"),
        ("6912.00", "陶瓷餐具", 6.4, 5.0, "Kitchen", "Tableware"),
        ("9503.00", "玩具类", 0.0, 0.0, "Toy", "Kids"),
        ("9504.50", "视频游戏机/用品", 0.0, 0.0, "Gaming", "Entertainment"),
        ("8516.79", "其他电热器具", 2.7, 2.7, "Kitchen", "Appliance"),
        ("6802.10", "人造石/雕塑品", 6.0, 5.0, "Home", "Decor"),
        ("4420.10", "木制装饰品", 0.0, 0.0, "Home", "Decor"),
        ("7013.99", "玻璃装饰品", 6.4, 5.0, "Home", "Decor"),
        ("6307.90", "其他纺织制成品", 7.0, 6.0, "Home", "Textile"),
    ]

    for code, desc, us, eu, cat, subcat in hs_codes:
        kg_add_hscode(code, desc, us, eu, category=cat)

    # 添加品类
    categories = [
        ("pet_supplies", "宠物用品", "Pet Supplies", "Q1-Q4", ["情人节", "感恩节", "圣诞节"]),
        ("kitchen_gadgets", "厨房小工具", "Kitchen", "Q1-Q4", ["感恩节", "圣诞节", "新年"]),
        ("outdoor_gear", "户外装备", "Outdoor", "Q2-Q3", ["独立日", "劳动节", "感恩节"]),
        ("beauty_skin", "美妆护肤", "Beauty", "Q1-Q4", ["情人节", "母亲节", "圣诞节"]),
        ("home_decor", "家居装饰", "Home Decor", "Q1-Q4", ["情人节", "母亲节", "圣诞节"]),
    ]

    for cid, name, parent, seas, hols in categories:
        kg_add_category(name, parent, seas, hols)

    print("[KG] 示例数据初始化完成 ✅")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM nodes")
    print(f"[KG] 当前节点总数: {cur.fetchone()[0]}")


# ============================================================
# Product DNA 引擎
# ============================================================

def extract_product_dna(product_id):
    """
    提取产品 DNA 向量（从节点 properties 读取或计算）
    返回 10 维向量列表
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT properties FROM nodes WHERE id=?", (product_id,))
    row = cur.fetchone()
    if not row:
        return None
    props = json.loads(row[0])
    dna = props.get("dna", {})
    if dna:
        return [
            dna.get("price_tier", 3),
            dna.get("pain_point_intensity", 3),
            dna.get("emotion_intensity", 3),
            dna.get("demo_effectiveness", 3),
            dna.get("viral_potential", 3),
            dna.get("profit_margin", 3),
            dna.get("repurchase_rate", 3),
            dna.get("supply_difficulty", 3),
            dna.get("brandability", 3),
            dna.get("competition_level", 3),
        ]
    return None


def calculate_dna_similarity(dna_a, dna_b):
    """
    计算两个 DNA 向量的余弦相似度
    返回 0-100% 的相似度分数
    """
    if not dna_a or not dna_b:
        return 0.0
    dot_product = sum(a * b for a, b in zip(dna_a, dna_b))
    mag_a = sqrt(sum(a**2 for a in dna_a))
    mag_b = sqrt(sum(b**2 for b in dna_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return round(dot_product / (mag_a * mag_b) * 100, 1)


def match_to_winning_patterns(dna_vector):
    """
    将产品 DNA 与已知爆款模式匹配
    返回匹配报告
    """
    # 已知的爆款 DNA 模板
    patterns = {
        "礼品套装型": {
            "dna": [3, 4, 5, 4, 5, 3, 2, 2, 4, 3],
            "description": "高情绪+高传播+高品牌化，适合礼品场景"
        },
        "宠物用品型": {
            "dna": [2, 3, 4, 3, 4, 3, 4, 2, 3, 3],
            "description": "中等情感+高复购，宠物主消费力强"
        },
        "厨房功能型": {
            "dna": [3, 4, 3, 4, 2, 3, 3, 3, 2, 4],
            "description": "高痛点+高演示，适合对比视频"
        },
        "户外装备型": {
            "dna": [3, 3, 3, 3, 3, 4, 3, 4, 3, 3],
            "description": "高利润+高供应链难度，专业性要求高"
        },
        "美妆护肤型": {
            "dna": [2, 5, 3, 4, 3, 3, 5, 4, 3, 4],
            "description": "极高痛点+高复购，功效型产品"
        },
    }

    if not dna_vector:
        return []

    matches = []
    for name, info in patterns.items():
        score = calculate_dna_similarity(dna_vector, info["dna"])
        matches.append({
            "pattern": name,
            "match_score": score,
            "description": info["description"]
        })

    matches.sort(key=lambda x: x["match_score"], reverse=True)
    return matches


# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS 知识图谱引擎")
    parser.add_argument("--action", required=True, 
                        choices=["status", "update_product", "add_category", "add_hscode", 
                                 "link", "query", "init_sample", "dna_match"],
                        help="操作类型")
    parser.add_argument("--name", help="产品/品类名称")
    parser.add_argument("--category", help="品类")
    parser.add_argument("--price_tier", type=int, help="价格带 1-5")
    parser.add_argument("--dna", help="DNA 向量，逗号分隔，如: 3,4,5,4,5,3,2,2,4,3")
    parser.add_argument("--status", default="watchlist", help="产品状态")
    parser.add_argument("--parent", help="父品类")
    parser.add_argument("--seasonality", help="季节性，如 Q2-Q3")
    parser.add_argument("--holidays", help="关键节日，逗号分隔")
    parser.add_argument("--code", help="HS Code")
    parser.add_argument("--description", help="HS Code 描述")
    parser.add_argument("--duty_us", type=float, default=0.0, help="美国关税税率")
    parser.add_argument("--duty_eu", type=float, default=0.0, help="欧盟关税税率")
    parser.add_argument("--duty_uk", type=float, default=0.0, help="英国关税税率")
    parser.add_argument("--hs_category", help="HS Code 品类分类")
    parser.add_argument("--from_id", help="起始节点ID")
    parser.add_argument("--rel_type", help="关系类型")
    parser.add_argument("--to_id", help="目标节点ID")
    parser.add_argument("--type", help="查询类型：Product/Category/HSCode")
    parser.add_argument("--product_id", help="产品节点ID（用于DNA匹配）")
    parser.add_argument("--extra", help="额外JSON属性")

    args = parser.parse_args()

    if args.action == "status":
        kg_status()

    elif args.action == "update_product":
        extra = json.loads(args.extra) if args.extra else None
        kg_update_product(args.name, args.category, args.price_tier or 3, args.dna, args.status, extra)

    elif args.action == "add_category":
        holidays = args.holidays.split(",") if args.holidays else None
        kg_add_category(args.name, args.parent, args.seasonality, holidays)

    elif args.action == "add_hscode":
        kg_add_hscode(args.code, args.description, args.duty_us, args.duty_eu, args.duty_uk, args.hs_category)

    elif args.action == "link":
        if not all([args.from_id, args.rel_type, args.to_id]):
            print("[KG] 错误：--from_id, --rel_type, --to_id 都需要指定")
        else:
            kg_link_nodes(args.from_id, args.rel_type, args.to_id)

    elif args.action == "query":
        results = kg_query(args.type)
        print(f"\n[KG] 查询结果：{len(results)} 条")
        for r in results:
            print(f"  {r['id']} | {r.get('name', r.get('code', 'N/A'))}")

    elif args.action == "init_sample":
        kg_init_sample_data()

    elif args.action == "dna_match":
        if args.product_id:
            dna = extract_product_dna(args.product_id)
        elif args.dna:
            dna = [int(x.strip()) for x in args.dna.split(",")]
        else:
            print("[KG] 错误：需要 --product_id 或 --dna")
            sys.exit(1)

        print(f"\n[DNA] 产品DNA: {dna}")
        matches = match_to_winning_patterns(dna)
        print(f"\n[DNA] 爆款基因匹配结果：")
        for m in matches:
            bar = "█" * int(m["match_score"] / 10) + "░" * (10 - int(m["match_score"] / 10))
            print(f"  {m['pattern']}: {bar} {m['match_score']}%")
            print(f"    → {m['description']}")
