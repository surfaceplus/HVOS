"""
HVOS V8.4 — Knowledge Reasoner
======================================
KG 推理引擎：从 Knowledge Graph 的实体关系中，推断隐性商业知识。

核心能力：
  infer_supplier_network()     — 从产品节点推断供应链网络
  infer_brand_competition()     — 构建品牌竞争图谱
  find_similar_winners()       — 找相似成功产品
  predict_supply_chain_risk()   — 预测供应链风险
  infer_causal_chain()         — 从 Event 序列推断因果链
  recommend_next_action()       — 基于 KG 推理推荐下一步行动
"""

import sqlite3
import os
import json
from collections import defaultdict
from datetime import datetime

class KnowledgeReasoner:
    """推理引擎：从 KG 实体/关系中推断新知识"""

    def __init__(self, kg_db=None):
        if kg_db is None:
            kg_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kg.db")
        self.kg_db = kg_db

    def _conn(self):
        conn = sqlite3.connect(self.kg_db)
        conn.row_factory = sqlite3.Row
        return conn

    # ----------------------------------------------------------
    # 1. 推断供应链网络
    # ----------------------------------------------------------

    def infer_supplier_network(self, category=None):
        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT n.node_id, n.name, n.properties
            FROM kg_nodes n
            WHERE n.entity_type = 'Opportunity'
        """)
        opportunities = []
        for row in cur.fetchall():
            r = dict(row)
            r["properties"] = json.loads(r["properties"])
            opportunities.append(r)

        # 查询 HS Code 关系
        cur.execute("""
            SELECT r.from_node, r.to_node, r.rel_type
            FROM kg_relations r
            WHERE r.rel_type = 'HAS_HSCODE'
        """)
        hs_relations = [dict(r) for r in cur.fetchall()]

        # 按 HS Code 分组
        hs_groups = defaultdict(list)
        for rel in hs_relations:
            if "HSCode" in rel["from_node"]:
                hs_groups[rel["from_node"]].append(rel["from_node"])
            if "HSCode" in rel["to_node"]:
                hs_groups[rel["to_node"]].append(rel["to_node"])

        factories = []
        for hs_node, products in hs_groups.items():
            if len(products) >= 2:
                factories.append({
                    "hs_code": hs_node,
                    "shared_product_count": len(products),
                    "confidence": min(0.9, 0.5 + 0.1 * len(products)),
                    "inference": f"{len(products)}个产品共享HS Code → 推断共享供应商"
                })

        conn.close()
        return {
            "type": "SUPPLIER_NETWORK",
            "opportunities_analyzed": len(opportunities),
            "supplier_groups": factories,
            "confidence": min(0.95, 0.6 + 0.05 * len(opportunities))
        }

    # ----------------------------------------------------------
    # 2. 推断竞争图谱
    # ----------------------------------------------------------

    def infer_brand_competition(self, category=None):
        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT n.node_id, n.name, n.properties
            FROM kg_nodes n
            WHERE n.entity_type = 'Opportunity'
        """)
        opportunities = []
        for row in cur.fetchall():
            r = dict(row)
            r["properties"] = json.loads(r["properties"])
            opportunities.append(r)

        # 按 category × market 分组
        market_groups = defaultdict(list)
        for o in opportunities:
            props = o["properties"]
            key = f"{props.get('category','')}_{props.get('market', '')}"
            market_groups[key].append(o["name"])

        competitors = []
        for key, names in market_groups.items():
            if len(names) >= 2:
                cat, mkt = key.rsplit("_", 1)
                competitors.append({
                    "category": cat,
                    "market": mkt,
                    "competitor_count": len(names),
                    "products": names,
                    "level": "HIGH" if len(names) > 3 else "MEDIUM",
                    "confidence": 0.75
                })

        conn.close()
        return {
            "type": "BRAND_COMPETITION",
            "competition_pairs": competitors,
            "confidence": 0.75
        }

    # ----------------------------------------------------------
    # 3. 找相似成功产品
    # ----------------------------------------------------------

    def find_similar_winners(self, category, market, margin=None, limit=5):
        conn = self._conn()
        cur = conn.cursor()

        # 查询所有有投资结论的 Opportunity
        cur.execute("""
            SELECT n.node_id, n.name, n.properties,
                   i.properties as inv_props
            FROM kg_nodes n
            JOIN kg_relations r ON n.node_id = r.to_node
            JOIN kg_nodes i ON r.from_node = i.node_id
            WHERE n.entity_type = 'Opportunity'
            AND r.rel_type = 'INVESTED_IN'
            AND i.entity_type = 'Investment'
        """)

        scored = []
        for row in cur.fetchall():
            r = dict(row)
            props = json.loads(r["properties"])
            inv_props = json.loads(r["inv_props"])
            verdict = inv_props.get("verdict", "REJECT")
            cat = props.get("category", "")
            mkt = props.get("market", "")
            fob = props.get("fob_cost", 0)
            retail = props.get("retail_price", 0)
            calc_margin = (retail - fob) / retail if retail > 0 else 0

            if cat.lower() != category.lower() or mkt.lower() != market.lower():
                continue

            score = 0.0
            reasons = []

            if mkt.lower() == market.lower():
                score += 0.4; reasons.append("市场匹配")

            if verdict.upper() == "INVEST":
                score += 0.4; reasons.append("历史INVEST")

            if margin and abs(calc_margin - margin) < 0.15:
                score += 0.2; reasons.append("毛利率接近")

            if score >= 0.3:
                scored.append({
                    "name": r["name"],
                    "opp_id": r["node_id"],
                    "score": round(min(score, 1.0), 2),
                    "reasons": reasons,
                    "verdict": verdict,
                    "calc_margin": round(calc_margin, 3)
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        conn.close()
        return {
            "type": "SIMILAR_WINNERS",
            "query": {"category": category, "market": market},
            "winners": scored[:limit],
            "total": len(scored),
            "top_score": scored[0]["score"] if scored else 0.0
        }

    # ----------------------------------------------------------
    # 4. 预测供应链风险
    # ----------------------------------------------------------

    def predict_supply_chain_risk(self, category=None):
        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT n.name, n.properties
            FROM kg_nodes n
            WHERE n.entity_type = 'Product'
        """)

        risk_signals = []
        for row in cur.fetchall():
            r = dict(row)
            props = json.loads(r["properties"])
            risks = []
            retail = props.get("retail_price", 0)
            fob = props.get("fob_cost", 0)
            moq = props.get("moq", 0)

            if fob > 50:
                risks.append({"type": "TARIFF", "severity": "HIGH",
                              "desc": f"FOB=${fob}>$50，关税风险"})
            if moq > 300:
                risks.append({"type": "INVENTORY", "severity": "MEDIUM",
                              "desc": f"MOQ={moq}>300，积压风险"})
            if retail > 150:
                risks.append({"type": "CUSTOMS", "severity": "MEDIUM",
                              "desc": f"零售${retail}>$150，清关复杂"})

            if risks:
                risk_signals.append({
                    "product": r["name"],
                    "risks": risks,
                    "overall": "HIGH" if any(x["severity"] == "HIGH" for x in risks) else "MEDIUM"
                })

        conn.close()
        high = [r for r in risk_signals if r["overall"] == "HIGH"]
        med = [r for r in risk_signals if r["overall"] == "MEDIUM"]
        return {
            "type": "SUPPLY_CHAIN_RISK",
            "high_risk": high[:5],
            "medium_risk": med[:5],
            "confidence": 0.80
        }

    # ----------------------------------------------------------
    # 5. 因果链推断
    # ----------------------------------------------------------

    def infer_causal_chain(self, opp_id, event_store_db=None):
        if event_store_db is None:
            event_store_db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reality", "events.db")
        conn = sqlite3.connect(event_store_db)
        cur = conn.cursor()
        cur.execute("""
            SELECT event_id, event_type, description, timestamp
            FROM event_log
            WHERE opportunity_id = ?
            ORDER BY timestamp
        """, (opp_id,))
        events = []
        for row in cur.fetchall():
            events.append({
                "event_id": row[0],
                "event_type": row[1],
                "description": row[2],
                "timestamp": row[3]
            })
        conn.close()

        if not events:
            return {"type": "CAUSAL_CHAIN", "opp_id": opp_id,
                    "error": "No events found"}

        chain = []
        causal_pairs = {
            ("OPPORTUNITY_DISCOVERED", "SCREENING_COMPLETED"): ("发现机会", "进入初筛"),
            ("SCREENING_COMPLETED", "INTELLIGENCE_ANALYSIS_COMPLETED"): ("初筛通过", "Intelligence分析"),
            ("INTELLIGENCE_ANALYSIS_COMPLETED", "COMPLIANCE_REVIEW_COMPLETED"): ("数据就绪", "合规审查"),
            ("COMPLIANCE_REVIEW_COMPLETED", "BOARD_VOTE_CAST"): ("合规通过", "董事会投票"),
            ("BOARD_VOTE_CAST", "INVESTMENT_DECISION_RENDERED"): ("投票完成", "裁决生成"),
        }

        for i in range(len(events) - 1):
            cause = events[i]["event_type"]
            effect = events[i + 1]["event_type"]
            rel = causal_pairs.get((cause, effect))
            if rel:
                chain.append({
                    "step": i + 1,
                    "cause": cause,
                    "effect": effect,
                    "cause_label": rel[0],
                    "effect_label": rel[1]
                })

        verdict_ev = next((e for e in events if "INVESTMENT_DECISION" in e.get("event_type", "")), None)
        if verdict_ev:
            desc = verdict_ev.get("description", "")
            key_insight = "因果链完整，决策为INVEST" if "INVEST" in desc else "因果链完整，决策为REJECT"
        else:
            key_insight = "事件序列过短"

        return {
            "type": "CAUSAL_CHAIN",
            "opp_id": opp_id,
            "events": len(events),
            "chain": chain,
            "key_insight": key_insight,
            "confidence": min(0.9, 0.5 + 0.1 * len(events))
        }

    # ----------------------------------------------------------
    # 6. 推荐下一步行动
    # ----------------------------------------------------------

    def recommend_next_action(self, opp_id, stage):
        stage_map = {
            "DISCOVERED": ("提交初筛", "MEDIUM"),
            "SCREENING_COMPLETED": ("进行Intelligence分析", "HIGH"),
            "INTELLIGENCE_ANALYSIS_COMPLETED": ("提交合规审查", "HIGH"),
            "COMPLIANCE_REVIEW_COMPLETED": ("提交董事会投票", "HIGH"),
            "BOARD_VOTE_CAST": ("等待决策", "LOW"),
            "INVESTMENT_DECISION_RENDERED": ("执行决策", "MEDIUM"),
        }
        action, priority = stage_map.get(stage, ("未知阶段", "LOW"))
        return {
            "opp_id": opp_id,
            "current_stage": stage,
            "recommended_action": action,
            "priority": priority
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS V8.4 Knowledge Reasoner")
    parser.add_argument("--action", choices=[
        "supplier-network", "competition", "similar-winners",
        "supply-risk", "causal-chain", "next-action"
    ], default="similar-winners")
    parser.add_argument("--category")
    parser.add_argument("--market", default="US")
    parser.add_argument("--opp_id")
    parser.add_argument("--stage", default="DISCOVERED")
    parser.add_argument("--margin", type=float)
    args = parser.parse_args()

    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kg.db")
    kr = KnowledgeReasoner(db)

    if args.action == "supplier-network":
        print(json.dumps(kr.infer_supplier_network(args.category), indent=2, ensure_ascii=False))
    elif args.action == "competition":
        print(json.dumps(kr.infer_brand_competition(args.category), indent=2, ensure_ascii=False))
    elif args.action == "similar-winners":
        r = kr.find_similar_winners(
            category=args.category or "厨房小家电",
            market=args.market or "US",
            margin=args.margin
        )
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif args.action == "supply-risk":
        print(json.dumps(kr.predict_supply_chain_risk(args.category), indent=2, ensure_ascii=False))
    elif args.action == "causal-chain":
        if args.opp_id:
            print(json.dumps(kr.infer_causal_chain(args.opp_id,
                event_store_db = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "reality", "events.db")),
                      indent=2, ensure_ascii=False))
        else:
            print("❌ 需要 --opp_id")
    elif args.action == "next-action":
        print(json.dumps(kr.recommend_next_action(args.opp_id or "unknown", args.stage), indent=2, ensure_ascii=False))
