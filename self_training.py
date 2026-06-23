"""
HVOS V9.0 — 自我训练引擎
======================================
完整闭环跑通所有 V9.0 模块：

  1. 输入机会 → KG Consumer（更新知识图谱）
  2. KG → Knowledge Reasoner（商业推理）
  3. 推理结果 → Pattern Mining（自动发现高阶组合）
  4. Pattern → Strategy Memory（提炼策略规则）
  5. 策略 → Policy Learning（生成治理Policy）
  6. Policy → Agent Factory（Agent绩效更新）
  7. Agent → Agent Ecology（生态演化）
  8. 失败案例 → Causal Reasoner（因果推理+反事实分析）
  9. 输出：V9.0 完整诊断报告

用法：
  python self_training.py --action full_cycle
  python self_training.py --action incremental --opp "New Smart Watch"
  python self_training.py --action health_report
"""

import sys
import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path

# ─── DB 路径 ───────────────────────────────────────────────
HVOS = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
KG_DB = rf"{HVOS}\knowledge-graph\kg.db"
STRATEGY_DB = rf"{HVOS}\knowledge-graph\strategy_memory.db"
AGENT_DB = rf"{HVOS}\knowledge-graph\agent_factory.db"
ES_DB = rf"{HVOS}\reality\events.db"

# ─── 导入 V9.0 模块（直接文件路径） ──────────────────────
sys.path.insert(0, rf"{HVOS}\knowledge-graph")
sys.path.insert(0, HVOS)

from kg_event_consumer import KGEventConsumer
from strategy_memory import StrategyMemory
from policy_learning_engine import PolicyLearningEngine, PolicyCompressionEngine
from agent_factory import AgentFactory
from knowledge_reasoner import KnowledgeReasoner
from pattern_mining_engine import PatternMiningEngine
from causal_reasoner import CausalReasoningEngine
from agent_ecology import AgentEcologyEngine

# V9.2 模块
sys.path.insert(0, rf"{HVOS}\knowledge-graph")
from learning_loop import LearningLoop, ErrorAttributionEngine


# ============================================================
# V9.0 自我训练引擎
# ============================================================

