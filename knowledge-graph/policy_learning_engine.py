"""
HVOS V8.2 — Policy Learning Engine
=====================================
核心职责：从 Strategy Library 的经验模式，自动生成 Governance Policy，
           提交 Governance 审批，通过后全系统生效。

Policy Learning vs Weight Learning：
  Weight Learning  → 调参数（机器学习）
  Policy Learning → 生成规则（组织学习）

闭环流程：
  Strategy Library (patterns)
    ↓ PolicyGenerator
  Pending Policies
    ↓ GovernanceEngine.approve()
  Active Policies (binding rules)
    ↓
  Opportunity Assessment (查询Policy辅助决策)
    ↓
  Governance Engine (Policy作为评分维度之一)
    ↓
  Better decisions → New outcomes
    ↓
  Strategy Memory (feedback)
    ↓
  Flywheel CLOSED

使用方式：
  python policy_learning_engine.py --action scan        # 扫描策略库，生成候选Policy
  python policy_learning_engine.py --action approve --policy_id POL_xxx  # 审批Policy
  python policy_learning_engine.py --action list --status active         # 列出活跃Policy
  python policy_learning_engine.py --action evaluate --opp_id opp_xxx  # 用Policy评估机会
"""

import sys
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

# ============================================================
# Policy Types
# ============================================================

class PolicyType:
    """Policy 维度"""
    CHANNEL      = "channel"       # 渠道策略：TikTok优先/Meta禁入
    MARKET_ENTRY  = "market_entry"   # 入市时机：Q4提前6周
    PRICING       = "pricing"        # 定价规则：毛利率≥35%
    COMPLIANCE    = "compliance"     # 合规规则：FCC必过/COPPA禁入
    SUPPLY        = "supply"         # 供应链规则：MOQ分批
    CREATIVE      = "creative"       # 内容策略：UGC来源/TikTok风格


# ============================================================
# Policy Definition
# ============================================================

class Policy:
    """Policy 对象"""
    def __init__(
        self,
        policy_id: str,
        name: str,
        policy_type: str,
        description: str,
        trigger_conditions: dict,   # 触发条件：{category, market, signal}
        governance_rule: dict,        # 治理规则：{dimension, score_adjustment, threshold}
        confidence: float,
        source_strategy_ids: list,
        status: str = "pending",   # pending/approved/rejected/active
        approved_by: str = "",
        approved_at: str = "",
        notes: str = ""
    ):
        self.policy_id = policy_id
        self.name = name
        self.policy_type = policy_type
        self.description = description
        self.trigger_conditions = trigger_conditions
        self.governance_rule = governance_rule
        self.confidence = confidence
        self.source_strategy_ids = source_strategy_ids
        self.status = status
        self.approved_by = approved_by
        self.approved_at = approved_at
        self.notes = notes

    def to_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "policy_type": self.policy_type,
            "description": self.description,
            "trigger_conditions": self.trigger_conditions,
            "governance_rule": self.governance_rule,
            "confidence": self.confidence,
            "source_strategy_ids": self.source_strategy_ids,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "notes": self.notes
        }


# ============================================================
# Policy Learning Engine
# ============================================================

