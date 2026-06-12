"""
HVOS × CausaMem Bridge
=======================
将 CausaMem 因果记忆系统接入 HVOS。

集成架构：
  HVOS Event Bus → event_capture.py → CausaMem L0 raw_events
  HVOS KG Query  → causal_query.py  → CausaMem C6 因果链
  HVOS Evolution → cognitive_anchor  → CausaMem I7 直觉注入
  HVOS Pattern   → pattern_mining   → CausaMem 因果规则

依赖 CausaMem：C:\\Users\\Administrator\\causality-memory
  (git clone https://github.com/MaiHHConnect/MHH-Causality-Memory.git)

Stage 1.5+Integration

Author: HVOS X × CausaMem
Version: 1.0.0
"""

from __future__ import annotations

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 路径配置
# ─────────────────────────────────────────────────────────────────────────────

CAUSAMEM_ROOT = os.path.expanduser("~/causality-memory")
GBRAIN_SCRIPT = os.path.join(CAUSAMEM_ROOT, "scripts", "gbrain", "gbrain.py")
CAUSAMEM_DB = os.path.join(os.path.expanduser("~/gbrain-data"), "brain.db")

# 添加 CausaMem 到 Python 路径（用于直接导入 gbrain 模块）
CAUSAMEM_PYTHON_PATH = os.path.join(CAUSAMEM_ROOT, "scripts")
if CAUSAMEM_PYTHON_PATH not in sys.path:
    sys.path.insert(0, CAUSAMEM_PYTHON_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _get_causamem_db() -> sqlite3.Connection:
    """获取 CausaMem 数据库连接（懒初始化）"""
    os.makedirs(os.path.dirname(CAUSAMEM_DB), exist_ok=True)
    conn = sqlite3.connect(CAUSAMEM_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _slugify(text: str) -> str:
    """将文本转换为 URL-safe slug"""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:80]


# ─────────────────────────────────────────────────────────────────────────────
# L0 事件捕获 — 替代 EventBus 纯内存日志
# ─────────────────────────────────────────────────────────────────────────────

class CausaMemEventCapture:
    """
    将 HVOS Event Bus 事件写入 CausaMem L0 raw_events 表

    用法：
        capture = CausaMemEventCapture()
        capture.capture_hvos_event(
            session_id="hvos_session_001",
            role="agent",
            content="投资决策：向 opp_ai_watch_TK 投入 $3000，预测 ROI 2.1x",
            source="portfolio_manager",
            metadata={
                "event_type": "INVESTMENT_DECISION",
                "opp_id": "opp_ai_watch_TK",
                "amount": 3000,
                "predicted_roi": 2.1,
            }
        )
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CAUSAMEM_DB

    def capture_hvos_event(
        self,
        session_id: str,
        role: str,
        content: str,
        source: str = "hvos",
        metadata: Optional[dict] = None,
    ) -> int:
        """
        捕获 HVOS 事件到 CausaMem L0 raw_events

        Args:
            session_id: 会话 ID
            role: user / assistant / system
            content: 事件内容
            source: HVOS 子系统（portfolio_manager / evolution / rfe 等）
            metadata: 额外元数据

        Returns:
            int: 写入的 raw_event ID
        """
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        cursor = conn.cursor()

        # 确保 raw_events 表存在（CausaMem schema 初始化）
        self._ensure_raw_events_schema(cursor)

        cursor.execute("""
            INSERT INTO raw_events (session_id, role, content, source, metadata, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'raw', ?)
        """, (
            session_id,
            role,
            content,
            source,
            json.dumps(metadata or {}, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ))

        event_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"[CausaMem] Captured L0 event {event_id} from {source}")
        return event_id

    def _ensure_raw_events_schema(self, cursor: sqlite3.Cursor):
        """确保 raw_events 表存在"""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                source TEXT,
                metadata TEXT,
                status TEXT DEFAULT 'raw',
                created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_events_session
            ON raw_events(session_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_raw_events_status
            ON raw_events(status)
        """)

    def capture_decision(
        self,
        session_id: str,
        decision: str,
        reason: str,
        outcome: Optional[str] = None,
        opp_id: Optional[str] = None,
        investment_amount: Optional[float] = None,
    ) -> int:
        """
        捕获投资决策（结构化）

        写入 CausaMem 的结构化字段：cause / effect / decided
        """
        content = f"决定：{decision}\n原因：{reason}"
        if outcome:
            content += f"\n结果：{outcome}"

        metadata = {
            "decision": decision,
            "reason": reason,
            "outcome": outcome,
            "opp_id": opp_id,
            "investment_amount": investment_amount,
            "obs_type": "DECISION",
        }

        return self.capture_hvos_event(
            session_id=session_id,
            role="agent",
            content=content,
            source="hvos_decision",
            metadata=metadata,
        )

    def capture_signal(
        self,
        session_id: str,
        signal_type: str,
        content: str,
        source: str,
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
    ) -> int:
        """捕获市场信号事件"""
        metadata = {
            "signal_type": signal_type,
            "metric_name": metric_name,
            "metric_value": metric_value,
        }
        return self.capture_hvos_event(
            session_id=session_id,
            role="system",
            content=content,
            source=f"signal_{source}",
            metadata=metadata,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 因果查询 — 替代假 causal_reasoner.py
# ─────────────────────────────────────────────────────────────────────────────

class CausaMemCausalQuery:
    """
    查询 CausaMem 因果记忆，回答"为什么"类问题

    用法：
        cq = CausaMemCausalQuery()
        results = cq.query_why("投资失败")
        # → [{"page_id": 1, "cause": "...", "effect": "...", "confidence": 0.85}]
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CAUSAMEM_DB

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        """检查表是否存在"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return cursor.fetchone() is not None

    def query_why(self, question: str, limit: int = 10) -> list[dict]:
        """
        查询"为什么"类问题的因果解释

        搜索含 cause/effect 字段的 pages 和 causal_events
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        events = []
        pages = []

        # 1. 从 causal_events 表查询（时人事因果）
        if self._table_exists(conn, "causal_events"):
            keyword = f"%{question}%"
            cursor.execute("""
                SELECT
                    ce.id,
                    ce.event_time,
                    ce.actor,
                    ce.event,
                    ce.cause,
                    ce.effect,
                    ce.strength,
                    ce.confidence,
                    ce.context,
                    ce.source_slug
                FROM causal_events ce
                WHERE ce.event LIKE ? OR ce.cause LIKE ? OR ce.effect LIKE ?
                ORDER BY ce.confidence DESC, ce.event_time DESC
                LIMIT ?
            """, (keyword, keyword, keyword, limit))
            events = [dict(row) for row in cursor.fetchall()]

        # 2. 从 pages 表查询含因果字段的记忆
        if self._table_exists(conn, "pages"):
            keyword = f"%{question}%"
            cursor.execute("""
                SELECT
                    p.id,
                    p.slug,
                    p.title,
                    p.cause,
                    p.effect,
                    p.summary_struct,
                    p.confidence,
                    p.valid_from,
                    p.valid_until
                FROM pages p
                WHERE (p.cause LIKE ? OR p.effect LIKE ?)
                  AND p.status = 'active'
                ORDER BY p.confidence DESC
                LIMIT ?
            """, (keyword, keyword, limit))
            pages = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return {
            "causal_events": events,
            "pages": pages,
            "total_events": len(events),
            "total_pages": len(pages),
            "question": question,
        }

    def query_what_happened(
        self,
        subject: str,
        limit: int = 10,
    ) -> list[dict]:
        """查询某个主体（opp_id/user_id/brand）发生了什么"""
        conn = self._get_conn()
        cursor = conn.cursor()

        keyword = f"%{subject}%"

        # state_transitions — 状态变化
        cursor.execute("""
            SELECT
                st.id,
                st.subject,
                st.state_key,
                st.before_value,
                st.after_value,
                st.trigger,
                st.reason,
                st.event_time,
                st.confidence
            FROM state_transitions st
            WHERE st.subject LIKE ? OR st.trigger LIKE ?
            ORDER BY st.event_time DESC
            LIMIT ?
        """, (keyword, keyword, limit))

        transitions = [dict(row) for row in cursor.fetchall()]

        # causal_events — 因果事件
        cursor.execute("""
            SELECT
                ce.id, ce.actor, ce.event, ce.cause, ce.effect,
                ce.strength, ce.confidence, ce.event_time
            FROM causal_events ce
            WHERE ce.actor LIKE ? OR ce.event LIKE ?
            ORDER BY ce.event_time DESC
            LIMIT ?
        """, (keyword, keyword, limit))

        events = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return {
            "subject": subject,
            "state_transitions": transitions,
            "causal_events": events,
        }

    def query_beliefs(self, subject: str, limit: int = 8) -> list[dict]:
        """查询信念/规则（如"投资原则"、"选品标准"）"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                cb.id, cb.subject, cb.predicate, cb.value,
                cb.belief_type, cb.status, cb.confidence,
                cb.valid_from, cb.valid_until,
                cb.evidence, cb.contradiction
            FROM causal_beliefs cb
            WHERE cb.subject LIKE ?
              AND cb.status = 'active'
            ORDER BY cb.confidence DESC
            LIMIT ?
        """, (f"%{subject}%", limit))

        beliefs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return beliefs

    def trace_chain(self, keyword: str, depth: int = 2, limit: int = 20) -> list[dict]:
        """
        沿因果边深度追踪

        depth=1: 直接因果邻居
        depth=2: 邻居的邻居
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        results = []

        # 找到初始页面
        cursor.execute("""
            SELECT id, slug, title, cause, effect
            FROM pages
            WHERE cause LIKE ? OR effect LIKE ? OR title LIKE ?
            LIMIT ?
        """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", 5))

        seed_pages = [dict(row) for row in cursor.fetchall()]

        visited = {p["id"] for p in seed_pages}
        frontier = list(seed_pages)

        for _ in range(depth):
            next_frontier = []
            for page in frontier:
                # 找因果出边
                cursor.execute("""
                    SELECT to_page, to_slug, relation_type, strength, evidence
                    FROM causal_edges
                    WHERE from_page = ?
                """, (page["id"],))

                for edge in cursor.fetchall():
                    if edge["to_page"] and edge["to_page"] not in visited:
                        cursor.execute("SELECT * FROM pages WHERE id = ?", (edge["to_page"],))
                        row = cursor.fetchone()
                        if row:
                            next_frontier.append(dict(row))
                            visited.add(edge["to_page"])

            frontier = next_frontier

        conn.close()
        return list(frontier)[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Cognitive Anchor — 推理前锚点注入
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveAnchorBuilder:
    """
    调用 CausaMem build_cognitive_anchor 逻辑

    在 HVOS 推理前注入：
    - 相关事实（R0）
    - 活跃规则（C6）
    - 历史决策（已验证的信念）
    - 用户偏好（Profile）
    - 执行状态（Beads）

    返回结构化的认知锚点，注入到 LLM context
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CAUSAMEM_DB
        self._conn = None

    def build_anchor(self, question: str, limit: int = 5) -> dict:
        """
        构建认知锚点

        Args:
            question: 当前要回答/推理的问题
            limit: 每个维度返回的最大条目数

        Returns:
            {
                "facts": [...],        # R0 现实证据
                "rules": [...],        # C6 因果规则
                "decisions": [...],    # 历史决策
                "preferences": [...],  # Profile 用户偏好
                "state_changes": [...], # 状态变化
                "causal_chains": [...],# 因果链追踪
            }
        """
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        keyword = f"%{question}%"

        # 1. 相关事实（F1 原子事实）
        cursor.execute("""
            SELECT p.id, p.slug, p.title, p.compiled_truth,
                   p.cause, p.effect, p.confidence, p.source
            FROM pages p
            WHERE (p.compiled_truth LIKE ? OR p.title LIKE ?)
              AND p.status = 'active'
            ORDER BY p.confidence DESC
            LIMIT ?
        """, (keyword, keyword, limit))

        facts = [dict(r) for r in cursor.fetchall()]

        # 2. 活跃因果规则（C6）
        cursor.execute("""
            SELECT cb.id, cb.subject, cb.predicate, cb.value,
                   cb.confidence, cb.evidence, cb.valid_from
            FROM causal_beliefs cb
            WHERE cb.status = 'active'
              AND cb.confidence >= 0.6
            ORDER BY cb.confidence DESC
            LIMIT ?
        """, (limit,))

        rules = [dict(r) for r in cursor.fetchall()]

        # 3. 历史决策（decided 字段）
        cursor.execute("""
            SELECT p.slug, p.title, p.decided, p.learned,
                   p.completed, p.next_steps, p.confidence
            FROM pages p
            WHERE p.decided IS NOT NULL
              AND p.decided != ''
              AND p.status = 'active'
            ORDER BY p.updated_at DESC
            LIMIT ?
        """, (limit,))

        decisions = [dict(r) for r in cursor.fetchall()]

        # 4. Profile 用户偏好
        cursor.execute("""
            SELECT profile_type, key, value, confidence, evidence
            FROM profiles
            WHERE confidence >= 0.7
              AND status = 'active'
            ORDER BY confidence DESC
            LIMIT ?
        """, (limit,))

        preferences = [dict(r) for r in cursor.fetchall()]

        # 5. 状态变化
        cursor.execute("""
            SELECT subject, state_key, before_value, after_value,
                   trigger, reason, event_time
            FROM state_transitions
            ORDER BY event_time DESC
            LIMIT ?
        """, (limit,))

        state_changes = [dict(r) for r in cursor.fetchall()]

        # 6. 因果链（从 causal_events）
        cursor.execute("""
            SELECT actor, event, cause, effect, strength,
                   confidence, event_time
            FROM causal_events
            WHERE event LIKE ? OR cause LIKE ?
            ORDER BY confidence DESC
            LIMIT ?
        """, (keyword, keyword, limit))

        causal_chains = [dict(r) for r in cursor.fetchall()]

        conn.close()

        return {
            "question": question,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "facts": facts,
            "rules": rules,
            "decisions": decisions,
            "preferences": preferences,
            "state_changes": state_changes,
            "causal_chains": causal_chains,
            "anchor_stats": {
                "facts_count": len(facts),
                "rules_count": len(rules),
                "decisions_count": len(decisions),
                "preferences_count": len(preferences),
                "state_changes_count": len(state_changes),
                "causal_chains_count": len(causal_chains),
            }
        }

    def format_for_llm(self, anchor: dict) -> str:
        """
        将认知锚点格式化为 LLM 可读的文本

        用于注入到 LLM system prompt 或 context
        """
        lines = [
            "## 认知锚点（Cognitive Anchor）",
            f"生成时间：{anchor['generated_at']}",
            "",
        ]

        if anchor["facts"]:
            lines.append("### 📌 相关事实")
            for f in anchor["facts"][:3]:
                lines.append(f"- **{f['title']}**: {f.get('compiled_truth', '')[:200]}")
            lines.append("")

        if anchor["rules"]:
            lines.append("### ⚙️ 活跃规则")
            for r in anchor["rules"][:3]:
                lines.append(
                    f"- [{r['subject']}] {r['predicate']} {r['value']} "
                    f"(置信度 {r['confidence']:.0%})"
                )
            lines.append("")

        if anchor["decisions"]:
            lines.append("### ✅ 历史决策")
            for d in anchor["decisions"][:3]:
                lines.append(f"- {d.get('decided', '')[:200]}")
            lines.append("")

        if anchor["causal_chains"]:
            lines.append("### 🔗 因果链")
            for c in anchor["causal_chains"][:3]:
                lines.append(
                    f"- {c['actor']}: {c['event']} "
                    f"→ 原因: {c.get('cause', '')[:100]} "
                    f"→ 结果: {c.get('effect', '')[:100]}"
                )
            lines.append("")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 便捷函数
# ─────────────────────────────────────────────────────────────────────────────

def capture_hvos_event(**kwargs) -> int:
    """一行 API：捕获 HVOS 事件"""
    return CausaMemEventCapture().capture_hvos_event(**kwargs)


def query_causal(question: str, **kwargs) -> dict:
    """一行 API：因果查询"""
    return CausaMemCausalQuery().query_why(question, **kwargs)


def build_anchor(question: str) -> dict:
    """一行 API：构建认知锚点"""
    return CognitiveAnchorBuilder().build_anchor(question)


def format_anchor_for_llm(question: str) -> str:
    """一行 API：生成 LLM 可注入的锚点文本"""
    anchor = build_anchor(question)
    return CognitiveAnchorBuilder().format_for_llm(anchor)
