# HVOS V10 — Policy Governor
# ===========================
# Replaces the "generate-without-governance" model of policy_learning_engine.py.
# Implements: semantic dedup, decoy, promotion, retirement, lifecycling.
#
# Policy Lifecycle (V10):
#   Draft → Candidate → Active → Trusted → Decaying → Archived → Deleted
#
# Target: < 500 active policies (from current 2,817)

from __future__ import annotations

import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("policy_governor")

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
STRATEGY_DB = rf"{HVOS_ROOT}\knowledge-graph\strategy_memory.db"

# ──────────────────────────────────────────────────────────────
# Policy Lifecycle States
# ──────────────────────────────────────────────────────────────


class PolicyState:
    DRAFT = "draft"       # Auto-generated, not yet reviewed
    CANDIDATE = "candidate"  # Under review
    ACTIVE = "active"     # In use for scoring
    TRUSTED = "trusted"   # Validated by multiple successes
    DECAYING = "decaying"  # Losing effectiveness
    ARCHIVED = "archived"  # Retired but record kept
    DELETED = "deleted"   # Permanently removed


# ──────────────────────────────────────────────────────────────
# Policy Governor
# ──────────────────────────────────────────────────────────────


class PolicyGovernor:
    """
    Policy governance engine.

    Responsibilities:
      1. Semantic deduplication
      2. Lifecycle management (promote/demote/retire)
      3. Quality scoring
      4. Cap enforcement (< 500 active)
    """

    def __init__(self, db_path: str = STRATEGY_DB):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ──────────────────────────────────────────────────────────
    # 1. Policy Quality Scoring
    # ──────────────────────────────────────────────────────────

    def score_policy(self, policy_id: str) -> dict:
        """
        Multi-dimensional quality score for a policy.

        Factors:
          - accuracy: has this policy led to correct decisions? (0-40)
          - support: how many strategy rules back it? (0-25)
          - recency: how recently was it used/last updated? (0-20)
          - specificity: how specific are its trigger conditions? (0-15)
        """
        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT policy_id, name, policy_type, trigger_conditions, governance_rule,
                   confidence, source_strategy_ids, status,
                   approved_at, updated_at, notes
            FROM governance_policies
            WHERE policy_id = ?
        """, (policy_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return {"policy_id": policy_id, "score": 0, "error": "not_found"}

        d = dict(row)

        # ── Accuracy (0-40) ──
        conf = d["confidence"] or 0
        accuracy = conf * 40

        # ── Support (0-25) ──
        sources = json.loads(d["source_strategy_ids"] or "[]")
        n_sources = len(sources)
        support = min(25, n_sources * 5)

        # ── Recency (0-20) ──
        recency = 10  # default
        updated = d.get("updated_at") or d.get("approved_at")
        if updated:
            try:
                days = (datetime.now() - datetime.fromisoformat(updated)).days
                if days <= 30:
                    recency = 20
                elif days <= 90:
                    recency = 15
                elif days <= 180:
                    recency = 10
                elif days <= 365:
                    recency = 5
                else:
                    recency = 2
            except Exception:
                pass

        # ── Specificity (0-15) ──
        triggers = json.loads(d["trigger_conditions"] or "{}")
        n_conditions = sum(1 for v in triggers.values() if v)
        specificity = min(15, n_conditions * 3)

        total = round(accuracy + support + recency + specificity, 1)

        return {
            "policy_id": policy_id,
            "name": d["name"],
            "type": d["policy_type"],
            "status": d["status"],
            "score": total,
            "factors": {
                "accuracy": round(accuracy, 1),
                "support": round(support, 1),
                "recency": round(recency, 1),
                "specificity": round(specificity, 1),
            },
            "target_state": self._target_state(total, d["status"]),
        }

    def _target_state(self, score: float, current_status: str) -> str:
        """Determine target lifecycle state based on score."""
        if current_status == "deleted":
            return PolicyState.DELETED
        if score >= 85:
            return PolicyState.TRUSTED
        elif score >= 60:
            return PolicyState.ACTIVE
        elif score >= 40:
            return PolicyState.DECAYING
        elif score >= 20:
            return PolicyState.ARCHIVED
        else:
            return PolicyState.DELETED

    # ──────────────────────────────────────────────────────────
    # 2. Semantic Deduplication
    # ──────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> set:
        """Simple tokenization for similarity comparison."""
        import re
        tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text.lower())
        return set(tokens)

    def _jaccard(self, a: set, b: set) -> float:
        if not a and not b:
            return 1.0
        inter = a & b
        union = a | b
        return len(inter) / len(union) if union else 0.0

    def deduplicate(
        self,
        policy_type: str = "",
        similarity_threshold: float = 0.80,
        dry_run: bool = True,
    ) -> dict:
        """
        Find and merge semantically similar policies.

        Strategy:
          1. Group by policy_type
          2. Within each group, compare trigger_conditions + governance_rule
          3. Merge pairs with similarity > threshold
        """
        conn = self._conn()
        cur = conn.cursor()

        if policy_type:
            cur.execute("""
                SELECT policy_id, name, policy_type, trigger_conditions, governance_rule,
                       confidence, status
                FROM governance_policies
                WHERE policy_type = ? AND status IN ('active', 'trusted', 'pending')
                ORDER BY confidence DESC
            """, (policy_type,))
        else:
            cur.execute("""
                SELECT policy_id, name, policy_type, trigger_conditions, governance_rule,
                       confidence, status
                FROM governance_policies
                WHERE status IN ('active', 'trusted', 'pending')
                ORDER BY policy_type, confidence DESC
            """)
        rows = cur.fetchall()
        conn.close()

        # Group by type
        groups = defaultdict(list)
        for row in rows:
            groups[row["policy_type"]].append(dict(row))

        merge_candidates = []
        merged_count = 0

        for ptype, policies in groups.items():
            n = len(policies)
            seen_pairs = set()

            for i in range(n):
                for j in range(i + 1, n):
                    pi, pj = policies[i], policies[j]
                    pair_key = tuple(sorted([pi["policy_id"], pj["policy_id"]]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    # Compare trigger conditions
                    ti = json.dumps(pi["trigger_conditions"] or {}, sort_keys=True)
                    tj = json.dumps(pj["trigger_conditions"] or {}, sort_keys=True)
                    trigger_sim = self._jaccard(self._tokenize(ti), self._tokenize(tj))

                    if trigger_sim < 0.5:
                        continue  # Must have similar triggers

                    # Compare governance rules
                    gi = json.dumps(pi["governance_rule"] or {}, sort_keys=True)
                    gj = json.dumps(pj["governance_rule"] or {}, sort_keys=True)
                    rule_sim = self._jaccard(self._tokenize(gi), self._tokenize(gj))

                    overall = 0.5 * trigger_sim + 0.5 * rule_sim

                    if overall >= similarity_threshold:
                        merge_candidates.append({
                            "keep_id": pi["policy_id"],
                            "keep_name": pi["name"],
                            "merge_id": pj["policy_id"],
                            "merge_name": pj["name"],
                            "type": ptype,
                            "similarity": round(overall, 4),
                            "trigger_sim": round(trigger_sim, 4),
                            "rule_sim": round(rule_sim, 4),
                        })

                        if not dry_run:
                            self._merge_pair(pi["policy_id"], pj["policy_id"])
                            merged_count += 1

        return {
            "merge_candidates": len(merge_candidates),
            "merged": merged_count if not dry_run else 0,
            "dry_run": dry_run,
            "candidates": merge_candidates[:30],
        }

    def _merge_pair(self, keep_id: str, merge_id: str):
        """Merge merge_id into keep_id."""
        conn = self._conn()
        cur = conn.cursor()

        # Get source for merge_id
        cur.execute("SELECT source_strategy_ids FROM governance_policies WHERE policy_id = ?", (merge_id,))
        merge_row = cur.fetchone()
        if merge_row:
            merge_sources = set(json.loads(merge_row["source_strategy_ids"] or "[]"))

            # Add to keep
            cur.execute("SELECT source_strategy_ids FROM governance_policies WHERE policy_id = ?", (keep_id,))
            keep_row = cur.fetchone()
            if keep_row:
                keep_sources = set(json.loads(keep_row["source_strategy_ids"] or "[]"))
                keep_sources |= merge_sources
                cur.execute("""
                    UPDATE governance_policies
                    SET source_strategy_ids = ?, updated_at = ?
                    WHERE policy_id = ?
                """, (json.dumps(sorted(list(keep_sources))), datetime.now().isoformat(), keep_id))

        # Archive merged
        cur.execute("""
            UPDATE governance_policies
            SET status = 'archived', notes = ?, updated_at = ?
            WHERE policy_id = ?
        """, (f"Merged into {keep_id}", datetime.now().isoformat(), merge_id))

        conn.commit()
        conn.close()
        logger.info(f"[PolicyGovernor] Merged {merge_id} → {keep_id}")

    # ──────────────────────────────────────────────────────────
    # 3. Lifecycle Management
    # ──────────────────────────────────────────────────────────

    def promote_policies(self, min_score: float = 85) -> int:
        """Promote high-scoring policies to Trusted."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT policy_id FROM governance_policies
            WHERE status IN ('active', 'candidate')
        """)
        promoted = 0
        for row in cur.fetchall():
            score_info = self.score_policy(row["policy_id"])
            if score_info["score"] >= min_score:
                cur.execute("""
                    UPDATE governance_policies
                    SET status = 'trusted', updated_at = ?
                    WHERE policy_id = ?
                """, (datetime.now().isoformat(), row["policy_id"]))
                promoted += 1
        conn.commit()
        conn.close()
        return promoted

    def retire_decayed(self, max_score: float = 20, dry_run: bool = True) -> dict:
        """Retire policies that have decayed below threshold."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT policy_id FROM governance_policies
            WHERE status IN ('active', 'decaying', 'trusted')
        """)
        retired = 0
        deleted = 0
        for row in cur.fetchall():
            score_info = self.score_policy(row["policy_id"])
            if score_info["score"] <= max_score:
                if not dry_run:
                    target = score_info["target_state"]
                    cur.execute("""
                        UPDATE governance_policies
                        SET status = ?, updated_at = ?, notes = ?
                        WHERE policy_id = ?
                    """, (target, datetime.now().isoformat(),
                          f"Auto-retired: score={score_info['score']}", row["policy_id"]))
                if score_info["target_state"] == PolicyState.DELETED:
                    deleted += 1
                else:
                    retired += 1
        conn.commit()
        conn.close()
        return {"retired": retired, "deleted": deleted, "dry_run": dry_run}

    def enforce_cap(self, max_active: int = 500) -> dict:
        """
        Enforce the active policy cap.
        If more than max_active policies are active/trusted,
        retire the lowest-scoring ones.
        """
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT policy_id, name FROM governance_policies
            WHERE status IN ('active', 'trusted')
            ORDER BY confidence ASC
        """)
        policies = [(r["policy_id"], r["name"]) for r in cur.fetchall()]

        excess = len(policies) - max_active
        if excess <= 0:
            conn.close()
            return {"excess": 0, "retired": 0, "message": "Cap not exceeded"}

        # Score and sort by quality (ascending)
        scored = []
        for pid, name in policies:
            si = self.score_policy(pid)
            scored.append((pid, name, si["score"]))

        scored.sort(key=lambda x: x[2])  # lowest first

        to_retire = scored[:excess]
        for pid, name, score in to_retire:
            cur.execute("""
                UPDATE governance_policies
                SET status = 'archived', notes = ?, updated_at = ?
                WHERE policy_id = ?
            """, (f"Cap enforcement: score={score:.1f}", datetime.now().isoformat(), pid))
            logger.info(f"[PolicyGovernor] Cap retired: {name} (score={score:.1f})")

        conn.commit()
        conn.close()

        return {
            "excess": excess,
            "retired": len(to_retire),
            "remaining_active": max_active,
            "retired_policies": [{"policy_id": pid, "name": name, "score": score} for pid, name, score in to_retire[:10]],
        }

    # ──────────────────────────────────────────────────────────
    # 4. Governance Report
    # ──────────────────────────────────────────────────────────

    def governance_report(self) -> dict:
        """Full policy governance report."""
        conn = self._conn()
        cur = conn.cursor()

        # Count by status
        status_counts = {}
        cur.execute("""
            SELECT status, COUNT(*) as n FROM governance_policies
            GROUP BY status
        """)
        for r in cur.fetchall():
            status_counts[r["status"]] = r["n"]

        # Count by type
        type_counts = {}
        cur.execute("""
            SELECT policy_type, COUNT(*) as n FROM governance_policies
            GROUP BY policy_type
        """)
        for r in cur.fetchall():
            type_counts[r["policy_type"]] = r["n"]

        conn.close()

        # Score all active
        scored = []
        total_active = status_counts.get("active", 0) + status_counts.get("trusted", 0)
        if total_active > 0:
            conn2 = self._conn()
            cur2 = conn2.cursor()
            cur2.execute("""
                SELECT policy_id FROM governance_policies
                WHERE status IN ('active', 'trusted')
                LIMIT 500
            """)
            for r in cur2.fetchall():
                si = self.score_policy(r["policy_id"])
                scored.append(si)
            conn2.close()

        avg_score = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else 0

        return {
            "generated_at": datetime.now().isoformat(),
            "total_policies": sum(status_counts.values()),
            "by_status": status_counts,
            "by_type": type_counts,
            "active_count": total_active,
            "average_quality_score": avg_score,
            "cap_status": "OK" if total_active <= 500 else f"EXCEEDED ({total_active}/500)",
            "recommended_actions": self._recommend_actions(status_counts, avg_score, total_active),
        }

    def _recommend_actions(self, status_counts: dict, avg_score: float, active: int) -> list[str]:
        actions = []
        if active > 500:
            actions.append(f"🔴 Cap exceeded: {active} active, must reduce to 500")
        if avg_score < 50:
            actions.append("🟡 Average quality below 50 — run deduplication and retirement")
        if status_counts.get("draft", 0) > 100:
            actions.append("🟡 High draft backlog — run governance review cycle")
        if status_counts.get("decaying", 0) > 200:
            actions.append("🔴 Many decaying policies — run retirement sweep")
        if not actions:
            actions.append("✅ Policy governance is healthy")
        return actions


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V10 — Policy Governor")
    parser.add_argument("--action", choices=["dedup", "promote", "retire", "cap", "report", "score"],
                        default="report")
    parser.add_argument("--policy_id", default="")
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    gov = PolicyGovernor()

    if args.action == "dedup":
        result = gov.deduplicate(similarity_threshold=args.threshold, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "promote":
        n = gov.promote_policies()
        print(f"✅ Promoted {n} policies to Trusted")

    elif args.action == "retire":
        result = gov.retire_decayed(dry_run=args.dry_run)
        print(json.dumps(result, indent=2))

    elif args.action == "cap":
        result = gov.enforce_cap(max_active=500)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "report":
        report = gov.governance_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))

    elif args.action == "score":
        if not args.policy_id:
            print("❌ --policy_id required for score")
        else:
            score = gov.score_policy(args.policy_id)
            print(json.dumps(score, indent=2, ensure_ascii=False))