class PolicyLearningEngine:
    """
    Policy 学习引擎：扫描策略库，生成候选 Policy，提交 Governance 审批。
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge-graph\strategy_memory.db"
        self.db_path = db_path

    # ----------------------------------------------------------
    # Policy Generation
    # ----------------------------------------------------------

    def scan_and_generate(self) -> list[Policy]:
        """
        扫描 Strategy Library，生成候选 Policy。

        Policy 生成规则：

        1. CHANNEL Policy
           条件：同一品类+渠道+outcome=success ≥ 2次
           规则：增加该渠道评分

        2. COMPLIANCE Policy
           条件：品类+合规风险触发 REJECT
           规则：该品类+风险组合 = 自动 REJECT

        3. PRICING Policy
           条件：品类+定价规则+outcome=success
           规则：毛利率门槛写入评估维度

        4. MARKET_ENTRY Policy
           条件：品类+Q4+outcome=success
           规则：Q4前6周启动作为评分加分项
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        policies: list[Policy] = []

        # ---- 1. 合规 Policy（最强规则）----
        cur.execute("""
            SELECT category, market, COUNT(*) as cnt, AVG(confidence) as conf
            FROM strategy_library
            WHERE strategy_type = 'compliance'
              AND verdict = 'REJECT'
              AND outcome = 'failure'
            GROUP BY category, market
            HAVING cnt >= 1
            ORDER BY cnt DESC, conf DESC
        """)
        for row in cur.fetchall():
            cat, market, cnt, conf = row
            pid = f"POL_{uuid.uuid4().hex[:8]}"
            policy = Policy(
                policy_id=pid,
                name=f"{cat}/{market} 合规风险 Policy",
                policy_type=PolicyType.COMPLIANCE,
                description=(
                    f"{cat}品类在{market}市场曾因合规问题导致REJECT，"
                    f"该品类若涉及相关合规风险自动提升风险评分"
                ),
                trigger_conditions={
                    "category": cat,
                    "market": market,
                    "risk_keywords": ["COPPA", "FCC", "Prop65", "FDA", "儿童", "GPS"]
                },
                governance_rule={
                    "dimension": "compliance_risk",
                    "score_adjustment": -2.0,  # 降低合规评分
                    "threshold": 5.0,            # 若原评分<5则直接触发REJECT
                    "auto_reject": True          # 强制REJECT条件
                },
                confidence=min(conf + 0.1, 0.99),
                source_strategy_ids=[]
            )
            policies.append(policy)

        # ---- 2. 渠道 Policy（成功模式）----
        cur.execute("""
            SELECT category, market, COUNT(*) as cnt, AVG(confidence) as conf,
                   SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) as success_cnt
            FROM strategy_library
            WHERE strategy_type = 'channel'
            GROUP BY category, market
            HAVING cnt >= 1 AND success_cnt >= 1
            ORDER BY success_cnt DESC, conf DESC
        """)
        for row in cur.fetchall():
            cat, market, cnt, conf, success_cnt = row
            pid = f"POL_{uuid.uuid4().hex[:8]}"
            policy = Policy(
                policy_id=pid,
                name=f"{cat}/{market} 渠道策略 Policy",
                policy_type=PolicyType.CHANNEL,
                description=(
                    f"{cat}品类在{market}市场{success_cnt}次成功经验表明，"
                    f"自然流量+UGC是核心驱动，应降低付费广告依赖"
                ),
                trigger_conditions={
                    "category": cat,
                    "market": market,
                    "prefer_channel": "TikTok",
                    "avoid_channel": "Meta"
                },
                governance_rule={
                    "dimension": "market_size",
                    "score_adjustment": +0.5,
                    "note": f"成功{success_cnt}次，置信度{conf:.0%}"
                },
                confidence=min(conf, 0.95),
                source_strategy_ids=[]
            )
            policies.append(policy)

        # ---- 3. 定价 Policy（毛利率门槛）----
        cur.execute("""
            SELECT category, market, COUNT(*) as cnt,
                   AVG(CASE WHEN outcome='success' THEN confidence ELSE NULL END) as conf
            FROM strategy_library
            WHERE strategy_type = 'pricing'
            GROUP BY category, market
            HAVING conf IS NOT NULL
            ORDER BY conf DESC
        """)
        for row in cur.fetchall():
            cat, market, cnt, conf = row
            pid = f"POL_{uuid.uuid4().hex[:8]}"
            policy = Policy(
                policy_id=pid,
                name=f"{cat}/{market} 定价策略 Policy",
                policy_type=PolicyType.PRICING,
                description=(
                    f"{cat}品类定价应保持毛利率≥35%，"
                    f"低于此线产品通过CFO Math Veto概率高"
                ),
                trigger_conditions={
                    "category": cat,
                    "market": market
                },
                governance_rule={
                    "dimension": "unit_economics",
                    "score_adjustment": 0,  # 不调评分，只记录规则
                    "margin_threshold": 0.35,
                    "note": "毛利率≥35%为硬门槛"
                },
                confidence=min(conf or 0.6, 0.95),
                source_strategy_ids=[]
            )
            policies.append(policy)

        # ---- 4. 入市时机 Policy（Q4季节性）----
        cur.execute("""
            SELECT category, market, COUNT(*) as cnt, AVG(confidence) as conf
            FROM strategy_library
            WHERE strategy_type = 'entry'
              AND outcome = 'success'
            GROUP BY category, market
            HAVING cnt >= 1
            ORDER BY conf DESC
        """)
        for row in cur.fetchall():
            cat, market, cnt, conf = row
            pid = f"POL_{uuid.uuid4().hex[:8]}"
            policy = Policy(
                policy_id=pid,
                name=f"{cat}/{market} Q4旺季入市 Policy",
                policy_type=PolicyType.MARKET_ENTRY,
                description=(
                    f"{cat}品类在Q4旺季表现强劲，"
                    f"建议提前6-8周启动备货和广告热身"
                ),
                trigger_conditions={
                    "category": cat,
                    "market": market,
                    "seasonal": "Q4"
                },
                governance_rule={
                    "dimension": "market_size",
                    "score_adjustment": +1.0,
                    "launch_timing": "Q4_start_minus_6_weeks",
                    "note": "Q4前6周启动为最佳时机"
                },
                confidence=min(conf, 0.95),
                source_strategy_ids=[]
            )
            policies.append(policy)

        conn.close()
        return policies

    # ----------------------------------------------------------
    # Policy Storage
    # ----------------------------------------------------------

    def save_policy(self, policy: Policy) -> bool:
        """将 Policy 写入数据库"""
        import time
        for attempt in range(5):
            conn = None
            try:
                conn = sqlite3.connect(self.db_path, timeout=15)
                conn.execute("PRAGMA busy_timeout = 10000")
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO governance_policies
                    (policy_id, name, policy_type, description,
                     trigger_conditions, governance_rule,
                     confidence, source_strategy_ids,
                     status, approved_by, approved_at, notes,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    policy.policy_id, policy.name, policy.policy_type,
                    policy.description,
                    json.dumps(policy.trigger_conditions, ensure_ascii=False),
                    json.dumps(policy.governance_rule, ensure_ascii=False),
                    policy.confidence,
                    json.dumps(policy.source_strategy_ids),
                    policy.status, policy.approved_by, policy.approved_at,
                    policy.notes,
                    datetime.now().isoformat(), datetime.now().isoformat()
                ))
                conn.commit()
                return True
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

    def get_policy(self, policy_id: str) -> Optional[Policy]:
        """查询 Policy"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT policy_id, name, policy_type, description,
                   trigger_conditions, governance_rule,
                   confidence, source_strategy_ids,
                   status, approved_by, approved_at, notes
            FROM governance_policies
            WHERE policy_id = ?
        """, (policy_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return Policy(
            policy_id=row[0], name=row[1], policy_type=row[2],
            description=row[3],
            trigger_conditions=json.loads(row[4]),
            governance_rule=json.loads(row[5]),
            confidence=row[6],
            source_strategy_ids=json.loads(row[7]),
            status=row[8], approved_by=row[9], approved_at=row[10],
            notes=row[11]
        )

    def list_policies(self, status: str = None) -> list[Policy]:
        """列出 Policy"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT policy_id, name, policy_type, description,
                       trigger_conditions, governance_rule,
                       confidence, source_strategy_ids,
                       status, approved_by, approved_at, notes
                FROM governance_policies
                WHERE status = ?
                ORDER BY confidence DESC
            """, (status,))
        else:
            cur.execute("""
                SELECT policy_id, name, policy_type, description,
                       trigger_conditions, governance_rule,
                       confidence, source_strategy_ids,
                       status, approved_by, approved_at, notes
                FROM governance_policies
                ORDER BY status, confidence DESC
            """)
        rows = cur.fetchall()
        conn.close()
        return [
            Policy(
                policy_id=r[0], name=r[1], policy_type=r[2],
                description=r[3],
                trigger_conditions=json.loads(r[4]),
                governance_rule=json.loads(r[5]),
                confidence=r[6],
                source_strategy_ids=json.loads(r[7]),
                status=r[8], approved_by=r[9], approved_at=r[10],
                notes=r[11]
            ) for r in rows
        ]

    def approve_policy(self, policy_id: str, approved_by: str = "Founder") -> bool:
        """审批 Policy"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute("""
            UPDATE governance_policies
            SET status = 'active', approved_by = ?, approved_at = ?, updated_at = ?
            WHERE policy_id = ? AND status = 'pending'
        """, (approved_by, now, now, policy_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def reject_policy(self, policy_id: str, reason: str = "") -> bool:
        """拒绝 Policy"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute("""
            UPDATE governance_policies
            SET status = 'rejected', notes = ?, updated_at = ?
            WHERE policy_id = ?
        """, (reason, now, policy_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    # ----------------------------------------------------------
    # Policy Evaluation (应用到机会评估)
    # ----------------------------------------------------------

    def evaluate_opportunity(
        self,
        opp_category: str,
        opp_market: str,
        current_scores: dict,
        risk_keywords: list[str] = None
    ) -> dict:
        """
        将 Active Policies 应用到机会评估。

        Args:
            opp_category: 机会品类
            opp_market: 目标市场
            current_scores: 当前各维度评分
            risk_keywords: 风险关键词列表

        Returns:
            {
                "policy_adjustments": [...],
                "new_scores": {...},
                "auto_reject": bool,
                "auto_reject_reason": str
            }
        """
        active_policies = self.list_policies(status="active")
        adjustments = []
        new_scores = dict(current_scores)
        auto_reject = False
        auto_reject_reason = ""

        for policy in active_policies:
            tc = policy.trigger_conditions

            # 检查触发条件
            triggered = False
            if tc.get("category") == opp_category and tc.get("market") == opp_market:
                triggered = True
            elif tc.get("category") == opp_category:
                triggered = True

            if not triggered:
                continue

            # 合规 Policy 检查关键词
            if policy.policy_type == PolicyType.COMPLIANCE:
                risk_kws = tc.get("risk_keywords", [])
                if risk_keywords:
                    for kw in risk_kws:
                        if any(kw.lower() in rk.lower() for rk in risk_keywords):
                            rule = policy.governance_rule
                            dim = rule.get("dimension", "compliance_risk")
                            if rule.get("auto_reject"):
                                auto_reject = True
                                auto_reject_reason = (
                                    f"[{policy.name}] 触发合规Policy: "
                                    f"{policy.description[:50]}"
                                )
                            if dim in new_scores and rule.get("score_adjustment"):
                                new_scores[dim] = max(0, new_scores[dim] + rule["score_adjustment"])
                            adjustments.append({
                                "policy_id": policy.policy_id,
                                "type": policy.policy_type,
                                "dimension": dim,
                                "adjustment": rule.get("score_adjustment", 0),
                                "reason": policy.description
                            })

            # 其他 Policy 评分调整
            else:
                rule = policy.governance_rule
                dim = rule.get("dimension", "market_size")
                if dim in new_scores and rule.get("score_adjustment"):
                    new_scores[dim] = min(10, new_scores[dim] + rule["score_adjustment"])
                adjustments.append({
                    "policy_id": policy.policy_id,
                    "type": policy.policy_type,
                    "dimension": dim,
                    "adjustment": rule.get("score_adjustment", 0),
                    "reason": policy.description[:80]
                })

        return {
            "policy_adjustments": adjustments,
            "new_scores": new_scores,
            "auto_reject": auto_reject,
            "auto_reject_reason": auto_reject_reason,
            "policies_applied": len(adjustments)
        }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V8.2 — Policy Learning Engine")
    parser.add_argument("--action", choices=["scan", "approve", "reject", "list", "evaluate"],
                        default="list", help="操作类型")
    parser.add_argument("--policy_id", help="Policy ID")
    parser.add_argument("--status", help="状态过滤：pending/active/rejected")
    parser.add_argument("--notes", help="审批备注")
    parser.add_argument("--category", help="品类")
    parser.add_argument("--market", help="市场")
    parser.add_argument("--risk_keywords", help="风险关键词（逗号分隔）")
    parser.add_argument("--scores", help="当前评分JSON")
    parser.add_argument("--db", help="数据库路径")

    args = parser.parse_args()
    db = args.db or r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge-graph\strategy_memory.db"
    ple = PolicyLearningEngine(db)

    if args.action == "scan":
        print("=" * 60)
        print("  Policy Learning Engine — 扫描中")
        print("=" * 60)
        policies = ple.scan_and_generate()
        print(f"\n  生成 {len(policies)} 条候选 Policy：\n")
        for p in policies:
            print(f"  [{p.policy_id}] {p.name}")
            print(f"    类型: {p.policy_type} | 置信度: {p.confidence:.0%}")
            print(f"    描述: {p.description[:70]}")
            print(f"    规则: {json.dumps(p.governance_rule)[:80]}")
            print()
            # 保存
            saved = ple.save_policy(p)
            print(f"  → {'✅ 已写入' if saved else '❌ 写入失败'}")

        print("\n" + "=" * 60)

    elif args.action == "approve":
        if not args.policy_id:
            print("❌ 需要 --policy_id")
        else:
            ok = ple.approve_policy(args.policy_id, args.notes or "Founder approved")
            print(f"{'✅' if ok else '❌'} Policy {args.policy_id} {'已批准' if ok else '批准失败（可能已处理）'}")

    elif args.action == "reject":
        if not args.policy_id:
            print("❌ 需要 --policy_id")
        else:
            ok = ple.reject_policy(args.policy_id, args.notes or "")
            print(f"{'✅' if ok else '❌'} Policy {args.policy_id} {'已拒绝' if ok else '拒绝失败'}")

    elif args.action == "list":
        policies = ple.list_policies(args.status)
        print("=" * 60)
        print(f"  Governance Policies ({args.status or '全部'})")
        print("=" * 60)
        if not policies:
            print("  (无)")
        for p in policies:
            emoji = {"pending": "⏳", "active": "✅", "rejected": "❌"}.get(p.status, "?")
            print(f"\n  {emoji} [{p.policy_id}] {p.name}")
            print(f"     类型: {p.policy_type} | 置信度: {p.confidence:.0%}")
            print(f"     状态: {p.status}")
            if p.approved_by:
                print(f"     审批人: {p.approved_by} @ {p.approved_at}")
            print(f"     规则: {json.dumps(p.governance_rule)[:80]}")
        print("\n" + "=" * 60)

    elif args.action == "evaluate":
        scores = json.loads(args.scores or '{"market_size":7,"unit_economics":7,"compliance_risk":5}')
        risk_kws = args.risk_keywords.split(",") if args.risk_keywords else []
        cat = args.category or "厨房小家电"
        market = args.market or "US"
        result = ple.evaluate_opportunity(cat, market, scores, risk_kws)
        print("=" * 60)
        print(f"  Policy Evaluation: {cat} / {market}")
        print("=" * 60)
        print(f"\n  应用 Policy 数: {result['policies_applied']}")
        if result["policy_adjustments"]:
            print("  评分调整：")
            for adj in result["policy_adjustments"]:
                sign = "+" if adj["adjustment"] > 0 else ""
                print(f"    [{adj['type']}] {adj['dimension']}: {sign}{adj['adjustment']}")
                print(f"      {adj['reason'][:60]}")
        print(f"\n  原始评分:   {scores}")
        print(f"  Policy评分: {result['new_scores']}")
        if result["auto_reject"]:
            print(f"\n  🚫 AUTO-REJECT: {result['auto_reject_reason']}")
        else:
            print(f"\n  ✅ 通过 Policy 检查")
        print("=" * 60)
