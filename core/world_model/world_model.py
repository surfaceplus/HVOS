# HVOS V10 — World Model Engine
# ==============================
# Purpose: Unified cognitive prediction layer.
# Every subsystem must consume predictions from here — NOT maintain its own prediction logic.
#
# Design principle:
#   "One model, one prediction, one source of truth."
#
# Supported predictions:
#   ROI, CVR, CTR, LTV, Refund Risk, Competition Intensity, Demand Growth,
#   Market Saturation, Lifecycle Duration, Success Probability

from __future__ import annotations

import json
import math
import sqlite3
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger("world_model")

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
KG_DB = rf"{HVOS_ROOT}\knowledge-graph\kg.db"
STRATEGY_DB = rf"{HVOS_ROOT}\knowledge-graph\strategy_memory.db"
WM_DB = rf"{HVOS_ROOT}\knowledge-graph\world_model.db"

# ──────────────────────────────────────────────────────────────
# Prediction Contract
# ──────────────────────────────────────────────────────────────


@dataclass
class WorldModelPrediction:
    """Unified prediction output contract."""

    prediction_id: str
    opp_id: str
    model_version: str = "v1.0.0"
    predicted_at: str = ""

    # ── Core metrics ──────────────────────────
    predicted_roi: float = 0.0
    predicted_roi_std: float = 0.0
    roi_distribution: List[float] = field(default_factory=list)

    predicted_cvr: float = 0.0
    predicted_ctr: float = 0.0
    predicted_ltv: float = 0.0
    predicted_refund_risk: float = 0.0

    # ── Market metrics ────────────────────────
    predicted_demand_growth: float = 0.0
    predicted_competition_intensity: float = 0.0
    predicted_market_saturation: float = 0.0
    predicted_lifecycle_duration_days: int = 0

    # ── Probability ───────────────────────────
    success_probability: float = 0.0
    probability_of_loss: float = 0.0

    # ── Confidence ────────────────────────────
    confidence_score: float = 0.0
    confidence_factors: dict = field(default_factory=dict)

    # ── Recommendation ────────────────────────
    recommendation: str = "HOLD"  # INVEST / TEST / HOLD / REJECT

    def __post_init__(self):
        import uuid
        if not self.prediction_id:
            self.prediction_id = f"wm_{uuid.uuid4().hex[:12]}"
        if not self.predicted_at:
            self.predicted_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["roi_distribution"] = json.dumps(d["roi_distribution"][:100])
        return d


# ──────────────────────────────────────────────────────────────
# 1. Bayesian Parameter Store
# ──────────────────────────────────────────────────────────────


