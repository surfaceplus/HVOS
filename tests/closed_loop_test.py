import sys, random, json
sys.path.insert(0, ".")

from datetime import datetime
from hcom import (
    OpportunityObject, Decision, OpportunityStage,
    MarketSignal, SignalPlatform, TrendPhase,
    new_opportunity, new_market_signal,
)
from hvos_state import SystemStateManager, AlertLevel
from hvos_decision import DecisionKernel, OpportunityContext


class MockOutcomeEngine:
    def predict(self, opp):
        prob = max(opp.probability_of_success, 0.5)
        base = opp.margin_estimate * 10
        p50 = base * prob * 90
        return {
            "prob_success": prob,
            "p10": round(p50 * 0.3, 0),
            "p50": round(p50, 0),
            "p90": round(p50 * 2.5, 0),
            "expected_roi": round(opp.margin_estimate * prob, 1),
            "payback_days": int(90 / prob) if prob > 0.3 else 999,
        }

class MockPortfolioManager:
    def __init__(self):
        self.cat_count = {}
    def analyze(self, opp, all_opps):
        niche = opp.product_niche
        self.cat_count[niche] = self.cat_count.get(niche, 0) + 1
        total = max(len(all_opps), 1)
        hhi = sum((c / total) ** 2 for c in self.cat_count.values())
        return {
            "portfolio_concentration": hhi,
            "budget_available": 10000.0,
            "suggested_budget": min(3000, 10000 * (1 - hhi)),
        }

class MockLearningLoop:
    def __init__(self):
        self.n = 0
    def extract(self, opp):
        self.n += 1
        risks = []
        if opp.risk_score > 6: risks.append("high_risk")
        if opp.margin_estimate < 20: risks.append("low_margin")
        if opp.trend_score < 5: risks.append("low_trend")
        return {
            "causal_confidence": min(0.9, 0.5 + self.n * 0.05),
            "failure_risks": risks,
        }
    def feedback(self, opp, actual):
        return f"Feedback: ROI={actual:.1f}%"

class MockRFE:
    def __init__(self):
        self.errors = []
    def record_pred(self, pred):
        self.errors.append({"pred": pred})
    def record_actual(self, actual):
        if self.errors:
            e = self.errors[-1]
            err = abs(actual - e["pred"]) / max(e["pred"], 1) * 100
            e["actual"] = actual
            e["error"] = err
    def trust(self):
        if not self.errors: return 0.5
        recent = [e["error"] for e in self.errors[-5:] if "error" in e]
        if not recent: return 0.5
        avg = sum(recent) / len(recent)
        if avg < 10: return 0.9
        if avg < 25: return 0.7
        if avg < 50: return 0.5
        return 0.3


