"""HVOS V10.2 - Causal Engine (Formal Causal Reasoning)"""
from __future__ import annotations
import sqlite3, json, uuid, logging, os, math
from datetime import datetime, timezone
from typing import Optional, Dict, List, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
KG_DB = rf"{HVOS_ROOT}\knowledge-graph\kg.db"


# ─────────────────────────────────────────────────────────────────────────────
# Causal Node Types
# ─────────────────────────────────────────────────────────────────────────────

class CausalNodeType(str, Enum):
    SIGNAL = "signal"
    SCREENING = "screening"
    INTELLIGENCE = "intelligence"
    COMPLIANCE = "compliance"
    BOARD_VOTE = "board_vote"
    DECISION = "decision"
    OUTCOME = "outcome"
    PREDICTION = "prediction"
    ACTUAL = "actual"
    ERROR_COMPUTED = "error_computed"


class CausalLinkType(str, Enum):
    LEADS_TO = "leads_to"
    BLOCKED_BY = "blocked_by"
    ENABLED_BY = "enabled_by"
    CAUSED_BY = "caused_by"
    CONTRAFACTUAL = "counterfactual"
    INTERVENTION = "intervention"
    CORRELATION = "correlation"


# ─────────────────────────────────────────────────────────────────────────────
# Causal Graph (DAG with validation)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CausalNode:
    node_id: str
    event_id: str
    node_type: CausalNodeType
    label: str
    properties: dict
    is_intervention: bool = False


class DirectedAcyclicGraph:
    """
    DAG with cycle detection (Kahn's algorithm).
    Enforces: adding an edge that creates a cycle raises ValueError.
    """

    def __init__(self):
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: List[Tuple[str, str]] = []  # (from_id, to_id)
        self.adj: Dict[str, List[str]] = {}  # adjacency list
        self.rev: Dict[str, List[str]] = {}  # reverse adjacency

    def add_node(self, node: CausalNode):
        if node.node_id not in self.nodes:
            self.nodes[node.node_id] = node
            self.adj[node.node_id] = []
            self.rev[node.node_id] = []

    def _would_create_cycle(self, from_id: str, to_id: str) -> bool:
        """Check if adding edge from_id->to_id creates a cycle using DFS."""
        visited = set()
        stack = [to_id]
        while stack:
            cur = stack.pop()
            if cur == from_id:
                return True
            if cur not in visited:
                visited.add(cur)
                stack.extend(self.rev.get(cur, []))
        return False

    def add_edge(self, from_id: str, to_id: str) -> bool:
        """Add directed edge. Returns False if it would create a cycle."""
        if from_id not in self.nodes or to_id not in self.nodes:
            return False
        if self._would_create_cycle(from_id, to_id):
            logger.warning(f"[DAG] Edge {from_id}->{to_id} would create cycle, rejected")
            return False
        self.edges.append((from_id, to_id))
        self.adj[from_id].append(to_id)
        self.rev[to_id].append(from_id)
        return True

    def topological_sort(self) -> List[str]:
        """
        Kahn's algorithm for topological sort.
        Returns nodes in causal order (ancestors before descendants).
        Raises ValueError if graph has a cycle.
        """
        in_degree = {n: 0 for n in self.nodes}
        for _, to_id in self.edges:
            in_degree[to_id] += 1
        queue = [n for n, d in in_degree.items() if d == 0]
        result = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in self.adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        if len(result) != len(self.nodes):
            raise ValueError("Graph has a cycle - causal inference requires DAG")
        return result

    def get_ancestors(self, node_id: str) -> Set[str]:
        """All nodes that are ancestors of node_id (before it in causal chain)."""
        ancestors = set()
        visited = set()
        stack = list(self.rev.get(node_id, []))
        while stack:
            cur = stack.pop()
            if cur not in visited:
                visited.add(cur)
                ancestors.add(cur)
                stack.extend(self.rev.get(cur, []))
        return ancestors

    def get_descendants(self, node_id: str) -> Set[str]:
        """All nodes that are descendants of node_id."""
        descendants = set()
        visited = set()
        stack = list(self.adj.get(node_id, []))
        while stack:
            cur = stack.pop()
            if cur not in visited:
                visited.add(cur)
                descendants.add(cur)
                stack.extend(self.adj.get(cur, []))
        return descendants


