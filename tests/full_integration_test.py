"""
HVOS V10.3 — 全链路闭关测试 (Full Integration Test)
=====================================================
覆盖范围：
  Phase 1: 核心引擎 (hvos_state / decision / kg / rfe / digital_twin)
  Phase 2: 机会引擎 (OE + 6 collectors + signal_filter + signal_enricher)
  Phase 3: 商业引擎 (HCOM margins / capital_book / portfolio_manager)
  Phase 4: 现实数据层 (reality_pipeline / woo_pipeline)
  Phase 5: 学习引擎 (adaptive_learning / evolution / self_training)
  Phase 6: 治理与推理 (policy_governor / causal_engine)
  Phase 7: 世界模型 (world_model)
  Phase 8: 配置文件完整性 (config/*.json)
  Phase 9: Knowledge Graph
  Phase 10: Board Meetings / Outcome Engine

输出: JSON报告 + 打印摘要
"""
import sys, os, json, time, traceback
from datetime import datetime

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
sys.path.insert(0, HVOS_ROOT)
os.chdir(HVOS_ROOT)

RESULTS = {"started": datetime.now().isoformat(), "phases": {}, "summary": {}}

def phase(name):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            print(f"\n{'='*65}")
            print(f"  PHASE: {name}")
            print(f"{'='*65}")
            results = {}
            ok_count = 0; fail_count = 0; warn_count = 0
            try:
                results = fn()
            except Exception as e:
                results = {"_ERROR": f"{type(e).__name__}: {e}\n{traceback.format_exc()[-300:]}"}
            for k, v in results.items():
                if k.startswith("_"): continue
                if isinstance(v, dict) and "status" in v:
                    s = v["status"]
                    if s == "PASS": ok_count += 1
                    elif s == "FAIL": fail_count += 1
                    else: warn_count += 1
                elif isinstance(v, bool):
                    if v: ok_count += 1
                    else: fail_count += 1
            total = ok_count + fail_count + warn_count
            status = "PASS" if fail_count == 0 else "FAIL"
            print(f"\n  [{status}] {name}: {ok_count}/{total} OK", end="")
            if warn_count: print(f" ({warn_count} WARN)", end="")
            if fail_count: print(f" ({fail_count} FAIL)", end="")
            print()
            RESULTS["phases"][name] = {
                "status": status,
                "passed": ok_count, "failed": fail_count, "warned": warn_count,
                "results": results
            }
            return results
        return wrapper
    return decorator

