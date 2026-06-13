import sys, random, json
sys.path.insert(0, ".")

from datetime import datetime
from hcom import (
    OpportunityObject, Decision, OpportunityStage, CapitalEvent, CapitalEventType,
    MarketSignal, SignalPlatform, TrendPhase,
    new_opportunity, new_capital_event, new_market_signal,
)
from hvos_state import SystemStateManager, AlertLevel
from hvos_decision import DecisionKernel, OpportunityContext


class MockOutcomeEngine:
    def predict(self, opp):
        base_profit = opp.margin_estimate * 10
        prob = opp.probability_of_success
        p50 = base_profit * prob * 90
        p10 = p50 * 0.3
        p90 = p50 * 2.5
        roi = opp.margin_estimate * prob
        payback = int(90 / prob) if prob > 0.3 else 999
        return {"prob_success": prob, "p10": round(p10, 0), "p50": round(p50, 0),
                "p90": round(p90, 0), "expected_roi": round(roi, 1), "payback_days": payback}


class MockPortfolioManager:
    def __init__(self):
        self.category_exposure = {}
    def analyze(self, opp, all_opps):
        niche = opp.product_niche
        self.category_exposure[niche] = self.category_exposure.get(niche, 0) + 1
        total = len(all_opps) or 1
        hhi = sum((c / total) ** 2 for c in self.category_exposure.values())
        return {"portfolio_concentration": hhi, "category_exposure": self.category_exposure.copy(),
                "budget_available": 10000.0, "suggested_budget": min(3000, 10000 * (1 - hhi))}


class MockLearningLoop:
    def __init__(self):
        self.causal_factors = []
        self.predictions_made = 0
        self.feedback_received = 0
    def extract_causal_factors(self, opp):
        self.predictions_made += 1
        failure_factors = []
        if opp.risk_score > 6: failure_factors.append("高风险产品")
        if opp.margin_estimate < 20: failure_factors.append("低毛利率")
        if opp.trend_score < 5: failure_factors.append("趋势评分低")
        return {"causal_confidence": min(0.9, opp.confidence + 0.05 * self.predictions_made),
                "similar_success_pattern": f"{opp.product_niche}_pattern_v1" if opp.roi_estimate > 20 else "",
                "failure_risk_factors": failure_factors}
    def record_outcome(self, opp, actual_roi, error_pct):
        self.feedback_received += 1
        print(f"  [Learning] Feedback #{self.feedback_received}: actual ROI={actual_roi:.1f}%")


class MockRFE:
    def __init__(self):
        self.predictions = []
        self.actuals = []
        self.avg_error = 0.0
    def record_prediction(self, opp, predicted_roi):
        self.predictions.append({"id": opp.id, "predicted": predicted_roi})
    def record_actual(self, opp_id, actual_roi):
        self.actuals.append({"id": opp_id, "actual": actual_roi})
        for p in reversed(self.predictions):
            if p["id"] == opp_id:
                error = abs(actual_roi - p["predicted"]) / max(p["predicted"], 1) * 100
                self.avg_error = self.avg_error * 0.8 + error * 0.2
                break
    def get_trust_score(self):
        if self.avg_error < 10: return 0.9
        elif self.avg_error < 20: return 0.7
        elif self.avg_error < 40: return 0.5
        return 0.3