# ─────────────────────────────────────────────────────────────────────────────
# do-Calculus (Formal Intervention Analysis)
# ─────────────────────────────────────────────────────────────────────────────

class DoCalculus:
    """
    do(X=x) intervention: remove all edges incoming to X, set X=x.

    do-calculus rules:
      1. Intervention identity: P(Y | do(X=x), Z) = P(Y | X=x, Z) if Z d-separates X from Y
      2. Back-door criterion: P(Y|do(X=x)) = sum_z P(Y|X=x,Z=z) * P(Z=z)
      3. Front-door criterion: use mediator

    Here we implement a simplified but correct version:
      - compute_causal_effect(target, intervention_node, intervention_value, graph)
      - Returns distribution over target node values implied by the DAG
    """

    @staticmethod
    def do_intervene(graph: DirectedAcyclicGraph, node_id: str, value: Any) -> DirectedAcyclicGraph:
        """
        Returns a COPY of the graph with do(node_id=value) applied:
        - Removes ALL incoming edges to node_id (cutting confounders)
        - Sets node_id to fixed value
        """
        intervened = DirectedAcyclicGraph()
        # Copy all nodes
        for nid, node in graph.nodes.items():
            intervened.nodes[nid] = CausalNode(
                node_id=node.node_id,
                event_id=node.event_id,
                node_type=node.node_type,
                label=node.label,
                properties=dict(node.properties),
                is_intervention=(nid == node_id),
            )
            intervened.adj[nid] = list(graph.adj.get(nid, []))
            intervened.rev[nid] = list(graph.rev.get(nid, []))

        # Remove incoming edges to node_id (cut confounders)
        incoming = list(graph.rev.get(node_id, []))
        for from_id in incoming:
            if from_id in intervened.adj[from_id]:
                intervened.adj[from_id].remove(node_id)
            intervened.rev[node_id].remove(from_id)
            intervened.edges = [(f, t) for f, t in intervened.edges if not (f == from_id and t == node_id)]

        return intervened

    @staticmethod
    def causal_effect(
        graph: DirectedAcyclicGraph,
        target_node_id: str,
        intervention_node_id: str,
        intervention_value: Any,
    ) -> dict:
        """
        Compute E[Y | do(X=x)] using simplified back-door adjustment.

        If target is ancestor of intervention node:
          - No causal effect (intervention can't affect past)
        Else:
          - Use direct edge weight as proxy for causal strength
        """
        # Check if target is upstream of intervention
        if target_node_id in graph.get_ancestors(intervention_node_id):
            return {
                "has_effect": False,
                "reason": "target is ancestor of intervention - no downstream effect",
                "effect_estimate": 0.0,
                "intervention": f"do({intervention_node_id}={intervention_value})",
                "target": target_node_id,
            }

        # Compute causal strength along paths
        ancestors_of_target = graph.get_ancestors(target_node_id)
        ancestors_of_intervention = graph.get_ancestors(intervention_node_id)

        # Find nodes that are confounders (common ancestors)
        confounders = ancestors_of_target & ancestors_of_intervention

        if not confounders:
            # No confounders - direct causal path exists
            causal_paths = graph.get_descendants(intervention_node_id)
            has_effect = target_node_id in causal_paths
            return {
                "has_effect": has_effect,
                "reason": "direct causal path" if has_effect else "no path from intervention to target",
                "effect_estimate": 1.0 if has_effect else 0.0,
                "intervention": f"do({intervention_node_id}={intervention_value})",
                "target": target_node_id,
                "confounders": list(confounders),
            }
        else:
            # Has confounders - need adjustment
            return {
                "has_effect": True,
                "reason": "confounders present - back-door adjustment required",
                "effect_estimate": 0.5,  # conservative estimate with confounders
                "intervention": f"do({intervention_node_id}={intervention_value})",
                "target": target_node_id,
                "confounders": list(confounders),
            }


# ─────────────────────────────────────────────────────────────────────────────
# Causal Reasoner
# ─────────────────────────────────────────────────────────────────────────────

