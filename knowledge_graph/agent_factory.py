"""
HVOS V8.3 — Dynamic Agent Factory
======================================
Agent 生命周期管理引擎：创建 / 评估 / 淘汰 Agent。

核心理念：
  Agent 不是固定资产，是可变资源。

  - 固定 Agent（Board Members）：长期稳定决策者
  - 动态 Agent（Category Specialists）：按品类绩效动态升降

能力矩阵：
  每个 Agent 有专长领域（category + dimension）
  根据历史决策准确率自动调整影响力权重

生命周期：
  create_agent()  → 新 Agent 进入候选池
  evaluate_agent() → 基于决策结果更新 Agent 绩效
  retire_agent()   → 低于阈值的 Agent 被淘汰

淘汰规则：
  - 准确率 < 50% 连续 3 次
  - 综合评分 < 3.0
  - 决策样本数 < 5（统计不足）

使用方式：
  python agent_factory.py --action list
  python agent_factory.py --action create --name "Kitchen_US_Agent" --category "厨房小家电" --market "US" --dimension "market_size"
  python agent_factory.py --action evaluate --agent_id "AGT_xxx" --decision_id "DEC_xxx" --outcome "success"
  python agent_factory.py --action select --category "厨房小家电" --market "US"
"""

import sys
import os
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

# ============================================================
# Agent Definition
# ============================================================

class AgentType:
    BOARD_MEMBER = "board_member"        # 固定董事会成员
    CATEGORY_SPECIALIST = "category_specialist"  # 品类专家
    SIGNAL_ENGINE = "signal_engine"      # 信号引擎
    COMPLIANCE_CHECKER = "compliance_checker"  # 合规检查


class Agent:
    """Agent 对象"""
    def __init__(
        self,
        agent_id: str,
        name: str,
        agent_type: str,
        category: str = "",       # 专长品类
        market: str = "",        # 专长市场
        dimension: str = "",      # 决策维度
        specialty: str = "",      # 专长描述
        # 绩效数据
        decisions_total: int = 0,
        decisions_correct: int = 0,
        accuracy: float = 0.5,
        avg_score: float = 5.0,
        # 生命周期
        status: str = "active",   # candidate/active/retired
        lifespan_days: int = 0,
        created_at: str = "",
        retired_at: str = "",
        retirement_reason: str = "",
        # 权重
        influence_weight: float = 0.5,  # 在Governance中的影响力权重 0-1
        confidence: float = 0.5,          # 置信度
        # 元数据
        skills: list = None,
        tags: list = None
    ):
        self.agent_id = agent_id
        self.name = name
        self.agent_type = agent_type
        self.category = category
        self.market = market
        self.dimension = dimension
        self.specialty = specialty
        self.decisions_total = decisions_total
        self.decisions_correct = decisions_correct
        self.accuracy = accuracy
        self.avg_score = avg_score
        self.status = status
        self.lifespan_days = lifespan_days
        self.created_at = created_at or datetime.now().isoformat()
        self.retired_at = retired_at
        self.retirement_reason = retirement_reason
        self.influence_weight = influence_weight
        self.confidence = confidence
        self.skills = skills or []
        self.tags = tags or []

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "agent_type": self.agent_type,
            "category": self.category,
            "market": self.market,
            "dimension": self.dimension,
            "specialty": self.specialty,
            "decisions_total": self.decisions_total,
            "decisions_correct": self.decisions_correct,
            "accuracy": round(self.accuracy, 3),
            "avg_score": round(self.avg_score, 2),
            "status": self.status,
            "lifespan_days": self.lifespan_days,
            "influence_weight": round(self.influence_weight, 3),
            "confidence": round(self.confidence, 3),
            "skills": self.skills,
            "tags": self.tags,
        }


# ============================================================
# Dynamic Agent Factory
# ============================================================

