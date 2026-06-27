"""
HVOS V8.0 — Knowledge Graph Event Consumer
============================================
核心职责：将 Event Bus 中的事件实时消费，转化为 Knowledge Graph 中的实体和关系。

Event → KG 自动构建流程：
  OPPORTUNITY_DISCOVERED  → 创建 Product/Brand/HSCode 节点
  INTELLIGENCE_ANALYSIS  → 更新产品维度评分
  COMPLIANCE_REVIEW      → 创建 Compliance 节点 + 关系
  BOARD_VOTE_CAST        → 创建 BoardMember 节点 + 投票关系
  INVESTMENT_DECISION     → 创建 Investment 关系 + 更新 Portfolio
  PATTERN_DETECTED       → 创建 Pattern 节点 + 关联成功/失败案例

Knowledge Flywheel 起点。
"""

import sys
import json
import sqlite3
import os
from datetime import datetime
from typing import Optional

# ============================================================
# KG Schema Definitions
# ============================================================

ENTITY_TYPES = [
    "Product", "Brand", "Factory", "Supplier", "Influencer",
    "Campaign", "Customer", "Country", "Platform", "HSCode",
    "Shipment", "Category", "Pattern", "Policy", "BoardMember",
    "Opportunity", "Investment"
]

RELATION_TYPES = [
    "MANUFACTURED_BY", "COMPETES_WITH", "SUPPLIED_BY", "PROMOTED_BY",
    "SHIPPED_TO", "BOUGHT_BY", "RELATED_TO", "INVESTED_IN", "LOCATED_IN",
    "TRACKED_BY", "REVIEWED_BY", "APPROVED_BY", "REJECTED_BY",
    "FOLLOWS_PATTERN", "GENERATES_SIGNAL", "BELONGS_TO", "PART_OF"
]

# ============================================================
# Event → KG Mapping
# ============================================================

EVENT_TO_ENTITIES = {
    "OPPORTUNITY_DISCOVERED": [
        ("Product", "name"),
        ("Category", "category"),
        ("Country", "target_market"),
        ("HSCode", "hs_code"),
        ("Opportunity", "opp_id"),
    ],
    "INTELLIGENCE_ANALYSIS_COMPLETED": [
        ("Opportunity", "opp_id"),
        ("Category", "category"),
    ],
    "COMPLIANCE_REVIEW_COMPLETED": [
        ("Product", "name"),
        ("Opportunity", "opp_id"),
        ("Policy", "regulation"),
    ],
    "BOARD_VOTE_CAST": [
        ("BoardMember", "voter"),
        ("Opportunity", "opp_id"),
    ],
    "INVESTMENT_DECISION_RENDERED": [
        ("Opportunity", "opp_id"),
        ("Investment", "decision_id"),
    ],
    "RISK_VETO_TRIGGERED": [
        ("Opportunity", "opp_id"),
        ("Policy", "risk_factor"),
    ],
    "PATTERN_DETECTED": [
        ("Pattern", "pattern_id"),
        ("Category", "affected_category"),
    ],
}

EVENT_TO_RELATIONS = {
    "OPPORTUNITY_DISCOVERED": [
        ("Opportunity", "BELONGS_TO", "Category"),
        ("Opportunity", "SHIPPED_TO", "Country"),
        ("Product", "HAS_HSCODE", "HSCode"),
    ],
    "INTELLIGENCE_ANALYSIS_COMPLETED": [
        ("Opportunity", "TRACKED_BY", "Platform"),
    ],
    "COMPLIANCE_REVIEW_COMPLETED": [
        ("Product", "REVIEWED_BY", "Policy"),
        ("Opportunity", "REVIEWED_BY", "BoardMember"),
    ],
    "BOARD_VOTE_CAST": [
        ("BoardMember", "VOTED_ON", "Opportunity"),
    ],
    "INVESTMENT_DECISION_RENDERED": [
        ("Investment", "INVESTED_IN", "Opportunity"),
        ("BoardMember", "APPROVED_BY", "Investment"),
    ],
    "RISK_VETO_TRIGGERED": [
        ("Opportunity", "REJECTED_BY", "Policy"),
    ],
    "PATTERN_DETECTED": [
        ("Pattern", "FOLLOWS_PATTERN", "Category"),
    ],
}

