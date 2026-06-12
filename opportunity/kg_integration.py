"""
KG Integration — Knowledge Graph 集成模块

职责：
1. 将 Opportunity Engine 发现的机会写入 KG
2. 创建 Opportunity 节点 + 关联关系
3. 查询 KG 中已知品牌/供应商，避免重复发现
4. 写入后触发 Pattern Mining

复用：knowledge-graph/kg_event_consumer.py 的 consume_event() 接口
"""

import sys
import os
from datetime import datetime
from typing import Optional, List, Dict

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
KG_DIR = os.path.join(HVOS_ROOT, "knowledge-graph")

sys.path.insert(0, KG_DIR)

try:
    from kg_event_consumer import KGEventConsumer
    KG_AVAILABLE = True
except ImportError as e:
    KG_AVAILABLE = False
    print(f"[KGIntegration] kg_event_consumer not available: {e}")


class KGIntegration:
    """
    Knowledge Graph 集成模块

    使用方式：

    kg = KGIntegration()

    # 写入机会
    node_id = kg.write_opportunity(opportunity)

    # 查询已知品牌（用于 Amazon New Releases 去重）
    known_brands = kg.get_known_brands(category="kitchen")

    # 查询已知供应商（用于供应链深度验证）
    known_suppliers = kg.get_known_suppliers(hs_code="9619.00")
    """

    def __init__(self, kg_db: str = None):
        """
        Args:
            kg_db: KG 数据库路径
        """
        self.kg_db = kg_db or os.path.join(KG_DIR, "kg.db")
        self.consumer = None

        if KG_AVAILABLE:
            try:
                self.consumer = KGEventConsumer(kg_db=self.kg_db)
                print(f"[KGIntegration] Connected to KG: {self.kg_db}")
            except Exception as e:
                print(f"[KGIntegration] KG connection failed: {e}")
                self.consumer = None
        else:
            print("[KGIntegration] KG module not available")

    def write_opportunity(self, opportunity) -> Optional[str]:
        """
        将 Opportunity 写入 Knowledge Graph

        使用 OPPORTUNITY_DISCOVERED 事件类型

        Args:
            opportunity: Opportunity 对象

        Returns:
            node_id: KG 节点 ID
        """
        if not self.consumer:
            return None

        try:
            event = {
                "event_id": f"evt_{opportunity.opp_id}",
                "event_type": "OPPORTUNITY_DISCOVERED",
                "actor": "OpportunityEngine",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "opp_id": opportunity.opp_id,
                    "name": opportunity.name,
                    "category": opportunity.category,
                    "alpha_score": opportunity.alpha_score,
                    "recommendation": opportunity.recommendation,
                    "velocity": getattr(opportunity, 'velocity', 0),
                    "breadth": getattr(opportunity, 'breadth', 0),
                    "depth": getattr(opportunity, 'depth', 0),
                    "competition_gap": getattr(opportunity, 'competition_gap', 0),
                    "seasonal_fit": getattr(opportunity, 'seasonal_fit', 0),
                    "days_to_window": getattr(opportunity, 'days_to_window', 999),
                    "seasonal_window": getattr(opportunity, 'seasonal_window', ''),
                    "target_market": getattr(opportunity, 'market', 'US'),
                    "hs_code": getattr(opportunity, 'hs_code', ''),
                    "signal_count": getattr(opportunity, 'signal_count', 0),
                    "status": "discovered"
                }
            }

            result = self.consumer.consume_event(event)
            node_id = f"Opportunity_{opportunity.opp_id}"

            print(f"[KGIntegration] Opportunity written: {opportunity.name}")
            print(f"[KGIntegration]   nodes_created={result.get('nodes', 0)}, "
                  f"relations_created={result.get('relations', 0)}")
            return node_id

        except Exception as e:
            print(f"[KGIntegration] write_opportunity failed: {e}")
            return None

    def write_opportunity_signal(self, opportunity, signal: dict) -> Optional[str]:
        """
        将 Opportunity 的信号写入 KG（作为事件记录）

        Args:
            opportunity: Opportunity 对象
            signal: 信号 dict

        Returns:
            node_id
        """
        if not self.consumer:
            return None

        try:
            event = {
                "event_type": "SIGNAL_DETECTED",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "opportunity_id": opportunity.opp_id,
                    "signal_source": signal.get("source", "unknown"),
                    "signal_type": signal.get("type", "surge"),
                    "raw_value": signal.get("velocity", signal.get("volume", 0)),
                    "source": "opportunity_engine"
                }
            }

            result = self.consumer.consume_event(event)
            return result.get("node_id") if isinstance(result, dict) else None

        except Exception as e:
            print(f"[KGIntegration] write_opportunity_signal failed: {e}")
            return None

    def get_known_brands(self, category: str = None, limit: int = 100) -> set:
        """
        查询 KG 中已知的品牌集合（用于 Amazon New Releases 去重）

        Returns:
            set of brand names
        """
        if not self.consumer:
            return set()

        try:
            brands = set()
            # 查询 Brand 实体
            conn = self.consumer._get_conn()
            cur = conn.cursor()

            if category:
                cur.execute("""
                    SELECT DISTINCT b.name
                    FROM kg_nodes b
                    WHERE b.entity_type = 'Brand'
                    AND b.name LIKE ?
                    LIMIT ?
                """, (f"%{category}%", limit))
            else:
                cur.execute("""
                    SELECT DISTINCT name FROM kg_nodes
                    WHERE entity_type = 'Brand'
                    LIMIT ?
                """, (limit,))

            for row in cur.fetchall():
                brands.add(row[0])

            conn.close()
            return brands

        except Exception as e:
            print(f"[KGIntegration] get_known_brands failed: {e}")
            return set()

    def get_known_suppliers(self, hs_code: str = None, category: str = None, limit: int = 50) -> List[Dict]:
        """
        查询 KG 中已知的供应商

        Returns:
            [{"supplier_id": "...", "name": "...", "hs_code": "..."}, ...]
        """
        if not self.consumer:
            return []

        try:
            suppliers = []
            conn = self.consumer._get_conn()
            cur = conn.cursor()

            if hs_code:
                cur.execute("""
                    SELECT node_id, name, properties
                    FROM kg_nodes
                    WHERE entity_type = 'Supplier'
                    AND properties LIKE ?
                    LIMIT ?
                """, (f"%{hs_code}%", limit))
            else:
                cur.execute("""
                    SELECT node_id, name, properties
                    FROM kg_nodes
                    WHERE entity_type = 'Supplier'
                    LIMIT ?
                """, (limit,))

            for row in cur.fetchall():
                import json as json_lib
                try:
                    props = json_lib.loads(row[2]) if row[2] else {}
                except:
                    props = {}
                suppliers.append({
                    "supplier_id": row[0],
                    "name": row[1],
                    "properties": props
                })

            conn.close()
            return suppliers

        except Exception as e:
            print(f"[KGIntegration] get_known_suppliers failed: {e}")
            return []

    def get_kg_stats(self) -> dict:
        """获取 KG 统计信息"""
        if not self.consumer:
            return {"error": "KG not available"}

        try:
            return self.consumer.get_kg_stats()
        except Exception as e:
            return {"error": str(e)}

    def get_recent_opportunities(self, limit: int = 20) -> List[Dict]:
        """
        获取最近发现的机会（从 KG）

        Returns:
            [{"opportunity_id": "...", "name": "...", "alpha_score": ..., "created_at": "..."}, ...]
        """
        if not self.consumer:
            return []

        try:
            conn = self.consumer._get_conn()
            cur = conn.cursor()

            cur.execute("""
                SELECT node_id, name, properties, created_at
                FROM kg_nodes
                WHERE entity_type = 'Opportunity'
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

            results = []
            import json as json_lib
            for row in cur.fetchall():
                try:
                    props = json_lib.loads(row[2]) if row[2] else {}
                except:
                    props = {}
                results.append({
                    "opportunity_id": row[0],
                    "name": row[1],
                    "alpha_score": props.get("alpha_score", 0),
                    "recommendation": props.get("recommendation", ""),
                    "created_at": row[3]
                })

            conn.close()
            return results

        except Exception as e:
            print(f"[KGIntegration] get_recent_opportunities failed: {e}")
            return []


# ──────────────────────────────────────────────────────────────
# 单独运行测试
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    kg = KGIntegration()

    print("\n[KG Stats]")
    stats = kg.get_kg_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n[Recent Opportunities]")
    recent = kg.get_recent_opportunities(limit=5)
    for r in recent:
        print(f"  {r.get('name', 'unknown')}: score={r.get('alpha_score', 0)}")
