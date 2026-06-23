# HVOS V10 — 20品类选品压力测试
# ===================================
# 用 V10 World Model 对 20 个不同品类进行预测
# 验证系统对多元化商品结构的认知能力

from __future__ import annotations
import sys
import os
import json
import uuid
import random
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from core.world_model.world_model import WorldModel
from governance.policy_governor import PolicyGovernor
from reasoning.causal_intelligence_engine import CausalIntelligenceEngine
from learning.adaptive_learning_engine import AdaptiveThresholdLearner

class V10CategoryScout:
    """V10 品类侦察兵 — 对20个品类进行认知评估"""

    # 20个不同品类，覆盖户外/家居/美妆/宠物等
    CATEGORIES = [
        # 户外 & 运动
        {"category": "露营帐篷", "market": "US", "tags": ["outdoor", "summer"]},
        {"category": "跑步鞋", "market": "US", "tags": ["sports", "fitness"]},
        {"category": "瑜伽垫", "market": "DE", "tags": ["fitness", "wellness"]},
        # 家居 & 宠物
        {"category": "智能猫砂盆", "market": "US", "tags": ["pet", "smart home"]},
        {"category": "空气炸锅", "market": "UK", "tags": ["kitchen", "appliance"]},
        {"category": "吸尘机器人", "market": "JP", "tags": ["smart home", "cleaning"]},
        # 美妆 & 个护
        {"category": "VC精华液", "market": "US", "tags": ["beauty", "skincare"]},
        {"category": "睫毛增长液", "market": "KR", "tags": ["beauty", "cosmetic"]},
        # 母婴 & 玩具
        {"category": "儿童安全座椅", "market": "US", "tags": ["baby", "safety"]},
        {"category": "磁力片积木", "market": "DE", "tags": ["toy", "education"]},
        # 3C & 配件
        {"category": "氮化镓充电器", "market": "US", "tags": ["3c", "charger"]},
        {"category": "无线蓝牙耳机", "market": "CN", "tags": ["3c", "audio"]},
        # 服饰 & 配件
        {"category": "瑜伽紧身裤", "market": "AU", "tags": ["apparel", "fitness"]},
        {"category": "防晒衣", "market": "US", "tags": ["apparel", "summer"]},
        # 宠物用品
        {"category": "宠物自动饮水机", "market": "UK", "tags": ["pet", "dog_cat"]},
        # 工具 & 户外
        {"category": "高压洗车枪", "market": "US", "tags": ["tools", "outdoor"]},
        # 办公 & 收纳
        {"category": "人体工学椅", "market": "DE", "tags": ["office", "ergonomic"]},
        {"category": "桌面收纳盒", "market": "JP", "tags": ["office", "organization"]},
        # 节日 & 派对
        {"category": "万圣节LED装饰", "market": "US", "tags": ["seasonal", "holiday"]},
        {"category": "圣诞投影灯", "market": "UK", "tags": ["seasonal", "holiday"]},
    ]

    def __init__(self):
        self.wm = WorldModel()
        self.gov = PolicyGovernor()
        self.causal = CausalIntelligenceEngine()
        self.atl = AdaptiveThresholdLearner()
        self.results = []
        self._inject_prior_knowledge()

    def _inject_prior_knowledge(self):
        """为一些品类注入先验知识（模拟历史数据）"""
        # 常见品类的历史表现先验
        priors = {
            ("智能猫砂盆", "US"): {"roi": 3.2, "cvr": 0.045, "refund": 0.03},
            ("空气炸锅", "UK"): {"roi": 2.8, "cvr": 0.038, "refund": 0.05},
            ("VC精华液", "US"): {"roi": 4.1, "cvr": 0.052, "refund": 0.02},
            ("高压洗车枪", "US"): {"roi": 2.5, "cvr": 0.033, "refund": 0.04},
            ("人体工学椅", "DE"): {"roi": 3.5, "cvr": 0.040, "refund": 0.06},
            ("无线蓝牙耳机", "CN"): {"roi": 2.1, "cvr": 0.028, "refund": 0.08},
            ("瑜伽紧身裤", "AU"): {"roi": 3.8, "cvr": 0.055, "refund": 0.03},
        }
        for (cat, mkt), vals in priors.items():
            for _ in range(5):  # 注入5条历史数据
                self.wm.learn_from_outcome(
                    category=cat, market=mkt,
                    actual_roi=vals["roi"],
                    actual_cvr=vals["cvr"],
                    actual_refund_rate=vals["refund"]
                )

    def scout(self) -> list[dict]:
        """对所有20个品类进行 V10 认知评估"""
        print(f"\n{'='*70}")
        print(f"  HVOS V10 — 20品类选品认知评估")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")

        for i, item in enumerate(self.CATEGORIES, 1):
            cat = item["category"]
            mkt = item["market"]
            opp_id = f"opp_{i:02d}_{uuid.uuid4().hex[:6]}"

            print(f"[{i:02d}/20] {cat} ({mkt})...")

            # Step 1: World Model 预测
            pred = self.wm.predict(category=cat, market=mkt, opp_id=opp_id)
            pd = pred  # dataclass instance

            # Step 2: 因果图推断
            try:
                causal = self.causal.infer_causal_graph(opp_id=opp_id)
                # BayesianCausalGraph → extract causal metrics
                edge_strengths = [e.strength for e in causal.edges] if causal.edges else [0.0]
                causal_strength = round(sum(edge_strengths) / len(edge_strengths), 3) if edge_strengths else 0.0
                causal_nodes = len(causal.nodes)
                causal_edges = len(causal.edges)
            except Exception as e:
                causal = None
                causal_strength = 0.0
                causal_nodes = 0
                causal_edges = 0

            # Step 3: 因果干预分析
            try:
                cf = self.causal.counterfactual(
                    opp_id=opp_id,
                    intervention_node="supply_risk",
                    original_value="normal",
                    counterfactual_value="disrupted",
                    target_node="roi_outcome"
                )
            except Exception:
                cf = {}

            # Step 4: 政策健康
            try:
                gov = self.gov.governance_report()
                total_policies = gov.get("total_policies", 0) if isinstance(gov, dict) else 0
            except Exception:
                total_policies = 0

            # Step 5: 动态阈值
            roi_class = self.atl.classify(metric="roi", value=pd.predicted_roi, category=cat, market=mkt)
            cvr_class = self.atl.classify(metric="cvr", value=pd.predicted_cvr, category=cat, market=mkt)

            # 综合评分
            score = self._compute_score(pd, roi_class, cvr_class)

            # Extract counterfactual insight
            cf_insight = ""
            if cf:
                cf_insight = cf.get("counterfactual_outcome", cf.get("insight", ""))
                if isinstance(cf_insight, float):
                    cf_insight = f"Δ={cf_insight:+.2f}"

            result = {
                "rank": i,
                "category": cat,
                "market": mkt,
                "tags": item["tags"],
                "opp_id": opp_id,
                "prediction": {
                    "roi": round(pd.predicted_roi, 2),
                    "cvr": round(pd.predicted_cvr, 4),
                    "refund": round(pd.predicted_refund_risk, 4),
                    "lTV": round(pd.predicted_ltv, 2),
                    "confidence": round(pd.confidence_score, 3),
                },
                "recommendation": pd.recommendation,
                "roi_level": roi_class["level"],
                "cvr_level": cvr_class["level"],
                "confidence": pd.confidence_score,
                "causal_strength": causal_strength,
                "causal_nodes": causal_nodes,
                "causal_edges": causal_edges,
                "counterfactual": cf_insight,
                "policy_health": total_policies,
                "score": score,
            }
            self.results.append(result)

        return self.results

    def _compute_score(self, pred, roi_class: dict, cvr_class: dict) -> float:
        """综合评分：ROI权重0.4 + CVR权重0.3 + 置信度0.2 + 退款风险-0.1"""
        roi_score = min(pred.predicted_roi / 4.0, 1.0) * 0.4
        cvr_score = min(pred.predicted_cvr / 0.05, 1.0) * 0.3
        conf_score = pred.confidence_score * 0.2
        refund_penalty = max(0, pred.predicted_refund_risk - 0.05) * 1.0  # 超过5%开始扣分
        return round(roi_score + cvr_score + conf_score - refund_penalty, 3)

    def print_leaderboard(self):
        """打印排行榜"""
        # 按综合评分排序
        sorted_results = sorted(self.results, key=lambda x: x["score"], reverse=True)

        print(f"\n{'='*90}")
        print(f"  🏆 HVOS V10 — TOP 20 品类选品排行榜")
        print(f"{'='*90}")
        print(f"{'排名':<4} {'品类':<18} {'市场':<4} {'ROI':>6} {'CVR':>6} {'置信':>6} {'推荐':<8} {'评分':>6}")
        print(f"{'-'*90}")

        medals = ["🥇", "🥈", "🥉"]
        for rank, r in enumerate(sorted_results, 1):
            medal = medals[rank-1] if rank <= 3 else "  "
            roi_lvl = {"low": "↓", "normal": "→", "high": "↑"}.get(r["roi_level"], "?")
            print(
                f"{medal}{rank:<3} {r['category']:<18} {r['market']:<4} "
                f"{r['prediction']['roi']:>5.1f}{roi_lvl} "
                f"{r['prediction']['cvr']:>6.2%} "
                f"{r['confidence']:>5.1%} "
                f"{r['recommendation']:<8} "
                f"{r['score']:>6.3f}"
            )

        print(f"{'-'*90}")

        # 按市场分布
        print(f"\n📊 市场分布：")
        from collections import Counter
        by_market = Counter(r["market"] for r in self.results)
        for mkt, cnt in sorted(by_market.items(), key=lambda x: -x[1]):
            print(f"   {mkt}: {cnt}个品类")

        # 按标签分布
        print(f"\n🏷️ 标签分布：")
        all_tags = [tag for r in self.results for tag in r["tags"]]
        by_tag = Counter(all_tags)
        for tag, cnt in sorted(by_tag.items(), key=lambda x: -x[1])[:8]:
            print(f"   {tag}: {cnt}个品类")

        # 投资建议汇总
        recs = Counter(r["recommendation"] for r in self.results)
        print(f"\n💰 投资建议汇总：")
        for rec, cnt in sorted(recs.items(), key=lambda x: -x[1]):
            pct = cnt / len(self.results) * 100
            bar = "█" * int(pct / 5)
            print(f"   {rec:<12}: {cnt:>2}个 ({pct:>5.1f}%) {bar}")

        return sorted_results

    def print_detail_card(self, r: dict):
        """打印单个品类的详细卡片"""
        print(f"\n{'='*60}")
        print(f"  📦 {r['category']} ({r['market']})")
        print(f"{'='*60}")
        print(f"  Opp ID    : {r['opp_id']}")
        print(f"  标签      : {', '.join(r['tags'])}")
        print(f"  综合评分  : {r['score']:.3f}")
        print(f"  ── 预测 ──")
        print(f"  ROI       : {r['prediction']['roi']:.2f}x  ({r['roi_level']})")
        print(f"  CVR       : {r['prediction']['cvr']:.2%}  ({r['cvr_level']})")
        print(f"  退款率    : {r['prediction']['refund']:.2%}")
        print(f"  LTV       : ${r['prediction']['lTV']:.2f}")
        print(f"  置信度   : {r['confidence']:.1%}")
        print(f"  推荐决策  : {r['recommendation']}")
        print(f"  ── 因果 ──")
        print(f"  因果强度  : {r['causal_strength']:.2f}")
        print(f"  反事实   : {r['counterfactual']}")
        print(f"  ── 政策 ──")
        print(f"  Policy总数: {r['policy_health']}")


def main():
    scout = V10CategoryScout()
    results = scout.scout()
    top20 = scout.print_leaderboard()

    # 打印 TOP3 详细卡片
    print("\n\n")
    for r in top20[:3]:
        scout.print_detail_card(r)

    # 保存结果
    out_path = os.path.join(os.path.dirname(__file__), "v10_category_scout_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        # 序列化时忽略 opp_id 中的 UUID（太长了）
        serializable = []
        for r in results:
            sr = dict(r)
            sr["prediction"] = {k: round(v, 4) if isinstance(v, float) else v
                                for k, v in r["prediction"].items()}
            sr["confidence"] = round(r["confidence"], 4)
            sr["causal_strength"] = round(r["causal_strength"], 4)
            sr["score"] = round(r["score"], 4)
            serializable.append(sr)
        json.dump({"timestamp": datetime.now().isoformat(),
                   "total": len(results),
                   "results": serializable}, f, ensure_ascii=False, indent=2)

    print(f"\n\n✅ 结果已保存: {out_path}")
    return top20


if __name__ == "__main__":
    main()
