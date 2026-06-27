import sys, json
sys.path.insert(0, ".")

from hcom import new_opportunity, new_market_signal, OpportunityStage, SignalPlatform, TrendPhase
from hvos_state import SystemStateManager
from hvos_decision import DecisionKernel, OpportunityContext
from outcome_engine import OutcomeEngine


# ============================================================
# V9 PIPELINE: 手工规则 + 直接调用 engine
# ============================================================
def run_v9(trend=8.0, supply=5.0, risk=3.5, margin=0.38):
    print("=" * 60)
    print("V9 PIPELINE  (hardcoded rules, no SSM, no DK)")
    print("=" * 60)

    # Step 1: Outcome Engine 直接调用
    oe = OutcomeEngine()
    pred = oe.predict(
        opp_id="v9_test_001",
        opp_name="Pet Grooming Gloves",
        trend_score=trend,
        supply_score=supply,
        risk_score=risk,
        margin_pct=margin,
        investment_usd=5000.0,
        write_to_kg=False,
    )

    prob = pred.success_probability
    roi = pred.expected_roi
    loss_prob = pred.probability_of_loss
    conf = pred.confidence_score

    print(f"Product: Pet Grooming Gloves")
    print(f"  trend={trend} supply={supply} risk={risk} margin={margin:.0%}")
    print(f"  OutcomeEngine: prob={prob:.1%} roi={roi:.1f}x loss_prob={loss_prob:.1%} conf={conf:.2f}")

    # Step 2: 手工决策规则 (V9 硬编码)
    # V9 thresholds: prob<0.35=STOP, prob>0.65+ROI>1.5=INVEST, ROI>2.0=SCALE, else WAIT
    roi_pct = roi * 100
    if prob < 0.35 or risk > 7.0:
        decision = "STOP"
        reason = "Hard stop: prob<35% or risk>7"
        budget = 0
    elif prob > 0.65 and roi > 1.5:
        decision = "INVEST"
        reason = f"prob>{0.65} AND roi>{1.5}"
        budget = 1000.0
    elif roi > 2.0:
        decision = "SCALE"
        reason = f"roi>{2.0} (actual={roi:.2f})"
        budget = 3000.0
    else:
        decision = "WAIT"
        reason = "Below thresholds"
        budget = 0

    print(f"  V9 Decision: {decision}")
    print(f"  Reason: {reason}")
    print(f"  Budget: ${budget:,.0f}")

    return {
        "decision": decision,
        "reason": reason,
        "prob": prob,
        "roi": roi,
        "roi_pct": roi_pct,
        "loss_prob": loss_prob,
        "conf": conf,
        "budget": budget,
        "stage": "N/A (no SSM)",
    }