class HVOS9SelfTrainer:
    """
    V9.0 自我训练引擎。

    完整闭环：
    Opportunity → KG → Reasoner → PatternMiner → StrategyMemory
           → PolicyLearning → AgentFactory → AgentEcology
           → CausalReasoner → 输出报告
    """

    def __init__(self):
        self.kg     = KGEventConsumer(KG_DB)
        self.sm      = StrategyMemory(STRATEGY_DB)
        self.pl      = PolicyLearningEngine(STRATEGY_DB)
        self.af      = AgentFactory(AGENT_DB)
        self.kr      = KnowledgeReasoner(KG_DB)
        self.pme     = PatternMiningEngine(STRATEGY_DB, KG_DB)
        self.cre     = CausalReasoningEngine(ES_DB, KG_DB)
        self.eco     = AgentEcologyEngine(AGENT_DB)
        self.report = {}

    # ----------------------------------------------------------
    # Step 1: 机会输入 → KG 更新
    # ----------------------------------------------------------

    def _process_opportunity_to_kg(self, opp_data: dict) -> dict:
        """将机会数据注入 KG（模拟 Event Store 写入）"""
        opp_id = opp_data["opp_id"]
        name = opp_data["name"]
        category = opp_data.get("category", "general")
        market = opp_data.get("market", "US")

        conn = sqlite3.connect(KG_DB)
        cur = conn.cursor()
        now = datetime.now().isoformat()

        # Opportunity 节点
        opp_node = f"Opportunity_{opp_id}"
        cur.execute("""
            INSERT OR REPLACE INTO kg_nodes
            (node_id, entity_type, name, properties, created_at)
            VALUES (?, 'Opportunity', ?, ?, ?)
        """, (opp_node, name, json.dumps(opp_data), now))

        # Category 节点
        cat_node = f"Category_{category}"
        cur.execute("""
            INSERT OR IGNORE INTO kg_nodes
            (node_id, entity_type, name, created_at)
            VALUES (?, 'Category', ?, ?)
        """, (cat_node, category, now))

        # 关系
        cur.execute("""
            INSERT OR IGNORE INTO kg_relations
            (relation_id, from_node, to_node, rel_type, properties, created_at)
            VALUES (?, ?, ?, 'BELONGS_TO', '{}', ?)
        """, (f"REL_{uuid.uuid4().hex[:8]}", opp_node, cat_node, now))

        conn.commit()
        conn.close()

        return {
            "step": "KG Update",
            "opp_id": opp_id,
            "node_created": opp_node,
            "status": "ok"
        }

    # ----------------------------------------------------------
    # Step 2: KG → 商业推理
    # ----------------------------------------------------------

    def _reason_about_opportunity(self, opp_data: dict) -> dict:
        """Knowledge Reasoner 推理"""
        category = opp_data.get("category", "")
        market = opp_data.get("market", "US")

        # 找相似赢家
        similar = self.kr.find_similar_winners(category, market)

        # 预测供应链风险
        supply_risk = self.kr.predict_supply_chain_risk(category)

        # 推荐下一步
        next_action = self.kr.recommend_next_action(
            opp_id=opp_data["opp_id"],
            stage="DISCOVERED"
        )

        return {
            "step": "Knowledge Reasoning",
            "similar_winners": similar.get("winners", [])[:3],
            "supply_risks": supply_risk.get("high_risk", [])[:2],
            "recommended_action": next_action.get("recommended_action", ""),
            "recommended_priority": next_action.get("priority", ""),
        }

    # ----------------------------------------------------------
    # Step 3: Pattern Mining
    # ----------------------------------------------------------

    def _mine_patterns(self) -> dict:
        """Pattern Mining — 自动发现高阶组合"""
        combos = self.pme.discover_combinations()
        top = combos.get("top_combinations", [])[:5]
        return {
            "step": "Pattern Mining",
            "combinations_found": combos.get("combinations_found", 0),
            "base_success_rate": combos.get("base_success_rate", 0),
            "top_patterns": [
                {"category": p["category"], "lift": p["lift"],
                 "success_rate": p["success_rate"], "verdict": p.get("verdict","")}
                for p in top
            ]
        }

    # ----------------------------------------------------------
    # Step 4: Strategy Memory
    # ----------------------------------------------------------

    def _update_strategy_memory(self, opp_data: dict, outcome: str, insight: str) -> dict:
        """Strategy Memory — 记录结果，提炼策略"""
        result = self.sm.record_outcome(
            opp_id=opp_data["opp_id"],
            opp_name=opp_data.get("name", ""),
            category=opp_data.get("category", "general"),
            market=opp_data.get("market", "US"),
            verdict=opp_data.get("verdict", "REJECT"),
            outcome=outcome,
            revenue_90d=opp_data.get("revenue_90d", 0),
            roi_actual=opp_data.get("roi_actual", 0),
            net_margin_actual=opp_data.get("margin", 0),
            key_insight=insight
        )
        return {
            "step": "Strategy Memory",
            "log_id": result["log_id"],
            "strategies_extracted": result["strategies_extracted"],
        }

    # ----------------------------------------------------------
    # Step 5: Policy Learning
    # ----------------------------------------------------------

    def _scan_and_approve_policies(self) -> dict:
        """Policy Learning — 扫描策略库，生成候选 Policy"""
        policies = self.pl.scan_and_generate()
        approved = []
        for p in policies:
            self.pl.save_policy(p)
            if p.confidence >= 0.85 and p.policy_type == "compliance":
                ok = self.pl.approve_policy(p.policy_id)
                if ok:
                    approved.append(p.policy_id)
        return {
            "step": "Policy Learning",
            "policies_generated": len(policies),
            "policies_approved": len(approved),
            "approved_ids": approved
        }

    # ----------------------------------------------------------
    # Step 6: Agent Factory — 绩效更新
    # ----------------------------------------------------------

    def _evaluate_agents(self, opp_data: dict, outcome: str) -> dict:
        """Agent Factory — 基于结果更新 Agent 绩效"""
        category = opp_data.get("category", "")
        market = opp_data.get("market", "US")
        predicted = opp_data.get("predicted_score", 7.0)

        # 找对应 Agent
        agent = self.af.select_agent(category, market, "market_size")
        if not agent:
            return {"step": "Agent Evaluation", "agent_selected": None}

        # 评估
        result = self.af.evaluate_agent(
            agent_id=agent.agent_id,
            decision_id=f"DEC_{uuid.uuid4().hex[:8]}",
            opp_id=opp_data["opp_id"],
            dimension="market_size",
            predicted_score=predicted,
            actual_outcome=outcome
        )
        return {
            "step": "Agent Evaluation",
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "is_correct": result.get("is_correct"),
            "new_accuracy": result.get("new_accuracy"),
            "new_influence": result.get("new_influence_weight"),
            "status": result.get("status"),
        }

    # ----------------------------------------------------------
    # Step 7: Agent Ecology — 生态演化
    # ----------------------------------------------------------

    def _run_ecology_cycle(self) -> dict:
        """Agent Ecology — 完整演化循环"""
        cycle = self.eco.run_ecology_cycle()
        health = self.eco.ecology_health_score()
        return {
            "step": "Agent Ecology",
            "retired": len(cycle.get("retired", [])),
            "merged": len(cycle.get("merged", [])),
            "split": len(cycle.get("split", [])),
            "new_born": len(cycle.get("new_born", [])),
            "health_score": health.get("score", 0),
            "health_status": health.get("status", "UNKNOWN"),
        }

    # ----------------------------------------------------------
    # Step 8: Causal Reasoning — 失败归因
    # ----------------------------------------------------------

    def _causal_analysis(self, opp_id: str) -> dict:
        """Causal Reasoner — 失败归因 + 反事实"""
        graph = self.cre.infer_causal_graph(opp_id)
        if "error" in graph:
            return {"step": "Causal Reasoning", "status": "no_data"}

        # 找 REJECT 裁决节点
        reject_node = None
        for nid, ndata in graph.get("nodes", {}).items():
            if ndata.get("properties", {}).get("verdict", "").upper() in ("REJECT", "REJECTED"):
                reject_node = nid
                break

        if reject_node:
            cf = self.cre.counterfactual(
                opp_id=opp_id,
                intervention_node=reject_node,
                intervention_action="enhance",
                original_outcome="REJECT"
            )
            attribution = self.cre.attribute_failure(opp_id)
            points = self.cre.find_intervention_points(opp_id)
            return {
                "step": "Causal Reasoning",
                "opp_id": opp_id,
                "nodes_in_graph": len(graph.get("nodes", {})),
                "edges_in_graph": len(graph.get("edges", {})),
                "counterfactual": {
                    "original": cf.get("original_outcome"),
                    "counterfactual": cf.get("counterfactual_outcome"),
                    "changed": cf.get("outcome_changed"),
                    "insight": cf.get("insight", "")
                },
                "attribution": attribution,
                "top_intervention": points[0] if points else None
            }
        return {"step": "Causal Reasoning", "opp_id": opp_id, "status": "no_reject_found"}

    # ----------------------------------------------------------
    # 完整闭环
    # ----------------------------------------------------------

    def full_cycle(self, test_opportunity: dict = None) -> dict:
        """
        运行完整 V9.0 自我训练闭环。

        test_opportunity: 可选，传入测试机会数据
        """
        start = datetime.now()
        steps = []
        report = {
            "start_time": start.isoformat(),
            "steps": [],
            "summary": {}
        }

        # ── 测试机会数据 ──────────────────────────
        if test_opportunity is None:
            test_opp = {
                "opp_id": f"opp_self_{uuid.uuid4().hex[:8]}",
                "name": "Smart Water Bottle with UV Purification",
                "category": "户外用品",
                "market": "US",
                "predicted_score": 7.5,
                "verdict": "WATCHLIST",
                "revenue_90d": 18000,
                "margin": 0.68,
                "roi_actual": 2.8,
                "fob_cost": 22.0,
                "retail_price": 68.99,
                "moq": 200,
                "hs_code": "9617.00"
            }
        else:
            test_opp = test_opportunity

        # ── Step 1: KG 更新 ──────────────────────
        s1 = self._process_opportunity_to_kg(test_opp)
        steps.append(s1)

        # ── Step 2: 商业推理 ───────────────────
        s2 = self._reason_about_opportunity(test_opp)
        steps.append(s2)

        # ── Step 3: Pattern Mining ────────────────
        s3 = self._mine_patterns()
        steps.append(s3)

        # ── Step 4: Strategy Memory ──────────────
        outcome = "success" if test_opp.get("revenue_90d", 0) > 0 else "failure"
        insight = f"UV净水水壶，{test_opp.get('category')}品类，"
        insight += "毛利率68%表现强劲，Q4户外需求季节性机会明显"
        s4 = self._update_strategy_memory(test_opp, outcome, insight)
        steps.append(s4)

        # ── Step 5: Policy Learning ──────────────
        s5 = self._scan_and_approve_policies()
        steps.append(s5)

        # ── Step 6: Agent Evaluation ────────────
        s6 = self._evaluate_agents(test_opp, outcome)
        steps.append(s6)

        # ── Step 7: Agent Ecology ───────────────
        s7 = self._run_ecology_cycle()
        steps.append(s7)

        # ── Step 8: Causal Reasoning ────────────
        # 找一个历史 REJECT 案例做因果分析
        conn = sqlite3.connect(KG_DB)
        cur = conn.cursor()
        cur.execute("""
            SELECT n.node_id FROM kg_nodes n
            JOIN kg_relations r ON n.node_id = r.to_node
            JOIN kg_nodes i ON r.from_node = i.node_id
            WHERE n.entity_type = 'Opportunity'
            AND r.rel_type = 'INVESTED_IN'
            AND i.entity_type = 'Investment'
        """)
        opps = [row[0] for row in cur.fetchall()]
        conn.close()

        s8 = {"step": "Causal Reasoning", "status": "no_reject_found"}
        for opp_node in opps[:3]:
            opp_id = opp_node.replace("Opportunity_", "")
            causal = self._causal_analysis(opp_id)
            if causal.get("counterfactual", {}).get("changed"):
                s8 = causal
                break
        steps.append(s8)

        # ── 生成摘要 ──────────────────────────
        end = datetime.now()
        report["end_time"] = end.isoformat()
        report["duration_ms"] = int((end - start).total_seconds() * 1000)
        report["steps"] = steps

        # 摘要关键指标
        all_ok = all(s.get("status") != "error" for s in steps)
        report["summary"] = {
            "overall_status": "PASS" if all_ok else "DEGRADED",
            "steps_completed": len(steps),
            "knowledge_graph_nodes": self._kg_count("nodes"),
            "knowledge_graph_relations": self._kg_count("relations"),
            "strategy_library_size": self._sm_count(),
            "active_policies": self._pl_count(),
            "agent_portfolio_health": s7.get("health_status", "UNKNOWN"),
            "causal_insight": s8.get("counterfactual", {}).get("insight", ""),
            "pattern_discovered": len(s3.get("top_patterns", [])),
        }

        self.report = report
        return report

    def _kg_count(self, what: str) -> int:
        conn = sqlite3.connect(KG_DB)
        cur = conn.cursor()
        if what == "nodes":
            cur.execute("SELECT COUNT(*) FROM kg_nodes")
        else:
            cur.execute("SELECT COUNT(*) FROM kg_relations")
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt

    def _sm_count(self) -> int:
        conn = sqlite3.connect(STRATEGY_DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM strategy_library")
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt

    def _pl_count(self) -> int:
        conn = sqlite3.connect(STRATEGY_DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM governance_policies WHERE status='active'")
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt

    def health_report(self) -> dict:
        """生成 V9.0 系统健康报告"""
        health = self.eco.ecology_health_score()
        patterns = self.pme.discover_combinations()
        reasoner = self.kr.predict_supply_chain_risk()

        return {
            "timestamp": datetime.now().isoformat(),
            "system": "HVOS V9.0",
            "knowledge_graph": {
                "nodes": self._kg_count("nodes"),
                "relations": self._kg_count("relations")
            },
            "strategy_library": {
                "rules": self._sm_count(),
                "patterns_discovered": patterns.get("combinations_found", 0),
                "base_success_rate": patterns.get("base_success_rate", 0)
            },
            "governance": {
                "active_policies": self._pl_count()
            },
            "agent_ecosystem": health,
            "supply_chain_risk": {
                "high_risk_products": len(reasoner.get("high_risk", [])),
                "medium_risk_products": len(reasoner.get("medium_risk", []))
            }
        }

    # ----------------------------------------------------------
    # V9.2 Step 9: Learning Loop — 持续学习
    # ----------------------------------------------------------

    def _run_learning_loop(self, opp_data: dict, outcome: str) -> dict:
        """完整学习闭环：因果因素 + KG边权重 + 失败模式"""
        loop = LearningLoop()
        result = loop.run(
            opp_id=opp_data["opp_id"],
            success=(outcome == "success"),
            roi=opp_data.get("roi_actual", 0),
            cvr=opp_data.get("cvr", 0),
            ctr=opp_data.get("ctr", 0),
            aov=opp_data.get("aov", 0),
            refund_rate=opp_data.get("refund_rate", 0),
            category=opp_data.get("category", ""),
            market=opp_data.get("market", "US"),
            publish=True,
        )
        return {
            "step": "Learning Loop",
            "causal_factors": result.get("causal_factors", []),
            "edge_update": result.get("edge_update", {}),
        }

    # ----------------------------------------------------------
    # V9.2 Step 10: Error Attribution — 预测误差归因
    # ----------------------------------------------------------

    def _record_prediction_error(self, opp_data: dict, predicted_roi: float) -> dict:
        """记录预测误差并归因"""
        if "roi_actual" not in opp_data or not opp_data.get("roi_actual"):
            return {"step": "Error Attribution", "status": "skipped_no_actual"}
        eae = ErrorAttributionEngine()
        record = eae.record_prediction_error(
            prediction_id=f"pred_{uuid.uuid4().hex[:12]}",
            opp_id=opp_data["opp_id"],
            predicted_roi=predicted_roi,
            actual_roi=opp_data.get("roi_actual", 0),
            actual_cvr=opp_data.get("cvr", 0),
            actual_ctr=opp_data.get("ctr", 0),
            actual_aov=opp_data.get("aov", 0),
            actual_refund_rate=opp_data.get("refund_rate", 0),
            category=opp_data.get("category", ""),
            market=opp_data.get("market", "US"),
        )
        return {
            "step": "Error Attribution",
            "prediction_id": record.prediction_id,
            "error_pct": record.error_pct,
            "error_magnitude": record.error_magnitude,
            "primary_engine": record.attribution.get("primary_engine", ""),
            "recommendation": record.attribution.get("recommendation", ""),
        }

    # ----------------------------------------------------------
    # V9.2 Step 11: Policy Compression — 策略瘦身
    # ----------------------------------------------------------

    def _run_policy_compression(self) -> dict:
        """Policy 压缩：同义合并 + 低效归档"""
        pce = PolicyCompressionEngine(STRATEGY_DB)
        report = pce.run_compression(dry_run=False)
        return {
            "step": "Policy Compression",
            "duplicates_found": report["duplicates_found"],
            "auto_merged": report["auto_merged"],
            "archived": report["archive_result"]["archived"],
            "deleted": report["archive_result"]["deleted"],
            "total_after": report["total_policies"],
        }

    # ----------------------------------------------------------
    # V9.2 增强 full_cycle
    # ----------------------------------------------------------

    def full_cycle_v92(self, test_opportunity: dict = None) -> dict:
        """
        V9.2 增强闭环（在 V9.0 基础上增加学习+归因+压缩）。

        在 V9.0 的 8 步闭环后，新增：
          Step 9:  Learning Loop（持续学习）
          Step 10: Error Attribution（误差归因）
          Step 11: Policy Compression（策略压缩）
        """
        # 先跑 V9.0 标准闭环
        base = self.full_cycle(test_opportunity)
        steps = base.get("steps", [])
        test_opp = test_opportunity or {
            "opp_id": f"opp_v92_{uuid.uuid4().hex[:8]}",
            "name": "Smart Water Bottle with UV Purification",
            "category": "户外用品",
            "market": "US",
            "roi_actual": 2.8,
            "cvr": 0.035,
            "ctr": 0.042,
            "aov": 89,
            "refund_rate": 0.04,
        }
        if test_opportunity:
            test_opp = test_opportunity

        outcome = "success" if test_opp.get("roi_actual", 0) > 1.0 else "failure"

        # Step 9: Learning Loop
        s9 = self._run_learning_loop(test_opp, outcome)
        steps.append(s9)

        # Step 10: Error Attribution（模拟预测 ROI=2.0 vs 实际）
        s10 = self._record_prediction_error(test_opp, predicted_roi=2.0)
        steps.append(s10)

        # Step 11: Policy Compression
        s11 = self._run_policy_compression()
        steps.append(s11)

        base["steps"] = steps
        base["summary"]["steps_completed"] = len(steps)
        base["summary"]["v92_learning_loop"] = s9.get("edge_update", {}).get("updated", 0)
        base["summary"]["v92_error_attribution"] = s10.get("error_magnitude", "")
        base["summary"]["v92_policy_compression"] = f"{s11['auto_merged']} merged, {s11['archived']} archived"
        base["v92_version"] = "1.0.0"
        return base


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS V9.0 自我训练引擎")
    parser.add_argument("--action", choices=[
        "full_cycle", "health_report", "incremental",
        "full_cycle_v92", "compress", "attribution"
    ], default="full_cycle")
    parser.add_argument("--opp_name")
    parser.add_argument("--category")
    parser.add_argument("--market", default="US")
    args = parser.parse_args()

    trainer = HVOS9SelfTrainer()

    if args.action == "full_cycle":
        result = trainer.full_cycle()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "health_report":
        print(json.dumps(trainer.health_report(), indent=2, ensure_ascii=False))

    elif args.action == "incremental":
        opp = {
            "opp_id": f"opp_inc_{uuid.uuid4().hex[:8]}",
            "name": args.opp_name or "New Product",
            "category": args.category or "general",
            "market": args.market,
            "predicted_score": 7.0,
            "verdict": "WATCHLIST",
            "revenue_90d": 0,
            "margin": 0.60
        }
        result = trainer.full_cycle(test_opportunity=opp)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "full_cycle_v92":
        """V9.2 增强闭环"""
        print("=" * 60)
        print("  HVOS V9.2 — 增强自我训练闭环（11步）")
        print("=" * 60)
        opp = None
        if args.opp_name:
            opp = {
                "opp_id": f"opp_v92_{uuid.uuid4().hex[:8]}",
                "name": args.opp_name,
                "category": args.category or "general",
                "market": args.market,
                "roi_actual": 2.8,
                "cvr": 0.035,
                "ctr": 0.042,
                "aov": 89,
                "refund_rate": 0.04,
                "margin": 0.68,
            }
        result = trainer.full_cycle_v92(test_opportunity=opp)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\n✅ V9.2 闭环完成 — {result['summary']['steps_completed']} steps")

    elif args.action == "compress":
        """V9.2 Policy 压缩"""
        pce = PolicyCompressionEngine(STRATEGY_DB)
        report = pce.run_compression(dry_run=False)
        print("=" * 60)
        print("  HVOS V9.2 — Policy Compression")
        print("=" * 60)
        print(f"\n  重复对:     {report['duplicates_found']}")
        print(f"  自动合并:   {report['auto_merged']}")
        ar = report['archive_result']
        print(f"  归档:       {ar['archived']}")
        print(f"  删除:       {ar['deleted']}")
        print(f"  保留:       {ar['kept']}")
        print(f"\n  最终统计:")
        print(f"    active:   {report.get('count_active', 0)}")
        print(f"    pending:  {report.get('count_pending', 0)}")
        print(f"    weak:     {report.get('count_weak', 0)}")
        print(f"    archived: {report.get('count_archived', 0)}")
        print(f"    total:    {report['total_policies']}")
        print(f"\n✅ Policy 压缩完成")

    elif args.action == "attribution":
        """V9.2 误差归因报告"""
        eae = ErrorAttributionEngine()
        report = eae.generate_report()
        print("=" * 60)
        print("  HVOS V9.2 — Error Attribution Report")
        print("=" * 60)
        print(f"\n  总误差记录: {report['total_errors']}")
        print(f"  平均绝对误差: {report['avg_abs_error_pct']:.1f}%")
        print(f"  系统偏差: {report['system_bias']}")
        print(f"\n  校准建议:")
        for a in report['calibration_actions']:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a['priority'], '⚪')
            print(f"    {emoji} [{a['priority']}] {a['action']}")
        print(f"\n✅ 归因报告完成")