# ──────────────────────────────────────────────────────────────────
# PHASE 1: Core Engine
# ──────────────────────────────────────────────────────────────────
@phase("Phase 1: 核心引擎 (hvos_state/decision/kg/rfe/digital_twin)")
def phase1():
    from hvos_state import SystemStateManager, AlertLevel
    from hvos_decision import DecisionKernel, OpportunityContext
    from hcom import new_opportunity, OpportunityStage
    from hvos_kg_engine import KnowledgeGraphEngine
    from core.hvos_rfe_engine import RealityFeedbackEngine
    from hvos_digital_twin_engine import DigitalTwinEngine

    r = {}

    # 1-1: SystemStateManager
    ssm = SystemStateManager()
    opp = new_opportunity("Test Product", "test_category")
    opp.trend_score = 7.0; opp.demand_score = 7.0; opp.supply_score = 5.0
    opp.margin_estimate = 32.0; opp.risk_score = 3.5; opp.probability_of_success = 0.65
    ssm.register(opp)
    ssm.update_decision(opp.id, "invest", "Test reason")
    stats = ssm.get_global_stats()
    r["1-1 SystemStateManager register+stats"] = {
        "status": "PASS" if stats.total_opportunities >= 1 else "FAIL",
        "detail": f"total={stats.total_opportunities}"
    }

    # 1-2: DecisionKernel
    dk = DecisionKernel()
    ctx = OpportunityContext(
        opportunity=opp,
        prob_success=0.65, expected_roi=20.8, payback_days_estimate=60,
        portfolio_concentration=0.2, budget_available=10000,
        suggested_budget=3000, causal_confidence=0.75,
        failure_risk_factors=[], model_trust_score=0.8,
    )
    dec = dk.decide(ctx)
    r["1-2 DecisionKernel decide"] = {
        "status": "PASS" if dec.decision.value in ("invest","test","hold") else "FAIL",
        "detail": f"decision={dec.decision.value}, priority={dec.priority}"
    }

    # 1-3: KnowledgeGraphEngine
    try:
        kg = KnowledgeGraphEngine()
        kg.add_opportunity_node("TestOPP", {"category": "test", "alpha_score": 75})
        kg.add_signal_node("TestSignal", {"source": "test", "strength": 8.0})
        kg.add_relation("TestOPP", "identified_by", "TestSignal")
        subgraph = kg.query_opportunity_signals("TestOPP")
        r["1-3 KnowledgeGraphEngine"] = {
            "status": "PASS",
            "detail": f"nodes={len(subgraph.get('nodes',[]))}, edges={len(subgraph.get('edges',[]))}"
        }
    except Exception as e:
        r["1-3 KnowledgeGraphEngine"] = {"status": "FAIL", "detail": str(e)}

    # 1-4: RealityFeedbackEngine
    try:
        rfe = RealityFeedbackEngine()
        rfe.record_prediction("test_opp", {"roi": 25.0, "cvr": 0.04})
        rfe.record_actual("test_opp", {"roi": 22.0, "cvr": 0.038})
        trust = rfe.get_trust_score("test_opp")
        r["1-4 RealityFeedbackEngine"] = {
            "status": "PASS" if trust >= 0 else "FAIL",
            "detail": f"trust={trust:.3f}"
        }
    except Exception as e:
        r["1-4 RealityFeedbackEngine"] = {"status": "FAIL", "detail": str(e)}

    # 1-5: DigitalTwinEngine
    try:
        dte = DigitalTwinEngine()
        sim = dte.simulate_opportunity({"trend": 7, "margin": 32, "risk": 3.5, "demand": 7})
        r["1-5 DigitalTwinEngine simulate"] = {
            "status": "PASS" if sim.get("simulated_roi") > 0 else "FAIL",
            "detail": f"simulated_roi={sim.get('simulated_roi')}"
        }
    except Exception as e:
        r["1-5 DigitalTwinEngine"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 2: Opportunity Engine (OE + 6 collectors + filter + enricher)
# ──────────────────────────────────────────────────────────────────
@phase("Phase 2: 机会引擎 (OE + 6 collectors + filter + enricher)")
def phase2():
    from opportunity.opportunity_engine import OpportunityEngine
    from opportunity.signal_filter import SignalFilter
    from opportunity.signal_enricher import SignalEnricher

    r = {}

    # 2-1: OpportunityEngine init + collectors
    try:
        oe = OpportunityEngine()
        collectors = list(oe.collectors.keys())
        r["2-1 OE init"] = {
            "status": "PASS",
            "detail": f"collectors={collectors}"
        }
    except Exception as e:
        r["2-1 OE init"] = {"status": "FAIL", "detail": str(e)}

    # 2-2: SignalFilter
    sf = SignalFilter()
    good = {"source": "test", "keyword": "x", "estimated_gmv": 20000, "bsr": 30000}
    res = sf._filter_signal(good)
    r["2-2a SignalFilter pass good signal"] = {
        "status": "PASS" if res.passed else "FAIL",
        "detail": f"passed={res.passed}"
    }
    bad_gmv = {"source": "test", "keyword": "x", "estimated_gmv": 5000}
    res = sf._filter_signal(bad_gmv)
    r["2-2b SignalFilter reject low GMV"] = {
        "status": "PASS" if not res.passed else "FAIL",
        "detail": f"reason={res.reason}"
    }
    bad_bsr = {"source": "test", "keyword": "x", "bsr": 90000}
    res = sf._filter_signal(bad_bsr)
    r["2-2c SignalFilter reject high BSR"] = {
        "status": "PASS" if not res.passed else "FAIL",
        "detail": f"reason={res.reason}"
    }
    enriched = sf.enrich_seasonal_info([{"keyword": "x"}])
    r["2-2d SignalFilter seasonal enrich"] = {
        "status": "PASS" if "_days_to_america250" in enriched[0] else "FAIL",
        "detail": f"days={enriched[0].get('_days_to_america250')}"
    }

    # 2-3: SignalEnricher
    se = SignalEnricher(max_workers=2)
    test_sigs = [{"keyword": "christmas lights", "category": "holiday"}]
    en = se.enrich(test_sigs)
    r["2-3 SignalEnricher"] = {
        "status": "PASS" if all(k in en[0] for k in ("_competitors","_swot","_enriched","_market_size_b")) else "FAIL",
        "detail": f"keys={list(en[0].keys())}"
    }

    # 2-4: OE pipeline steps
    import inspect
    src = inspect.getsource(oe.run_full_scan)
    has_filter = "SignalFilter" in src
    has_enrich = "enricher.enrich" in src or "SignalEnricher" in src
    r["2-4 OE pipeline filter+enrich"] = {
        "status": "PASS" if has_filter and has_enrich else "FAIL",
        "detail": f"filter={has_filter}, enrich={has_enrich}"
    }

    # 2-5: All 5 collectors registered (industry_recon priority)
    expected = ['serpapi', 'reddit', 'amazon', 'hackernews', 'industry_recon']
    missing = [c for c in expected if c not in collectors]
    r["2-5 All 5 collectors registered"] = {
        "status": "PASS" if not missing else "FAIL",
        "detail": f"missing={missing}, present={collectors}"
    }

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 3: Commerce Engine (HCOM / margins / pricing)
# ──────────────────────────────────────────────────────────────────
@phase("Phase 3: 商业引擎 (HCOM / margins / capital_book)")
def phase3():
    import hcom
    from hcom import new_opportunity, OpportunityStage
    from margins import calculate_margins
    from capital_book import CapitalBook

    r = {}

    # 3-1: HCOM new_opportunity
    try:
        opp = new_opportunity("Christmas Gift Set", "gift_sets")
        r["3-1 HCOM new_opportunity"] = {
            "status": "PASS",
            "detail": f"id={opp.id[:8]}, stage={opp.stage.value}"
        }
    except Exception as e:
        r["3-1 HCOM new_opportunity"] = {"status": "FAIL", "detail": str(e)}

    # 3-2: HCOM OpportunityObject has required fields
    try:
        opp = new_opportunity("Test", "test")
        required = ["id", "product_name", "product_niche", "stage", "trend_score",
                    "demand_score", "supply_score", "margin_estimate", "risk_score",
                    "roi_estimate", "probability_of_success", "alpha_score"]
        missing = [f for f in required if not hasattr(opp, f)]
        r["3-2 HCOM OpportunityObject fields"] = {
            "status": "PASS" if not missing else "FAIL",
            "detail": f"missing={missing}" if missing else "all present"
        }
    except Exception as e:
        r["3-2 HCOM OpportunityObject fields"] = {"status": "FAIL", "detail": str(e)}

    # 3-3: margins.py
    try:
        margins = calculate_margins(35.0, 8.50, 12.0, 5.0)
        r["3-3 margins calculate_margins"] = {
            "status": "PASS" if margins.get("net_margin", 0) > 0 else "FAIL",
            "detail": f"net_margin={margins.get('net_margin')}, roi={margins.get('roi_estimate')}"
        }
    except Exception as e:
        r["3-3 margins"] = {"status": "FAIL", "detail": str(e)}

    # 3-4: CapitalBook
    try:
        cb = CapitalBook()
        summary = cb.get_summary()
        r["3-4 CapitalBook summary"] = {
            "status": "PASS" if "total_capital" in summary else "FAIL",
            "detail": f"keys={list(summary.keys())}"
        }
    except Exception as e:
        r["3-4 CapitalBook"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 4: Reality Data Layer
# ──────────────────────────────────────────────────────────────────
@phase("Phase 4: 现实数据层 (reality_pipeline / woo_pipeline)")
def phase4():
    r = {}
    # 4-1: reality_config.json
    try:
        with open(os.path.join(HVOS_ROOT, "config", "reality_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        r["4-1 reality_config.json valid JSON"] = {
            "status": "PASS",
            "detail": f"shopify_enabled={cfg.get('shopify',{}).get('enabled')}, keys={list(cfg.keys())}"
        }
    except Exception as e:
        r["4-1 reality_config.json"] = {"status": "FAIL", "detail": str(e)}

    # 4-2: woo_reality_scored.json
    try:
        with open(os.path.join(HVOS_ROOT, "config", "woo_reality_scored.json"), encoding="utf-8") as f:
            woo = json.load(f)
        r["4-2 woo_reality_scored.json"] = {
            "status": "PASS",
            "detail": f"products={woo.get('products_fetched', woo.get('woo_products_fetched','?'))}"
        }
    except Exception as e:
        r["4-2 woo_reality_scored.json"] = {"status": "FAIL", "detail": str(e)}

    # 4-3: v10_reality_scored.json
    try:
        with open(os.path.join(HVOS_ROOT, "config", "v10_reality_scored.json"), encoding="utf-8") as f:
            v10 = json.load(f)
        r["4-3 v10_reality_scored.json"] = {
            "status": "PASS",
            "detail": f"products={v10.get('woo_products_fetched','?')}"
        }
    except Exception as e:
        r["4-3 v10_reality_scored.json"] = {"status": "FAIL", "detail": str(e)}

    # 4-4: reality_data_pipeline functions
    try:
        from reality_data_pipeline import fetch_all_products, analyze_product_catalog
        products = fetch_all_products()
        analyzed = analyze_product_catalog(products or [])
        r["4-4 reality_data_pipeline functions"] = {
            "status": "PASS" if isinstance(analyzed, dict) else "FAIL",
            "detail": f"products={len(products)}, analyzed_keys={list(analyzed.keys()) if isinstance(analyzed,dict) else type(analyzed)}"
        }
    except Exception as e:
        r["4-4 reality_data_pipeline"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 5: Learning & Evolution
# ──────────────────────────────────────────────────────────────────
@phase("Phase 5: 学习引擎 (adaptive_learning / evolution / self_training)")
def phase5():
    from learning.adaptive_learning_engine import AdaptiveThresholdLearner, PredictionCalibrator
    from hvos_evolution_engine import HVOSEvolutionEngine

    r = {}

    # 5-1: AdaptiveThresholdLearner
    try:
        learner = AdaptiveThresholdLearner()
        result = learner.classify("gift_sets", "US", "roi", 25.0)
        r["5-1 AdaptiveThresholdLearner classify"] = {
            "status": "PASS" if result.get("level") in ("low","normal","high") else "FAIL",
            "detail": f"level={result.get('level')}, n_samples={result.get('n_samples')}"
        }
    except Exception as e:
        r["5-1 AdaptiveThresholdLearner"] = {"status": "FAIL", "detail": str(e)}

    # 5-2: PredictionCalibrator
    try:
        cal = PredictionCalibrator()
        cal.record_actual("pred_test", "opp_test", 22.0)
        cal_record = cal.get_calibration("pred_test")
        r["5-2 PredictionCalibrator record+get"] = {
            "status": "PASS" if cal_record else "FAIL",
            "detail": f"record={cal_record}"
        }
    except Exception as e:
        r["5-2 PredictionCalibrator"] = {"status": "FAIL", "detail": str(e)}

    # 5-3: HVOSEvolutionEngine
    try:
        evo = HVOSEvolutionEngine()
        r["5-3 HVOSEvolutionEngine init"] = {
            "status": "PASS",
            "detail": f"version={getattr(evo,'version','?')}"
        }
    except Exception as e:
        r["5-3 HVOSEvolutionEngine"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 6: Governance & Reasoning
# ──────────────────────────────────────────────────────────────────
@phase("Phase 6: 治理与推理 (policy_governor / causal_engine)")
def phase6():
    from governance.policy_governor import PolicyGovernor
    from reasoning.causal_intelligence_engine import CausalIntelligenceEngine

    r = {}

    # 6-1: PolicyGovernor
    try:
        gov = PolicyGovernor()
        report = gov.governance_report()
        r["6-1 PolicyGovernor governance_report"] = {
            "status": "PASS" if "total_policies" in report else "FAIL",
            "detail": f"total={report.get('total_policies')}, active={report.get('active_count')}"
        }
    except Exception as e:
        r["6-1 PolicyGovernor"] = {"status": "FAIL", "detail": str(e)}

    # 6-2: CausalIntelligenceEngine
    try:
        causal = CausalIntelligenceEngine()
        # Real API: infer_causal_graph(opp_id) → BayesianCausalGraph
        graph = causal.infer_causal_graph("test_opp")
        r["6-2 CausalIntelligenceEngine infer_causal_graph"] = {
            "status": "PASS" if graph is not None else "FAIL",
            "detail": f"type={type(graph).__name__}"
        }
    except Exception as e:
        r["6-2 CausalIntelligenceEngine infer_causal_graph"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 7: World Model
# ──────────────────────────────────────────────────────────────────
@phase("Phase 7: 世界模型 (world_model)")
def phase7():
    sys.path.insert(0, os.path.join(HVOS_ROOT, "core", "world_model"))
    from world_model import WorldModel

    r = {}

    # 7-1: WorldModel init + predict
    try:
        wm = WorldModel()
        pred = wm.predict("test_opp_001", "gift_sets", "US",
                          trend_score=7.0, supply_score=5.0,
                          risk_score=3.5, margin_pct=0.32)
        r["7-1 WorldModel predict"] = {
            "status": "PASS" if pred.predicted_roi > 0 else "FAIL",
            "detail": f"roi={pred.predicted_roi:.2f}, cvr={pred.predicted_cvr:.4f}"
        }
    except Exception as e:
        r["7-1 WorldModel predict"] = {"status": "FAIL", "detail": str(e)}

    # 7-2: WorldModel learn_from_outcome (Bayesian update)
    try:
        result = wm.learn_from_outcome("gift_sets", "US",
                                        actual_roi=22.0, actual_cvr=0.038,
                                        actual_ctr=0.025, actual_ltv=65.0,
                                        actual_refund_rate=0.03)
        r["7-2 WorldModel learn_from_outcome"] = {
            "status": "PASS" if result.get("updated_params") else "FAIL",
            "detail": f"updated={result.get('updated_params')}"
        }
    except Exception as e:
        r["7-2 WorldModel learn_from_outcome"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 8: Config Files
# ──────────────────────────────────────────────────────────────────
@phase("Phase 8: 配置文件完整性")
def phase8():
    configs = {
        "reality_config.json": ["shopify", "woo"],
        "margin_report.json": ["products"],
        "v10_category_scout_results.json": ["results", "total"],
        "v10_reality_scored.json": ["woo_products_fetched", "woo_categories"],
        "woo_reality_scored.json": ["products_fetched"],
        "ar_trending_signals.json": ["signals"],
    }
    r = {}
    for fname, required_keys in configs.items():
        fpath = os.path.join(HVOS_ROOT, "config", fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            missing = [k for k in required_keys if k not in data]
            r[f"8 Config: {fname}"] = {
                "status": "PASS" if not missing else "WARN",
                "detail": f"keys={list(data.keys())[:5]}" + (f", MISSING={missing}" if missing else "")
            }
        except json.JSONDecodeError as e:
            r[f"8 Config: {fname}"] = {"status": "FAIL", "detail": f"JSON error: {e}"}
        except Exception as e:
            r[f"8 Config: {fname}"] = {"status": "FAIL", "detail": str(e)}
    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 9: Knowledge Graph
# ──────────────────────────────────────────────────────────────────
@phase("Phase 9: Knowledge Graph")
def phase9():
    from hvos_kg_engine import KnowledgeGraphEngine
    r = {}
    kg_path = os.path.join(HVOS_ROOT, "knowledge_graph", "knowledge_graph.json")
    # 9-1: KG file valid JSON
    try:
        with open(kg_path, encoding="utf-8") as f:
            kg_data = json.load(f)
        node_count = len(kg_data.get("nodes", []))
        edge_count = len(kg_data.get("edges", []))
        r["9-1 KG JSON valid"] = {
            "status": "PASS",
            "detail": f"nodes={node_count}, edges={edge_count}"
        }
    except Exception as e:
        r["9-1 KG JSON valid"] = {"status": "FAIL", "detail": str(e)}

    # 9-2: KnowledgeGraphEngine CRUD
    try:
        kg = KnowledgeGraphEngine()
        kg.add_opportunity_node("IntegTest", {"category": "test", "alpha_score": 80})
        kg.add_signal_node("SigTest", {"source": "test", "strength": 8.5})
        kg.add_relation("IntegTest", "identified_by", "SigTest")
        sub = kg.query_opportunity_signals("IntegTest")
        r["9-2 KG CRUD operations"] = {
            "status": "PASS" if sub.get("nodes") and sub.get("edges") else "FAIL",
            "detail": f"nodes={len(sub.get('nodes',[]))}, edges={len(sub.get('edges',[]))}"
        }
    except Exception as e:
        r["9-2 KG CRUD operations"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# PHASE 10: Board & Outcome Engine
# ──────────────────────────────────────────────────────────────────
@phase("Phase 10: Board & Outcome Engine")
def phase10():
    from hvos_state import SystemStateManager
    from hvos_decision import DecisionKernel, OpportunityContext
    from hcom import new_opportunity
    from outcome_engine import OutcomeEngine

    r = {}

    # 10-1: Board summary
    try:
        ssm = SystemStateManager()
        summary = ssm.get_board_summary()
        r["10-1 Board summary structure"] = {
            "status": "PASS" if "total_opportunities" in summary else "FAIL",
            "detail": f"keys={list(summary.keys())}"
        }
    except Exception as e:
        r["10-1 Board summary"] = {"status": "FAIL", "detail": str(e)}

    # 10-2: OutcomeEngine
    try:
        from outcome_engine import OutcomeEngine
        oe = OutcomeEngine()
        # Real API: predict(opp_id, opp_name, trend_score, supply_score,
        #                   risk_score, margin_pct, write_to_kg=False)
        # Returns OutcomePrediction: expected_roi, success_probability,
        #                             worst_case_roi, best_case_roi,
        #                             confidence_score, etc.
        pred = oe.predict("test_opp_001", "Board Test OPP",
                          trend_score=7.0, supply_score=5.0,
                          risk_score=3.5, margin_pct=0.30,
                          write_to_kg=False)
        r["10-2 OutcomeEngine predict"] = {
            "status": "PASS" if hasattr(pred, 'expected_roi') and hasattr(pred, 'success_probability') else "FAIL",
            "detail": f"expected_roi={pred.expected_roi:.2f}, prob={pred.success_probability:.3f}"
        }
    except Exception as e:
        r["10-2 OutcomeEngine predict"] = {"status": "FAIL", "detail": str(e)}

    return r

# ──────────────────────────────────────────────────────────────────
# RUN ALL PHASES
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    phases = [
        phase1, phase2, phase3, phase4, phase5,
        phase6, phase7, phase8, phase9, phase10
    ]

    for p in phases:
        try:
            p()
        except Exception as e:
            print(f"  [{p.__name__}] FATAL: {e}")

    # ── Summary ──────────────────────────────────────────────────
    total_pass = sum(r["passed"] for r in RESULTS["phases"].values())
    total_fail = sum(r["failed"] for r in RESULTS["phases"].values())
    total_warn = sum(r["warned"] for r in RESULTS["phases"].values())
    total = total_pass + total_fail + total_warn
    overall = "PASS" if total_fail == 0 else "FAIL"

    RESULTS["summary"] = {
        "overall": overall,
        "total_passed": total_pass,
        "total_failed": total_fail,
        "total_warned": total_warn,
        "total": total,
        "completed_at": datetime.now().isoformat()
    }

    print(f"\n{'='*65}")
    print(f"  HVOS V10.3 FULL INTEGRATION TEST — FINAL SUMMARY")
    print(f"{'='*65}")
    print(f"  Overall: [{overall}]")
    print(f"  Total:   {total_pass}/{total} passed", end="")
    if total_warn: print(f", {total_warn} warned", end="")
    if total_fail: print(f", {total_fail} FAILED", end="")
    print()

    print(f"\n  By Phase:")
    for name, data in RESULTS["phases"].items():
        icon = "✅" if data["status"] == "PASS" else "❌"
        print(f"    {icon} {name}: {data['passed']}/{data['passed']+data['failed']} OK")

    # Save JSON report
    report_dir = os.path.join(HVOS_ROOT, "pipeline_output")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"full_integration_test_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Report: {report_path}")

    sys.exit(0 if overall == "PASS" else 1)
