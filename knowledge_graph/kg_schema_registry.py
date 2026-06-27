"""
HVOS Knowledge Graph Schema Registry
====================================
解决 id / node_id / entity_id 混乱问题。

问题背景：
  Event Bus → KG Consumer 写入时，出现了三种 ID：
    - event_id: 事件的唯一标识
    - node_id: KG 节点的内部主键
    - entity_id: 业务实体标识（opp_id / product_id 等）

  混乱原因：
    1. 早期实现混用了这三种 ID
    2. 没有统一 schema 约束
    3. 不同 Event Type 使用不同的 ID 字段

解决方案：
  1. 定义清晰的 ID 体系
  2. 所有 KG 节点使用统一的 node_id 格式
  3. Event 与 KG 节点通过 canonical mapping 关联

ID 体系：
  - event_id:     evt_{uuid12}         # Event Bus 事件唯一ID
  - node_id:      {entity_type}_{canonical_id}  # KG 节点全局唯一ID
  - entity_id:    业务层面的真实ID（opp_id / sku / brand_id 等）
  - canonical_id: 业务ID的规范化版本（用于生成 node_id）

Schema Registry：
  - 记录所有 Entity Type 的字段约束
  - 记录所有 Relation Type 的起点/终点类型
  - 提供 ID 生成和解析工具

Stage 1.5: KG Schema Registry

Author: HVOS X Knowledge Graph
Version: 1.0.0
"""

from __future__ import annotations

import json
import sqlite3
import uuid
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ID 格式定义
# ─────────────────────────────────────────────────────────────────────────────

class EntityType(str, Enum):
    """KG 节点实体类型"""
    PRODUCT = "Product"
    BRAND = "Brand"
    FACTORY = "Factory"
    SUPPLIER = "Supplier"
    INFLUENCER = "Influencer"
    CAMPAIGN = "Campaign"
    CUSTOMER = "Customer"
    COUNTRY = "Country"
    PLATFORM = "Platform"
    HSCODE = "HSCode"
    SHIPMENT = "Shipment"
    CATEGORY = "Category"
    PATTERN = "Pattern"
    POLICY = "Policy"
    BOARD_MEMBER = "BoardMember"
    OPPORTUNITY = "Opportunity"
    INVESTMENT = "Investment"
    EVENT = "Event"           # 映射到 RealityEvent
    SIGNAL = "Signal"         # 映射到 Intelligence Signal


class RelationType(str, Enum):
    """KG 关系类型"""
    MANUFACTURED_BY = "MANUFACTURED_BY"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPLIED_BY = "SUPPLIED_BY"
    PROMOTED_BY = "PROMOTED_BY"
    SHIPPED_TO = "SHIPPED_TO"
    BOUGHT_BY = "BOUGHT_BY"
    RELATED_TO = "RELATED_TO"
    INVESTED_IN = "INVESTED_IN"
    LOCATED_IN = "LOCATED_IN"
    TRACKED_BY = "TRACKED_BY"
    REVIEWED_BY = "REVIEWED_BY"
    APPROVED_BY = "APPROVED_BY"
    REJECTED_BY = "REJECTED_BY"
    FOLLOWS_PATTERN = "FOLLOWS_PATTERN"
    GENERATES_SIGNAL = "GENERATES_SIGNAL"
    BELONGS_TO = "BELONGS_TO"
    PART_OF = "PART_OF"
    TRIGGERS = "TRIGGERS"
    RECEIVED = "RECEIVED"


