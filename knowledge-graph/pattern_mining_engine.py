"""
HVOS V8.5 — Pattern Mining Engine
======================================
自动模式发现引擎：从 Strategy Library + KG + Event Store 中，
自动发现高阶组合 Pattern，而非手工定义策略类型。

核心能力：
  mine_patterns()         — 运行关联规则挖掘
  discover_combinations()   — 发现高阶组合（品类×渠道×时机×定价）
  update_pattern_confidence() — 根据新案例更新 Pattern 置信度
  recommend_pattern_based()  — 基于发现的 Pattern 做机会推荐

V8.5 = Strategy Memory 的进化
  V8.1: 手工提炼策略规则（人定义了类型）
  V8.5: 系统自动发现组合（机器发现人没想到的）
"""

import sqlite3
import json
import math
from collections import defaultdict
from datetime import datetime

# ============================================================
# Pattern Mining Engine
# ============================================================

class PatternMiningEngine:
    """
    自动模式发现引擎。

    方法：
    1. 关联规则挖掘（Association Rule Mining）
       - 找频繁项集（frequent itemsets）
       - 计算置信度（confidence）和提升度（lift）
       - 过滤有意义的规则

    2. 高阶组合发现
       - 品类 + 渠道 + 时机 + 定价 → 成功?
       - 例如：Kitchen × Pinterest × Q4 × Margin>40% → SUCCESS (lift=2.3)
    """

    def __init__(self, strategy_db=None, kg_db=None):
        if strategy_db is None:
            strategy_db = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge-graph\strategy_memory.db"
        if kg_db is None:
            kg_db = r"C:\Users\Administrator\AppData\Local\hermes\hvos\knowledge-graph\kg.db"
        self.strategy_db = strategy_db
        self.kg_db = kg_db

    def _strat_conn(self):
        conn = sqlite3.connect(self.strategy_db)
        return conn

    def _kg_conn(self):
        conn = sqlite3.connect(self.kg_db)
        conn.row_factory = sqlite3.Row
        return conn

    # ----------------------------------------------------------
    # 关联规则挖掘
    # ----------------------------------------------------------

    def _apriori(self, transactions: list[set], min_support: float = 0.2) -> dict:
        """
        Apriori 算法：发现所有长度的频繁项集。

        transactions: 列表，每个元素是一个事务（item集合）
        例如：[{"Kitchen", "TikTok", "Q4", "success"}, ...]

        正确实现：
        1. 找 L1（1-项集）
        2. 从 L{k-1} 生成 C{k}（候选k-项集）
        3. 剪枝：剔除含非频繁子集的候选项
        4. 过滤得 L{k}
        5. 重复直到没有新的频繁项集

        返回：{itemset: support_count}，包含所有长度的频繁项集
        """
        n = len(transactions)
        if n == 0:
            return {}

        # ── Step 1: L1（1-项集）─────────────────────────────────────
        item_counts = defaultdict(int)
        for txn in transactions:
            for item in txn:
                item_counts[item] += 1

        # 初始频繁项集：key=item, value=count
        frequent = {}  # item → count
        for item, count in item_counts.items():
            if count / n >= min_support:
                frequent[item] = count

        # 转换为 frozenset 格式的频繁项集
        L1 = {frozenset([item]): count for item, count in frequent.items()}
        all_frequent = dict(L1)

        if not L1:
            return all_frequent

        # ── Step 2: 迭代生成 L2, L3, ... ───────────────────────────
        k = 2
        while True:
            # 从 L{k-1} 生成候选 k-项集
            prev_items = list(L1.keys()) if k == 2 else list(
                {fs for fs in all_frequent.keys() if len(fs) == k - 1}
            )

            candidates = set()
            prev_list = list(prev_items)

            # 生成 k-项集候选项：两两合并 L{k-1}
            for i in range(len(prev_list)):
                for j in range(i + 1, len(prev_list)):
                    union = prev_list[i] | prev_list[j]
                    if len(union) == k:
                        candidates.add(union)

            # 剪枝：剔除含非频繁子集的候选项
            # Apriori 性质：如果 {a,b,c} 是频繁的，则 {a,b}、{a,c}、{b,c} 都必须是频繁的
            pruned = set()
            for candidate in candidates:
                valid = True
                for item in candidate:
                    subset = candidate - {item}
                    # 检查所有 (k-1)-子集是否频繁
                    if not any(fs >= subset and len(fs) == k - 1 for fs in all_frequent):
                        # 更简单：直接检查是否在 all_frequent
                        if subset not in all_frequent:
                            valid = False
                            break
                if valid:
                    pruned.add(candidate)

            if not pruned:
                break

            # 计数：统计每个候选的支持度
            candidate_counts = defaultdict(int)
            for txn in transactions:
                for candidate in pruned:
                    if candidate.issubset(txn):
                        candidate_counts[candidate] += 1

            # 过滤得 Lk
            Lk = {}
            for candidate, count in candidate_counts.items():
                support = count / n
                if support >= min_support:
                    Lk[candidate] = count
                    all_frequent[candidate] = count

            if not Lk:
                break

            # 更新 L1 为 Lk（用于下一次迭代）
            # 但实际上对于 k>=3，我们需要跟踪所有 k-1 项集
            # 所以我们把 Lk 作为下一轮的基础项集（按长度分组）
            L1 = Lk
            k += 1

        return all_frequent

    def _generate_rules(
        self,
        frequent_itemsets: dict,
        transactions: list[set],
        min_confidence: float = 0.6
    ) -> list[dict]:
        """
        从频繁项集生成关联规则。

        规则：A → B
        confidence = P(B|A) = count(A∪B) / count(A)
        lift = confidence / P(B)
        lift > 1 表示正相关
        """
        rules = []
        n = len(transactions)

        for itemset, support in frequent_itemsets.items():
            if len(itemset) < 2:
                continue

            items = list(itemset)
            for i in range(1, len(items)):
                # 生成所有 A → B 的组合
                from itertools import combinations
                for combo_size in range(1, len(items)):
                    for antecedent in combinations(items, combo_size):
                        antecedent_set = frozenset(antecedent)
                        consequent_set = itemset - antecedent_set

                        if not consequent_set:
                            continue

                        # 计算置信度
                        antecedent_support = frequent_itemsets.get(antecedent_set, 0)
                        if antecedent_support == 0:
                            continue

                        rule_support = support
                        confidence = rule_support / antecedent_support

                        if confidence < min_confidence:
                            continue

                        # 计算提升度
                        consequent_counts = defaultdict(int)
                        for txn in transactions:
                            if consequent_set.issubset(txn):
                                consequent_counts[consequent_set] += 1
                        p_b = consequent_counts[consequent_set] / n

                        lift = confidence / p_b if p_b > 0 else 0

                        if lift > 1.2:  # 提升度 > 1.2 表示有意义的相关性
                            rules.append({
                                "antecedent": list(antecedent_set),
                                "consequent": list(consequent_set),
                                "confidence": round(confidence, 3),
                                "support": round(support, 3),
                                "lift": round(lift, 2),
                                "rule_type": self._classify_rule(list(antecedent_set), list(consequent_set))
                            })

        rules.sort(key=lambda x: (x["lift"], x["confidence"]), reverse=True)
        return rules

    def _classify_rule(self, antecedent: list, consequent: list) -> str:
        """分类规则类型"""
        ant_set = set(antecedent)
        cons_set = set(consequent)

        if "success" in cons_set or "invest" in cons_set:
            return "SUCCESS_DRIVER"
        elif "failure" in cons_set or "reject" in cons_set:
            return "FAILURE_SIGNAL"
        elif ant_set & {"Q4", "Q1", "Q2", "Q3"}:
            return "SEASONAL_TRIGGER"
        elif ant_set & {"TikTok", "Pinterest", "Meta"}:
            return "CHANNEL_PATTERN"
        elif ant_set & {"margin", "pricing"}:
            return "PRICING_PATTERN"
        else:
            return "MIXED"

    # ----------------------------------------------------------
    # Pattern 发现主函数
    # ----------------------------------------------------------

    def mine_patterns(self, min_confidence: float = 0.6) -> list[dict]:
        """
        从 Strategy Library 挖掘关联规则 Pattern。

        过程：
        1. 构建事务集（每条策略 = 一个事务）
        2. Apriori 发现频繁项集
        3. 生成关联规则
        4. 过滤高提升度规则
        """
        conn = self._strat_conn()
        cur = conn.cursor()

        # 构建事务集
        cur.execute("""
            SELECT category, market, strategy_type, outcome, verdict, signal
            FROM strategy_library
            WHERE confidence >= 0.3
        """)

        transactions = []
        strategy_records = []
        for row in cur.fetchall():
            category, market, stype, outcome, verdict, signal = row
            txn = set()
            if category: txn.add(f"CATEGORY:{category}")
            if market: txn.add(f"MARKET:{market}")
            if stype: txn.add(f"TYPE:{stype}")
            if outcome: txn.add(f"OUTCOME:{outcome}")
            if verdict: txn.add(f"VERDICT:{verdict}")
            if signal: txn.add(f"SIGNAL:{signal}")
            if txn:
                transactions.append(txn)
                strategy_records.append({
                    "category": category, "market": market,
                    "strategy_type": stype, "outcome": outcome
                })

        conn.close()

        if len(transactions) < 3:
            return {"error": "样本不足（需要≥3条策略记录）",
                    "transactions": len(transactions)}

        # Apriori
        frequent = self._apriori(transactions, min_support=0.2)

        # 生成规则
        rules = self._generate_rules(frequent, transactions, min_confidence)

        return {
            "transactions_analyzed": len(transactions),
            "frequent_itemsets": len(frequent),
            "rules_found": len(rules),
            "top_rules": rules[:20]
        }

    # ----------------------------------------------------------
    # 高阶组合发现
    # ----------------------------------------------------------

    def discover_combinations(self) -> list[dict]:
        """
        发现高阶组合 Pattern。

        核心组合维度：
        - 品类（category）
        - 渠道（channel: TikTok/Pinterest/Meta）
        - 时机（season: Q4/Q1/Q2/Q3）
        - 定价（margin tier: 高/中/低）
        - 合规（compliance: FCC/COPPA/Prop65）

        输出：
        - 组合 → 成功率/提升度
        """
        conn = self._strat_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT category, market, strategy_type, outcome, verdict
            FROM strategy_library
            WHERE confidence >= 0.3
        """)

        # 构建维度矩阵
        combinations = defaultdict(lambda: {"success": 0, "total": 0})

        for row in cur.fetchall():
            cat, market, stype, outcome, verdict = row
            key = f"{cat or '?'}_{market or '?'}_{stype or '?'}"
            combinations[key]["total"] += 1
            if outcome == "success":
                combinations[key]["success"] += 1

        conn.close()

        # 计算提升度
        total_success = sum(v["success"] for v in combinations.values())
        total_all = sum(v["total"] for v in combinations.values())
        base_rate = total_success / total_all if total_all > 0 else 0.5

        discovered = []
        for combo, counts in combinations.items():
            if counts["total"] < 1:
                continue
            success_rate = counts["success"] / counts["total"]
            lift = success_rate / base_rate if base_rate > 0 else 1.0

            parts = combo.split("_")
            discovered.append({
                "category": parts[0] if len(parts) > 0 else "?",
                "market": parts[1] if len(parts) > 1 else "?",
                "strategy_type": parts[2] if len(parts) > 2 else "?",
                "success_count": counts["success"],
                "total_count": counts["total"],
                "success_rate": round(success_rate, 3),
                "lift": round(lift, 2),
                "verdict": "SUCCESS_PATTERN" if lift > 1.5 else "MIXED",
                "confidence": min(success_rate, 0.99)
            })

        discovered.sort(key=lambda x: x["lift"], reverse=True)
        return {
            "combinations_found": len(discovered),
            "base_success_rate": round(base_rate, 3),
            "top_combinations": discovered[:15]
        }

    # ----------------------------------------------------------
    # Pattern 置信度更新
    # ----------------------------------------------------------

    def update_pattern_confidence(
        self,
        pattern_id: str,
        actual_outcome: str  # "success" or "failure"
    ) -> dict:
        """
        当新案例发生时，更新对应 Pattern 的置信度。

        使用贝叶斯更新：
        new_confidence = (old_confidence * n + outcome) / (n + 1)
        """
        conn = self._strat_conn()
        cur = conn.cursor()

        # 查询当前 Pattern
        cur.execute("""
            SELECT pattern_id, confidence, times_observed
            FROM kg_patterns
            WHERE pattern_id = ?
        """, (pattern_id,))

        row = cur.fetchone()
        if not row:
            conn.close()
            return {"error": f"Pattern {pattern_id} not found"}

        old_conf = row[1]
        n = row[2]
        outcome_val = 1.0 if actual_outcome == "success" else 0.0

        # 贝叶斯更新
        new_conf = (old_conf * n + outcome_val) / (n + 1)
        new_n = n + 1

        cur.execute("""
            UPDATE kg_patterns
            SET confidence = ?, times_observed = ?, last_observed = ?
            WHERE pattern_id = ?
        """, (new_conf, new_n, datetime.now().isoformat(), pattern_id))
        conn.commit()
        conn.close()

        return {
            "pattern_id": pattern_id,
            "old_confidence": old_conf,
            "new_confidence": round(new_conf, 3),
            "observations": new_n,
            "delta": round(new_conf - old_conf, 3)
        }

    # ----------------------------------------------------------
    # 基于 Pattern 的推荐
    # ----------------------------------------------------------

    def recommend_pattern_based(
        self,
        category: str,
        market: str,
        available_signals: list[str] = None
    ) -> dict:
        """
        基于已发现的高阶 Pattern，对新机会做推荐。

        输入：品类、市场、可用信号
        输出：匹配 Pattern + 推荐行动
        """
        combos = self.discover_combinations()
        top_combos = combos.get("top_combinations", [])

        # 找匹配的 Pattern
        matched = []
        for combo in top_combos:
            if combo["category"].lower() == category.lower():
                matched.append(combo)

        if not matched:
            return {
                "category": category,
                "market": market,
                "matched_patterns": [],
                "recommendation": "无历史 Pattern，建议标准流程"
            }

        # 生成推荐
        best = matched[0]  # 提升度最高的 Pattern
        actions = []

        if best.get("strategy_type"):
            actions.append({
                "action": f"采用{best['strategy_type']}策略",
                "confidence": best["confidence"],
                "reason": f"历史{best['total_count']}个案例中{best['success_count']}个成功，提升度{best['lift']}x"
            })

        if best.get("lift", 0) > 2.0:
            actions.append({
                "action": "高度匹配历史最优 Pattern，可优先投资",
                "confidence": best["confidence"],
                "reason": f"提升度{best['lift']}x表示该组合显著优于基准"
            })

        return {
            "category": category,
            "market": market,
            "matched_patterns": matched,
            "best_pattern": best,
            "recommended_actions": actions,
            "overall_confidence": best["confidence"]
        }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS V8.5 — Pattern Mining Engine")
    parser.add_argument("--action", choices=[
        "mine", "combinations", "update", "recommend"
    ], default="mine")
    parser.add_argument("--pattern_id", help="Pattern ID（update时用）")
    parser.add_argument("--outcome", choices=["success", "failure"], help="新案例结果")
    parser.add_argument("--category", help="品类（recommend时用）")
    parser.add_argument("--market", default="US", help="市场")
    args = parser.parse_args()

    pme = PatternMiningEngine()

    if args.action == "mine":
        result = pme.mine_patterns()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "combinations":
        result = pme.discover_combinations()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "update":
        if not all([args.pattern_id, args.outcome]):
            print("❌ 需要 --pattern_id 和 --outcome")
        else:
            result = pme.update_pattern_confidence(args.pattern_id, args.outcome)
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "recommend":
        cat = args.category or "厨房小家电"
        result = pme.recommend_pattern_based(cat, args.market)
        print(json.dumps(result, indent=2, ensure_ascii=False))
