"""
ROI Calculator Tool
===================
Calculates full economics breakdown using HVOS EconomicsEngine.

Computes: Revenue, COGS, Gross Profit, Net Profit, ROI, Payback Period.
Uses DTC gift industry benchmarks by default.
"""

import sys
import os
from typing import Dict, Any, Optional

# Add HVOS paths
HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
for _p in [HVOS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ROICalculator:
    """
    ROI Calculator Tool.
    
    Wraps EconomicsEngine to provide ROI calculations via API.
    
    Usage:
        calc = ROICalculator()
        result = calc.calculate(
            predicted_revenue=10000.0,
            horizon_days=90,
            cogs_pct=0.28
        )
    """
    
    def __init__(self, defaults: dict = None):
        self.defaults = defaults or {}
        self._engine = None
    
    def _get_engine(self):
        """Lazy initialization of EconomicsEngine"""
        if self._engine is None:
            try:
                from economics_engine import EconomicsEngine, EconomicsInput
                self._engine = EconomicsEngine(defaults=self.defaults)
                self._engine_input_class = EconomicsInput
            except ImportError as e:
                raise RuntimeError(
                    f"Failed to import EconomicsEngine: {e}. "
                    "Make sure economics_engine.py is available."
                )
        return self._engine
    
    def calculate(
        self,
        predicted_revenue: float,
        horizon_days: int = 90,
        currency: str = "USD",
        cogs_pct: float = 0.28,
        advertising_cost_pct: float = 0.15,
        shipping_cost_pct: float = 0.05,
        packaging_cost_pct: float = 0.02,
        transaction_fee_pct: float = 0.029,
        platform_fee_pct: float = 0.02,
        investment_amount: float = 0.0,
        other_operating_cost: float = 0.0,
        tax_rate: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Calculate full economics breakdown.
        
        Args:
            predicted_revenue: Predicted revenue for horizon period (USD)
            horizon_days: Forecast horizon in days (default 90)
            currency: Currency code
            cogs_pct: COGS as % of revenue (default 0.28)
            advertising_cost_pct: Ad cost as % (default 0.15)
            shipping_cost_pct: Shipping as % (default 0.05)
            packaging_cost_pct: Packaging as % (default 0.02)
            transaction_fee_pct: Payment processing fee % (default 0.029)
            platform_fee_pct: Platform commission % (default 0.02)
            investment_amount: Override investment amount (auto-calc if 0)
            other_operating_cost: Additional operating costs
            tax_rate: Tax rate % (default 0)
            
        Returns:
            Structured economics breakdown with all metrics
        """
        try:
            engine = self._get_engine()
            
            # Build input
            input_data = self._engine_input_class(
                predicted_revenue=predicted_revenue,
                horizon_days=horizon_days,
                currency=currency,
                cogs_pct=cogs_pct,
                advertising_cost_pct=advertising_cost_pct,
                shipping_cost_pct=shipping_cost_pct,
                packaging_cost_pct=packaging_cost_pct,
                transaction_fee_pct=transaction_fee_pct,
                platform_fee_pct=platform_fee_pct,
                other_operating_cost=other_operating_cost,
                tax_rate=tax_rate,
            )
            
            # Override investment if provided
            if investment_amount > 0:
                input_data.predicted_revenue = investment_amount * 2  # Engine expects revenue, we provide derived
            
            # Run full forecast
            forecast = engine.forecast_full(input_data)
            
            # Override investment amount if specified
            if investment_amount > 0:
                # Recalculate ROI with provided investment
                inv = investment_amount
                roi = forecast.net_profit / inv if inv > 0 else 0
                roi_pct = roi * 100
                payback_days = (inv / (forecast.net_profit / horizon_days)) if forecast.net_profit > 0 else float('inf')
            else:
                inv = forecast.investment_amount
                roi = forecast.roi
                roi_pct = forecast.roi_pct
                payback_days = forecast.payback_days
            
            return {
                "success": True,
                "tool": "roi_calculator",
                "input": {
                    "predicted_revenue": predicted_revenue,
                    "horizon_days": horizon_days,
                    "currency": currency,
                    "cogs_pct": cogs_pct,
                    "advertising_cost_pct": advertising_cost_pct,
                },
                "output": {
                    "revenue": forecast.revenue,
                    "revenue_low": forecast.revenue_low,
                    "revenue_high": forecast.revenue_high,
                    "cogs": forecast.cogs,
                    "cogs_pct": forecast.cogs_pct,
                    "advertising_cost": forecast.advertising_cost,
                    "advertising_cost_pct": forecast.advertising_cost_pct,
                    "shipping_cost": forecast.shipping_cost,
                    "packaging_cost": forecast.packaging_cost,
                    "transaction_fee": forecast.transaction_fee,
                    "transaction_fee_pct": forecast.transaction_fee_pct,
                    "platform_fee": forecast.platform_fee,
                    "platform_fee_pct": forecast.platform_fee_pct,
                    "other_cost": forecast.other_cost,
                    "total_cost": forecast.total_cost,
                    "gross_profit": forecast.gross_profit,
                    "gross_margin": forecast.gross_margin,
                    "gross_margin_pct": forecast.gross_margin_pct,
                    "net_profit": forecast.net_profit,
                    "net_margin": forecast.net_margin,
                    "investment_amount": inv,
                    "roi": roi,
                    "roi_pct": roi_pct,
                    "payback_days": payback_days,
                    "horizon_days": forecast.horizon_days,
                    "currency": forecast.currency,
                    "model_version": forecast.model_version,
                    "timestamp": forecast.timestamp,
                },
                "summary": {
                    "gross_margin_pct": f"{forecast.gross_margin_pct:.1f}%",
                    "net_margin_pct": f"{forecast.net_margin * 100:.1f}%",
                    "roi_pct": f"{roi_pct:.1f}%",
                    "payback_days": f"{payback_days:.0f} days",
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "tool": "roi_calculator",
                "error": str(e),
                "error_type": type(e).__name__,
            }
    
    def compute_roi_error(
        self,
        predicted_roi: float,
        actual_roi: float,
    ) -> Dict[str, Any]:
        """
        Compute ROI prediction error.
        
        Args:
            predicted_roi: Predicted ROI value
            actual_roi: Actual observed ROI value
            
        Returns:
            Error analysis with diagnosis
        """
        try:
            engine = self._get_engine()
            result = engine.compute_roi_error(predicted_roi, actual_roi)
            return {
                "success": True,
                "tool": "roi_calculator",
                "analysis": result,
            }
        except Exception as e:
            return {
                "success": False,
                "tool": "roi_calculator",
                "error": str(e),
            }