# ============================================================
# Knowledge Graph Event Consumer
# ============================================================

class KGEventConsumer:
    """
    消费 Event Bus 事件，自动构建 Knowledge Graph。

    使用方式：
        consumer = KGEventConsumer()

        # 实时消费新事件
        consumer.consume_event(event_dict)

        # 批量处理历史事件（启动时回填）
        consumer.backfill_from_event_store(event_store_path, opp_id=None)

        # 从 Event Store 拉取所有事件并构建 KG
        consumer.rebuild_kg_from_scratch()
    """

    def __init__(self, kg_db: str = None):
        if kg_db is None:
            kg_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kg.db")
        self.kg_db = kg_db
        self._init_schema()
        self.stats = {"nodes_created": 0, "relations_created": 0, "nodes_updated": 0}

    # ----------------------------------------------------------
    # Schema Initialization
    # ----------------------------------------------------------

    def _init_schema(self):
        """初始化 KG Schema"""
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()

        # Nodes 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_nodes (
                node_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT,
                source_event_id TEXT,
                confidence REAL DEFAULT 0.5
            )
        """)

        # Relations 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_relations (
                relation_id TEXT PRIMARY KEY,
                from_node TEXT NOT NULL,
                to_node TEXT NOT NULL,
                rel_type TEXT NOT NULL,
                properties TEXT DEFAULT '{}',
                created_at TEXT,
                source_event_id TEXT,
                confidence REAL DEFAULT 0.5,
                UNIQUE(from_node, to_node, rel_type)
            )
        """)

        # Event log（追踪 KG 构建历史）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_event_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                event_type TEXT,
                action TEXT,
                detail TEXT,
                ts TEXT
            )
        """)

        # Pattern 表（自动发现的 Pattern）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_patterns (
                pattern_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                category TEXT,
                success_indicators TEXT DEFAULT '[]',
                failure_indicators TEXT DEFAULT '[]',
                confidence REAL DEFAULT 0.5,
                times_observed INTEGER DEFAULT 1,
                last_observed TEXT,
                created_at TEXT
            )
        """)

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON kg_nodes(entity_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rels_type ON kg_relations(rel_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rels_from ON kg_relations(from_node)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rels_to ON kg_relations(to_node)")

        conn.commit()
        conn.close()

    # ----------------------------------------------------------
    # Core Methods
    # ----------------------------------------------------------

    def consume_event(self, event: dict) -> dict:
        """
        消费单个事件，构建 KG 实体和关系。

        Args:
            event: {
                "event_id": "evt_xxx",
                "event_type": "OPPORTUNITY_DISCOVERED",
                "actor": "System",
                "timestamp": "2026-06-10T...",
                "description": "...",
                "data": {...}
            }
        Returns:
            {"nodes_created": N, "relations_created": M}
        """
        event_type = event.get("event_type", "")
        event_data = event.get("data", {})
        ts = event.get("timestamp", datetime.now().isoformat())
        source_event = event.get("event_id", "")

        stats = {"nodes": 0, "relations": 0}

        # 创建实体
        entity_specs = EVENT_TO_ENTITIES.get(event_type, [])
        for entity_type, id_field in entity_specs:
            if id_field not in event_data:
                continue
            node_id = self._sanitize_id(f"{entity_type}_{event_data[id_field]}")
            name = str(event_data.get("name", event_data[id_field]))
            props = self._extract_properties(event_data, entity_type)
            created = self._upsert_node(
                node_id=node_id,
                entity_type=entity_type,
                name=name,
                properties=props,
                ts=ts,
                source_event=source_event
            )
            if created:
                stats["nodes"] += 1

        # 创建关系
        relation_specs = EVENT_TO_RELATIONS.get(event_type, [])
        for from_type, rel_type, to_type in relation_specs:
            # 从 event_data 推断 from_node 和 to_node ID
            from_id = self._infer_node_id(event_data, from_type)
            to_id = self._infer_node_id(event_data, to_type)
            if from_id and to_id:
                rel_id = f"{from_id}_{rel_type}_{to_id}"
                props = self._extract_relation_properties(event_data, rel_type)
                created = self._upsert_relation(
                    relation_id=rel_id,
                    from_node=from_id,
                    to_node=to_id,
                    rel_type=rel_type,
                    properties=props,
                    ts=ts,
                    source_event=source_event
                )
                if created:
                    stats["relations"] += 1

        # 通用关系：从 data 中提取的所有 entity 也可以与 Opportunity 关联
        if event_type == "INVESTMENT_DECISION_RENDERED":
            self._link_decision_to_opportunity(event_data, ts, source_event, stats)

        # Pattern 自动发现
        if event_type == "INTELLIGENCE_ANALYSIS_COMPLETED":
            self._detect_pattern(event_data, ts, source_event, stats)

        # 记录日志
        self._log_event(event, stats, ts)

        self.stats["nodes_created"] += stats["nodes"]
        self.stats["relations_created"] += stats["relations"]
        return stats

    def backfill_from_event_store(
        self,
        event_store_path: str,
        opp_id: str = None
    ) -> dict:
        """
        从 Event Store 拉取历史事件，批量构建 KG。

        Args:
            event_store_path: event_store.db 路径
            opp_id: 可选，只处理特定 opportunity 的事件
        """
        conn_es = sqlite3.connect(event_store_path)
        cur_es = conn_es.cursor()

        if opp_id:
            cur_es.execute("""
                SELECT event_id, timestamp, actor, event_type, description, data
                FROM event_log
                WHERE opportunity_id = ?
                ORDER BY timestamp
            """, (opp_id,))
        else:
            cur_es.execute("""
                SELECT event_id, timestamp, actor, event_type, description, data
                FROM event_log
                ORDER BY timestamp
            """)

        rows = cur_es.fetchall()
        conn_es.close()

        total = {"nodes": 0, "relations": 0}

        for row in rows:
            event = {
                "event_id": row[0],
                "timestamp": row[1],
                "actor": row[2],
                "event_type": row[3],
                "description": row[4],
                "data": json.loads(row[5]) if row[5] else {}
            }
            stats = self.consume_event(event)
            total["nodes"] += stats["nodes"]
            total["relations"] += stats["relations"]

        return total

    def rebuild_kg_from_scratch(self, event_store_path: str = None) -> dict:
        """
        清空 KG 并从 Event Store 完全重建。
        """
        if event_store_path is None:
            event_store_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hvos_v7", "event_store.db")

        # 清空 KG
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()
        cur.execute("DELETE FROM kg_nodes")
        cur.execute("DELETE FROM kg_relations")
        cur.execute("DELETE FROM kg_event_log")
        conn.commit()
        conn.close()

        # 重建
        return self.backfill_from_event_store(event_store_path)

    # ----------------------------------------------------------
    # Node & Relation Management
    # ----------------------------------------------------------

    def _upsert_node(
        self,
        node_id: str,
        entity_type: str,
        name: str,
        properties: dict,
        ts: str,
        source_event: str
    ) -> bool:
        """创建或更新节点。返回 True 表示新建。"""
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()

        cur.execute("SELECT node_id FROM kg_nodes WHERE node_id = ?", (node_id,))
        existing = cur.fetchone()

        now = datetime.now().isoformat()
        props_json = json.dumps(properties, ensure_ascii=False)

        if existing:
            cur.execute("""
                UPDATE kg_nodes
                SET properties = ?, updated_at = ?, source_event_id = ?
                WHERE node_id = ?
            """, (props_json, now, source_event, node_id))
            created = False
        else:
            cur.execute("""
                INSERT INTO kg_nodes
                (node_id, entity_type, name, properties, created_at, updated_at, source_event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (node_id, entity_type, name, props_json, now, now, source_event))
            created = True

        conn.commit()
        conn.close()
        return created
    def _get_conn(self):
        """获取带超时配置的数据库连接"""
        import time
        conn = sqlite3.connect(self.kg_db, timeout=15.0)
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.row_factory = sqlite3.Row
        return conn

    def _upsert_relation(
        self,
        relation_id: str,
        from_node: str,
        to_node: str,
        rel_type: str,
        properties: dict,
        ts: str,
        source_event: str
    ) -> bool:
        """创建或更新关系。返回 True 表示新建。"""
        import time
        for attempt in range(5):
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO kg_relations
                    (relation_id, from_node, to_node, rel_type, properties, created_at, source_event_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    relation_id, from_node, to_node, rel_type,
                    json.dumps(properties, ensure_ascii=False),
                    datetime.now().isoformat(), source_event
                ))
                created = cur.rowcount > 0
                conn.commit()
                return created
            except sqlite3.OperationalError as e:
                if conn:
                    conn.rollback()
                if "locked" in str(e) and attempt < 4:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise
            finally:
                if conn:
                    conn.close()
        return False

    def _link_decision_to_opportunity(
        self,
        data: dict,
        ts: str,
        source_event: str,
        stats: dict
    ):
        """将投资决策与机会、投票成员关联"""
        opp_id = data.get("opp_id")
        verdict = data.get("verdict", "")
        decision_id = data.get("decision_id", "")

        if not opp_id:
            return

        # 创建 Investment 节点
        inv_node = f"Investment_{decision_id}"
        self._upsert_node(
            inv_node, "Investment",
            f"Investment_{verdict.upper()}",
            {"verdict": verdict, "budget": data.get("budget_recommendation", 0)},
            ts, source_event
        )
        stats["nodes"] += 1

        # Investment → Opportunity
        inv_rel = f"{inv_node}_INVESTED_IN_Opportunity_{opp_id}"
        self._upsert_relation(inv_rel, inv_node, f"Opportunity_{opp_id}",
                            "INVESTED_IN", {"verdict": verdict}, ts, source_event)
        stats["relations"] += 1

        # 添加投票成员关系
        votes_summary = data.get("votes_summary", {})
        for voter, position in votes_summary.items():
            bm_node = f"BoardMember_{voter}"
            self._upsert_node(bm_node, "BoardMember", voter, {}, ts, source_event)
            stats["nodes"] += 1

            rel_id = f"{bm_node}_VOTED_ON_Opportunity_{opp_id}"
            self._upsert_relation(rel_id, bm_node, f"Opportunity_{opp_id}",
                                "VOTED_ON", {"position": position}, ts, source_event)
            stats["relations"] += 1

    # ----------------------------------------------------------
    # Pattern Detection
    # ----------------------------------------------------------

    def _detect_pattern(
        self,
        data: dict,
        ts: str,
        source_event: str,
        stats: dict
    ):
        """
        基于 Intelligence 分析结果自动发现 Pattern。
        使用单一连接，避免与 _upsert_relation 冲突。
        """
        import time
        market_score = data.get("market_size_score", 5)
        financial_score = data.get("financial_score", 5)
        competitive_score = data.get("competitive_score", 5)
        category = data.get("category", "general")

        if market_score >= 7 and financial_score >= 7 and competitive_score <= 5:
            pattern_name = "Premium Niche"
            description = "高增长 + 高毛利 + 低竞争 → 优质细分市场"
        elif market_score >= 7 and financial_score < 6:
            pattern_name = "Commodity Trap"
            description = "高增长 + 低毛利 → 商品陷阱风险"
        elif financial_score >= 8 and competitive_score >= 5:
            pattern_name = "Moat Business"
            description = "高毛利 + 高壁垒 → 护城河业务"
        else:
            return

        pattern_id = f"Pattern_{category}_{pattern_name.replace(' ', '_')}".lower()

        conn = None
        for attempt in range(5):
            try:
                conn = self._get_conn()
                cur = conn.cursor()
                now = datetime.now().isoformat()

                cur.execute("SELECT times_observed FROM kg_patterns WHERE pattern_id = ?", (pattern_id,))
                row = cur.fetchone()

                if row:
                    cur.execute("""
                        UPDATE kg_patterns
                        SET times_observed = times_observed + 1, last_observed = ?,
                            confidence = MIN(confidence + 0.05, 0.95)
                        WHERE pattern_id = ?
                    """, (now, pattern_id))
                    conn.commit()
                else:
                    cur.execute("""
                        INSERT INTO kg_patterns
                        (pattern_id, name, description, category, confidence, times_observed, last_observed, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (pattern_id, pattern_name, description, category, 0.5, 1, now, now))
                    conn.commit()
                    stats["nodes"] += 1

                # Pattern → Category 关系（在同一连接中）
                cat_node = f"Category_{category}"
                pat_rel = f"{pattern_id}_FOLLOWS_PATTERN_{cat_node}"
                cur.execute("""
                    INSERT OR IGNORE INTO kg_relations
                    (relation_id, from_node, to_node, rel_type, properties, created_at, source_event_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (pat_rel, pattern_id, cat_node, "FOLLOWS_PATTERN",
                      json.dumps({}, ensure_ascii=False), now, source_event))
                conn.commit()
                stats["relations"] += 1
                return
            except sqlite3.OperationalError as e:
                if conn:
                    conn.rollback()
                if "locked" in str(e) and attempt < 4:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                raise
            finally:
                if conn:
                    conn.close()

    # ----------------------------------------------------------
    # Utility
    # ----------------------------------------------------------

    def _sanitize_id(self, raw_id: str) -> str:
        """清理节点ID，确保合法且唯一"""
        return raw_id.replace(" ", "_").replace("/", "_").replace("\\", "_")[:128]

    def _infer_node_id(self, data: dict, entity_type: str) -> Optional[str]:
        """从 event data 推断节点ID"""
        type_to_field = {
            "Opportunity": "opp_id",
            "Product": "name",
            "Category": "category",
            "Country": "market",
            "HSCode": "hs_code",
            "BoardMember": "voter",
            "Investment": "decision_id",
            "Policy": "regulation",
            "Pattern": "pattern_id",
        }
        field = type_to_field.get(entity_type)
        if not field or field not in data:
            return None
        val = data[field]
        if not val:
            return None
        return self._sanitize_id(f"{entity_type}_{val}")

    def _extract_properties(self, data: dict, entity_type: str) -> dict:
        """从 event data 提取实体属性"""
        props = {}
        if entity_type == "Product" or entity_type == "Opportunity":
            for key in ["name", "category", "retail_price", "fob_cost",
                        "tam", "growth_rate", "predicted_roas", "source_confidence"]:
                if key in data:
                    props[key] = data[key]
        elif entity_type == "Investment":
            for key in ["verdict", "budget_recommendation", "confidence",
                        "timeline_months", "risk_veto_active"]:
                if key in data:
                    props[key] = data[key]
        return props

    def _extract_relation_properties(self, data: dict, rel_type: str) -> dict:
        """从 event data 提取关系属性"""
        props = {"rel_type": rel_type}
        if "position" in data:
            props["position"] = data["position"]
        if "score" in data:
            props["score"] = data["score"]
        if "confidence" in data:
            props["confidence"] = data["confidence"]
        return props

    def _log_event(self, event: dict, stats: dict, ts: str):
        """记录 KG 构建日志"""
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO kg_event_log
            (event_id, event_type, action, detail, ts)
            VALUES (?, ?, ?, ?, ?)
        """, (
            event.get("event_id", ""),
            event.get("event_type", ""),
            f"consumed",
            json.dumps({"nodes": stats["nodes"], "relations": stats["relations"]}, ensure_ascii=False),
            ts
        ))
        conn.commit()
        conn.close()

    # ----------------------------------------------------------
    # Query Methods
    # ----------------------------------------------------------

    def get_product_network(self, product_name: str) -> dict:
        """
        查询某个产品的完整商业网络（供应商/品牌/竞争对手/物流）
        """
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()

        product_node = self._sanitize_id(f"Product_{product_name}")

        # 一度关系
        cur.execute("""
            SELECT to_node, rel_type FROM kg_relations WHERE from_node = ?
            UNION ALL
            SELECT from_node, rel_type FROM kg_relations WHERE to_node = ?
        """, (product_node, product_node))

        relations = [{"node": r[0], "type": r[1]} for r in cur.fetchall()]

        # 获取关联节点详情
        nodes = set()
        for r in relations:
            nodes.add(r["node"])
        nodes.add(product_node)

        cur.execute(f"""
            SELECT node_id, entity_type, name, properties FROM kg_nodes
            WHERE node_id IN ({','.join('?' * len(nodes))})
        """, list(nodes))
        node_data = {
            r[0]: {"type": r[1], "name": r[2], "props": json.loads(r[3])}
            for r in cur.fetchall()
        }

        conn.close()
        return {"nodes": node_data, "relations": relations}

    def get_patterns(self, category: str = None) -> list:
        """查询发现的 Pattern"""
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()
        if category:
            cur.execute("""
                SELECT pattern_id, name, description, category, confidence, times_observed
                FROM kg_patterns WHERE category = ?
                ORDER BY confidence DESC, times_observed DESC
            """, (category,))
        else:
            cur.execute("""
                SELECT pattern_id, name, description, category, confidence, times_observed
                FROM kg_patterns ORDER BY confidence DESC, times_observed DESC
            """)
        patterns = [dict(zip(
            ["id", "name", "description", "category", "confidence", "times_observed"],
            r
        )) for r in cur.fetchall()]
        conn.close()
        return patterns

    def get_kg_stats(self) -> dict:
        """KG 统计摘要"""
        conn = sqlite3.connect(self.kg_db)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM kg_nodes")
        nodes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM kg_relations")
        relations = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM kg_patterns")
        patterns = cur.fetchone()[0]
        cur.execute("SELECT entity_type, COUNT(*) FROM kg_nodes GROUP BY entity_type")
        by_type = dict(cur.fetchall())
        conn.close()
        return {
            "total_nodes": nodes,
            "total_relations": relations,
            "total_patterns": patterns,
            "by_entity_type": by_type
        }


# ============================================================
# CLI Entry Point
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V8.0 — Knowledge Graph Event Consumer")
    parser.add_argument("--action", choices=["rebuild", "backfill", "stats", "patterns"],
                        default="stats", help="操作类型")
    parser.add_argument("--opp_id", help="可选：只处理特定 opportunity")
    parser.add_argument("--event_store", default=None, help="Event Store 路径")
    parser.add_argument("--kg_db", default=None, help="KG 数据库路径")

    args = parser.parse_args()

    consumer = KGEventConsumer(kg_db=args.kg_db)

    if args.action == "rebuild":
        es = args.event_store or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reality", "events.db")
        print("正在重建 KG（从 Event Store 完全回填）...")
        result = consumer.rebuild_kg_from_scratch(es)
        print(f"完成：新建 {result['nodes']} 节点，{result['relations']} 关系")

    elif args.action == "backfill":
        es = args.event_store or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reality", "events.db")
        print(f"回填事件（opp_id={args.opp_id or '全部'}）...")
        result = consumer.backfill_from_event_store(es, args.opp_id)
        print(f"完成：新建 {result['nodes']} 节点，{result['relations']} 关系")

    elif args.action == "stats":
        stats = consumer.get_kg_stats()
        print("=" * 50)
        print("  KG 统计摘要")
        print("=" * 50)
        print(f"  总节点数: {stats['total_nodes']}")
        print(f"  总关系数: {stats['total_relations']}")
        print(f"  Pattern数: {stats['total_patterns']}")
        print("  按类型分布:")
        for et, count in stats["by_entity_type"].items():
            print(f"    {et}: {count}")
        print("=" * 50)

    elif args.action == "patterns":
        patterns = consumer.get_patterns()
        print("=" * 50)
        print("  发现的 Pattern")
        print("=" * 50)
        for p in patterns:
            print(f"\n  [{p['id']}] {p['name']}")
            print(f"    描述: {p['description']}")
            print(f"    品类: {p['category']} | 置信度: {p['confidence']:.0%} | 出现: {p['times_observed']}次")
        print("=" * 50)
