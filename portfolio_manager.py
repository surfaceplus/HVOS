"""
HVOS Portfolio Manager — Board Meeting Level Portfolio Analysis
==============================================================
A board-meeting-grade portfolio analysis module backed by capital_book.db.

Functions:
  1. Category Concentration (HHI Index)
  2. Pool Health Dashboard
  3. Systemic Risk Indicators
  4. Alert Generator
  5. CLI Report (python portfolio_manager.py --report)

Author: HVOS X Capital Layer
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_HVOS_ROOT = Path(__file__).resolve().parent
DB_PATH = _HVOS_ROOT / "capital_book.db"


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class RiskLevel(Enum):
    LOW = "🟢 LOW"
    MEDIUM = "🟡 MEDIUM"
    HIGH = "🟠 HIGH"
    CRITICAL = "🔴 CRITICAL"


class PoolStatus(Enum):
    HEALTHY = "🟢 HEALTHY"
    CAUTION = "🟡 CAUTION"
    WARNING = "🟠 WARNING"
    DANGER = "🔴 DANGER"


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HHIMetric:
    """HHI (Herfindahl-Hirschman Index) for category concentration."""
    hhi: float                      # Raw HHI: sum of squared market-share fractions (× 10000)
    normalized_hhi: float           # Normalized HHI: (HHI - 1/N) / (1 - 1/N) × 100
    category_count: int             # Number of distinct categories
    dominant_category: Optional[str] = None
    dominant_share: float = 0.0     # Market share of dominant category (%)
    interpretation: str = ""


@dataclass
class PoolHealth:
    """Single pool health status."""
    pool_type: str
    total_capital: float
    allocated: float
    available: float
    reserved: float
    utilization_pct: float          # allocated / total_capital × 100
    available_pct: float           # available / total_capital × 100
    status: PoolStatus
    status_reason: str = ""


@dataclass
class SystemicRiskIndicators:
    """Systemic risk metrics for the portfolio."""
    # Concentration risk
    hhi: HHIMetric

    # Liquidity risk
    total_liquidity_ratio: float    # (sum available across pools) / total_deployed
    reserve_depleted: bool

    # ROI prediction accuracy
    avg_prediction_error: float     # Mean absolute % error across roi_records
    severe_miss_count: int          # Count of predictions where actual_roi < 0
    total_predictions: int

    # Portfolio performance
    total_deployed: float          # Sum of invested_amount (active only)
    total_revenue: float           # Sum of actual_revenue (active only)
    overall_roi: float             # portfolio-level ROI

    # Risk level
    risk_level: RiskLevel
    risk_factors: list[str] = field(default_factory=list)


@dataclass
class Alert:
    """Single alert item."""
    alert_id: str
    timestamp: str
    severity: RiskLevel
    category: str                  # CONCENTRATION | LIQUIDITY | PREDICTION | ROI | POOL
    title: str
    message: str
    recommendation: str
    metric_value: float
    threshold: float
    unit: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Database Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_pool_health(row: sqlite3.Row) -> PoolHealth:
    total = row["total_capital"] or 0.0
    allocated = row["allocated"] or 0.0
    available = row["available"] or 0.0
    reserved = row["reserved"] or 0.0

    util_pct = (allocated / total * 100) if total > 0 else 0.0
    avail_pct = (available / total * 100) if total > 0 else 0.0

    # Determine status
    if util_pct >= 90:
        status = PoolStatus.DANGER
        reason = f"Utilisation {util_pct:.1f}% ≥ 90% — pool nearly exhausted"
    elif util_pct >= 75:
        status = PoolStatus.WARNING
        reason = f"Utilisation {util_pct:.1f}% ≥ 75% — approach limit"
    elif util_pct >= 60:
        status = PoolStatus.CAUTION
        reason = f"Utilisation {util_pct:.1f}% ≥ 60% — monitor closely"
    elif avail_pct <= 5 and total > 0:
        status = PoolStatus.WARNING
        reason = f"Available {avail_pct:.1f}% ≤ 5% — low liquidity"
    else:
        status = PoolStatus.HEALTHY
        reason = f"Pool healthy — {util_pct:.1f}% utilised, {avail_pct:.1f}% available"

    return PoolHealth(
        pool_type=row["pool_type"],
        total_capital=total,
        allocated=allocated,
        available=available,
        reserved=reserved,
        utilization_pct=round(util_pct, 2),
        available_pct=round(avail_pct, 2),
        status=status,
        status_reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Category Concentration — HHI Index
# ─────────────────────────────────────────────────────────────────────────────

def compute_hhi(db_path: Optional[str] = None) -> HHIMetric:
    """
    Compute HHI (Herfindahl-Hirschman Index) for category concentration.

    HHI = Σ (market_share_i)²  — higher = more concentrated
    Normalized HHI = (HHI - 1/N) / (1 - 1/N) × 100  [0-100 scale]

    Thresholds (normalized):
      < 15  : Diversified
      15-25 : Moderate concentration
      25-40 : High concentration
      > 40  : Very high concentration (alert)
    """
    conn = _connect(db_path)
    c = conn.cursor()

    # Get all active investments with category info
    c.execute("""
        SELECT
            opp_id,
            invested_amount,
            actual_revenue,
            actual_cost,
            status
        FROM investments
        WHERE status = 'active'
    """)
    rows = c.fetchall()
    conn.close()

    if not rows:
        return HHIMetric(
            hhi=0.0, normalized_hhi=0.0, category_count=0,
            interpretation="No active investments — N/A",
        )

    # Use opp_id as proxy for category bucket (in real system would join category table)
    # We group by opp_id and treat each as a "category" for concentration analysis
    total_invested = sum(r["invested_amount"] for r in rows)

    if total_invested == 0:
        return HHIMetric(
            hhi=0.0, normalized_hhi=0.0, category_count=len(rows),
            interpretation="No invested capital — N/A",
        )

    # Compute share per investment bucket
    shares = []
    dominant_idx = -1
    dominant_share = 0.0

    for i, row in enumerate(rows):
        share = row["invested_amount"] / total_invested
        shares.append(share)
        if share > dominant_share:
            dominant_share = share
            dominant_idx = i

    # HHI = sum of squared shares (× 10000 to convert to 0-10000 scale)
    hhi = sum(s ** 2 for s in shares) * 10000
    n = len(shares)

    # Normalized HHI: (HHI - 1/N) / (1 - 1/N) × 100
    # N=1 is a special case: 1 investment = 100% of portfolio = maximum concentration
    if n == 1:
        normalized_hhi = 100.0
    else:
        normalized_hhi = (hhi - 10000 / n) / (10000 - 10000 / n) * 100
    normalized_hhi = max(0.0, min(100.0, normalized_hhi))

    # Interpretation
    opp_names = {r["opp_id"]: r["opp_id"] for r in rows}
    dominant_category = rows[dominant_idx]["opp_id"] if dominant_idx >= 0 else None

    if normalized_hhi < 15:
        interpretation = "Diversified — low concentration risk"
    elif normalized_hhi < 25:
        interpretation = "Moderate concentration — monitor for drift"
    elif normalized_hhi < 40:
        interpretation = "High concentration — consider diversifying"
    else:
        interpretation = "Very high concentration — REBALANCE REQUIRED"

    return HHIMetric(
        hhi=round(hhi, 2),
        normalized_hhi=round(normalized_hhi, 2),
        category_count=n,
        dominant_category=dominant_category,
        dominant_share=round(dominant_share * 100, 2),
        interpretation=interpretation,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pool Health Dashboard
# ─────────────────────────────────────────────────────────────────────────────

def get_pool_health(db_path: Optional[str] = None) -> dict:
    """
    Returns health status for all capital pools (core, growth, exploration, reserve).
    """
    conn = _connect(db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM capital_pools ORDER BY pool_type")
    rows = c.fetchall()
    conn.close()

    pools = [_row_to_pool_health(r) for r in rows]

    # Aggregate summary
    total_deployed = sum(p.allocated for p in pools)
    total_available = sum(p.available for p in pools)
    total_reserved = sum(p.reserved for p in pools)

    danger_pools = [p for p in pools if p.status == PoolStatus.DANGER]
    warning_pools = [p for p in pools if p.status == PoolStatus.WARNING]
    caution_pools = [p for p in pools if p.status == PoolStatus.CAUTION]
    healthy_pools = [p for p in pools if p.status == PoolStatus.HEALTHY]

    return {
        "pools": [asdict(p) for p in pools],
        "summary": {
            "total_deployed": round(total_deployed, 2),
            "total_available": round(total_available, 2),
            "total_reserved": round(total_reserved, 2),
            "pools_at_risk": len(danger_pools) + len(warning_pools),
            "status_breakdown": {
                "healthy": len(healthy_pools),
                "caution": len(caution_pools),
                "warning": len(warning_pools),
                "danger": len(danger_pools),
            },
            "alerts": [
                {
                    "pool": p.pool_type,
                    "reason": p.status_reason,
                    "status": p.status.value,
                }
                for p in danger_pools + warning_pools
            ],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Systemic Risk Indicators
# ─────────────────────────────────────────────────────────────────────────────

def get_systemic_risk(db_path: Optional[str] = None) -> SystemicRiskIndicators:
    """
    Compute systemic risk indicators for the portfolio.
    """
    conn = _connect(db_path)
    c = conn.cursor()

    # ── Active investment performance ──────────────────────────────────────
    c.execute("""
        SELECT
            invested_amount,
            actual_revenue,
            actual_cost,
            status
        FROM investments
        WHERE status = 'active'
    """)
    active_rows = c.fetchall()

    total_deployed = sum(r["invested_amount"] for r in active_rows)
    total_revenue = sum(r["actual_revenue"] for r in active_rows)
    total_cost = sum(r["actual_cost"] for r in active_rows)
    overall_roi = (total_revenue - total_cost) / total_cost if total_cost > 0 else 0.0

    # ── ROI prediction accuracy ─────────────────────────────────────────────
    c.execute("""
        SELECT
            predicted_roi,
            actual_roi,
            error_rate,
            error_direction,
            verdict
        FROM roi_records
    """)
    roi_rows = c.fetchall()

    total_predictions = len(roi_rows)
    severe_miss_count = 0
    total_error = 0.0

    for row in roi_rows:
        if row["actual_roi"] is not None:
            if row["actual_roi"] < 0:
                severe_miss_count += 1
        if row["error_rate"] is not None:
            total_error += abs(row["error_rate"])

    avg_prediction_error = total_error / total_predictions if total_predictions > 0 else 0.0

    # ── Liquidity ratio ──────────────────────────────────────────────────────
    c.execute("""
        SELECT SUM(available) as total_available,
               SUM(allocated) as total_allocated
        FROM capital_pools
    """)
    pool_row = c.fetchone()
    total_available = pool_row["total_available"] or 0.0
    total_allocated = pool_row["total_allocated"] or 0.0

    liquidity_ratio = total_available / total_allocated if total_allocated > 0 else 0.0

    # Reserve check
    c.execute("SELECT available FROM capital_pools WHERE pool_type = 'reserve'")
    reserve_row = c.fetchone()
    reserve_available = reserve_row["available"] if reserve_row else 0.0
    reserve_depleted = reserve_available < 100.0  # < $100 = depleted

    conn.close()

    # ── HHI ─────────────────────────────────────────────────────────────────
    hhi = compute_hhi(db_path)

    # ── Risk level ──────────────────────────────────────────────────────────
    risk_factors: list[str] = []

    if hhi.normalized_hhi >= 40:
        risk_factors.append(f"HHI {hhi.normalized_hhi:.1f}% — very high concentration")

    if liquidity_ratio < 0.3:
        risk_factors.append(f"Liquidity ratio {liquidity_ratio:.2f} — low liquidity")

    if avg_prediction_error > 50:
        risk_factors.append(f"Avg prediction error {avg_prediction_error:.1f}% — model unreliable")

    if severe_miss_count > 0:
        risk_factors.append(f"{severe_miss_count} investments with negative ROI")

    if reserve_depleted:
        risk_factors.append("Reserve pool depleted — emergency buffer missing")

    # Determine risk level
    if len(risk_factors) == 0:
        risk_level = RiskLevel.LOW
    elif len(risk_factors) >= 3 or severe_miss_count >= 2:
        risk_level = RiskLevel.HIGH
    elif len(risk_factors) >= 1 or avg_prediction_error > 50:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    # Override to critical if HHI extremely high or severe liquidity
    if hhi.normalized_hhi >= 70 or liquidity_ratio < 0.1:
        risk_level = RiskLevel.CRITICAL

    return SystemicRiskIndicators(
        hhi=hhi,
        total_liquidity_ratio=round(liquidity_ratio, 4),
        reserve_depleted=reserve_depleted,
        avg_prediction_error=round(avg_prediction_error, 2),
        severe_miss_count=severe_miss_count,
        total_predictions=total_predictions,
        total_deployed=round(total_deployed, 2),
        total_revenue=round(total_revenue, 2),
        overall_roi=round(overall_roi, 4),
        risk_level=risk_level,
        risk_factors=risk_factors,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Alert Generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_alerts(db_path: Optional[str] = None) -> list[Alert]:
    """
    Scan all metrics and generate actionable alerts.
    Each alert includes severity, category, title, message, recommendation.
    """
    alerts: list[Alert] = []
    now = datetime.now(timezone.utc).isoformat()
    alert_counter = 1

    def add(
        severity: RiskLevel,
        category: str,
        title: str,
        message: str,
        recommendation: str,
        metric_value: float,
        threshold: float,
        unit: str = "",
    ):
        nonlocal alert_counter
        alerts.append(Alert(
            alert_id=f"ALT_{alert_counter:04d}",
            timestamp=now,
            severity=severity,
            category=category,
            title=title,
            message=message,
            recommendation=recommendation,
            metric_value=metric_value,
            threshold=threshold,
            unit=unit,
        ))
        alert_counter += 1

    conn = _connect(db_path)
    c = conn.cursor()

    # ── HHI alerts ──────────────────────────────────────────────────────────
    hhi = compute_hhi(db_path)
    if hhi.normalized_hhi >= 40:
        add(
            RiskLevel.HIGH, "CONCENTRATION",
            f"Portfolio HHI {hhi.normalized_hhi:.1f}% — Concentration Risk",
            f"Dominant investment '{hhi.dominant_category}' holds {hhi.dominant_share:.1f}% of deployed capital. "
            f"HHI = {hhi.hhi:.0f} (normalized {hhi.normalized_hhi:.1f}%). Diversification needed.",
            f"Consider allocating capital to secondary opportunity buckets. "
            f"Target normalized HHI < 25% for balanced portfolio.",
            hhi.normalized_hhi, 40.0, "%",
        )
    elif hhi.normalized_hhi >= 25:
        add(
            RiskLevel.MEDIUM, "CONCENTRATION",
            f"Portfolio HHI {hhi.normalized_hhi:.1f}% — Moderate Concentration",
            f"Current normalized HHI = {hhi.normalized_hhi:.1f}%. "
            f"Dominant bucket: {hhi.dominant_category} at {hhi.dominant_share:.1f}%.",
            "Monitor concentration drift. Prepare secondary bucket for capital rotation.",
            hhi.normalized_hhi, 25.0, "%",
        )

    # ── Pool health alerts ──────────────────────────────────────────────────
    pool_data = get_pool_health(db_path)
    for pool in pool_data["pools"]:
        util = pool["utilization_pct"]
        if util >= 90:
            add(
                RiskLevel.CRITICAL, "POOL",
                f"Pool '{pool['pool_type']}' — CRITICAL Utilisation {util:.1f}%",
                f"Pool {pool['pool_type']} has only {pool['available_pct']:.1f}% available. "
                f"Deployed: ${pool['allocated']:.0f} / ${pool['total_capital']:.0f} total.",
                "Halt new allocations to this pool immediately. Re-balance from Growth/Exploration.",
                util, 90.0, "%",
            )
        elif util >= 75:
            add(
                RiskLevel.HIGH, "POOL",
                f"Pool '{pool['pool_type']}' — WARNING Utilisation {util:.1f}%",
                f"Pool {pool['pool_type']} at {util:.1f}% utilisation. "
                f"Available: ${pool['available']:.0f}.",
                "Set allocation ceiling. Do not deploy >10% additional capital to this pool.",
                util, 75.0, "%",
            )
        elif util >= 60:
            add(
                RiskLevel.MEDIUM, "POOL",
                f"Pool '{pool['pool_type']}' — CAUTION Utilisation {util:.1f}%",
                f"Pool {pool['pool_type']} approaching 75% threshold. "
                f"Monitor deploy rate.",
                "Review deployment velocity. Prepare reserve rebalancing if >75%.",
                util, 60.0, "%",
            )

    # ── Liquidity alerts ─────────────────────────────────────────────────────
    c.execute("""
        SELECT SUM(available) as total_available,
               SUM(allocated) as total_allocated
        FROM capital_pools
    """)
    pool_row = c.fetchone()
    total_available = pool_row["total_available"] or 0.0
    total_allocated = pool_row["total_allocated"] or 0.0
    liquidity_ratio = total_available / total_allocated if total_allocated > 0 else 0.0

    if liquidity_ratio < 0.2:
        add(
            RiskLevel.CRITICAL, "LIQUIDITY",
            f"Liquidity Ratio {liquidity_ratio:.2f} — CRITICAL",
            f"Available capital (${total_available:.0f}) vs deployed (${total_allocated:.0f}). "
            f"Ratio = {liquidity_ratio:.2f} (threshold: 0.20).",
            "Emergency capital reallocation required. Halt all new investments until ratio > 0.30.",
            liquidity_ratio, 0.20, "",
        )
    elif liquidity_ratio < 0.3:
        add(
            RiskLevel.HIGH, "LIQUIDITY",
            f"Liquidity Ratio {liquidity_ratio:.2f} — LOW",
            f"Available ${total_available:.0f} vs deployed ${total_allocated:.0f}. "
            f"Ratio below 0.30 threshold.",
            "Pause non-essential deployments. Review reserve pool replenishment.",
            liquidity_ratio, 0.30, "",
        )

    # ── Reserve depleted ─────────────────────────────────────────────────────
    c.execute("SELECT available FROM capital_pools WHERE pool_type = 'reserve'")
    reserve_row = c.fetchone()
    reserve_available = reserve_row["available"] if reserve_row else 0.0
    if reserve_available < 100.0:
        add(
            RiskLevel.CRITICAL, "RESERVE",
            f"Reserve Pool Depleted — ${reserve_available:.0f} Available",
            "Emergency reserve < $100. HVOS policy requires minimum 10% reserve (target 5% hard floor).",
            "Immediately top up reserve pool from Core/Growth surpluses. No new INVEST decisions until reserve > 5% of total capital.",
            reserve_available, 100.0, "USD",
        )

    # ── ROI prediction accuracy ─────────────────────────────────────────────
    c.execute("SELECT * FROM roi_records")
    roi_rows = c.fetchall()
    if roi_rows:
        total_error = sum(abs(r["error_rate"] or 0) for r in roi_rows)
        avg_error = total_error / len(roi_rows)
        severe_count = sum(1 for r in roi_rows if (r["actual_roi"] or 0) < 0)

        if avg_error > 50:
            add(
                RiskLevel.HIGH, "PREDICTION",
                f"RFE Prediction Error {avg_error:.1f}% — Model Degraded",
                f"Average ROI prediction error across {len(roi_rows)} records is {avg_error:.1f}%. "
                f"{severe_count} investments yielded negative ROI (severe miss).",
                "Retrain RFE model with latest actuals. Apply higher uncertainty discount to new predictions.",
                avg_error, 50.0, "%",
            )
        elif avg_error > 30:
            add(
                RiskLevel.MEDIUM, "PREDICTION",
                f"RFE Prediction Error {avg_error:.1f}% — Moderate Drift",
                f"Average prediction error = {avg_error:.1f}% across {len(roi_rows)} records.",
                "Monitor prediction accuracy. Increase safety margin in INVEST decisions.",
                avg_error, 30.0, "%",
            )

        if severe_count >= 2:
            add(
                RiskLevel.HIGH, "ROI",
                f"{severe_count} Investments with Negative ROI — Severe Losses",
                f"{severe_count} out of {len(roi_rows)} investments resulted in negative actual ROI. "
                f"This signals either poor opportunity selection or adverse market conditions.",
                "Conduct post-mortem on all negative-ROI investments. Apply tighter V_profit filter.",
                severe_count, 1.0, "count",
            )

    # ── Closed/written-off investments ──────────────────────────────────────
    c.execute("SELECT COUNT(*) as cnt FROM investments WHERE status = 'written_off'")
    wo_row = c.fetchone()
    if wo_row and wo_row["cnt"] > 0:
        add(
            RiskLevel.MEDIUM, "ROI",
            f"{wo_row['cnt']} Written-Off Investment(s)",
            f"{wo_row['cnt']} investment(s) have been written off. Review loss pattern.",
            "Audit written-off positions. Update V_risk veto criteria if pattern emerges.",
            wo_row["cnt"], 0.0, "count",
        )

    conn.close()
    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# 5. Investment Committee Summary
# ─────────────────────────────────────────────────────────────────────────────

def get_ic_summary(db_path: Optional[str] = None) -> dict:
    """
    Generate Investment Committee summary (board-meeting-ready).
    """
    conn = _connect(db_path)
    c = conn.cursor()

    # Active investments
    c.execute("SELECT COUNT(*) as cnt, SUM(invested_amount) as deployed, SUM(actual_revenue) as revenue FROM investments WHERE status = 'active'")
    active_row = c.fetchone()
    active_count = active_row["cnt"] or 0
    active_deployed = active_row["deployed"] or 0.0
    active_revenue = active_row["revenue"] or 0.0

    # Closed investments
    c.execute("SELECT COUNT(*) as cnt FROM investments WHERE status = 'closed'")
    closed_count = c.fetchone()["cnt"] or 0

    # Written off
    c.execute("SELECT COUNT(*) as cnt FROM investments WHERE status = 'written_off'")
    wo_count = c.fetchone()["cnt"] or 0

    # Capital pools summary
    c.execute("SELECT pool_type, total_capital, allocated, available FROM capital_pools")
    pool_rows = c.fetchall()

    # Transactions summary
    c.execute("SELECT SUM(amount) as total_amount FROM transactions WHERE amount > 0")
    total_inflow = c.fetchone()["total_amount"] or 0.0

    conn.close()

    # Top investments by deployed capital
    hhi = compute_hhi(db_path)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio_snapshot": {
            "active_investments": active_count,
            "closed_investments": closed_count,
            "written_off": wo_count,
            "total_deployed_capital": round(active_deployed, 2),
            "total_realized_revenue": round(active_revenue, 2),
            "portfolio_roi": round((active_revenue - active_deployed) / active_deployed, 4) if active_deployed > 0 else 0.0,
            "total_inflow": round(total_inflow, 2),
        },
        "pool_allocation": [
            {
                "pool": r["pool_type"],
                "total": r["total_capital"],
                "allocated": r["allocated"],
                "available": r["available"],
                "utilization_pct": round(r["allocated"] / r["total_capital"] * 100, 2) if r["total_capital"] > 0 else 0.0,
            }
            for r in pool_rows
        ],
        "concentration": {
            "hhi": hhi.hhi,
            "normalized_hhi": hhi.normalized_hhi,
            "category_count": hhi.category_count,
            "dominant_category": hhi.dominant_category,
            "dominant_share_pct": hhi.dominant_share,
            "interpretation": hhi.interpretation,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Board Meeting Report — Text Renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_board_report(
    ic_summary: dict,
    pool_health: dict,
    systemic_risk: SystemicRiskIndicators,
    alerts: list[Alert],
) -> str:
    """Render a formatted board-meeting text report."""

    lines: list[str] = []
    W = 80
    SEP = "═" * W

    def section(title: str):
        lines.append(f"\n{SEP}")
        lines.append(f"  {title}")
        lines.append(SEP)

    def kv(key: str, value: str, indent: int = 2):
        lines.append(f"  {' ' * indent}{key:<30} {value}")

    # ── Header ────────────────────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(SEP)
    lines.append(f"  HVOS PORTFOLIO BOARD REPORT")
    lines.append(f"  Generated: {ts}")
    lines.append(SEP)

    # ── 1. Portfolio Snapshot ───────────────────────────────────────────────
    section("1. PORTFOLIO SNAPSHOT")
    snap = ic_summary["portfolio_snapshot"]
    kv("Active Investments",    str(snap["active_investments"]))
    kv("Closed Investments",    str(snap["closed_investments"]))
    kv("Written Off",           str(snap["written_off"]))
    kv("Total Deployed Capital", f"${snap['total_deployed_capital']:,.2f}")
    kv("Total Revenue (active)", f"${snap['total_realized_revenue']:,.2f}")
    kv("Portfolio ROI",         f"{snap['portfolio_roi']*100:.2f}%")
    kv("Total Capital Inflow",  f"${snap['total_inflow']:,.2f}")

    # ── 2. Category Concentration (HHI) ─────────────────────────────────────
    section("2. CATEGORY CONCENTRATION (HHI INDEX)")
    hhi = systemic_risk.hhi
    kv("HHI Score",              f"{hhi.hhi:.2f} (scale: 0–10,000)")
    kv("Normalized HHI",         f"{hhi.normalized_hhi:.2f}%  [{hhi.interpretation}]")
    kv("Investment Buckets",     str(hhi.category_count))
    kv("Dominant Bucket",        f"{hhi.dominant_category} ({hhi.dominant_share:.1f}% share)")

    # HHI bar
    bar_len = 40
    filled = int(min(hhi.normalized_hhi / 100, 1.0) * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"\n  HHI Concentration: [{bar}] {hhi.normalized_hhi:.1f}%")

    thresholds = [
        ("Diversified",    15, "🟢"),
        ("Moderate",       25, "🟡"),
        ("High",           40, "🟠"),
        ("Very High",     100, "🔴"),
    ]
    for label, threshold, emoji in thresholds:
        status = emoji if hhi.normalized_hhi >= threshold else "  "
        lines.append(f"  {status} {threshold:>3}% — {label}")

    # ── 3. Pool Health Dashboard ──────────────────────────────────────────────
    section("3. POOL HEALTH DASHBOARD")

    for pool in pool_health["pools"]:
        status_icon = pool["status"].value[:4]
        lines.append(f"\n  [{status_icon}] {pool['pool_type'].upper():12} "
                     f"Total: ${pool['total_capital']:>10,.2f}  "
                     f"Alloc: ${pool['allocated']:>10,.2f}  "
                     f"Avail: ${pool['available']:>10,.2f}")
        lines.append(f"  {'':16} Utilisation: {pool['utilization_pct']:>5.1f}%   "
                     f"Available: {pool['available_pct']:>5.1f}%")
        lines.append(f"  {'':16} {pool['status_reason']}")

    summary = pool_health["summary"]
    lines.append(f"\n  ── Pool Summary ──")
    sb = summary["status_breakdown"]
    kv("Healthy Pools",    f"{sb['healthy']}")
    kv("Caution Pools",   f"{sb['caution']}")
    kv("Warning Pools",   f"{sb['warning']}")
    kv("Danger Pools",    f"{sb['danger']}")
    kv("Pools at Risk",   f"{summary['pools_at_risk']}")
    kv("Total Deployed",  f"${summary['total_deployed']:,.2f}")
    kv("Total Available", f"${summary['total_available']:,.2f}")

    # ── 4. Systemic Risk Indicators ─────────────────────────────────────────
    section("4. SYSTEMIC RISK INDICATORS")
    risk = systemic_risk
    kv("Overall Risk Level",    risk.risk_level.value)
    kv("Liquidity Ratio",       f"{risk.total_liquidity_ratio:.4f}")
    kv("Reserve Depleted",      f"{'YES ⚠️' if risk.reserve_depleted else 'No'}")
    kv("Avg Prediction Error",  f"{risk.avg_prediction_error:.1f}%  (across {risk.total_predictions} records)")
    kv("Severe Miss Count",    f"{risk.severe_miss_count}  (negative ROI investments)")
    kv("Portfolio ROI",         f"{risk.overall_roi*100:.2f}%")
    kv("Total Deployed",        f"${risk.total_deployed:,.2f}")
    kv("Total Revenue",         f"${risk.total_revenue:,.2f}")

    if risk.risk_factors:
        lines.append(f"\n  Risk Factors:")
        for rf in risk.risk_factors:
            lines.append(f"    ⚠️  {rf}")
    else:
        lines.append(f"\n  ✅ No risk factors identified")

    # ── 5. Alert Generator ───────────────────────────────────────────────────
    section("5. ALERT GENERATOR")
    if not alerts:
        lines.append("\n  ✅ No alerts — portfolio within thresholds")
    else:
        # Group by severity
        crit = [a for a in alerts if a.severity == RiskLevel.CRITICAL]
        high = [a for a in alerts if a.severity == RiskLevel.HIGH]
        med  = [a for a in alerts if a.severity == RiskLevel.MEDIUM]
        low  = [a for a in alerts if a.severity == RiskLevel.LOW]

        lines.append(f"\n  Total Alerts: {len(alerts)} "
                     f"  🔴 {len(crit)}  🟠 {len(high)}  🟡 {len(med)}  🟢 {len(low)}")

        for alt in alerts:
            lines.append(f"\n  [{alt.alert_id}] {alt.severity.value} | {alt.category}")
            lines.append(f"  Title: {alt.title}")
            lines.append(f"  Issue: {alt.message}")
            lines.append(f"  → {alt.recommendation}")
            if alt.unit == "%":
                lines.append(f"  Metric: {alt.metric_value:.2f}{alt.unit}  (threshold: {alt.threshold:.2f}{alt.unit})")
            elif alt.unit == "USD":
                lines.append(f"  Metric: ${alt.metric_value:.2f}  (threshold: ${alt.threshold:.2f})")
            else:
                lines.append(f"  Metric: {alt.metric_value}  (threshold: {alt.threshold})")

    # ── Footer ───────────────────────────────────────────────────────────────
    lines.append(f"\n{SEP}")
    lines.append(f"  END OF BOARD REPORT — {ts}")
    lines.append(SEP)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="HVOS Portfolio Manager — Board Meeting Level Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate full board meeting report",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help=f"Path to capital_book.db (default: {DB_PATH})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON instead of text report (for --report)",
    )
    parser.add_argument(
        "--alerts", action="store_true",
        help="Show current alerts only",
    )
    parser.add_argument(
        "--hhi", action="store_true",
        help="Show HHI concentration metric only",
    )
    parser.add_argument(
        "--pools", action="store_true",
        help="Show pool health dashboard only",
    )
    parser.add_argument(
        "--risk", action="store_true",
        help="Show systemic risk indicators only",
    )
    args = parser.parse_args()

    db = args.db

    # If no specific flag, default to --report
    if not any([args.report, args.alerts, args.hhi, args.pools, args.risk]):
        args.report = True

    if args.report:
        ic = get_ic_summary(db)
        ph = get_pool_health(db)
        sr = get_systemic_risk(db)
        al = generate_alerts(db)

        if args.json:
            print(json.dumps({
                "ic_summary": ic,
                "pool_health": ph,
                "systemic_risk": asdict(sr),
                "alerts": [asdict(a) for a in al],
            }, indent=2, default=str))
        else:
            report_text = render_board_report(ic, ph, sr, al)
            print(report_text)

    elif args.alerts:
        al = generate_alerts(db)
        if args.json:
            print(json.dumps([asdict(a) for a in al], indent=2, default=str))
        else:
            print(f"Alert Generator — {len(al)} alert(s) found\n")
            for alt in al:
                print(f"[{alt.alert_id}] {alt.severity.value} | {alt.category}")
                print(f"  {alt.title}")
                print(f"  {alt.message}")
                print(f"  → {alt.recommendation}\n")

    elif args.hhi:
        hhi = compute_hhi(db)
        if args.json:
            print(json.dumps(asdict(hhi), indent=2, default=str))
        else:
            print(f"HHI Concentration Index")
            print(f"  HHI Score:         {hhi.hhi:.2f}")
            print(f"  Normalized HHI:    {hhi.normalized_hhi:.2f}%")
            print(f"  Category Count:    {hhi.category_count}")
            print(f"  Dominant:          {hhi.dominant_category} ({hhi.dominant_share:.1f}%)")
            print(f"  Interpretation:    {hhi.interpretation}")

    elif args.pools:
        ph = get_pool_health(db)
        if args.json:
            print(json.dumps(ph, indent=2, default=str))
        else:
            print("Pool Health Dashboard\n")
            for pool in ph["pools"]:
                print(f"[{pool['status'].value}] {pool['pool_type']}")
                print(f"  Total: ${pool['total_capital']:,.2f}  "
                      f"Alloc: ${pool['allocated']:,.2f}  "
                      f"Avail: ${pool['available']:,.2f}")
                print(f"  Utilisation: {pool['utilization_pct']:.1f}%  "
                      f"Available: {pool['available_pct']:.1f}%")
                print(f"  {pool['status_reason']}\n")

    elif args.risk:
        sr = get_systemic_risk(db)
        if args.json:
            print(json.dumps(asdict(sr), indent=2, default=str))
        else:
            print(f"Systemic Risk Indicators")
            print(f"  Risk Level:        {sr.risk_level.value}")
            print(f"  Liquidity Ratio:  {sr.total_liquidity_ratio:.4f}")
            print(f"  Reserve Depleted: {sr.reserve_depleted}")
            print(f"  Avg Pred Error:   {sr.avg_prediction_error:.1f}%")
            print(f"  Severe Misses:    {sr.severe_miss_count} / {sr.total_predictions}")
            print(f"  Total Deployed:   ${sr.total_deployed:,.2f}")
            print(f"  Total Revenue:    ${sr.total_revenue:,.2f}")
            print(f"  Portfolio ROI:    {sr.overall_roi*100:.2f}%")
            if sr.risk_factors:
                print(f"  Risk Factors:")
                for rf in sr.risk_factors:
                    print(f"    ⚠️  {rf}")


if __name__ == "__main__":
    main()
