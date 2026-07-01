"""
HVOS V9.0 — Causal Reasoning Engine
========================================
因果推理引擎：从投资事件序列中推断因果链，进行反事实分析，
             识别失败根因，推演最优干预点。

V8.4 Reasoner 的本质：Rule-Based Graph Heuristic
V9.0 Causal Reasoner 的本质：Counterfactual Causal Inference

核心能力：
  infer_causal_graph()    — 从 Event Chain 构建因果图
  counterfactual()         — 反事实分析："如果做了X，结果会怎样？"
  attribute_failure()       — 失败归因：哪个环节是致命断点
  find_intervention_point() — 找到最优干预点
  simulate_path()          — 推演替代投资路径
"""

import sqlite3
import json
from datetime import datetime
from collections import defaultdict

ES_DB = r"C:\Users\Administrator\AppData\Local\hermes\hvos\reality\events.db"
KG_DB = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph\kg.db"

# ============================================================
# Causal Node Types
# ============================================================

class CausalNodeType:
    SIGNAL = "signal"          # 市场信号发现
    SCREENING = "screening"    # 初筛决策
    INTELLIGENCE = "intelligence"  # Intelligence分析
    COMPLIANCE = "compliance"   # 合规审查
    BOARD_VOTE = "board_vote"  # 董事会投票
    DECISION = "decision"      # 最终裁决
    OUTCOME = "outcome"        # 投资结果


class CausalLinkType:
    LEADS_TO = "leads_to"
    BLOCKED_BY = "blocked_by"
    ENABLED_BY = "enabled_by"
    CAUSED_BY = "caused_by"
    CONTRAFACTS = "counterfactual"


# ============================================================
# Causal Graph
# ============================================================

class CausalGraph:
    """因果图"""

    def __init__(self):
        self.nodes = {}     # node_id -> CausalNode
        self.edges = []    # [CausalEdge]

    def add_node(self, node_id, node_type, label, properties=None):
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "properties": properties or {},
            "counterfactual_branch": None
        }

    def add_edge(self, from_id, to_id, link_type, weight=1.0, label=""):
        self.edges.append({
            "from": from_id,
            "to": to_id,
            "type": link_type,
            "weight": weight,
            "label": label
        })

    def to_dict(self):
        return {"nodes": self.nodes, "edges": self.edges}


# ============================================================
# Causal Reasoning Engine
# ============================================================

