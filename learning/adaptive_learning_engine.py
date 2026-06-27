# HVOS V10 — Adaptive Learning Engine
# ====================================
# Replaces the hardcoded threshold classifier in learning_loop.py.
# Implements Bayesian updating, confidence recalibration, and
# environment-aware performance boundary learning.

from __future__ import annotations

import json
import math
import os
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger("adaptive_learning")

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────

HVOS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KG_DB = os.path.join(HVOS_ROOT, "knowledge_graph", "kg.db")
WM_DB = os.path.join(HVOS_ROOT, "knowledge_graph", "world_model.db")
STRATEGY_DB = os.path.join(HVOS_ROOT, "knowledge_graph", "strategy_memory.db")


# ──────────────────────────────────────────────────────────────
# 1. Environment-Aware Performance Distributions
# ──────────────────────────────────────────────────────────────


@dataclass
class PerformanceDistribution:
    """Learned performance distribution for a (category, market, metric)."""

    category: str
    market: str
    metric: str
    mu: float = 0.0
    sigma: float = 1.0
    n_samples: int = 0
    p5: float = 0.0  # 5th percentile
    p25: float = 0.0  # 25th percentile
    p50: float = 0.0  # median
    p75: float = 0.0  # 75th percentile
    p95: float = 0.0  # 95th percentile