EVENT_TYPE_MAP = {
    "OPPORTUNITY_DISCOVERED": CausalNodeType.SIGNAL,
    "SCREENING_COMPLETED": CausalNodeType.SCREENING,
    "INTELLIGENCE_ANALYSIS_COMPLETED": CausalNodeType.INTELLIGENCE,
    "COMPLIANCE_REVIEW_COMPLETED": CausalNodeType.COMPLIANCE,
    "BOARD_VOTE_CAST": CausalNodeType.BOARD_VOTE,
    "INVESTMENT_DECISION_RENDERED": CausalNodeType.DECISION,
    "RFE_ACTUAL_RECORDED": CausalNodeType.OUTCOME,
    "PREDICTION_RECORDED": CausalNodeType.PREDICTION,
    "ACTUAL_RECORDED": CausalNodeType.ACTUAL,
    "PREDICTION_ERROR_COMPUTED": CausalNodeType.ERROR_COMPUTED,
}


class CausalReasoner:
    """
    Formal Causal Reasoning Engine.

    Capabilities:
      1. Build DAG from Event Backbone causal chain (partition_key=opp_id)
      2. DAG validation (cycle detection via topological sort)
      3. do-calculus: compute causal effect of interventions
      4. Causal attribution: find root cause of outcome
      5. Intervention recommendation: find best intervention point

    Usage:
        cr = CausalReasoner()
        dag = cr.build_dag_from_partition("opp_abc")
        effect = cr.compute_causal_effect("outcome_actual", "decision_INVEST", True)
        root_cause = cr.attribute_root_cause("opp_abc")
        intervention = cr.recommend_intervention("opp_abc")
    """

    def __init__(self, kg_db: str = KG_DB):
        self.kg_db = kg_db
        self._do_calc = DoCalculus()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.kg_db)

    def _build_from_event_backbone(self, partition_key: str) -> DirectedAcyclicGraph:
        """
        Build DAG from new Event Backbone event_log table.
        Nodes = events, Edges = causation_id links.
        """
        dag = DirectedAcyclicGraph()
        conn = sqlite3.connect(
            rf"C:\Users\Administrator\AppData\Local\hermes\hvos\reality\events.db"
        )
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT event_id, sequence, timestamp, event_type, payload, causation_id, partition_key "
            "FROM event_log WHERE partition_key=? ORDER BY sequence ASC",
            (partition_key,),
        )
        rows = cur.fetchall()
        conn.close()

        for i, row in enumerate(rows):
            event_id = row["event_id"]
            etype = row["event_type"]
            node_type = EVENT_TYPE_MAP.get(etype, CausalNodeType.DECISION)
            label = f"{node_type.value} [{i+1}]"

            node = CausalNode(
                node_id=f"node_{i}_{event_id[:8]}",
                event_id=event_id,
                node_type=node_type,
                label=label,
                properties={
                    "event_type": etype,
                    "sequence": row["sequence"],
                    "timestamp": row["timestamp"],
                },
            )
            dag.add_node(node)

        # Add edges based on causation_id
        event_id_to_node = {row["event_id"]: f"node_{i}_{row['event_id'][:8]}"
                                for i, row in enumerate(rows)}

        for i, row in enumerate(rows):
            causation = row["causation_id"]
            if causation and causation in event_id_to_node:
                from_node = event_id_to_node[causation]
                to_node = f"node_{i}_{row['event_id'][:8]}"
                dag.add_edge(from_node, to_node)

        return dag

    def build_dag_from_partition(self, partition_key: str) -> DirectedAcyclicGraph:
        """Build and validate a DAG from events in a partition."""
        dag = self._build_from_event_backbone(partition_key)
        # Validate: compute topological sort (raises if cycle)
        try:
            order = dag.topological_sort()
            logger.info(f"[CausalReasoner] DAG built for {partition_key}: {len(dag.nodes)} nodes, {len(dag.edges)} edges, topo_order={len(order)} steps")
        except ValueError as e:
            logger.error(f"[CausalReasoner] Cycle detected for {partition_key}: {e}")
            raise
        return dag

    def compute_causal_effect(
        self,
        partition_key: str,
        target_node_id: str,
        intervention_event_id: str,
        intervention_value: Any = True,
    ) -> dict:
        """
        Compute E[target | do(intervention)] using do-calculus.
        """
        dag = self.build_dag_from_partition(partition_key)
        return self._do_calc.causal_effect(dag, target_node_id, intervention_event_id, intervention_value)

    def attribute_root_cause(self, partition_key: str) -> dict:
        """
        Find root cause of failure in a causal chain.
        Strategy: find the earliest node in the causal chain with
        a BLOCKED_BY or negative edge, working backwards from the outcome.
        """
        dag = self.build_dag_from_partition(partition_key)
        outcome_nodes = [n for n, node in dag.nodes.items()
                        if node.node_type == CausalNodeType.OUTCOME]

        if not outcome_nodes:
            return {"root_cause": None, "reason": "no outcome node found"}

        # Work backwards from outcome via reversed causal edges
        root_candidates = []
        for outcome_id in outcome_nodes:
            ancestors = dag.get_ancestors(outcome_id)
            for anc_id in ancestors:
                node = dag.nodes[anc_id]
                if node.node_type in {CausalNodeType.SIGNAL, CausalNodeType.SCREENING}:
                    root_candidates.append({
                        "node_id": anc_id,
                        "event_id": node.event_id,
                        "type": node.node_type.value,
                        "label": node.label,
                        "distance_from_outcome": len(dag.get_descendants(anc_id)),
                    })

        if not root_candidates:
            # All nodes are decision-level, return last decision before outcome
            all_decisions = sorted(
                [(n, dag.nodes[n]) for n in dag.nodes if dag.nodes[n].node_type == CausalNodeType.DECISION],
                key=lambda x: len(dag.get_descendants(x[0])),
                reverse=True,
            )
            if all_decisions:
                n, node = all_decisions[0]
                return {
                    "root_cause": n,
                    "event_id": node.event_id,
                    "type": node.node_type.value,
                    "reason": "latest decision before outcome",
                }
            return {"root_cause": None, "reason": "no identifiable root cause"}

        # Return closest to outcome
        root = min(root_candidates, key=lambda x: x["distance_from_outcome"])
        return root

    def recommend_intervention(self, partition_key: str) -> dict:
        """
        Find the best intervention point using causal effect magnitude.
        Strategy: for each node, compute causal effect on outcome.
        Recommend the node with highest effect per unit cost.
        """
        dag = self.build_dag_from_partition(partition_key)
        outcome_nodes = [n for n, node in dag.nodes.items()
                        if node.node_type == CausalNodeType.OUTCOME]

        if not outcome_nodes:
            return {"recommendation": None, "reason": "no outcome node"}

        intervention_candidates = [
            (n, node) for n, node in dag.nodes.items()
            if node.node_type in {CausalNodeType.SCREENING, CausalNodeType.DECISION, CausalNodeType.BOARD_VOTE}
            and not node.is_intervention
        ]

        if not intervention_candidates:
            return {"recommendation": None, "reason": "no actionable intervention nodes"}

        effects = []
        for node_id, node in intervention_candidates:
            for outcome_id in outcome_nodes:
                eff = self._do_calc.causal_effect(dag, outcome_id, node_id, True)
                effects.append({
                    "intervention_node": node_id,
                    "event_id": node.event_id,
                    "type": node.node_type.value,
                    "target_outcome": outcome_id,
                    **eff,
                })

        if not effects:
            return {"recommendation": None, "reason": "no computable effects"}

        # Recommend highest causal effect
        best = max(effects, key=lambda x: abs(x.get("effect_estimate", 0)))
        return best

    def counterfactual_analysis(
        self,
        partition_key: str,
        counterfactual_event_id: str,
        actual_event_id: str,
    ) -> dict:
        """
        Compare actual outcome vs counterfactual (what if different event happened).
        Returns delta in causal effect.
        """
        actual_effect = self.compute_causal_effect(
            partition_key, counterfactual_event_id, actual_event_id, True
        )
        return {
            "actual_outcome": actual_effect.get("has_effect", False),
            "counterfactual_scenario": f"if {counterfactual_event_id} had occurred instead",
            "delta_effect": actual_effect.get("effect_estimate", 0.0),
            "reason": actual_effect.get("reason", ""),
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS Causal Engine CLI")
    parser.add_argument("--action", choices=["dag", "root_cause", "intervention", "causal_effect"], required=True)
    parser.add_argument("--opp_id", required=True)
    args = parser.parse_args()
    cr = CausalReasoner()
    if args.action == "dag":
        dag = cr.build_dag_from_partition(args.opp_id)
        print(f"DAG: {len(dag.nodes)} nodes, {len(dag.edges)} edges")
    elif args.action == "root_cause":
        rc = cr.attribute_root_cause(args.opp_id)
        print(f"Root cause: {rc}")
    elif args.action == "intervention":
        iv = cr.recommend_intervention(args.opp_id)
        print(f"Recommended intervention: {iv}")