class BayesianParameterStore:
    """
    Maintains Bayesian priors and posteriors for all prediction parameters.

    Each (category, market, metric) has:
      - mu: current mean estimate
      - sigma: current standard deviation
      - n_samples: number of observations
      - last_updated: timestamp
    """

    def __init__(self, db_path: str = WM_DB):
        self.db_path = db_path
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bayesian_params (
                category TEXT NOT NULL,
                market TEXT NOT NULL,
                metric TEXT NOT NULL,
                mu REAL DEFAULT 0,
                sigma REAL DEFAULT 1.0,
                n_samples INTEGER DEFAULT 0,
                prior_mu REAL DEFAULT 0,
                prior_sigma REAL DEFAULT 1.0,
                last_updated TEXT,
                PRIMARY KEY (category, market, metric)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prediction_log (
                prediction_id TEXT PRIMARY KEY,
                opp_id TEXT,
                model_version TEXT,
                predicted_at TEXT,
                predictions TEXT,
                actuals TEXT,
                error_score REAL,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ── Get current parameter ────────────────────────────

    def get(self, category: str, market: str, metric: str) -> dict:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT mu, sigma, n_samples, last_updated
            FROM bayesian_params
            WHERE category = ? AND market = ? AND metric = ?
        """, (category, market, metric))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "mu": float(row["mu"]),
                "sigma": float(row["sigma"]),
                "n_samples": int(row["n_samples"]),
                "last_updated": row["last_updated"],
            }
        # Return uninformative prior
        return {"mu": 0.0, "sigma": 1.0, "n_samples": 0, "last_updated": ""}

    def get_or_default(self, category: str, market: str, metric: str, default_mu: float, default_sigma: float) -> dict:
        params = self.get(category, market, metric)
        if params["n_samples"] == 0:
            params["mu"] = default_mu
            params["sigma"] = default_sigma
        return params

    # ── Bayesian update: conjugate normal-normal ─────────

    def update(self, category: str, market: str, metric: str, observed_value: float, observed_std: float = 0.0):
        """
        Robust Bayesian update using Winsorized estimation.

        V10.2: Replaces pure Normal-Normal conjugate with a robust estimator.
        Strategy:
          1. Maintain a rolling buffer of recent observations (up to N=100)
          2. On each update, compute winsorized mean (trim top/bottom 10%)
          3. Use winsorized mean as the posterior estimate
          4. sigma is estimated from interquartile range (IQR) for robustness

        This makes the estimator resistant to both:
          - Single extreme outliers (trimmed)
          - Systematic poisoning (IQR-based sigma)
        """
        prior = self.get(category, market, metric)
        prior_mu = prior["mu"]
        prior_sigma = max(prior["sigma"], 0.01)
        n_prior = prior["n_samples"]

        # ── Rolling buffer of recent observations ──────────────
        buffer = self._get_observation_buffer(category, market, metric)
        buffer.append(observed_value)
        if len(buffer) > 100:
            buffer = buffer[-100:]  # Keep last 100
        self._save_observation_buffer(category, market, metric, buffer)

        n_buf = len(buffer)

        # ── Winsorized estimation ──────────────────────────────
        if n_buf >= 5:
            sorted_vals = sorted(buffer)
            # Trim top and bottom 10%
            trim_n = max(1, int(n_buf * 0.10))
            trimmed = sorted_vals[trim_n:-trim_n] if n_buf > 2 * trim_n else sorted_vals

            posterior_mu = sum(trimmed) / len(trimmed)

            # IQR-based sigma (robust to outliers)
            q1_idx = max(0, int(len(sorted_vals) * 0.25))
            q3_idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.75))
            iqr = sorted_vals[q3_idx] - sorted_vals[q1_idx]
            posterior_sigma = max(iqr / 1.35, 0.01)  # IQR/1.35 ≈ σ for normal
        elif n_buf >= 2:
            posterior_mu = sum(buffer) / len(buffer)
            posterior_sigma = max(0.1, (max(buffer) - min(buffer)) / 2.0)
        else:
            posterior_mu = observed_value
            posterior_sigma = max(observed_std, 0.1)

        # ── Blend with prior (shrinkage toward prior when data is sparse) ──
        if n_prior > 0 and n_buf < 10:
            # Shrink toward prior: weight = n_buf / (n_buf + 5)
            shrinkage = n_buf / (n_buf + 5.0)
            posterior_mu = prior_mu * (1 - shrinkage) + posterior_mu * shrinkage
            posterior_sigma = math.sqrt(
                prior_sigma**2 * (1 - shrinkage) + posterior_sigma**2 * shrinkage
            )

        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO bayesian_params
            (category, market, metric, mu, sigma, n_samples,
             prior_mu, prior_sigma, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            category, market, metric,
            posterior_mu, posterior_sigma, n_prior + 1,
            prior_mu, prior_sigma,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
        conn.close()
        logger.info(
            f"[RobustUpdate] {category}/{market}/{metric}: "
            f"{prior_mu:.3f}→{posterior_mu:.3f} σ={posterior_sigma:.3f} (n={n_prior+1}, buf={n_buf})"
        )

    # ── Observation buffer (for robust estimation) ────────

    def _get_observation_buffer(self, category: str, market: str, metric: str) -> list[float]:
        """Retrieve the rolling observation buffer."""
        conn = self._conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT observations FROM obs_buffer
                WHERE category = ? AND market = ? AND metric = ?
            """, (category, market, metric))
            row = cur.fetchone()
            if row and row["observations"]:
                return json.loads(row["observations"])
        except Exception:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS obs_buffer (
                    category TEXT NOT NULL,
                    market TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    observations TEXT,
                    PRIMARY KEY (category, market, metric)
                )
            """)
            conn.commit()
        finally:
            conn.close()
        return []

    def _save_observation_buffer(self, category: str, market: str, metric: str, buffer: list[float]):
        """Persist the rolling observation buffer."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS obs_buffer (
                category TEXT NOT NULL,
                market TEXT NOT NULL,
                metric TEXT NOT NULL,
                observations TEXT,
                PRIMARY KEY (category, market, metric)
            )
        """)
        cur.execute("""
            INSERT OR REPLACE INTO obs_buffer (category, market, metric, observations)
            VALUES (?, ?, ?, ?)
        """, (category, market, metric, json.dumps(buffer[-100:])))
        conn.commit()
        conn.close()

    # ── List all learned parameters ──────────────────────

    def list_all(self) -> list[dict]:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT category, market, metric, mu, sigma, n_samples, last_updated
            FROM bayesian_params
            ORDER BY n_samples DESC, ABS(mu) DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows


# ──────────────────────────────────────────────────────────────
# 2. Feature Store
# ──────────────────────────────────────────────────────────────


class FeatureStore:
    """
    Extracts features from KG and reality data for prediction.

    Features are normalized 0-1 to feed into the prediction model.
    """

    def __init__(self, kg_db: str = KG_DB):
        self.kg_db = kg_db

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.kg_db, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def extract(self, category: str, market: str) -> dict:
        """Extract feature vector for a (category, market) pair."""
        conn = self._conn()
        cur = conn.cursor()

        # Category-level stats
        cur.execute("""
            SELECT COUNT(*) as n_opps
            FROM kg_nodes
            WHERE entity_type = 'Opportunity'
              AND properties LIKE ?
        """, (f"%{category}%",))
        n_opps = cur.fetchone()["n_opps"]
        n_opps_norm = min(1.0, n_opps / 50.0)  # normalize: 50+ = saturated

        # Market-level stats
        cur.execute("""
            SELECT COUNT(*) as n_opps
            FROM kg_nodes
            WHERE entity_type = 'Opportunity'
              AND properties LIKE ?
        """, (f"%{market}%",))
        n_market_opps = cur.fetchone()["n_opps"]
        n_market_norm = min(1.0, n_market_opps / 100.0)

        # Success rate
        cur.execute("""
            SELECT COUNT(*) as n_records,
                   SUM(CASE WHEN verdict IN ('success','INVEST') THEN 1 ELSE 0 END) as n_success
            FROM outcome_log
        """)
        outcome_row = cur.fetchone()
        success_rate = 0.0
        if outcome_row["n_records"] and outcome_row["n_records"] > 0:
            success_rate = outcome_row["n_success"] / outcome_row["n_records"]

        # Customs data richness
        cur.execute("SELECT COUNT(*) as n FROM customs_hs_codes")
        n_hs = cur.fetchone()["n"]
        hs_richness = min(1.0, n_hs / 50.0)

        # Supply chain data
        cur.execute("SELECT COUNT(*) as n FROM customs_shipments")
        n_shipments = cur.fetchone()["n"]
        shipment_richness = min(1.0, n_shipments / 200.0)

        # Prediction error coverage
        try:
            cur.execute("SELECT COUNT(*) as n FROM prediction_error_attributions")
            n_errors = cur.fetchone()["n"]
        except Exception:
            n_errors = 0
        error_coverage = min(1.0, n_errors / 20.0)

        conn.close()

        return {
            "category_opportunity_count": n_opps_norm,
            "market_opportunity_count": n_market_norm,
            "historical_success_rate": success_rate,
            "customs_hs_richness": hs_richness,
            "customs_shipment_richness": shipment_richness,
            "prediction_error_coverage": error_coverage,
        }


# ──────────────────────────────────────────────────────────────
# 3. World Model Prediction Engine
# ──────────────────────────────────────────────────────────────


class WorldModel:
    """
    Unified cognitive prediction engine.

    This is the SINGLE SOURCE OF TRUTH for all predictions.

    Rules:
      1. Every prediction flows through world_model.predict()
      2. No module may maintain its own prediction logic
      3. Parameters are learned via Bayesian updating, not hardcoded
    """

    def __init__(self, kg_db: str = KG_DB, wm_db: str = WM_DB):
        self.kg_db = kg_db
        self.wm_db = wm_db
        self.params = BayesianParameterStore(wm_db)
        self.features = FeatureStore(kg_db)

    # ── Main prediction API ────────────────────────────

    def predict(
        self,
        opp_id: str = "",
        category: str = "",
        market: str = "US",
        trend_score: float = 5.0,
        supply_score: float = 5.0,
        risk_score: float = 5.0,
        margin_pct: float = 0.0,
    ) -> WorldModelPrediction:
        """
        Generate unified prediction.

        Uses Bayesian parameters when available, falls back to informed defaults.
        """
        pred = WorldModelPrediction(
            prediction_id=f"wm_{opp_id}",
            opp_id=opp_id,
        )

        # ── Feature extraction ─────────────────────────
        features = self.features.extract(category, market)

        # ── ROI prediction (Bayesian) ──────────────────
        roi_params = self.params.get_or_default(category, market, "roi", default_mu=1.5, default_sigma=0.8)
        # Adjust by margin, trend, supply, risk
        margin_adj = (margin_pct - 0.3) * 2.0  # center at 30% margin
        trend_adj = (trend_score - 5.0) * 0.1
        supply_adj = (supply_score - 5.0) * 0.08
        risk_adj = (5.0 - risk_score) * 0.12  # higher risk → lower ROI
        pred.predicted_roi = roi_params["mu"] + margin_adj + trend_adj + supply_adj + risk_adj
        pred.predicted_roi_std = roi_params["sigma"]

        # ── CVR prediction ─────────────────────────────
        cvr_params = self.params.get_or_default(category, market, "cvr", default_mu=0.03, default_sigma=0.015)
        pred.predicted_cvr = max(0.005, cvr_params["mu"] + (trend_score - 5.0) * 0.002)

        # ── CTR prediction ─────────────────────────────
        ctr_params = self.params.get_or_default(category, market, "ctr", default_mu=0.02, default_sigma=0.01)
        pred.predicted_ctr = max(0.003, ctr_params["mu"] + (trend_score - 5.0) * 0.003)

        # ── LTV prediction ─────────────────────────────
        ltv_params = self.params.get_or_default(category, market, "ltv", default_mu=45.0, default_sigma=20.0)
        pred.predicted_ltv = max(5.0, ltv_params["mu"] + (trend_score - 5.0) * 5.0 + margin_pct * 50.0)

        # ── Refund risk ────────────────────────────────
        refund_params = self.params.get_or_default(category, market, "refund_rate", default_mu=0.04, default_sigma=0.02)
        pred.predicted_refund_risk = refund_params["mu"]

        # ── Market metrics ─────────────────────────────
        pred.predicted_demand_growth = max(0.0, (trend_score - 3.0) * 0.15 + features["category_opportunity_count"] * 0.3)
        pred.predicted_competition_intensity = features["market_opportunity_count"]
        pred.predicted_market_saturation = features["category_opportunity_count"]
        pred.predicted_lifecycle_duration_days = int(90 + trend_score * 30 - pred.predicted_market_saturation * 60)

        # ── Success probability ────────────────────────
        # Logistic mapping: combine multiple factors
        logit = (
            (pred.predicted_roi - 1.0) * 0.5
            + (pred.predicted_cvr - 0.02) * 20.0
            + (margin_pct - 0.25) * 3.0
            - pred.predicted_refund_risk * 10.0
            + features["historical_success_rate"] * 2.0
        )
        pred.success_probability = 1.0 / (1.0 + math.exp(-logit))
        pred.probability_of_loss = 1.0 - pred.success_probability

        # ── Confidence score ───────────────────────────
        confidence_factors = {
            "data_quality": features["prediction_error_coverage"],
            "roi_samples": roi_params["n_samples"],
            "cvr_samples": cvr_params["n_samples"],
            "market_density": features["market_opportunity_count"],
        }
        data_factor = min(0.3, sum(1 for k, v in confidence_factors.items() if k != "data_quality" and v > 0) * 0.1)
        sample_factor = min(0.5, max(roi_params["n_samples"], cvr_params["n_samples"]) / 20 * 0.5)
        error_factor = min(0.2, features["prediction_error_coverage"])
        pred.confidence_score = round(data_factor + sample_factor + error_factor, 4)
        pred.confidence_factors = confidence_factors

        # ── Recommendation ─────────────────────────────
        if pred.success_probability > 0.7 and pred.confidence_score > 0.5:
            pred.recommendation = "INVEST"
        elif pred.success_probability > 0.5:
            pred.recommendation = "TEST"
        elif pred.success_probability > 0.3:
            pred.recommendation = "HOLD"
        else:
            pred.recommendation = "REJECT"

        # ── Log prediction ─────────────────────────────
        self._log_prediction(pred)

        return pred

    def _log_prediction(self, pred: WorldModelPrediction):
        """Record prediction for accuracy tracking."""
        conn = self.params._conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO prediction_log
            (prediction_id, opp_id, model_version, predicted_at, predictions, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            pred.prediction_id, pred.opp_id, pred.model_version,
            pred.predicted_at,
            json.dumps(pred.to_dict(), ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
        conn.close()

    # ── Learn from outcome ─────────────────────────────

    def learn_from_outcome(
        self,
        category: str,
        market: str,
        actual_roi: float,
        actual_cvr: float = 0.0,
        actual_ctr: float = 0.0,
        actual_ltv: float = 0.0,
        actual_refund_rate: float = 0.0,
    ):
        """
        Bayesian update of all parameters based on observed outcomes.

        This is the core learning mechanism — every real outcome updates the model.
        """
        updates = []

        if actual_roi != 0:
            self.params.update(category, market, "roi", actual_roi, observed_std=0.5)
            updates.append("roi")

        if actual_cvr > 0:
            self.params.update(category, market, "cvr", actual_cvr, observed_std=0.01)
            updates.append("cvr")

        if actual_ctr > 0:
            self.params.update(category, market, "ctr", actual_ctr, observed_std=0.005)
            updates.append("ctr")

        if actual_ltv > 0:
            self.params.update(category, market, "ltv", actual_ltv, observed_std=10.0)
            updates.append("ltv")

        if actual_refund_rate > 0:
            self.params.update(category, market, "refund_rate", actual_refund_rate, observed_std=0.01)
            updates.append("refund_rate")

        logger.info(
            f"[WorldModel] Learned from {category}/{market}: "
            f"updated {len(updates)} params: {updates}"
        )

        return {"updated_params": updates}

    # ── Model health report ────────────────────────────

    def model_health_report(self) -> dict:
        """Report on model calibration and learning state."""
        all_params = self.params.list_all()
        total_params = len(all_params)
        well_trained = sum(1 for p in all_params if p["n_samples"] >= 5)
        poorly_trained = sum(1 for p in all_params if p["n_samples"] < 3)

        conn = self.params._conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as n FROM prediction_log")
        n_predictions = cur.fetchone()["n"]
        conn.close()

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": "v1.0.0",
            "total_parameters": total_params,
            "well_trained_params": well_trained,
            "poorly_trained_params": poorly_trained,
            "training_completeness": round(well_trained / total_params * 100, 1) if total_params > 0 else 0,
            "total_predictions": n_predictions,
            "top_learned_params": [
                {
                    "category": p["category"],
                    "market": p["market"],
                    "metric": p["metric"],
                    "mu": round(p["mu"], 4),
                    "sigma": round(p["sigma"], 4),
                    "n_samples": p["n_samples"],
                }
                for p in all_params[:15]
            ],
        }


# ──────────────────────────────────────────────────────────────
# 4. CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V10 — World Model Engine")
    parser.add_argument("--action", choices=["predict", "learn", "health", "params"],
                        default="health", help="Action")
    parser.add_argument("--category", default="", help="产品品类")
    parser.add_argument("--market", default="US", help="目标市场")
    parser.add_argument("--opp_id", default="test", help="机会ID")
    parser.add_argument("--roi", type=float, default=0.0, help="实际ROI（learn模式）")
    parser.add_argument("--cvr", type=float, default=0.0, help="实际CVR（learn模式）")
    parser.add_argument("--ctr", type=float, default=0.0, help="实际CTR（learn模式）")
    parser.add_argument("--ltv", type=float, default=0.0, help="实际LTV（learn模式）")
    parser.add_argument("--refund", type=float, default=0.0, help="实际退款率（learn模式）")
    parser.add_argument("--trend", type=float, default=5.0)
    parser.add_argument("--supply", type=float, default=5.0)
    parser.add_argument("--risk", type=float, default=5.0)
    parser.add_argument("--margin", type=float, default=0.30)
    args = parser.parse_args()

    wm = WorldModel()

    if args.action == "predict":
        pred = wm.predict(
            opp_id=args.opp_id,
            category=args.category,
            market=args.market,
            trend_score=args.trend,
            supply_score=args.supply,
            risk_score=args.risk,
            margin_pct=args.margin,
        )
        print("=" * 60)
        print("  World Model Prediction — V10")
        print("=" * 60)
        print(f"\n  Category: {args.category} / Market: {args.market}")
        print(f"  ROI:    {pred.predicted_roi:.2f}x ±{pred.predicted_roi_std:.2f}")
        print(f"  CVR:    {pred.predicted_cvr:.3f}  |  CTR: {pred.predicted_ctr:.3f}")
        print(f"  LTV:    ${pred.predicted_ltv:.0f}  |  Refund: {pred.predicted_refund_risk:.1%}")
        print(f"  Success: {pred.success_probability:.1%}  |  Loss: {pred.probability_of_loss:.1%}")
        print(f"  Confidence: {pred.confidence_score:.3f}")
        print(f"  Recommendation: {pred.recommendation}")
        print("=" * 60)

    elif args.action == "learn":
        result = wm.learn_from_outcome(
            category=args.category,
            market=args.market,
            actual_roi=args.roi,
            actual_cvr=args.cvr,
            actual_ctr=args.ctr,
            actual_ltv=args.ltv,
            actual_refund_rate=args.refund,
        )
        print(f"✅ Learned: {result['updated_params']}")

    elif args.action == "health":
        report = wm.model_health_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))

    elif args.action == "params":
        params = wm.params.list_all()
        for p in params:
            print(f"  {p['category']:20s}/{p['market']:5s} {p['metric']:15s} "
                  f"μ={p['mu']:.4f} σ={p['sigma']:.4f} n={p['n_samples']}")