class CausalReasoningEngine:
    """
    因果推理引擎。

    核心推理方法：

    1. 因果图构建
       Event Sequence → Causal Graph → Causal Chains

    2. 反事实分析
       "如果Q4进入而不是Q1，结果会不同吗？"

    3. 失败归因
       "哪个节点是致命阻断点？"

    4. 最优干预点
       "在哪干预最小成本最大效果？"
    """

    def __init__(self, es_db=None, kg_db=None):
        self.es_db = es_db or ES_DB
        self.kg_db = kg_db or KG_DB

    def _es_conn(self):
        conn = sqlite3.connect(self.es_db)
        return conn

    def _kg_conn(self):
        conn = sqlite3.connect(self.kg_db)
        return conn

    # ----------------------------------------------------------
    # 1. 构建因果图
    # ----------------------------------------------------------

    def infer_causal_graph(self, opp_id: str) -> dict:
        """
        从 Event Chain 构建因果图。

        节点类型映射：
          OPPORTUNITY_DISCOVERED → signal
          SCREENING_COMPLETED → screening
          INTELLIGENCE_ANALYSIS_COMPLETED → intelligence
          COMPLIANCE_REVIEW_COMPLETED → compliance
          BOARD_VOTE_CAST → board_vote
          INVESTMENT_DECISION_RENDERED → decision
          RFE_ACTUAL_RECORDED → outcome
        """
        conn = self._es_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT event_id, event_type, source AS actor, event_type AS description, timestamp, payload AS data
            FROM event_log
            WHERE partition_key = ?
            ORDER BY timestamp
        """, (opp_id,))

        events = []
        for row in cur.fetchall():
            events.append({
                "event_id": row[0],
                "event_type": row[1],
                "actor": row[2],
                "description": row[3],
                "timestamp": row[4],
                "data": json.loads(row[5]) if row[5] else {}
            })
        conn.close()

        if not events:
            return {"error": f"No events for {opp_id}"}

        graph = CausalGraph()
        node_map = {}  # event_id -> node_id

        # 节点类型映射
        type_map = {
            "OPPORTUNITY_DISCOVERED": (CausalNodeType.SIGNAL, "市场信号发现"),
            "SCREENING_COMPLETED": (CausalNodeType.SCREENING, "初筛通过"),
            "INTELLIGENCE_ANALYSIS_COMPLETED": (CausalNodeType.INTELLIGENCE, "Intelligence分析"),
            "COMPLIANCE_REVIEW_COMPLETED": (CausalNodeType.COMPLIANCE, "合规审查"),
            "BOARD_VOTE_CAST": (CausalNodeType.BOARD_VOTE, "董事会投票"),
            "INVESTMENT_DECISION_RENDERED": (CausalNodeType.DECISION, "裁决"),
            "RFE_ACTUAL_RECORDED": (CausalNodeType.OUTCOME, "实际结果"),
            "RISK_VETO_TRIGGERED": (CausalNodeType.COMPLIANCE, "Risk否决"),
        }

        # 构建节点
        for i, ev in enumerate(events):
            etype = ev["event_type"]
            ntype, label = type_map.get(etype, (CausalNodeType.DECISION, etype))
            node_id = f"node_{i}_{etype[:8]}"
            node_map[ev["event_id"]] = node_id

            verdict = ""
            if "data" in ev and isinstance(ev["data"], dict):
                verdict = ev["data"].get("verdict", "")

            graph.add_node(
                node_id=node_id,
                node_type=ntype,
                label=f"{label} ({i+1})",
                properties={
                    "event_id": ev["event_id"],
                    "event_type": etype,
                    "actor": ev["actor"],
                    "verdict": verdict,
                    "timestamp": ev["timestamp"]
                }
            )

        # 构建边
        causal_pairs = [
            ("OPPORTUNITY_DISCOVERED", "SCREENING_COMPLETED", CausalLinkType.ENABLED_BY, 0.9, "信号触发"),
            ("SCREENING_COMPLETED", "INTELLIGENCE_ANALYSIS_COMPLETED", CausalLinkType.LEADS_TO, 0.95, "进入分析"),
            ("INTELLIGENCE_ANALYSIS_COMPLETED", "COMPLIANCE_REVIEW_COMPLETED", CausalLinkType.LEADS_TO, 0.9, "数据就绪"),
            ("COMPLIANCE_REVIEW_COMPLETED", "BOARD_VOTE_CAST", CausalLinkType.LEADS_TO, 0.95, "合规通过"),
            ("BOARD_VOTE_CAST", "INVESTMENT_DECISION_RENDERED", CausalLinkType.LEADS_TO, 1.0, "投票完成"),
            ("RISK_VETO_TRIGGERED", "COMPLIANCE_REVIEW_COMPLETED", CausalLinkType.BLOCKED_BY, 1.0, "合规阻断"),
        ]

        for i, ev in enumerate(events):
            if i == len(events) - 1:
                break
            next_ev = events[i + 1]
            pair = (ev["event_type"], next_ev["event_type"])

            for from_et, to_et, link_type, weight, label in causal_pairs:
                if from_et == pair[0] and to_et == pair[1]:
                    graph.add_edge(
                        from_id=node_map[ev["event_id"]],
                        to_id=node_map[next_ev["event_id"]],
                        link_type=link_type,
                        weight=weight,
                        label=label
                    )

        return graph.to_dict()

    # ----------------------------------------------------------
    # 2. 反事实分析
    # ----------------------------------------------------------

    def counterfactual(
        self,
        opp_id: str,
        intervention_node: str,
        intervention_action: str,
        original_outcome: str
    ) -> dict:
        """
        反事实分析：

        问题：如果在 intervention_node 做不同的干预（intervention_action），
              结果会变成什么？

        逻辑：
        1. 找到 intervention_node 之后的所有路径
        2. 如果干预改变了节点输出
        3. 推断新的结果
        """
        graph_data = self.infer_causal_graph(opp_id)
        if "error" in graph_data:
            return graph_data

        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        # 找到干预节点的出边
        affected_paths = []
        intervention_weight = 1.0

        for edge in edges:
            if edge["from"] == intervention_node:
                # 模拟：如果干预改变了这个边的权重
                new_weight = 0.0 if intervention_action == "block" else 1.0
                intervention_weight *= edge["weight"]

                # 追踪后续节点
                path = [intervention_node]
                current = edge["to"]
                while True:
                    path.append(current)
                    # 找 current 的下一个
                    next_edge = next(
                        (e for e in edges if e["from"] == current),
                        None
                    )
                    if not next_edge:
                        break
                    current = next_edge["to"]
                    if len(path) > 10:  # 防止循环
                        break

                affected_paths.append({
                    "original_path": path,
                    "intervention": intervention_action,
                    "probability": intervention_weight
                })

        # 判断反事实结果
        original_verdict = ""
        for node_id, node_data in nodes.items():
            if node_data["properties"].get("verdict"):
                original_verdict = node_data["properties"]["verdict"]

        # 推断反事实裁决
        if intervention_action == "block":
            if nodes.get(intervention_node, {}).get("type") == CausalNodeType.COMPLIANCE:
                cf_verdict = "REJECT"  # 合规阻断 → REJECT
            else:
                cf_verdict = original_verdict
        elif intervention_action == "enhance":
            cf_verdict = "INVEST"
        else:
            cf_verdict = original_verdict

        changed = cf_verdict != original_verdict

        return {
            "opp_id": opp_id,
            "original_outcome": original_outcome or original_verdict,
            "counterfactual_outcome": cf_verdict,
            "outcome_changed": changed,
            "intervention_node": intervention_node,
            "intervention_action": intervention_action,
            "affected_paths": affected_paths,
            "probability_shift": round(intervention_weight, 3),
            "insight": (
                f"如果在{intervention_node}做'{intervention_action}'干预，"
                f"结果从{original_verdict}变为{cf_verdict}（{'变化' if changed else '无变化'}）"
            )
        }

    # ----------------------------------------------------------
    # 3. 失败归因
    # ----------------------------------------------------------

    def attribute_failure(self, opp_id: str) -> dict:
        """
        失败归因分析：

        找到导致投资失败的致命阻断点，并计算每个节点的贡献度。

        方法：
        1. 从结果回溯，找到 BLOCKED_BY 边
        2. 找到最后一个正常通过的节点
        3. 识别致命阻断点
        """
        graph_data = self.infer_causal_graph(opp_id)
        if "error" in graph_data:
            return graph_data

        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        # 找到所有 BLOCKED_BY 边
        blocked_edges = [e for e in edges if e["type"] == CausalLinkType.BLOCKED_BY]

        if blocked_edges:
            # 找到阻断节点
            blockers = []
            for edge in blocked_edges:
                blocker_node = nodes.get(edge["from"], {})
                blockers.append({
                    "node_id": edge["from"],
                    "node_type": blocker_node.get("type", ""),
                    "label": blocker_node.get("label", ""),
                    "block_strength": edge["weight"],
                    "description": f"{blocker_node.get('label','?')} 阻断后续流程"
                })

            # 找到阻断链的起点
            chain_start = blocked_edges[0]["from"]
            chain_node = nodes.get(chain_start, {})
            cause_analysis = {
                "failure_type": "BLOCKED_BY",
                "root_cause_node": chain_start,
                "root_cause_label": chain_node.get("label", ""),
                "root_cause_type": chain_node.get("type", ""),
                "blockers": blockers,
                "attribution": "该节点为致命阻断点，建议优化该环节"
            }
        else:
            # 没有 BLOCKED_BY，找 REJECT 裁决的节点
            reject_node = None
            for node_id, node_data in nodes.items():
                if node_data["properties"].get("verdict", "").upper() in ("REJECT", "REJECTED"):
                    reject_node = node_id
                    break

            # 回溯路径找到真正的断点
            if reject_node:
                # 找 reject_node 之前的最后一个 LEADS_TO 边
                prev_edges = [e for e in edges if e["to"] == reject_node]
                if prev_edges:
                    prev_edge = prev_edges[0]
                    prev_node = nodes.get(prev_edge["from"], {})
                    cause_analysis = {
                        "failure_type": "REJECT_AT_NODE",
                        "root_cause_node": prev_edge["from"],
                        "root_cause_label": prev_node.get("label", ""),
                        "root_cause_type": prev_node.get("type", ""),
                        "blockers": [],
                        "attribution": f"决策节点{prev_node.get('label','?')}导致拒绝，建议改善该维度评分"
                    }
                else:
                    cause_analysis = {
                        "failure_type": "UNKNOWN",
                        "root_cause_node": reject_node,
                        "attribution": "无法确定具体断点"
                    }
            else:
                cause_analysis = {
                    "failure_type": "NO_REJECT_FOUND",
                    "attribution": "未找到明确失败原因"
                }

        # 评估可干预性
        node_types_intervention = {
            CausalNodeType.SIGNAL: ("易", "信号维度可优化"),
            CausalNodeType.SCREENING: ("中", "初筛标准可调整"),
            CausalNodeType.INTELLIGENCE: ("中", "Intelligence深度可提升"),
            CausalNodeType.COMPLIANCE: ("难", "合规标准固定，需产品调整"),
            CausalNodeType.BOARD_VOTE: ("难", "董事会决策难干预"),
            CausalNodeType.DECISION: ("易", "决策阈值可优化"),
        }

        rctype = cause_analysis.get("root_cause_type", "")
        difficulty, suggestion = node_types_intervention.get(rctype, ("未知", "需人工分析"))
        cause_analysis["intervention_difficulty"] = difficulty
        cause_analysis["intervention_suggestion"] = suggestion

        return cause_analysis

    # ----------------------------------------------------------
    # 4. 最优干预点
    # ----------------------------------------------------------

    def find_intervention_points(self, opp_id: str) -> list[dict]:
        """
        找到所有可能的干预点，按效果/成本排序。

        干预点评估：
        - 越靠近起点，成本越低，效果越大
        - 合规阻断点 = 最优干预点（阻止一切后续浪费）
        - 定价点 = 晚期干预，效果有限
        """
        graph_data = self.infer_causal_graph(opp_id)
        if "error" in graph_data:
            return []

        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        intervention_points = []

        for node_id, node_data in nodes.items():
            ntype = node_data.get("type", "")

            # 评分
            cost_score = 0.0   # 干预成本（越低越好）
            effect_score = 0.0  # 干预效果（越高越好）
            priority = ""

            if ntype == CausalNodeType.SIGNAL:
                cost_score = 1.0; effect_score = 1.0
                priority = "极高" if node_data.get("properties", {}).get("event_type") == "RISK_VETO_TRIGGERED" else "高"
            elif ntype == CausalNodeType.SCREENING:
                cost_score = 2.0; effect_score = 0.8; priority = "高"
            elif ntype == CausalNodeType.INTELLIGENCE:
                cost_score = 3.0; effect_score = 0.7; priority = "中"
            elif ntype == CausalNodeType.COMPLIANCE:
                cost_score = 5.0; effect_score = 1.0; priority = "极高"
            elif ntype == CausalNodeType.BOARD_VOTE:
                cost_score = 4.0; effect_score = 0.6; priority = "中"
            elif ntype == CausalNodeType.DECISION:
                cost_score = 2.0; effect_score = 0.5; priority = "中"

            # 检查是否是阻断点
            is_blocker = any(
                e["type"] == CausalLinkType.BLOCKED_BY and e["from"] == node_id
                for e in edges
            )

            intervention_points.append({
                "node_id": node_id,
                "label": node_data.get("label", ""),
                "type": ntype,
                "is_blocker": is_blocker,
                "cost_score": cost_score,
                "effect_score": effect_score,
                "roi": round(effect_score / max(cost_score, 0.1), 2),
                "priority": priority if is_blocker else f"普通({priority})",
                "intervention_action": self._suggest_action(ntype, is_blocker)
            })

        intervention_points.sort(key=lambda x: x["roi"], reverse=True)
        return intervention_points

    def _suggest_action(self, node_type, is_blocker):
        if is_blocker:
            return "优化该节点或提前干预"
        actions = {
            CausalNodeType.SIGNAL: "选择信号更强的品类进入",
            CausalNodeType.SCREENING: "调整初筛标准",
            CausalNodeType.INTELLIGENCE: "增加Intelligence数据源深度",
            CausalNodeType.COMPLIANCE: "选择合规风险更低的成人版本",
            CausalNodeType.BOARD_VOTE: "优化Board Presentation策略",
            CausalNodeType.DECISION: "调整Governance评分阈值",
        }
        return actions.get(node_type, "维持现状")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS V9.0 Causal Reasoning Engine")
    parser.add_argument("--action", choices=[
        "causal-graph", "counterfactual", "attribute-failure", "intervention-points"
    ], default="causal-graph")
    parser.add_argument("--opp_id", help="Opportunity ID")
    parser.add_argument("--intervention_node", help="干预节点ID")
    parser.add_argument("--intervention_action", choices=["block", "enhance", "remove"], default="block")
    parser.add_argument("--original_outcome", help="原始结果")
    args = parser.parse_args()

    cre = CausalReasoningEngine()

    if args.action == "causal-graph":
        if not args.opp_id:
            print("need --opp_id")
        else:
            result = cre.infer_causal_graph(args.opp_id)
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "counterfactual":
        if not args.opp_id or not args.intervention_node:
            print("need --opp_id and --intervention_node")
        else:
            result = cre.counterfactual(
                opp_id=args.opp_id,
                intervention_node=args.intervention_node,
                intervention_action=args.intervention_action,
                original_outcome=args.original_outcome or ""
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "attribute-failure":
        if not args.opp_id:
            print("need --opp_id")
        else:
            result = cre.attribute_failure(args.opp_id)
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "intervention-points":
        if not args.opp_id:
            print("need --opp_id")
        else:
            points = cre.find_intervention_points(args.opp_id)
            print(json.dumps({"intervention_points": points}, indent=2, ensure_ascii=False))