@dataclass
class CanonicalID:
    """
    规范化 ID 生成器

    规则：
    - 去除特殊字符
    - 小写化
    - 空格替换为下划线
    - 截断到合理长度
    """
    original: str
    canonical: str
    entity_type: EntityType

    @staticmethod
    def normalize(entity_id: str) -> str:
        """将任意业务ID规范化为canonical形式"""
        # 去除协议前缀（如 https://, woo:)
        if "://" in entity_id:
            entity_id = entity_id.split("://", 1)[1]
        # 去除特殊字符，只保留字母数字下划线
        canonical = "".join(
            c if c.isalnum() else "_" for c in entity_id.lower()
        )
        # 折叠连续下划线
        while "__" in canonical:
            canonical = canonical.replace("__", "_")
        return canonical.strip("_")

    @classmethod
    def make(cls, entity_type: EntityType, entity_id: str) -> "CanonicalID":
        """创建规范化ID"""
        canonical = cls.normalize(entity_id)
        return cls(original=entity_id, canonical=canonical, entity_type=entity_type)

    def to_node_id(self) -> str:
        """生成 KG 节点全局唯一ID"""
        return f"{self.entity_type.value}_{self.canonical}"

    def to_event_id(self) -> str:
        """生成 Event ID"""
        return f"evt_{hashlib.sha256(self.original.encode()).hexdigest()[:12]}"


# ─────────────────────────────────────────────────────────────────────────────
# Schema 定义
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EntitySchema:
    """实体类型 Schema 定义"""
    name: EntityType
    required_fields: list[str]
    optional_fields: list[str]
    id_field: str          # 主键字段名
    id_prefix: str         # ID 前缀（如 opp_, prod_）
    description: str = ""

    def validate(self, data: dict) -> tuple[bool, list[str]]:
        """验证数据是否符合 Schema"""
        errors = []
        for field in self.required_fields:
            if field not in data or data[field] is None:
                errors.append(f"Missing required field: {field}")
        return len(errors) == 0, errors

    def generate_id(self, data: dict) -> str:
        """根据数据生成标准 node_id"""
        id_value = data.get(self.id_field, "")
        if not id_value:
            # 如果没有ID字段，用 name 或第一个字段
            id_value = data.get("name", data.get("opp_id", str(uuid.uuid4())[:8]))
        canonical = CanonicalID.normalize(str(id_value))
        return f"{self.id_prefix}{canonical}"


ENTITY_SCHEMAS: dict[EntityType, EntitySchema] = {
    EntityType.OPPORTUNITY: EntitySchema(
        name=EntityType.OPPORTUNITY,
        id_field="opp_id",
        id_prefix="opp_",
        required_fields=["opp_id", "name"],
        optional_fields=["category", "country", "hs_code", "status", "board_decision"],
        description="商机节点，代表一个被追踪的DTC产品机会",
    ),
    EntityType.INVESTMENT: EntitySchema(
        name=EntityType.INVESTMENT,
        id_field="inv_id",
        id_prefix="inv_",
        required_fields=["inv_id", "opp_id"],
        optional_fields=["pool_type", "amount", "predicted_roi", "actual_roi", "status"],
        description="投资节点，代表对一个Opportunity的资金投入",
    ),
    EntityType.PRODUCT: EntitySchema(
        name=EntityType.PRODUCT,
        id_field="sku",
        id_prefix="prod_",
        required_fields=["sku"],
        optional_fields=["name", "category", "brand", "price", "cost"],
        description="产品节点",
    ),
    EntityType.CAMPAIGN: EntitySchema(
        name=EntityType.CAMPAIGN,
        id_field="campaign_id",
        id_prefix="camp_",
        required_fields=["campaign_id"],
        optional_fields=["name", "platform", "status", "spend", "revenue"],
        description="营销活动节点",
    ),
    EntityType.PATTERN: EntitySchema(
        name=EntityType.PATTERN,
        id_field="pattern_id",
        id_prefix="pat_",
        required_fields=["pattern_id", "type"],
        optional_fields=["description", "success_rate", "category"],
        description="成功/失败模式节点",
    ),
    EntityType.BOARD_MEMBER: EntitySchema(
        name=EntityType.BOARD_MEMBER,
        id_field="member_id",
        id_prefix="board_",
        required_fields=["member_id", "name"],
        optional_fields=["role", "votes_cast", "decisions_made"],
        description="董事会成员节点",
    ),
    EntityType.EVENT: EntitySchema(
        name=EntityType.EVENT,
        id_field="event_id",
        id_prefix="evt_",
        required_fields=["event_id", "source", "event_type"],
        optional_fields=["timestamp", "metric_name", "metric_value", "severity"],
        description="事件节点，映射RealityEvent到KG",
    ),
    EntityType.SIGNAL: EntitySchema(
        name=EntityType.SIGNAL,
        id_field="signal_id",
        id_prefix="sig_",
        required_fields=["signal_id", "type"],
        optional_fields=["source", "strength", "description"],
        description="信号节点，代表市场 Intelligence Signal",
    ),
}