# ============================================================
# X CORE PIPELINE: HCOM + SSM + DecisionKernel
# ============================================================
def run_xcore(trend=8.0, supply=5.0, risk=3.5, margin=0.38):
    print("=" * 60)
    print("X CORE PIPELINE  (HCOM + SSM + Decision Kernel)")
    print("=" * 60)

    # Step 1: HCOM 对象
    opp = new_opportunity("Pet Grooming Gloves", "pet_grooming")
    opp.trend_score = trend
    opp.demand_score = 7.5
    opp.supply_score = supply
    opp.margin_estimate = margin * 100
    opp.risk_score = risk
    opp.probability_of_success = 0.72
    opp.confidence = 0.72
    opp.stage = OpportunityStage.DISCOVER
    print(f"Product: Pet Grooming Gloves")
    print(f"  HCOM id={opp.id[:16]}...")

    # Step 2: Outcome Engine (individual params)
    oe = OutcomeEngine()
    pred = oe.predict(
        opp_id=opp.id,
        opp_name=opp.product_name,
        trend_score=trend,
        supply_score=supply,
        risk_score=risk,
        margin_pct=margin,
        investment_usd=5000.0,
        write_to_kg=False,
    )
    prob = pred.success_probability
    roi = pred.expected_roi
    roi_pct = roi * 100
    print(f"  OutcomeEngine: prob={prob:.1%} roi={roi:.1f}x ({roi_pct:.0f}%)")

    # Step 3: In-memory HHI (simple)
    investments = [
        {"product_niche": "pet_grooming", "investment_usd": 1000},
        {"product_niche": "garden_tools", "investment_usd": 500},
    ]
    total_inv = sum(i["investment_usd"] for i in investments)
    niche_totals = {}
    for inv in investments:
        n = inv["product_niche"]
        niche_totals[n] = niche_totals.get(n, 0) + inv["investment_usd"]
    hhi = sum((v / total_inv) ** 2 for v in niche_totals.values()) if total_inv else 0
    print(f"  Portfolio HHI: {hhi:.3f}")

    # Step 4: SSM 注册
    ssm = SystemStateManager()
    ssm.register(opp)
    print(f"  SSM: registered as {opp.stage.value}")

    # Step 5: Decision Kernel
    dk = DecisionKernel()
    # 从 outcome_engine 结果构建 p10/p50/p90
    mc = pred.mc_samples
    p10 = max(0, sorted(mc)[len(mc)//10]) * 100 if mc else 0
    p50 = sorted(mc)[len(mc)//2] * 100 if mc else 0
    p90 = sorted(mc)[len(mc)*9//10] * 100 if mc else 0
    payback = int(90 / prob) if prob > 0.3 else 999

    ctx = OpportunityContext(
        opportunity=opp,
        prob_success=prob,
        expected_profit_p10=p10,
        expected_profit_p50=p50,
        expected_profit_p90=p90,
        expected_roi=roi_pct,
        payback_days_estimate=payback,
        portfolio_concentration=hhi,
        budget_available=10000.0,
        suggested_budget=3000.0,
        causal_confidence=0.72,
        failure_risk_factors=[],
        model_trust_score=0.70,
    )

    dec = dk.decide(ctx)

    # Step 6: SSM 更新
    ssm.update_decision(opp.id, dec.decision, dec.primary_reason)
    if dec.decision.value in ("invest", "scale"):
        ssm.transition(opp.id, OpportunityStage.VALIDATE, dec.action)

    print(f"  Decision Kernel: {dec.decision.value.upper()}")
    print(f"  Reason: {dec.primary_reason}")
    print(f"  Action: {dec.action}")
    print(f"  Budget: ${dec.allocated_budget:,.0f}")
    print(f"  Stage: {opp.stage.value}")

    return {
        "decision": dec.decision.value,
        "reason": dec.primary_reason,
        "prob": prob,
        "roi": roi,
        "roi_pct": roi_pct,
        "loss_prob": pred.probability_of_loss,
        "conf": pred.confidence_score,
        "budget": dec.allocated_budget,
        "stage": opp.stage.value,
    }


# ============================================================
# COMPARE
# ============================================================
def compare(v9, xcore):
    print()
    print("=" * 60)
    print("COMPARISON: V9  vs  X CORE")
    print("=" * 60)
    print(f"  {'Metric':<22} {'V9':<18} {'X Core':<18}")
    print("-" * 60)
    print(f"  {'Decision':<22} {v9['decision']:<18} {xcore['decision']:<18}")
    print(f"  {'Prob Success':<22} {v9['prob']:<18.1%} {xcore['prob']:<18.1%}")
    print(f"  {'Expected ROI':<22} {v9['roi_pct']:<18.1f}% {xcore['roi_pct']:<18.1f}%")
    print(f"  {'Loss Probability':<22} {v9['loss_prob']:<18.1%} {xcore['loss_prob']:<18.1%}")
    print(f"  {'Confidence':<22} {v9['conf']:<18.2f} {xcore['conf']:<18.2f}")
    print(f"  {'Budget':<22} ${v9['budget']:<17,.0f} ${xcore['budget']:<17,.0f}")
    print(f"  {'Stage':<22} {v9['stage']:<18} {xcore['stage']:<18}")
    print("-" * 60)
    print(f"  {'Decision Reason':<22} {v9['reason'][:30]:<30}")
    print(f"  {'':<22} {xcore['reason'][:30]:<30}")
    print()
    match = v9["decision"].upper() == xcore["decision"].upper()
    match_str = "SAME" if match else "DIFFERENT"
    print(f"  Decision Match: {match_str}")
    if not match:
        print("  KEY DIFF: V9=hardcoded rules | X Core=contextual decision kernel")


if __name__ == "__main__":
    print("HVOS V9 vs X Core - 1 Product Comparison")
    print("Product: Pet Grooming Gloves | trend=8, margin=38%, risk=3.5")
    print()
    v9 = run_v9()
    print()
    xcore = run_xcore()
    print()
    compare(v9, xcore)