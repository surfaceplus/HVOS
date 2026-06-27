"""
HVOS V9.0 — Agent Ecology Engine
========================================
Agent 生态系统：超越生命周期管理，实现生态演化。

V8.3 Agent Factory: 生命周期管理（Birth/评估/Retire）
V9.0 Agent Ecology: 生态演化（Merge/Split/自适应生态）

核心能力：
  auto_retire()     — 持续低效Agent自动淘汰
  auto_merge()      — 相似品类Agent合并
  auto_split()     — 高效单一Agent分裂为多渠道Agent
  run_ecology_cycle()  — 完整生态演化循环
  ecology_health_report() — 生态健康报告
"""

import sqlite3
import json
import uuid
from datetime import datetime

AGENT_DB = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph\agent_factory.db"
KG_DB   = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph\kg.db"

# ============================================================
# Agent Ecology Engine
# ============================================================

class AgentEcologyEngine:
    """
    Agent 生态系统引擎。

    三大演化机制：

    1. Auto-Retire（自动淘汰）
       条件：准确率 < 30% 持续 5 次决策
       效果：该能力缺口重新暴露，触发 auto_birth

    2. Auto-Merge（自动合并）
       条件：两个 Agent 准确率差距 < 10%，且同品类
       效果：合并能力范围，生成更强单一Agent

    3. Auto-Split（自动分裂）
       条件：单一 Agent 准确率 > 90%，决策数 > 10
       效果：分裂为多渠道/多市场Agent
    """

    def __init__(self, agent_db=None, kg_db=None):
        self.agent_db = agent_db or AGENT_DB
        self.kg_db   = kg_db   or KG_DB

    def _conn(self):
        conn = sqlite3.connect(self.agent_db)
        return conn

    def _sql(self, sql, params=()):
        c = self._conn()
        cur = c.cursor()
        cur.execute(sql, params)
        c.commit()
        c.close()

    # ----------------------------------------------------------
    # 1. Auto-Retire
    # ----------------------------------------------------------

    def auto_retire(self) -> list[dict]:
        """
        自动淘汰低效 Agent。

        规则：
        - 准确率 < 30% 且 决策数 >= 5 → 淘汰
        - 淘汰后记录退休原因，暴露能力缺口
        """
        rows = self._aql("""
            SELECT agent_id, name, agent_type, category, market,
                   accuracy, decisions_total, decisions_correct
            FROM agents
            WHERE status = 'active'
            AND agent_type = 'category_specialist'
        """)

        retired = []
        for row in rows:
            aid, name, atype, cat, mkt, acc, decs, corrects = row
            if acc is not None and acc < 0.30 and decs >= 5:
                reason = f"准确率{acc:.0%}<30%，连续{decs}次决策样本"
                self._sql("""
                    UPDATE agents
                    SET status='retired', influence_weight=0.0,
                        retired_at=?, retirement_reason=?
                    WHERE agent_id=?
                """, (datetime.now().isoformat(), reason, aid))
                retired.append({
                    "agent_id": aid,
                    "name": name,
                    "reason": reason,
                    "accuracy": acc,
                    "decisions": decs
                })

        return retired

    # ----------------------------------------------------------
    # 2. Auto-Merge
    # ----------------------------------------------------------

    def auto_merge(self) -> list[dict]:
        """
        自动合并相似 Agent。

        规则：
        - 两个 Agent 品类相同
        - 准确率差距 < 10%
        - 合并后新 Agent 准确率 = 加权平均
        - 合并后影响力 = 两者影响力之和
        """
        rows = self._aql("""
            SELECT agent_id, name, category, market, accuracy,
                   influence_weight, decisions_total
            FROM agents
            WHERE status='active' AND agent_type='category_specialist'
        """)

        merged = []
        processed = set()

        for i, r1 in enumerate(rows):
            if r1[0] in processed:
                continue
            for r2 in rows[i+1:]:
                if r2[0] in processed:
                    continue

                aid1, name1, cat1, mkt1, acc1, iw1, decs1 = r1
                aid2, name2, cat2, mkt2, acc2, iw2, decs2 = r2

                # 品类相同
                if cat1 != cat2 or mkt1 != mkt2:
                    continue

                # 准确率差距 < 10%
                if acc1 is None or acc2 is None:
                    continue
                if abs(acc1 - acc2) > 0.10:
                    continue

                # 合并
                new_acc = (acc1 * decs1 + acc2 * decs2) / max(decs1 + decs2, 1)
                new_iw  = min(0.95, iw1 + iw2)
                new_decs = decs1 + decs2
                new_name = f"{cat1}_{mkt1}_MergedAgent"
                new_id   = f"AGT_MERGED_{uuid.uuid4().hex[:8]}"

                self._sql("""
                    UPDATE agents SET status='merged', influence_weight=0.0
                    WHERE agent_id IN (?, ?)
                """, (aid1, aid2))

                self._sql("""
                    INSERT INTO agents
                    (agent_id,name,agent_type,category,market,dimension,
                     specialty,decisions_total,decisions_correct,accuracy,
                     avg_score,status,influence_weight,confidence,skills,tags,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    new_id, new_name, "category_specialist", cat1, mkt1,
                    f"merged:{aid1}+{aid2}",
                    f"Auto-merge {name1}+{name2}",
                    new_decs,
                    int(new_acc * new_decs),
                    round(new_acc, 3),
                    round(new_acc * 10, 1),
                    "active",
                    round(new_iw, 3),
                    round(new_acc, 3),
                    "[]",
                    json.dumps(["auto-merged"]),
                    datetime.now().isoformat()
                ))

                merged.append({
                    "new_agent_id": new_id,
                    "new_name": new_name,
                    "merged_from": [aid1, aid2],
                    "new_accuracy": round(new_acc, 3),
                    "new_influence": round(new_iw, 3)
                })
                processed.add(aid1)
                processed.add(aid2)
                break

        return merged

    # ----------------------------------------------------------
    # 3. Auto-Split
    # ----------------------------------------------------------

    def auto_split(self) -> list[dict]:
        """
        自动分裂高效单一 Agent。

        规则：
        - 准确率 > 90% 且 决策数 > 10
        - 分裂为多渠道Agent（如：Kitchen_US_TikTok, Kitchen_US_Pinterest）
        - 新Agent初始置信度 = 母Agent * 0.7
        """
        rows = self._aql("""
            SELECT agent_id, name, category, market, accuracy,
                   influence_weight, decisions_total, confidence
            FROM agents
            WHERE status='active' AND agent_type='category_specialist'
        """)

        splits = []
        for row in rows:
            aid, name, cat, mkt, acc, iw, decs, conf = row
            if acc is None or conf is None:
                continue
            if acc > 0.90 and decs > 10:
                # 分裂为两个渠道Agent
                channels = ["TikTok", "Pinterest"]
                for ch in channels:
                    new_id = f"AGT_SPLIT_{uuid.uuid4().hex[:8]}"
                    new_name = f"{cat}_{mkt}_{ch}_Agent"
                    new_conf = max(0.50, conf * 0.7)  # 降权启动
                    new_iw  = max(0.30, iw * 0.7)

                    self._sql("""
                        INSERT INTO agents
                        (agent_id,name,agent_type,category,market,dimension,
                         specialty,decisions_total,decisions_correct,accuracy,
                         avg_score,status,influence_weight,confidence,skills,tags,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        new_id, new_name, "channel_specialist", cat, mkt,
                        "channel",
                        f"Auto-split from {name}, channel={ch}",
                        0, 0, new_conf,
                        new_conf * 10,
                        "active",
                        round(new_iw, 3),
                        round(new_conf, 3),
                        json.dumps([ch]),
                        json.dumps(["auto-split"]),
                        datetime.now().isoformat()
                    ))
                    splits.append({
                        "parent_agent_id": aid,
                        "new_agent_id": new_id,
                        "new_name": new_name,
                        "channel": ch,
                        "initial_confidence": round(new_conf, 3)
                    })

                # 母Agent降权
                self._sql("""
                    UPDATE agents SET influence_weight=?, status='split_source'
                    WHERE agent_id=?
                """, (iw * 0.5, aid))

        return splits

    # ----------------------------------------------------------
    # 完整生态演化循环
    # ----------------------------------------------------------

    def run_ecology_cycle(self) -> dict:
        """
        运行完整生态演化循环：
        1. Auto-Retire（淘汰低效）
        2. Auto-Merge（合并相似）
        3. Auto-Split（分裂高效）
        """
        report = {
            "cycle_time": datetime.now().isoformat(),
            "retired": [],
            "merged": [],
            "split": [],
            "new_born": []
        }

        # Step 1: 淘汰
        retired = self.auto_retire()
        report["retired"] = retired
        print(f"  [Auto-Retire] 淘汰 {len(retired)} 个Agent")

        # Step 2: 合并
        merged = self.auto_merge()
        report["merged"] = merged
        print(f"  [Auto-Merge] 合并 {len(merged)} 对Agent")

        # Step 3: 分裂
        split = self.auto_split()
        report["split"] = split
        print(f"  [Auto-Split] 分裂 {len(split)} 个Agent")

        # Step 4: 检测淘汰后缺口 → 自动补充
        for r in retired:
            cat = self._get_agent_category(r["agent_id"])
            mkt = self._get_agent_market(r["agent_id"])
            if cat:
                self._auto_birth(cat, mkt or "US",
                                  reason=f"填补被淘汰Agent的品类能力缺口")
                report["new_born"].append({"category": cat, "market": mkt})

        # 汇总
        health = self.ecology_health_score()
        report["health_score"] = health["score"]
        report["health_status"] = health["status"]
        return report

    def _get_agent_category(self, agent_id):
        rows = self._aql("SELECT category FROM agents WHERE agent_id=?", (agent_id,))
        return rows[0][0] if rows else None

    def _get_agent_market(self, agent_id):
        rows = self._aql("SELECT market FROM agents WHERE agent_id=?", (agent_id,))
        return rows[0][0] if rows else None

    def _auto_birth(self, cat, mkt, reason=""):
        aid = f"AGT_ECOBORN_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        self._sql("""
            INSERT INTO agents
            (agent_id,name,agent_type,category,market,dimension,
             specialty,decisions_total,decisions_correct,accuracy,
             avg_score,status,influence_weight,confidence,skills,tags,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            aid, f"{cat}_{mkt}_EcoAgent",
            "category_specialist", cat, mkt, "market_size",
            f"Eco-born: {reason}",
            0, 0, 0.50, 5.0, "active", 0.25, 0.50,
            "[]", json.dumps(["eco-born"]), now
        ))
        return aid

    def ecology_health_score(self) -> dict:
        """计算生态健康度"""
        rows = self._aql("""
            SELECT agent_id, agent_type, status, accuracy,
                   decisions_total, influence_weight
            FROM agents
        """)
        if not rows:
            return {"score": 0.0, "status": "EMPTY"}

        n = len(rows)
        active = [r for r in rows if r[2] == "active"]
        specialists = [r for r in active if r[1] == "category_specialist"]
        high_acc = [r for r in active if r[3] and r[3] >= 0.70]
        retired = [r for r in rows if r[2] == "retired"]

        # 健康度公式
        diversity = len(set(r[0] for r in specialists)) / max(n, 1)  # 多样性
        capability = len(high_acc) / max(len(specialists), 1)           # 高效能力比例
        evolution = len(retired) / max(n, 1)                          # 淘汰率（适当淘汰=健康）

        score = 0.35 * diversity + 0.40 * capability + 0.25 * evolution
        status = "EXCELLENT" if score >= 0.75 else \
                "GOOD"      if score >= 0.55 else \
                "FAIR"      if score >= 0.35 else "POOR"

        return {
            "score": round(score, 3),
            "status": status,
            "total_agents": n,
            "active": len(active),
            "specialists": len(specialists),
            "high_accuracy": len(high_acc),
            "retired_count": len(retired),
            "diversity_ratio": round(diversity, 3),
            "capability_ratio": round(capability, 3)
        }

    def _aql(self, sql, params=()):
        c = self._conn()
        cur = c.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        c.close()
        return rows


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="HVOS V9.0 Agent Ecology Engine")
    p.add_argument("--action", choices=["retire","merge","split","cycle","health"], default="cycle")
    args = p.parse_args()
    eco = AgentEcologyEngine()

    if args.action == "retire":
        print(json.dumps({"retired": eco.auto_retire()}, indent=2, ensure_ascii=False))
    elif args.action == "merge":
        print(json.dumps({"merged": eco.auto_merge()}, indent=2, ensure_ascii=False))
    elif args.action == "split":
        print(json.dumps({"split": eco.auto_split()}, indent=2, ensure_ascii=False))
    elif args.action == "health":
        print(json.dumps(eco.ecology_health_score(), indent=2, ensure_ascii=False))
    elif args.action == "cycle":
        result = eco.run_ecology_cycle()
        print(json.dumps(result, indent=2, ensure_ascii=False))