@dataclass
class RelationSchema:
    """关系类型 Schema 定义"""
    name: RelationType
    from_types: list[EntityType]   # 允许的起点类型
    to_types: list[EntityType]     # 允许的终点类型
    description: str = ""

    def validate(self, from_type: EntityType, to_type: EntityType) -> bool:
        """验证关系是否符合 Schema"""
        return from_type in self.from_types and to_type in self.to_types


RELATION_SCHEMAS: dict[RelationType, RelationSchema] = {
    RelationType.INVESTED_IN: RelationSchema(
        name=RelationType.INVESTED_IN,
        from_types=[EntityType.BOARD_MEMBER, EntityType.PLATFORM],
        to_types=[EntityType.OPPORTUNITY, EntityType.INVESTMENT],
        description="BoardMember 或 Platform 对 Opportunity/Investment 进行了投资",
    ),
    RelationType.BELONGS_TO: RelationSchema(
        name=RelationType.BELONGS_TO,
        from_types=[EntityType.PRODUCT, EntityType.CAMPAIGN, EntityType.INVESTMENT],
        to_types=[EntityType.CATEGORY, EntityType.PLATFORM],
        description="产品/活动/投资属于某个品类或平台",
    ),
    RelationType.PART_OF: RelationSchema(
        name=RelationType.PART_OF,
        from_types=[EntityType.PRODUCT, EntityType.CAMPAIGN],
        to_types=[EntityType.CATEGORY],
        description="产品是品类的一部分",
    ),
    RelationType.FOLLOWS_PATTERN: RelationSchema(
        name=RelationType.FOLLOWS_PATTERN,
        from_types=[EntityType.OPPORTUNITY, EntityType.INVESTMENT],
        to_types=[EntityType.PATTERN],
        description="投资决策遵循某个成功/失败模式",
    ),
    RelationType.TRIGGERS: RelationSchema(
        name=RelationType.TRIGGERS,
        from_types=[EntityType.SIGNAL, EntityType.EVENT],
        to_types=[EntityType.OPPORTUNITY, EntityType.INVESTMENT],
        description="信号或事件触发了一个机会或投资",
    ),
    RelationType.GENERATES_SIGNAL: RelationSchema(
        name=RelationType.GENERATES_SIGNAL,
        from_types=[EntityType.OPPORTUNITY, EntityType.PRODUCT],
        to_types=[EntityType.SIGNAL],
        description="机会或产品产生了一个市场信号",
    ),
    RelationType.RECEIVED: RelationSchema(
        name=RelationType.RECEIVED,
        from_types=[EntityType.INVESTMENT],
        to_types=[EntityType.EVENT],
        description="投资收到了某个事件（如订单、退款）",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Schema Registry — 主类
# ─────────────────────────────────────────────────────────────────────────────

class KGSchemaRegistry:
    """
    KG Schema Registry — 统一管理 KG 的实体和关系定义

    核心职责：
    1. 提供 ID 生成和解析工具
    2. 验证实体/关系是否符合 Schema
    3. 维护 Schema 版本历史
    4. 导出 Schema 文档
    """

    VERSION = "1.0.0"

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: KG 数据库路径，默认使用 kg.db
        """
        import os
        if db_path is None:
            hvos_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(hvos_root, "knowledge_graph", "kg.db")
        self.db_path = db_path
        self._ensure_schema_tables()

    # ─────────────────────────────────────────────────────────────────────
    # ID 工具
    # ─────────────────────────────────────────────────────────────────────

    def generate_node_id(self, entity_type: EntityType, entity_id: str) -> str:
        """
        生成标准化的 KG 节点 ID

        Args:
            entity_type: 实体类型
            entity_id: 业务层面的实体ID

        Returns:
            str: 标准 node_id，格式为 {prefix}_{canonical_id}

        Example:
            registry.generate_node_id(EntityType.OPPORTUNITY, "opp_123")
            # → "opp_123"
        """
        canonical = CanonicalID.normalize(entity_id)
        schema = ENTITY_SCHEMAS.get(entity_type)
        prefix = schema.id_prefix if schema else entity_type.value.lower()[:4] + "_"
        return f"{prefix}{canonical}"

    def parse_node_id(self, node_id: str) -> tuple[EntityType, str]:
        """
        解析 node_id 为实体类型和原始ID

        Args:
            node_id: 标准 node_id

        Returns:
            tuple[EntityType, str]: (实体类型, 原始ID)
        """
        for et in EntityType:
            prefix = ENTITY_SCHEMAS.get(et, EntitySchema(
                name=et, id_field="id", id_prefix=et.value[:4].lower() + "_",
                required_fields=[], optional_fields=[]
            )).id_prefix
            if node_id.startswith(prefix):
                canonical = node_id[len(prefix):]
                return et, canonical
        # 找不到匹配，返回默认
        return EntityType.OPPORTUNITY, node_id

    def make_event_node_id(self, event_id: str, source: str, event_type: str) -> str:
        """
        生成事件节点的标准 ID

        Args:
            event_id: Event Bus 中的事件ID
            source: 事件来源（woo/meta/tiktok）
            event_type: 事件类型

        Returns:
            str: 格式为 evt_{source}_{hash}
        """
        combined = f"{source}:{event_type}:{event_id}"
        short_hash = hashlib.sha256(combined.encode()).hexdigest()[:10]
        return f"evt_{source}_{short_hash}"

    # ─────────────────────────────────────────────────────────────────────
    # Schema 验证
    # ─────────────────────────────────────────────────────────────────────

    def validate_entity(
        self,
        entity_type: EntityType,
        data: dict,
    ) -> tuple[bool, list[str]]:
        """
        验证实体数据是否符合 Schema

        Returns:
            (是否有效, 错误列表)
        """
        schema = ENTITY_SCHEMAS.get(entity_type)
        if not schema:
            return True, []  # 未知类型，不验证
        return schema.validate(data)

    def validate_relation(
        self,
        relation_type: RelationType,
        from_node_id: str,
        to_node_id: str,
    ) -> tuple[bool, str]:
        """
        验证关系是否符合 Schema

        Returns:
            (是否有效, 错误消息)
        """
        schema = RELATION_SCHEMAS.get(relation_type)
        if not schema:
            return True, ""  # 未知关系类型，不验证

        from_type, _ = self.parse_node_id(from_node_id)
        to_type, _ = self.parse_node_id(to_node_id)

        if not schema.validate(from_type, to_type):
            return False, (
                f"Invalid relation {relation_type.value}: "
                f"{from_type.value} → {to_type.value}. "
                f"Allowed: {[t.value for t in schema.from_types]} → "
                f"{[t.value for t in schema.to_types]}"
            )
        return True, ""

    # ─────────────────────────────────────────────────────────────────────
    # 数据库 Schema 版本管理
    # ─────────────────────────────────────────────────────────────────────

    def _ensure_schema_tables(self):
        """创建 Schema 版本记录表"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Schema 版本记录
        c.execute("""
            CREATE TABLE IF NOT EXISTS kg_schema_versions (
                version TEXT PRIMARY KEY,
                applied_at TEXT,
                changelog TEXT
            )
        """)

        # ID 映射表（解决历史数据中的 ID 混乱）
        c.execute("""
            CREATE TABLE IF NOT EXISTS kg_id_mappings (
                canonical_id TEXT PRIMARY KEY,
                entity_type TEXT,
                original_ids TEXT,          -- JSON array of alternative IDs
                node_id TEXT UNIQUE,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # 实体定义表（严格 Schema）
        c.execute("""
            CREATE TABLE IF NOT EXISTS kg_entity_definitions (
                entity_type TEXT PRIMARY KEY,
                required_fields TEXT,       -- JSON array
                optional_fields TEXT,        -- JSON array
                id_field TEXT,
                id_prefix TEXT,
                description TEXT
            )
        """)

        # 关系定义表
        c.execute("""
            CREATE TABLE IF NOT EXISTS kg_relation_definitions (
                relation_type TEXT PRIMARY KEY,
                from_types TEXT,            -- JSON array
                to_types TEXT,              -- JSON array
                description TEXT
            )
        """)

        conn.commit()
        conn.close()

        # 如果表为空，初始化当前 Schema
        self._init_current_schema()

    def _init_current_schema(self):
        """将当前 Schema 写入数据库"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # 检查是否已初始化
        c.execute("SELECT COUNT(*) FROM kg_entity_definitions")
        if c.fetchone()[0] > 0:
            conn.close()
            return

        now = datetime.now(timezone.utc).isoformat()

        for et, schema in ENTITY_SCHEMAS.items():
            c.execute("""
                INSERT OR REPLACE INTO kg_entity_definitions
                (entity_type, required_fields, optional_fields, id_field, id_prefix, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                et.value,
                json.dumps(schema.required_fields),
                json.dumps(schema.optional_fields),
                schema.id_field,
                schema.id_prefix,
                schema.description,
            ))

        for rt, schema in RELATION_SCHEMAS.items():
            c.execute("""
                INSERT OR REPLACE INTO kg_relation_definitions
                (relation_type, from_types, to_types, description)
                VALUES (?, ?, ?, ?)
            """, (
                rt.value,
                json.dumps([t.value for t in schema.from_types]),
                json.dumps([t.value for t in schema.to_types]),
                schema.description,
            ))

        c.execute("""
            INSERT OR REPLACE INTO kg_schema_versions (version, applied_at, changelog)
            VALUES (?, ?, ?)
        """, (self.VERSION, now, "Initial schema for Stage 1.5"))

        conn.commit()
        conn.close()

    def register_id_mapping(
        self,
        canonical_id: str,
        entity_type: EntityType,
        original_ids: list[str],
        node_id: Optional[str] = None,
    ):
        """
        注册 ID 映射（用于修复历史数据中的 ID 混乱）

        将多个历史 ID 映射到一个规范的 node_id
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        if node_id is None:
            node_id = self.generate_node_id(entity_type, canonical_id)

        c.execute("""
            INSERT OR REPLACE INTO kg_id_mappings
            (canonical_id, entity_type, original_ids, node_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            canonical_id,
            entity_type.value,
            json.dumps(original_ids),
            node_id,
            now,
            now,
        ))

        conn.commit()
        conn.close()

    def resolve_node_id(self, any_id: str) -> Optional[str]:
        """
        将任意 ID（可能是 event_id / node_id / entity_id）解析为标准 node_id

        Args:
            any_id: 任意形式的 ID

        Returns:
            str: 标准 node_id，如果无法解析则返回 None
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # 1. 直接查询是否是 node_id
        c.execute("SELECT node_id FROM kg_id_mappings WHERE node_id = ?", (any_id,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[0]

        # 2. 查询是否是 canonical_id
        c.execute("SELECT node_id FROM kg_id_mappings WHERE canonical_id = ?", (any_id,))
        row = c.fetchone()
        if row:
            conn.close()
            return row[0]

        # 3. 查询是否是原始 ID
        c.execute("SELECT node_id, original_ids FROM kg_id_mappings")
        for row in c.fetchall():
            node_id, original_ids = row
            if any_id in json.loads(original_ids):
                conn.close()
                return node_id

        conn.close()
        return None

    # ─────────────────────────────────────────────────────────────────────
    # Schema 导出
    # ─────────────────────────────────────────────────────────────────────

    def export_schema(self) -> dict:
        """导出完整 Schema 文档"""
        return {
            "version": self.VERSION,
            "entity_types": {
                et.value: {
                    "required_fields": schema.required_fields,
                    "optional_fields": schema.optional_fields,
                    "id_field": schema.id_field,
                    "id_prefix": schema.id_prefix,
                    "description": schema.description,
                }
                for et, schema in ENTITY_SCHEMAS.items()
            },
            "relation_types": {
                rt.value: {
                    "from_types": [t.value for t in schema.from_types],
                    "to_types": [t.value for t in schema.to_types],
                    "description": schema.description,
                }
                for rt, schema in RELATION_SCHEMAS.items()
            },
            "id_format": {
                "event_id": "evt_{hash12}",
                "node_id": "{prefix}_{canonical_id}",
                "canonical_id": "lowercase_alphanumeric_underscore",
            },
        }

    def print_schema(self):
        """打印 Schema 文档到控制台"""
        schema = self.export_schema()
        print("=== KG Schema Registry ===")
        print(f"Version: {schema['version']}")
        print(f"\nID Format:")
        for k, v in schema["id_format"].items():
            print(f"  {k}: {v}")

        print(f"\nEntity Types ({len(schema['entity_types'])}):")
        for name, defn in schema["entity_types"].items():
            print(f"  [{name}]")
            print(f"    ID: {defn['id_prefix']}... (field: {defn['id_field']})")
            print(f"    Required: {', '.join(defn['required_fields'])}")
            print(f"    Optional: {', '.join(defn['optional_fields'])}")

        print(f"\nRelation Types ({len(schema['relation_types'])}):")
        for name, defn in schema["relation_types"].items():
            print(f"  {name}: {' | '.join(defn['from_types'])} → {' | '.join(defn['to_types'])}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HVOS KG Schema Registry")
    parser.add_argument("--action", required=True,
                        choices=["export", "validate", "register", "resolve", "print"])
    parser.add_argument("--entity-type")
    parser.add_argument("--entity-id")
    parser.add_argument("--data", help="JSON data for validation")
    parser.add_argument("--original-ids", help="Comma-separated original IDs")
    args = parser.parse_args()

    registry = KGSchemaRegistry()

    if args.action == "print":
        registry.print_schema()

    elif args.action == "export":
        print(json.dumps(registry.export_schema(), indent=2))

    elif args.action == "validate":
        import json
        if not args.entity_type or not args.data:
            print("ERROR: --entity-type and --data required")
            return
        entity_type = EntityType(args.entity_type)
        data = json.loads(args.data)
        valid, errors = registry.validate_entity(entity_type, data)
        if valid:
            print(f"✅ {entity_type.value} data is valid")
        else:
            print(f"❌ Validation failed:")
            for err in errors:
                print(f"   - {err}")

    elif args.action == "register":
        if not args.entity_type or not args.entity_id:
            print("ERROR: --entity-type and --entity-id required")
            return
        entity_type = EntityType(args.entity_type)
        original_ids = args.original_ids.split(",") if args.original_ids else [args.entity_id]
        node_id = registry.generate_node_id(entity_type, args.entity_id)
        registry.register_id_mapping(
            CanonicalID.normalize(args.entity_id),
            entity_type,
            original_ids,
            node_id,
        )
        print(f"✅ Registered: {args.entity_id} → {node_id}")

    elif args.action == "resolve":
        if not args.entity_id:
            print("ERROR: --entity-id required")
            return
        node_id = registry.resolve_node_id(args.entity_id)
        if node_id:
            print(f"→ {node_id}")
        else:
            print(f"❌ Cannot resolve: {args.entity_id}")


if __name__ == "__main__":
    main()
