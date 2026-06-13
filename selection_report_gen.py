import sys, json, random, math
sys.path.insert(0, ".")

from hcom import new_opportunity, new_market_signal, OpportunityStage, SignalPlatform, TrendPhase
from hvos_state import SystemStateManager
from hvos_decision import DecisionKernel, OpportunityContext


def monte_carlo_outcome(prob, margin_pct, base_investment=5000):
    """基于 HCOM prob + margin 的简化蒙特卡洛模拟"""
    mu = prob * margin_pct * base_investment
    sigma = mu * 0.4
    samples = [max(-1, random.gauss(mu, sigma)) for _ in range(200)]
    samples.sort()
    p10 = samples[len(samples)//10]
    p50 = samples[len(samples)//2]
    p90 = samples[len(samples)*9//10]
    return p10, p50, p90, prob


def run_selection():
    signals = [
        new_market_signal(SignalPlatform.TIKTOK, 8.5, 1.2, "up", TrendPhase.EMERGING),
        new_market_signal(SignalPlatform.AMAZON, 7.0, 0.8, "up", TrendPhase.PEAK),
        new_market_signal(SignalPlatform.GOOGLE, 7.8, 0.9, "up", TrendPhase.PEAK),
    ]

    candidates = [
        {"name": "Pet Grooming Gloves (宠物美容手套)", "niche": "pet_grooming", "trend": 8.5, "demand": 8.0, "supply": 4.5, "margin": 0.42, "risk": 3.0, "prob": 0.72, "ad": ["TikTok", "Meta", "Amazon PPC"], "market": "北美/欧洲宠物主", "week": "W25"},
        {"name": "Mini Massage Gun (便携按摩枪)", "niche": "fitness_recovery", "trend": 9.0, "demand": 8.5, "supply": 3.0, "margin": 0.45, "risk": 2.5, "prob": 0.78, "ad": ["TikTok", "Instagram", "Amazon PPC"], "market": "北美健身/康复人群", "week": "W25"},
        {"name": "Smart Garden Light (智能园艺灯)", "niche": "garden_tools", "trend": 7.0, "demand": 6.5, "supply": 5.0, "margin": 0.35, "risk": 4.0, "prob": 0.58, "ad": ["TikTok", "Pinterest", "Amazon PPC"], "market": "北美园艺爱好者", "week": "W26"},
        {"name": "Foldable Travel Cup (折叠旅行杯)", "niche": "travel_accessories", "trend": 6.5, "demand": 5.5, "supply": 7.0, "margin": 0.25, "risk": 5.5, "prob": 0.42, "ad": ["TikTok", "Instagram"], "market": "北美千禧旅行族", "week": "W27"},
        {"name": "Smart Kitchen Bin (智能厨房垃圾桶)", "niche": "kitchen_home", "trend": 7.5, "demand": 7.0, "supply": 4.0, "margin": 0.38, "risk": 3.5, "prob": 0.65, "ad": ["TikTok", "Meta", "Pinterest"], "market": "北美/欧洲环保家庭", "week": "W26"},
        {"name": "Mens Grooming Kit (男士理容套装)", "niche": "mens_grooming", "trend": 8.0, "demand": 7.5, "supply": 5.5, "margin": 0.52, "risk": 4.0, "prob": 0.68, "ad": ["Meta", "Google", "TikTok"], "market": "北美25-40岁男性", "week": "W25"},
    ]

    ssm = SystemStateManager()
    dk = DecisionKernel()
    results = []

    for c in candidates:
        opp = new_opportunity(c["name"], c["niche"])
        opp.trend_score = c["trend"]
        opp.demand_score = c["demand"]
        opp.supply_score = c["supply"]
        opp.margin_estimate = c["margin"] * 100
        opp.risk_score = c["risk"]
        opp.probability_of_success = c["prob"]
        opp.confidence = c["prob"]
        opp.stage = OpportunityStage.DISCOVER
        for sig in signals:
            opp.update_signals(sig)

        # Monte Carlo (HCOM prob + margin)
        p10, p50, p90, prob = monte_carlo_outcome(c["prob"], c["margin"])
        roi_pct = (p50 / 5000) * 100
        opp.apply_outcome_prediction(p10, p50, p90, prob)

        payback = int(90 / prob) if prob > 0.3 else 999

        ctx = OpportunityContext(
            opportunity=opp,
            prob_success=prob,
            expected_profit_p10=p10,
            expected_profit_p50=p50,
            expected_profit_p90=p90,
            expected_roi=roi_pct,
            payback_days_estimate=payback,
            portfolio_concentration=0.3,
            budget_available=10000.0,
            suggested_budget=3000.0,
            causal_confidence=c["prob"],
            failure_risk_factors=[],
            model_trust_score=0.70,
        )

        dec = dk.decide(ctx)
        ssm.register(opp)
        ssm.update_decision(opp.id, dec.decision, dec.primary_reason)
        if dec.decision.value in ("invest", "scale"):
            ssm.transition(opp.id, OpportunityStage.VALIDATE, dec.action)
        elif dec.decision.value == "stop":
            ssm.transition(opp.id, OpportunityStage.STOP, dec.action)

        results.append({
            "name": c["name"],
            "niche": c["niche"],
            "decision": dec.decision.value,
            "priority": dec.priority,
            "prob": round(prob * 100, 1),
            "roi": round(roi_pct, 1),
            "p10": round(p10, 0),
            "p50": round(p50, 0),
            "p90": round(p90, 0),
            "payback_days": payback,
            "budget": dec.allocated_budget,
            "action": dec.action,
            "reason": dec.primary_reason,
            "stage": opp.stage.value,
            "ad": c["ad"],
            "market": c["market"],
            "week": c["week"],
            "trend": c["trend"],
            "risk": c["risk"],
        })

    priority_order = {"scale": 0, "invest": 1, "hold": 2, "wait": 3, "stop": 4}
    results.sort(key=lambda x: (priority_order.get(x["decision"], 5), x["priority"]))
    return results, ssm


if __name__ == "__main__":
    results, ssm = run_selection()
    report = {
        "generated_at": "2026-06-12",
        "total": len(results),
        "recommendations": results,
    }
    out = "C:/Users/Administrator/AppData/Local/hermes/selection_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Saved: {len(results)} products")
    for r in results:
        print(f"  [{r['decision'].upper():6}] {r['name'][:42]:42} prob={r['prob']:5.1f}% roi={r['roi']:6.1f}% budget=${r['budget']:6,.0f} stage={r['stage']}")