def run():
    print("=" * 70)
    print("HVOS X CORE - Full Closed Loop Test")
    print("=" * 70)

    ssm = SystemStateManager()
    dk = DecisionKernel()
    outcome_engine = MockOutcomeEngine()
    portfolio_mgr = MockPortfolioManager()
    learning_loop = MockLearningLoop()
    rfe = MockRFE()

    # Step 0: Reality Hub signals
    print("\n[STEP 0] Reality Hub - Market Signal Collection")
    print("-" * 50)
    signals = [
        new_market_signal(SignalPlatform.TIKTOK, 8.5, 1.2, "up", TrendPhase.EMERGING),
        new_market_signal(SignalPlatform.AMAZON, 7.0, 0.8, "up", TrendPhase.PEAK),
        new_market_signal(SignalPlatform.REDDIT, 6.5, 1.5, "up", TrendPhase.EMERGING),
    ]
    print(f"  Collected {len(signals)} market signals")
    for s in signals:
        print(f"    [{s.platform.value}] strength={s.strength}, velocity={s.velocity}")

    # Step 1: Opportunity Engine
    print("\n[STEP 1] Opportunity Engine - Create Opportunities")
    print("-" * 50)
    test_data = [
        ("Pet Gloves", "pet_grooming", 8.0, 7.5, 5.0, 38.0, 3.5, 0.72),
        ("Smart Garden Light", "garden_tools", 7.0, 6.5, 4.5, 32.0, 4.0, 0.58),
        ("Foldable Travel Cup", "travel_accessories", 6.5, 5.0, 7.0, 22.0, 5.5, 0.45),
        ("Mini Massage Gun", "fitness_recovery", 9.0, 8.0, 3.5, 42.0, 2.5, 0.78),
    ]
    created_opps = []
    for name, niche, trend, demand, supply, margin, risk, conf in test_data:
        opp = new_opportunity(name, niche)
        opp.trend_score = trend
        opp.demand_score = demand
        opp.supply_score = supply
        opp.margin_estimate = margin
        opp.risk_score = risk
        opp.confidence = conf
        opp.signal_sources = [s.platform.value for s in signals]
        opp.stage = OpportunityStage.DISCOVER
        for sig in signals:
            opp.update_signals(sig)
        created_opps.append(opp)
        print(f"  Created: {name} | trend={trend} demand={demand} margin={margin}% risk={risk} conf={conf}")

    # Step 2: Register to SSM
    print("\n[STEP 2] SystemStateManager - Register Opportunities")
    print("-" * 50)
    for opp in created_opps:
        ssm.register(opp)
        print(f"  Registered: {opp.product_name} [{opp.id[:8]}]")
    print(f"  Total: {ssm.get_global_stats().total_opportunities} opportunities")

    # Step 3: Decision Loop
    print("\n[STEP 3] Decision Kernel - Batch Decision")
    print("-" * 50)
    decisions = []
    for opp in created_opps:
        pred = outcome_engine.predict(opp)
        opp.apply_outcome_prediction(pred["p10"], pred["p50"], pred["p90"], pred["prob_success"])
        print(f"\n  [{opp.product_name}] Outcome Engine:")
        print(f"    P10=${pred["p10"]:,.0f} P50=${pred["p50"]:,.0f} P90=${pred["p90"]:,.0f}")
        print(f"    prob={pred["prob_success"]:.0%} ROI={pred["expected_roi"]:.1f}% payback={pred["payback_days"]}d")

        port = portfolio_mgr.analyze(opp, created_opps)
        print(f"  Portfolio: concentration={port["portfolio_concentration"]:.2f}")

        causal = learning_loop.extract_causal_factors(opp)
        print(f"  Learning: causal_confidence={causal["causal_confidence"]:.2f}")

        rfe.record_prediction(opp, pred["expected_roi"])

        ctx = OpportunityContext(
            opportunity=opp,
            prob_success=pred["prob_success"],
            expected_profit_p10=pred["p10"], expected_profit_p50=pred["p50"],
            expected_profit_p90=pred["p90"], expected_roi=pred["expected_roi"],
            payback_days_estimate=pred["payback_days"],
            portfolio_concentration=port["portfolio_concentration"],
            budget_available=port["budget_available"], suggested_budget=port["suggested_budget"],
            causal_confidence=causal["causal_confidence"],
            similar_success_pattern=causal["similar_success_pattern"],
            failure_risk_factors=causal["failure_risk_factors"],
            model_trust_score=rfe.get_trust_score(),
        )
        result = dk.decide(ctx)
        decisions.append(result)
        ssm.update_decision(opp.id, result.decision, result.primary_reason)

        if result.decision == Decision.INVEST:
            if opp.stage == OpportunityStage.DISCOVER:
                ssm.transition(opp.id, OpportunityStage.VALIDATE, result.action)
        elif result.decision == Decision.SCALE:
            ssm.transition(opp.id, OpportunityStage.SCALE, result.action)
        elif result.decision == Decision.STOP:
            ssm.transition(opp.id, OpportunityStage.STOP, result.action)

        print(f"  Decision: {result.decision.value.upper()} (priority={result.priority})")
        print(f"  Action: {result.action}")

    # Step 4: Portfolio View
    print("\n[STEP 4] Portfolio Manager - Portfolio View")
    print("-" * 50)
    summary = ssm.get_board_summary()
    for stage, count in summary["by_stage"].items():
        print(f"  {stage}: {count}")
    decision_counts = {}
    for d in decisions:
        key = d.decision.value
        decision_counts[key] = decision_counts.get(key, 0) + 1
    print("  Decisions:", decision_counts)

    # Step 5: RFE Feedback
    print("\n[STEP 5] RFE Engine - Pred vs Actual (Simulated Feedback)")
    print("-" * 50)
    print(f"  Initial Model Trust Score: {rfe.get_trust_score():.2f}")
    for opp in created_opps[:3]:
        actual_roi = opp.roi_estimate * random.uniform(0.5, 1.4)
        rfe.record_actual(opp.id, actual_roi)
        learning_loop.record_outcome(opp, actual_roi, 0)
        err = abs(actual_roi - opp.roi_estimate) / opp.roi_estimate * 100
        print(f"  [{opp.product_name}] predicted={opp.roi_estimate:.1f}% actual={actual_roi:.1f}% error={err:.0f}%")
    print(f"  Updated Model Trust Score: {rfe.get_trust_score():.2f}")

    # Step 6: Alerts
    print("\n[STEP 6] SystemStateManager - Alert Check")
    print("-" * 50)
    critical = ssm.get_critical_alerts()
    warns = ssm.get_active_alerts(AlertLevel.WARN)
    print(f"  Critical alerts: {len(critical)}")
    print(f"  Warning alerts: {len(warns)}")

    # Step 7: Final Board Report
    print("\n[STEP 7] Final Board Report")
    print("=" * 70)
    print(ssm.get_board_summary_text())
    print()
    print("Decision Outputs (JSON):")
    print(json.dumps([d.to_dict() for d in decisions], ensure_ascii=False, indent=2)[:800])
    print("=" * 70)
    print("Closed loop test COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    run()