def run():
    print("=" * 70)
    print("HVOS X CORE - Closed Loop Test")
    print("=" * 70)

    ssm = SystemStateManager()
    dk = DecisionKernel()
    oe = MockOutcomeEngine()
    pm = MockPortfolioManager()
    ll = MockLearningLoop()
    rfe = MockRFE()

    # Step 0: Market signals
    print("\n[STEP 0] Reality Hub")
    print("-" * 50)
    signals = [
        new_market_signal(SignalPlatform.TIKTOK, 8.5, 1.2, "up", TrendPhase.EMERGING),
        new_market_signal(SignalPlatform.AMAZON, 7.0, 0.8, "up", TrendPhase.PEAK),
        new_market_signal(SignalPlatform.REDDIT, 6.5, 1.5, "up", TrendPhase.EMERGING),
    ]
    for s in signals:
        print(f"  [{s.platform.value}] str={s.strength} vel={s.velocity}")

    # Step 1: Create opportunities
    print("\n[STEP 1] Opportunity Engine")
    print("-" * 50)
    raw = [
        ("Pet Gloves",        "pet_grooming",    8.0, 7.5, 5.0, 38.0, 3.5, 0.72),
        ("Smart Garden",      "garden_tools",     7.0, 6.5, 4.5, 32.0, 4.0, 0.58),
        ("Travel Cup",        "travel_acc",      6.5, 5.0, 7.0, 22.0, 5.5, 0.45),
        ("Massage Gun",       "fitness_rec",     9.0, 8.0, 3.5, 42.0, 2.5, 0.78),
    ]
    opps = []
    for row in raw:
        name, niche, trend, demand, supply, margin, risk, prob = row
        opp = new_opportunity(name, niche)
        opp.trend_score = trend
        opp.demand_score = demand
        opp.supply_score = supply
        opp.margin_estimate = margin
        opp.risk_score = risk
        opp.probability_of_success = prob
        opp.confidence = prob
        opp.stage = OpportunityStage.DISCOVER
        for sig in signals:
            opp.update_signals(sig)
        opps.append(opp)
        print(f"  {name}: margin={margin}% risk={risk} prob={prob:.0%}")

    # Step 2: Register to SSM
    print("\n[STEP 2] SystemStateManager")
    print("-" * 50)
    for o in opps:
        ssm.register(o)
        print(f"  {o.product_name} [{o.id[:8]}]")
    print(f"  Total: {ssm.get_global_stats().total_opportunities} opps")

    # Step 3: Decision Loop
    print("\n[STEP 3] Decision Kernel")
    print("-" * 50)
    results = []
    for opp in opps:
        pred = oe.predict(opp)
        opp.apply_outcome_prediction(pred["p10"], pred["p50"], pred["p90"], pred["prob_success"])
        port = pm.analyze(opp, opps)
        cf = ll.extract(opp)
        rfe.record_pred(pred["expected_roi"])
        ctx = OpportunityContext(
            opportunity=opp,
            prob_success=pred["prob_success"],
            expected_roi=pred["expected_roi"],
            payback_days_estimate=pred["payback_days"],
            portfolio_concentration=port["portfolio_concentration"],
            budget_available=port["budget_available"],
            suggested_budget=port["suggested_budget"],
            causal_confidence=cf["causal_confidence"],
            failure_risk_factors=cf["failure_risks"],
            model_trust_score=rfe.trust(),
        )
        dec = dk.decide(ctx)
        results.append(dec)
        ssm.update_decision(opp.id, dec.decision, dec.primary_reason)
        if dec.decision == Decision.INVEST:
            ssm.transition(opp.id, OpportunityStage.VALIDATE, dec.action)
        elif dec.decision == Decision.SCALE:
            ssm.transition(opp.id, OpportunityStage.SCALE, dec.action)
        elif dec.decision == Decision.STOP:
            ssm.transition(opp.id, OpportunityStage.STOP, dec.action)
        print(f"  [{opp.product_name}] decision={dec.decision.value} priority={dec.priority}")
        print(f"    P50=${pred['p50']:,.0f} ROI={pred['expected_roi']:.1f}% payback={pred['payback_days']}d")
        print(f"    Action: {dec.action}")

    # Step 4: Portfolio
    print("\n[STEP 4] Portfolio Manager")
    print("-" * 50)
    summary = ssm.get_board_summary()
    for s, c in summary["by_stage"].items():
        print(f"  {s}: {c}")
    dc = {}
    for d in results:
        dc[d.decision.value] = dc.get(d.decision.value, 0) + 1
    print(f"  Decisions: {dc}")

    # Step 5: RFE Feedback
    print("\n[STEP 5] RFE Engine")
    print("-" * 50)
    print(f"  Trust before feedback: {rfe.trust():.2f}")
    for opp in opps[:3]:
        actual = max(opp.roi_estimate * random.uniform(0.5, 1.5), 1)
        rfe.record_actual(actual)
        err = abs(actual - opp.roi_estimate) / max(opp.roi_estimate, 1) * 100
        print(f"  {opp.product_name}: pred={opp.roi_estimate:.1f}% actual={actual:.1f}% err={err:.0f}%")
    print(f"  Trust after feedback: {rfe.trust():.2f}")

    # Step 6: Alerts
    print("\n[STEP 6] SystemStateManager Alerts")
    print("-" * 50)
    crit = ssm.get_critical_alerts()
    warns = ssm.get_active_alerts(AlertLevel.WARN)
    print(f"  Critical={len(crit)} Warning={len(warns)}")

    # Step 7: Board Report
    print("\n[STEP 7] Board Report")
    print("=" * 70)
    print(ssm.get_board_summary_text())
    print()
    print(json.dumps([d.to_dict() for d in results], ensure_ascii=False, indent=2)[:600])
    print("=" * 70)
    print("CLOSED LOOP TEST COMPLETE")

if __name__ == "__main__":
    run()