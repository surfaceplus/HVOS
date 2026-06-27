"""
HVOS V9.0 - Agent Ecosystem
Auto Birth/Promotion/Retirement
"""

import sqlite3, json, uuid
from datetime import datetime

ADB = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph\agent_factory.db"
SDB = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge_graph\strategy_memory.db"

class AgentEcosystem:
    def _aql(self, sql, params=()):
        c = sqlite3.connect(ADB)
        cur = c.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        c.close()
        return rows

    def _sql(self, sql, params=()):
        c = sqlite3.connect(ADB)
        cur = c.cursor()
        cur.execute(sql, params)
        c.commit()
        c.close()

    def detect_gaps(self):
        ex = self._aql(
            "SELECT agent_id,category,market,dimension,accuracy,status "
            "FROM agents WHERE agent_type='category_specialist' "
            "AND status IN ('active','candidate')"
        )
        sc = sqlite3.connect(SDB)
        scur = sc.cursor()
        scur.execute(
            "SELECT DISTINCT category,market,COUNT(*) "
            "FROM strategy_library WHERE confidence>=0.3 GROUP BY category,market"
        )
        cats = list(scur.fetchall())
        sc.close()
        gaps = []
        dim_map = {"厨房": "market_size", "智能手表": "compliance_risk",
                    "健身追踪": "market_size", "美妆": "market_size"}
        for cat, mkt, cnt in cats:
            match = [r for r in ex if r[1] == cat and r[2] == mkt]
            if not match:
                gaps.append({
                    "gap_type": "CATEGORY_NO_AGENT",
                    "category": cat,
                    "market": mkt,
                    "severity": "HIGH",
                    "reason": f"no specialist for {cat}/{mkt}, {cnt} strategies pending",
                    "suggested_dimension": dim_map.get(cat, "market_size")
                })
            else:
                low = [r for r in match if r[4] and r[4] < 0.5]
                if low:
                    gaps.append({
                        "gap_type": "LOW_ACCURACY",
                        "category": cat, "market": mkt,
                        "severity": "HIGH",
                        "affected_agents": [r[0] for r in low]
                    })
        return gaps

    def auto_birth(self, cat, mkt, reason="", conf=0.6):
        aid = f"AGT_AUTO_{uuid.uuid4().hex[:8]}"
        name = f"{cat}_{mkt}_AutoAgent"
        dim_map = {"厨房": "market_size", "智能手表": "compliance_risk",
                    "健身追踪": "market_size", "美妆": "market_size"}
        dimension = dim_map.get(cat, "market_size")
        now = datetime.now().isoformat()
        self._sql(
            "INSERT INTO agents "
            "(agent_id,name,agent_type,category,market,dimension,specialty,"
            "decisions_total,decisions_correct,accuracy,avg_score,status,"
            "influence_weight,confidence,skills,tags,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, name, "category_specialist", cat, mkt, dimension,
             f"auto-born: {reason}", 0, 0, conf, conf * 10, "active",
             conf * 0.5, conf, "[]", json.dumps(["auto-born"]), now)
        )
        return {"agent_id": aid, "name": name, "category": cat,
                "market": mkt, "status": "active"}

    def auto_promote(self, aid, lv=1):
        rows = self._aql(
            "SELECT influence_weight,confidence FROM agents WHERE agent_id=?", (aid,))
        if not rows:
            return {"error": "not found"}
        iw, conf = rows[0]
        niw = min(0.95, iw + 0.1 * lv)
        nconf = min(0.99, conf + 0.05 * lv)
        self._sql(
            "UPDATE agents SET influence_weight=?,confidence=? WHERE agent_id=?",
            (niw, nconf, aid))
        return {"agent_id": aid, "old_iw": round(iw, 3), "new_iw": round(niw, 3),
                "old_conf": round(conf, 3), "new_conf": round(nconf, 3)}

    def ecosystem_report(self):
        rows = self._aql(
            "SELECT agent_id,agent_type,accuracy,decisions_total,status FROM agents"
        )
        n = len(rows)
        active = [r for r in rows if r[4] == "active"]
        specs = [r for r in rows if r[1] == "category_specialist"]
        high = [r for r in rows if r[2] and r[2] >= 0.7]
        gaps = self.detect_gaps()
        h = (0.3 * len(specs) / max(n, 1) +
             0.4 * len(high) / max(n, 1) +
             0.3 * (1 - min(len(gaps) / 10, 1)))
        status = "EXCELLENT" if h >= 0.8 else "GOOD" if h >= 0.6 else "FAIR" if h >= 0.4 else "POOR"
        return {
            "total_agents": n, "active": len(active),
            "specialists": len(specs), "high_accuracy": len(high),
            "health_score": round(h, 3), "health_status": status,
            "gaps_detected": len(gaps), "gaps": gaps[:5]
        }

    def run_autonomous_cycle(self):
        r = {"gaps_detected": 0, "new_agents": [], "promotions": [], "retirements": []}
        gaps = self.detect_gaps()
        r["gaps_detected"] = len(gaps)

        # Auto-birth: fill gaps
        for g in gaps:
            if g["gap_type"] == "CATEGORY_NO_AGENT":
                ag = self.auto_birth(g["category"], g["market"], g["reason"])
                r["new_agents"].append(ag)

        # Evaluate existing agents
        rows = self._aql(
            "SELECT agent_id,name,accuracy,decisions_total FROM agents "
            "WHERE status='active' AND agent_type='category_specialist'"
        )
        for row in rows:
            aid, name, acc, decs = row
            if acc and acc >= 0.8 and decs >= 3:
                p = self.auto_promote(aid)
                p["name"] = name
                r["promotions"].append(p)
            elif acc is not None and acc < 0.3 and decs >= 5:
                self._sql(
                    "UPDATE agents SET status='retired',influence_weight=0 "
                    "WHERE agent_id=?", (aid,))
                r["retirements"].append({"agent_id": aid, "name": name})

        rep = self.ecosystem_report()
        r["health_score"] = rep["health_score"]
        r["health_status"] = rep["health_status"]
        return r


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="HVOS V9.0 Agent Ecosystem")
    p.add_argument("--action", choices=["gaps", "birth", "promote", "report", "cycle"],
                   default="cycle")
    p.add_argument("--category")
    p.add_argument("--market", default="US")
    p.add_argument("--agent_id")
    p.add_argument("--reason")
    args = p.parse_args()
    eco = AgentEcosystem()

    if args.action == "gaps":
        print(json.dumps({"gaps": eco.detect_gaps()}, indent=2, ensure_ascii=False))
    elif args.action == "birth":
        if not args.category:
            print("need --category")
        else:
            print(json.dumps(eco.auto_birth(args.category, args.market,
                                          args.reason or ""), indent=2))
    elif args.action == "promote":
        if not args.agent_id:
            print("need --agent_id")
        else:
            print(json.dumps(eco.auto_promote(args.agent_id), indent=2))
    elif args.action == "report":
        print(json.dumps(eco.ecosystem_report(), indent=2, ensure_ascii=False))
    elif args.action == "cycle":
        print(json.dumps(eco.run_autonomous_cycle(), indent=2, ensure_ascii=False))