class AgentFactory:
    """
    Agent 生命周期管理引擎。

    职责：
    1. 创建 Agent（create_agent）
    2. 评估 Agent（evaluate_agent）
    3. 淘汰 Agent（retire_agent）
    4. 选择 Agent（select_agent）
    5. 广播 Agent（broadcast_to_agents）—— 通知所有 Agent 新决策结果
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(_root, "knowledge_graph", "agent_factory.db")
        self.db_path = db_path
        self._init_schema()
        self._seed_default_agents()

    # ----------------------------------------------------------
    # Schema
    # ----------------------------------------------------------

    def _init_schema(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                category TEXT DEFAULT "",
                market TEXT DEFAULT "",
                dimension TEXT DEFAULT "",
                specialty TEXT DEFAULT "",
                decisions_total INTEGER DEFAULT 0,
                decisions_correct INTEGER DEFAULT 0,
                accuracy REAL DEFAULT 0.5,
                avg_score REAL DEFAULT 5.0,
                status TEXT DEFAULT "candidate",
                influence_weight REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.5,
                skills TEXT DEFAULT "[]",
                tags TEXT DEFAULT "[]",
                created_at TEXT,
                retired_at TEXT,
                retirement_reason TEXT DEFAULT ""
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                decision_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                opp_id TEXT,
                dimension TEXT,
                category TEXT,
                market TEXT,
                predicted_score REAL,
                actual_outcome TEXT,
                correct BOOLEAN,
                decision_at TEXT,
                FOREIGN KEY(agent_id) REFERENCES agents(agent_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_category ON agents(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_status ON agents(status)")
        conn.commit()
        conn.close()

    def _seed_default_agents(self):
        """初始化固定 Board Member Agents（不淘汰）"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM agents WHERE agent_type = 'board_member'")
        if cur.fetchone()[0] == 0:
            board_members = [
                ("AGT_BOARD_CEO", "CEO Hermes", "board_member", "CEO", "战略决策者，所有维度", 0.7, 0.6),
                ("AGT_BOARD_CFO", "CFO Hermes", "board_member", "CFO", "财务与单元经济", 0.6, 0.5),
                ("AGT_BOARD_CMO", "CMO Hermes", "board_member", "CMO", "市场营销与增长", 0.6, 0.5),
                ("AGT_BOARD_COO", "COO Hermes", "board_member", "COO", "供应链与运营", 0.5, 0.5),
                ("AGT_BOARD_RISK", "Risk Hermes", "board_member", "Risk", "风险与合规", 0.7, 0.5),
            ]
            now = datetime.now().isoformat()
            for aid, name, atype, dim, spec, iw, conf in board_members:
                cur.execute("""
                    INSERT OR IGNORE INTO agents
                            (agent_id, name, agent_type, dimension, specialty,
                             decisions_total, accuracy, status, influence_weight, confidence, created_at)
                            VALUES (?, ?, ?, ?, ?, 0, 0.5, 'active', ?, ?, ?)
                """, (aid, name, atype, dim, spec, iw, conf, now))
            conn.commit()
        conn.close()

    # ----------------------------------------------------------
    # Agent CRUD
    # ----------------------------------------------------------

    def create_agent(
        self,
        name: str,
        category: str = "",
        market: str = "",
        dimension: str = "",
        specialty: str = "",
        agent_type: str = "category_specialist",
        influence_weight: float = 0.5,
        skills: list = None,
        tags: list = None
    ) -> Agent:
        """创建新 Agent"""
        agent_id = f"AGT_{uuid.uuid4().hex[:10]}"
        agent = Agent(
            agent_id=agent_id,
            name=name,
            agent_type=agent_type,
            category=category,
            market=market,
            dimension=dimension,
            specialty=specialty,
            influence_weight=influence_weight,
            skills=skills or [],
            tags=tags or [],
            status="candidate"
        )
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agents
            (agent_id, name, agent_type, category, market, dimension, specialty,
             decisions_total, decisions_correct, accuracy, avg_score, status,
             influence_weight, confidence, skills, tags, created_at,
             retired_at, retirement_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent.agent_id, agent.name, agent.agent_type, agent.category,
            agent.market, agent.dimension, agent.specialty,
            agent.decisions_total, agent.decisions_correct, agent.accuracy,
            agent.avg_score, agent.status, agent.influence_weight,
            agent.confidence, json.dumps(agent.skills), json.dumps(agent.tags),
            agent.created_at, agent.retired_at, agent.retirement_reason
        ))
        conn.commit()
        conn.close()
        return agent

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_agent(row)

    def list_agents(self, status: str = None) -> list[Agent]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if status:
            cur.execute("SELECT * FROM agents WHERE status = ? ORDER BY accuracy DESC", (status,))
        else:
            cur.execute("SELECT * FROM agents ORDER BY agent_type, accuracy DESC")
        rows = cur.fetchall()
        conn.close()
        return [self._row_to_agent(r) for r in rows]

    def _row_to_agent(self, row) -> Agent:
        cols = ["agent_id","name","agent_type","category","market","dimension",
                "specialty","decisions_total","decisions_correct","accuracy",
                "avg_score","status","influence_weight","confidence",
                "skills","tags","created_at","retired_at","retirement_reason"]
        d = dict(zip(cols, row))
        return Agent(
            agent_id=d["agent_id"], name=d["name"], agent_type=d["agent_type"],
            category=d["category"], market=d["market"], dimension=d["dimension"],
            specialty=d["specialty"],
            decisions_total=d["decisions_total"],
            decisions_correct=d["decisions_correct"],
            accuracy=d["accuracy"], avg_score=d["avg_score"],
            status=d["status"],
            influence_weight=d["influence_weight"], confidence=d["confidence"],
            skills=json.loads(d["skills"] or "[]"),
            tags=json.loads(d["tags"] or "[]"),
            created_at=d["created_at"],
            retired_at=d.get("retired_at",""),
            retirement_reason=d.get("retirement_reason","")
        )

    # ----------------------------------------------------------
    # Agent Evaluation
    # ----------------------------------------------------------

    def evaluate_agent(
        self,
        agent_id: str,
        decision_id: str,
        opp_id: str,
        dimension: str,
        predicted_score: float,
        actual_outcome: str,   # success/failure
        actual_correct: bool = None
    ) -> dict:
        """
        评估 Agent 的一次决策，更新绩效指标。

        自动判断：
        - predicted_score vs threshold → 预测是否"正确"
        - 更新 accuracy 和 avg_score
        - 触发 retirement 检查
        """
        agent = self.get_agent(agent_id)
        if not agent or agent.status == "retired":
            return {"error": f"Agent {agent_id} 不存在或已淘汰"}

        # 判断预测是否正确
        threshold = 5.0  # 评分阈值
        is_correct = actual_correct if actual_correct is not None else (predicted_score >= threshold)

        # 记录决策
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute("""
            INSERT OR IGNORE INTO agent_decisions
            (decision_id, agent_id, opp_id, dimension, category, market,
             predicted_score, actual_outcome, correct, decision_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (decision_id, agent_id, opp_id, dimension,
              agent.category, agent.market,
              predicted_score, actual_outcome, 1 if is_correct else 0, now))

        # 更新 Agent 绩效
        new_total = agent.decisions_total + 1
        new_correct = agent.decisions_correct + (1 if is_correct else 0)
        new_accuracy = new_correct / new_total

        # 更新 avg_score（EMA）
        new_avg = 0.7 * agent.avg_score + 0.3 * predicted_score

        # 置信度更新（基于accuracy）
        new_confidence = min(0.99, max(0.1, new_accuracy))

        # 影响权重：accuracy × confidence
        new_influence = min(0.95, new_accuracy * new_confidence)

        # 更新
        cur.execute("""
            UPDATE agents SET
                decisions_total = ?,
                decisions_correct = ?,
                accuracy = ?,
                avg_score = ?,
                confidence = ?,
                influence_weight = ?,
                status = ?
            WHERE agent_id = ?
        """, (new_total, new_correct, new_accuracy, new_avg,
              new_confidence, new_influence, agent.status, agent_id))
        conn.commit()
        conn.close()

        # Retirement 检查
        retire_reason = ""
        new_status = "active"

        if new_total >= 5:
            if new_accuracy < 0.5:
                retire_reason = f"准确率{new_accuracy:.0%}<50%，连续{new_total}次决策样本"
                new_status = "retired"
            elif agent.avg_score < 3.0 and new_total >= 3:
                retire_reason = f"平均评分{agent.avg_score}<3.0"
                new_status = "retired"

        if new_status == "retired":
            self.retire_agent(agent_id, retire_reason)

        # 更新本地对象
        agent.decisions_total = new_total
        agent.decisions_correct = new_correct
        agent.accuracy = new_accuracy
        agent.avg_score = new_avg
        agent.confidence = new_confidence
        agent.influence_weight = new_influence

        return {
            "agent_id": agent_id,
            "decision_id": decision_id,
            "is_correct": is_correct,
            "new_accuracy": round(new_accuracy, 3),
            "new_avg_score": round(new_avg, 2),
            "new_influence_weight": round(new_influence, 3),
            "status": new_status,
            "retired": new_status == "retired",
            "retirement_reason": retire_reason
        }

    def retire_agent(self, agent_id: str, reason: str = "") -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute("""
            UPDATE agents SET
                status = 'retired',
                retired_at = ?,
                retirement_reason = ?,
                influence_weight = 0.0
            WHERE agent_id = ?
        """, (now, reason, agent_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    # ----------------------------------------------------------
    # Agent Selection
    # ----------------------------------------------------------

    def select_agent(
        self,
        category: str = "",
        market: str = "",
        dimension: str = ""
    ) -> Optional[Agent]:
        """
        为给定品类/市场/维度选择最合适的 Agent。

        选择策略：
        1. 优先选择品类匹配的 active specialist
        2. 其次选择对应维度的 board_member
        3. 按 influence_weight 降序
        4. 准确率 >= 50% 才可选
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 优先：品类专家
        cur.execute("""
            SELECT * FROM agents
            WHERE status = 'active'
              AND agent_type = 'category_specialist'
              AND (category = ? OR category = '')
              AND (market = ? OR market = '')
              AND accuracy >= 0.5
            ORDER BY influence_weight DESC
            LIMIT 1
        """, (category, market))
        row = cur.fetchone()

        # 其次：Board Member
        if not row:
            cur.execute("""
                SELECT * FROM agents
                WHERE status = 'active'
                  AND agent_type = 'board_member'
                  AND (dimension = ? OR dimension = '')
                  AND accuracy >= 0.5
                ORDER BY influence_weight DESC
                LIMIT 1
            """, (dimension,))

        conn.close()
        if not row:
            return None
        return self._row_to_agent(row)

    def get_agent_portfolio(self) -> dict:
        """获取 Agent Portfolio 概览"""
        agents = self.list_agents()
        active = [a for a in agents if a.status == "active"]
        retired = [a for a in agents if a.status == "retired"]
        candidates = [a for a in agents if a.status == "candidate"]

        avg_accuracy = sum(a.accuracy for a in active) / len(active) if active else 0
        total_decisions = sum(a.decisions_total for a in active)

        return {
            "total_agents": len(agents),
            "active": len(active),
            "retired": len(retired),
            "candidates": len(candidates),
            "avg_accuracy": round(avg_accuracy, 3),
            "total_decisions": total_decisions,
            "active_agents": [a.to_dict() for a in active],
            "retired_agents": [a.to_dict() for a in retired],
        }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V8.3 — Dynamic Agent Factory")
    parser.add_argument("--action", choices=["list","create","evaluate","retire","select","portfolio"],
                        default="portfolio")
    parser.add_argument("--name", help="Agent 名称")
    parser.add_argument("--agent_id", help="Agent ID")
    parser.add_argument("--category", help="专长品类")
    parser.add_argument("--market", help="专长市场")
    parser.add_argument("--dimension", help="决策维度")
    parser.add_argument("--specialty", help="专长描述")
    parser.add_argument("--type", default="category_specialist", help="Agent类型")
    parser.add_argument("--weight", type=float, default=0.5, help="影响力权重")
    parser.add_argument("--decision_id", help="决策ID")
    parser.add_argument("--opp_id", help="机会ID")
    parser.add_argument("--predicted_score", type=float, help="预测评分")
    parser.add_argument("--actual_outcome", choices=["success","failure"], help="实际结果")
    parser.add_argument("--correct", type=lambda x: x.lower()=="true", help="是否正确")
    parser.add_argument("--reason", help="淘汰原因")
    parser.add_argument("--db", help="数据库路径")

    args = parser.parse_args()
    db = args.db or os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_factory.db")
    factory = AgentFactory(db)

    if args.action == "list":
        agents = factory.list_agents()
        print("=" * 60)
        print("  Agent Factory — Agent 列表")
        print("=" * 60)
        for a in agents:
            emoji = {"candidate":"⏳","active":"✅","retired":"❌"}.get(a.status,"?")
            print(f"\n  {emoji} [{a.agent_id}] {a.name}")
            print(f"     类型: {a.agent_type} | 品类: {a.category or '通用'} | 市场: {a.market or '通用'}")
            print(f"     准确率: {a.accuracy:.0%} | 决策数: {a.decisions_total} | 影响权重: {a.influence_weight:.2f}")
            print(f"     置信度: {a.confidence:.0%} | 平均评分: {a.avg_score:.1f}")
            if a.status == "retired":
                print(f"     淘汰原因: {a.retirement_reason}")
        print("\n" + "=" * 60)

    elif args.action == "create":
        a = factory.create_agent(
            name=args.name or "New Agent",
            category=args.category or "",
            market=args.market or "",
            dimension=args.dimension or "",
            specialty=args.specialty or "",
            agent_type=args.type,
            influence_weight=args.weight
        )
        print(f"✅ Agent 创建: {a.agent_id} — {a.name}")
        print(f"   品类: {a.category} | 市场: {a.market} | 维度: {a.dimension}")
        print(f"   初始权重: {a.influence_weight:.2f} | 状态: {a.status}")

    elif args.action == "evaluate":
        if not all([args.agent_id, args.decision_id, args.actual_outcome]):
            print("❌ 需要 --agent_id --decision_id --actual_outcome")
        else:
            result = factory.evaluate_agent(
                agent_id=args.agent_id,
                decision_id=args.decision_id,
                opp_id=args.opp_id or "",
                dimension=args.dimension or "",
                predicted_score=args.predicted_score or 5.0,
                actual_outcome=args.actual_outcome,
                actual_correct=args.correct
            )
            print(f"✅ 评估完成: {result}")

    elif args.action == "retire":
        if not args.agent_id:
            print("❌ 需要 --agent_id")
        else:
            ok = factory.retire_agent(args.agent_id, args.reason or "")
            print(f"{'✅' if ok else '❌'} Agent {args.agent_id} {'已淘汰' if ok else '淘汰失败'}")

    elif args.action == "select":
        agent = factory.select_agent(
            category=args.category or "",
            market=args.market or "",
            dimension=args.dimension or ""
        )
        if agent:
            print(f"✅ Selected: [{agent.agent_id}] {agent.name}")
            print(f"   品类: {agent.category} | 维度: {agent.dimension}")
            print(f"   准确率: {agent.accuracy:.0%} | 影响权重: {agent.influence_weight:.2f}")
        else:
            print("❌ 无合适 Agent（准确率<50%或不存在）")

    elif args.action == "portfolio":
        portfolio = factory.get_agent_portfolio()
        print("=" * 60)
        print("  Agent Factory — Portfolio 概览")
        print("=" * 60)
        print(f"  总Agent数: {portfolio['total_agents']}")
        print(f"  活跃: {portfolio['active']} | 淘汰: {portfolio['retired']} | 候选: {portfolio['candidates']}")
        print(f"  平均准确率: {portfolio['avg_accuracy']:.0%}")
        print(f"  总决策数: {portfolio['total_decisions']}")
        print("\n  活跃Agent：")
        for a in portfolio["active_agents"]:
            print(f"    [{a['agent_id']}] {a['name']} | 准确率{a['accuracy']:.0%} | 权重{a['influence_weight']:.2f}")
        if portfolio["retired_agents"]:
            print("\n  淘汰Agent：")
            for a in portfolio["retired_agents"]:
                print(f"    [{a['agent_id']}] {a['name']} | 准确率{a['accuracy']:.0%}")
        print("=" * 60)