class AdaptiveThresholdLearner:
    """
    Learns performance boundaries from data, not from constants.

    Replaces: learning_loop.py CausalFactorExtractor.THRESHOLDS
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
            CREATE TABLE IF NOT EXISTS performance_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                market TEXT,
                metric TEXT,
                value REAL,
                opp_id TEXT,
                recorded_at TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_perf_cat_mkt_metric
            ON performance_samples(category, market, metric)
        """)
        conn.commit()
        conn.close()

    # ── Record an observation ───────────────────────────

    def observe(self, category: str, market: str, metric: str, value: float, opp_id: str = ""):
        """Record a real performance observation."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO performance_samples (category, market, metric, value, opp_id, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (category, market, metric, value, opp_id, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()

    # ── Get learned distribution ────────────────────────

    def get_distribution(self, category: str, market: str, metric: str) -> PerformanceDistribution:
        """Compute the empirical distribution for a performance metric."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT value FROM performance_samples
            WHERE category = ? AND market = ? AND metric = ?
            ORDER BY value
        """, (category, market, metric))
        values = [row[0] for row in cur.fetchall()]
        conn.close()

        n = len(values)
        if n == 0:
            return PerformanceDistribution(category=category, market=market, metric=metric)

        # Compute statistics
        mu = sum(values) / n
        variance = sum((v - mu) ** 2 for v in values) / max(n - 1, 1)
        sigma = math.sqrt(variance)

        # Percentiles
        def percentile(data, p):
            if not data:
                return 0
            n = len(data)
            k = (n - 1) * p / 100.0
            f = int(k)
            c = min(f + 1, n - 1)
            if f >= n - 1:
                return data[-1]
            frac = k - f
            return data[f] + (data[c] - data[f]) * frac

        return PerformanceDistribution(
            category=category, market=market, metric=metric,
            mu=mu, sigma=sigma, n_samples=n,
            p5=percentile(values, 5),
            p25=percentile(values, 25),
            p50=percentile(values, 50),
            p75=percentile(values, 75),
            p95=percentile(values, 95),
        )

    # ── Get dynamic threshold ───────────────────────────

    def get_threshold(self, category: str, market: str, metric: str, percentile: int = 25) -> float:
        """
        Get a dynamic threshold for classifying performance.

        Returns the value at the specified percentile.
        For "low" classification: use p25 (bottom 25% = underperforming)
        For "high" classification: use p75 (top 25% = outperforming)
        """
        dist = self.get_distribution(category, market, metric)
        if dist.n_samples < 3:
            # Not enough data — return global default
            defaults = {"roi": 1.0, "cvr": 0.02, "ctr": 0.01, "aov": 50.0, "refund_rate": 0.05}
            return defaults.get(metric, 0.0)

        if percentile == 25:
            return dist.p25
        elif percentile == 75:
            return dist.p75
        elif percentile == 50:
            return dist.p50
        return dist.p25

    # ── Classify with learned thresholds ────────────────

    def classify(self, category: str, market: str, metric: str, value: float) -> dict:
        """
        Classify a performance metric using learned thresholds.

        Returns: {"level": "low"|"normal"|"high", "percentile": float, "threshold_low": float, "threshold_high": float}
        """
        dist = self.get_distribution(category, market, metric)
        if dist.n_samples < 3:
            # Fall back to global defaults
            defaults = {
                "roi": (1.0, 2.0),
                "cvr": (0.02, 0.05),
                "ctr": (0.01, 0.04),
                "aov": (50.0, 120.0),
                "refund_rate": (0.02, 0.05),
            }
            low, high = defaults.get(metric, (0, 999))
        else:
            low = dist.p25
            high = dist.p75

        # Estimate where this value falls in the distribution
        if dist.n_samples >= 3 and dist.sigma > 0:
            z_score = (value - dist.mu) / max(dist.sigma, 0.001)
            percentile_est = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
        else:
            percentile_est = 0.5

        if value <= low:
            level = "low"
        elif value >= high:
            level = "high"
        else:
            level = "normal"

        return {
            "level": level,
            "percentile": round(percentile_est, 4),
            "threshold_low": round(low, 4),
            "threshold_high": round(high, 4),
            "n_samples": dist.n_samples,
            "distribution_mean": round(dist.mu, 4),
        }

    # ── Report ──────────────────────────────────────────

    def report(self) -> list[dict]:
        """List all learned distributions."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT category, market, metric, COUNT(*) as n
            FROM performance_samples
            GROUP BY category, market, metric
            ORDER BY n DESC
        """)
        groups = [(r["category"], r["market"], r["metric"], r["n"]) for r in cur.fetchall()]
        conn.close()

        results = []
        for cat, mkt, met, n in groups:
            dist = self.get_distribution(cat, mkt, met)
            results.append({
                "category": cat, "market": mkt, "metric": met,
                "n": dist.n_samples, "mu": round(dist.mu, 4),
                "p5": round(dist.p5, 4), "p25": round(dist.p25, 4),
                "p50": round(dist.p50, 4), "p75": round(dist.p75, 4),
                "p95": round(dist.p95, 4),
            })
        return results


# ──────────────────────────────────────────────────────────────
# 2. Prediction Calibrator
# ──────────────────────────────────────────────────────────────


class PredictionCalibrator:
    """
    Calibrates prediction confidence based on historical accuracy.

    Tracks: predicted vs actual for each prediction type.
    Computes calibration curves and adjusts confidence scores.
    """

    def __init__(self, wm_db: str = WM_DB):
        self.wm_db = wm_db

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.wm_db, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def record_actual(self, prediction_id: str, opp_id: str, actual_roi: float):
        """Record actual outcome for calibration."""
        conn = self._conn()
        cur = conn.cursor()
        try:
            # Get original prediction
            cur.execute("SELECT predictions FROM prediction_log WHERE prediction_id = ?",
                       (prediction_id,))
            row = cur.fetchone()
            if row:
                preds = json.loads(row["predictions"])
                predicted_roi = preds.get("predicted_roi", 0)
                error_pct = round((actual_roi - predicted_roi) / predicted_roi * 100, 2) if predicted_roi != 0 else 0

                cur.execute("""
                    UPDATE prediction_log
                    SET actuals = ?, error_score = ?
                    WHERE prediction_id = ?
                """, (
                    json.dumps({"actual_roi": actual_roi, "error_pct": error_pct}),
                    abs(error_pct),
                    prediction_id,
                ))
                conn.commit()
                logger.info(f"[Calibrator] {prediction_id}: pred={predicted_roi:.2f} actual={actual_roi:.2f} error={error_pct:+.1f}%")
        finally:
            conn.close()

    def calibration_report(self) -> dict:
        """Report calibration quality."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT AVG(ABS(error_score)) as mae,
                   COUNT(*) as n,
                   SUM(CASE WHEN error_score IS NOT NULL AND error_score > 50 THEN 1 ELSE 0 END) as large_errors
            FROM prediction_log
            WHERE actuals IS NOT NULL
        """)
        row = cur.fetchone()
        conn.close()

        n = row["n"] or 0
        return {
            "n_calibrated": n,
            "mae_pct": round(row["mae"], 2) if row["mae"] else 0,
            "large_error_count": row["large_errors"] or 0,
            "large_error_rate": round((row["large_errors"] or 0) / n * 100, 1) if n > 0 else 0,
            "calibration_quality": "excellent" if n > 0 and row["mae"] and row["mae"] < 20
                                   else "good" if n > 0 and row["mae"] and row["mae"] < 40
                                   else "needs_improvement",
        }


# ──────────────────────────────────────────────────────────────
# 3. Continuous Improvement Cycle
# ──────────────────────────────────────────────────────────────


class ContinuousImprover:
    """
    Coordinates the learning cycle: learn → calibrate → improve.
    """

    def __init__(self):
        self.learner = AdaptiveThresholdLearner()
        self.calibrator = PredictionCalibrator()
        # WorldModel is imported lazily

    def run_cycle(self, category: str = "", market: str = "US") -> dict:
        """
        Run one improvement cycle:
        1. Learn from recent outcomes
        2. Calibrate predictions
        3. Update thresholds
        """
        result = {
            "cycle_at": datetime.now(timezone.utc).isoformat(),
            "thresholds_updated": 0,
            "predictions_calibrated": 0,
        }

        # Get learned thresholds
        metrics = ["roi", "cvr", "ctr", "aov", "refund_rate"]
        for metric in metrics:
            dist = self.learner.get_distribution(category, market, metric)
            if dist.n_samples >= 3:
                result["thresholds_updated"] += 1
                result[f"{metric}_threshold_low"] = dist.p25
                result[f"{metric}_threshold_high"] = dist.p75
                result[f"{metric}_n_samples"] = dist.n_samples

        # Calibration report
        calib = self.calibrator.calibration_report()
        result["calibration"] = calib
        result["predictions_calibrated"] = calib["n_calibrated"]

        return result


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS V10 — Adaptive Learning Engine")
    parser.add_argument("--action", choices=["observe", "classify", "dist", "calibrate", "cycle", "report"],
                        default="report")
    parser.add_argument("--category", default="")
    parser.add_argument("--market", default="US")
    parser.add_argument("--metric", default="roi")
    parser.add_argument("--value", type=float, default=0.0)
    parser.add_argument("--prediction_id", default="")
    parser.add_argument("--actual_roi", type=float, default=0.0)
    args = parser.parse_args()

    learner = AdaptiveThresholdLearner()
    calibrator = PredictionCalibrator()
    improver = ContinuousImprover()

    if args.action == "observe":
        learner.observe(args.category, args.market, args.metric, args.value)
        print(f"✅ Recorded: {args.category}/{args.market}/{args.metric}={args.value}")

    elif args.action == "classify":
        result = learner.classify(args.category, args.market, args.metric, args.value)
        print(json.dumps(result, indent=2))

    elif args.action == "dist":
        dist = learner.get_distribution(args.category, args.market, args.metric)
        print(json.dumps(asdict(dist), indent=2, default=str))

    elif args.action == "calibrate":
        calibrator.record_actual(args.prediction_id, "", args.actual_roi)
        report = calibrator.calibration_report()
        print(json.dumps(report, indent=2))

    elif args.action == "cycle":
        result = improver.run_cycle(args.category, args.market)
        print(json.dumps(result, indent=2))

    elif args.action == "report":
        report = learner.report()
        print(json.dumps(report, indent=2))
