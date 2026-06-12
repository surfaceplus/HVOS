"""
HVOS Economics Engine
====================
Revenue / Profit / Cashflow / ROI / Payback Period 分离建模。

核心理念：
  收入预测 ≠ ROI预测。
  一个公司可以收入很高但ROI很低（如高固定成本）。
  HVOS 必须分开建模，才能精确定位"错在哪里"。

Stage 1.5: Economics Layer MVP

Author: HVOS X Economics
Version: 1.0.0
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EconomicsInput:
    """经济模型输入"""
    # 收入（必填）
    predicted_revenue: float = 0.0
    horizon_days: int = 90
    currency: str = "USD"

    # 收入区间（可选）
    predicted_revenue_low: float = 0.0
    predicted_revenue_high: float = 0.0

    # 成本结构（可选，使用行业默认比例）
    cogs_pct: float = 0.0          # COGS占收入比（默认28%）
    advertising_cost_pct: float = 0.0  # 广告占收入比（默认15%）
    shipping_cost_pct: float = 0.0    # 物流占收入比（默认5%）
    packaging_cost_pct: float = 0.0   # 包装占收入比（默认2%）
    transaction_fee_pct: float = 0.0  # 支付手续费率（默认2.9%）
    platform_fee_pct: float = 0.0    # 平台佣金率（默认2%）

    # 绝对值覆盖（优先于比例）
    cogs: float = 0.0
    advertising_cost: float = 0.0
    shipping_cost: float = 0.0
    packaging_cost: float = 0.0
    transaction_fee: float = 0.0
    platform_fee: float = 0.0
    other_operating_cost: float = 0.0
    tax_rate: float = 0.0


@dataclass
class EconomicsForecast:
    """经济模型输出（完整分解）"""
    # 收入
    revenue: float
    revenue_low: float
    revenue_high: float
    revenue_pct_of_predicted: float = 100.0   # 实际/预测

    # 成本分解
    cogs: float
    cogs_pct: float                        # 占收入比
    advertising_cost: float
    advertising_cost_pct: float
    shipping_cost: float
    packaging_cost: float
    transaction_fee: float
    transaction_fee_pct: float
    platform_fee: float
    platform_fee_pct: float
    other_cost: float
    total_cost: float                      # COGS + 运营成本 + 手续费 + 平台费

    # 利润分层
    gross_profit: float                    # 毛利 = Revenue - COGS
    gross_margin: float                     # 毛利率 = GrossProfit / Revenue
    gross_margin_pct: float               # 毛利率百分比

    net_profit: float                     # 净利 = GrossProfit - 运营成本 - 税费
    net_margin: float                      # 净利率 = NetProfit / Revenue

    # ROI 核心
    investment_amount: float               # 投入金额
    roi: float                            # ROI = NetProfit / Investment
    roi_pct: float                       # ROI百分比

    # Payback
    payback_days: float                   # 回本天数

    # Cashflow
    gross_profit_first: float             # 首期毛利（用于现金流）
    net_profit_first: float               # 首期净利
    cumulative_cashflow: float             # 累计现金流

    # 对比误差
    revenue_error_pct: float = 0.0
    roi_error_pct: float = 0.0
    roi_error_direction: str = ""

    # 模型元数据
    horizon_days: int = 90
    currency: str = "USD"
    model_version: str = "v1.0"
    timestamp: str = ""


class EconomicsEngine:
    """
    经济模型引擎

    使用方法：
        engine = EconomicsEngine()

        # 预测（Board Approval前）
        forecast = engine.forecast_revenue(input)  # 收入
        forecast = engine.forecast_profit(input)      # 毛利
        forecast = engine.forecast_net_profit(input) # 净利
        forecast = engine.forecast_roi(input)       # ROI
        forecast = engine.forecast_payback(input)    # 回本周期
        forecast = engine.forecast_full(input)       # 全部模型

        # 回测（Reality Layer返回后）
        feedback = engine.compute_roi_error(
            predicted_roi=2.3,
            actual_roi=1.17,
        )
    """

    VERSION = "1.0.0"

    # ─────────────────────────────────────────────────────────────────────
    # 成本默认值（根据DTC礼品行业基准）
    # ─────────────────────────────────────────────────────────────────────

    DEFAULT_COGS_PCT = 0.28          # DTC礼品：28% of revenue
    DEFAULT_AD_COST_PCT = 0.15        # 广告：15% of revenue（成熟产品可降到8%）
    DEFAULT_SHIPPING_PCT = 0.05        # 物流：5% of revenue
    DEFAULT_PACKAGING_PCT = 0.02       # 包装：2% of revenue
    DEFAULT_PLATFORM_FEE_PCT = 0.02    # 平台费：2%

    def __init__(self, defaults: Optional[dict] = None):
        self.defaults = defaults or {}

    # ─────────────────────────────────────────────────────────────────────
    # 收入预测
    # ─────────────────────────────────────────────────────────────────────

    def forecast_revenue(
        self,
        input_data: EconomicsInput,
    ) -> EconomicsForecast:
        """
        纯收入预测（不考虑成本）
        用于：Google Trends / 竞品分析 → 收入估算
        """
        return self._build_forecast(input_data)

    # ─────────────────────────────────────────────────────────────────────
    # 毛利预测（COGS 后）
    # ─────────────────────────────────────────────────────────────────────

    def forecast_profit(
        self,
        input_data: EconomicsInput,
    ) -> EconomicsForecast:
        """
        毛利 = Revenue - COGS
        用于：了解产品本身毛利率（不含营销）
        DTC礼品典型：72% gross margin 为健康水平
        """
        inp = self._apply_defaults(input_data)
        return self._build_forecast(inp)

    # ─────────────────────────────────────────────────────────────────────
    # 净利预测（全部成本后）
    # ─────────────────────────────────────────────────────────────────────

    def forecast_net_profit(
        self,
        input_data: EconomicsInput,
    ) -> EconomicsForecast:
        """
        净利 = Revenue - COGS - 广告 - 物流 - 包装 - 手续费 - 平台费 - 税费
        用于：了解真实盈利能力
        DTC礼品典型：15-25% net margin 为良好
        """
        inp = self._apply_defaults(input_data)
        return self._build_forecast(inp)

    # ─────────────────────────────────────────────────────────────────────
    # ROI 预测（基于投入金额）
    # ─────────────────────────────────────────────────────────────────────

    def forecast_roi(
        self,
        input_data: EconomicsInput,
    ) -> EconomicsForecast:
        """
        ROI = NetProfit / Investment
        用于：投资决策核心指标
        """
        inp = self._apply_defaults(input_data)
        return self._build_forecast(inp)

    # ─────────────────────────────────────────────────────────────────────
    # 回本周期预测
    # ─────────────────────────────────────────────────────────────────────

    def forecast_payback(
        self,
        input_data: EconomicsInput,
    ) -> EconomicsForecast:
        """
        回本天数 = Investment / (Revenue - COGS - 运营成本) × horizon_days
        用于：现金流规划
        """
        inp = self._apply_defaults(input_data)
        return self._build_forecast(inp)

    # ─────────────────────────────────────────────────────────────────────
    # 完整经济模型（一次调用，返回所有指标）
    # ─────────────────────────────────────────────────────────────────────

    def forecast_full(
        self,
        input_data: EconomicsInput,
    ) -> EconomicsForecast:
        """
        完整经济模型
        返回 Revenue / GrossProfit / NetProfit / ROI / Payback 全部分解
        """
        inp = self._apply_defaults(input_data)
        return self._build_forecast(inp)

    # ─────────────────────────────────────────────────────────────────────
    # ROI 误差分析
    # ─────────────────────────────────────────────────────────────────────

    def compute_roi_error(
        self,
        predicted_roi: float,
        actual_roi: float,
    ) -> dict:
        """
        计算 ROI 预测误差，并诊断误差来源。

        误差来源分解：
        1. 收入误差：实际收入 vs 预测收入
        2. 成本误差：实际成本结构 vs 预测
        3. 投入金额误差：实际投入 vs 预测

        返回：
        {
            "predicted_roi": float,
            "actual_roi": float,
            "roi_error_pct": float,
            "roi_error_direction": "over" | "under",
            "verdict": str,
            "diagnosis": {
                "revenue_error_pct": float,
                "cost_error_pct": float,
                "investment_error_pct": float,
            }
        }
        """
        if predicted_roi == 0:
            roi_error = abs(actual_roi) * 100
        else:
            roi_error = abs(actual_roi - predicted_roi) / abs(predicted_roi) * 100

        direction = "over" if actual_roi > predicted_roi else "under"

        if roi_error < 10:
            verdict = "✅ 高精准"
        elif roi_error < 25:
            verdict = "⚠️ 可接受"
        elif roi_error < 50:
            verdict = "⚠️ 偏差较大"
        else:
            verdict = "❌ 严重偏差"

        return {
            "predicted_roi": round(predicted_roi, 4),
            "actual_roi": round(actual_roi, 4),
            "roi_error_pct": round(roi_error, 2),
            "roi_error_direction": direction,
            "verdict": verdict,
            "diagnosis": {
                "description": self._diagnose_roi_error(predicted_roi, actual_roi)
            }
        }

    def _diagnose_roi_error(self, predicted_roi: float, actual_roi: float) -> str:
        """
        ROI 误差根源诊断
        """
        ratio = actual_roi / predicted_roi if predicted_roi != 0 else 0
        if ratio > 1.2:
            return f"实际ROI {actual_roi:.2f}x 远超预测 {predicted_roi:.2f}x，可能成本控制优于预期或市场竞争减少"
        elif ratio < 0.8:
            return f"实际ROI {actual_roi:.2f}x 低于预测 {predicted_roi:.2f}x，需分析：是收入不足还是成本超支"
        else:
            return "误差在可接受范围内，维持现有模型"

    # ─────────────────────────────────────────────────────────────────────
    # 内部构建器
    # ─────────────────────────────────────────────────────────────────────

    def _apply_defaults(self, inp: EconomicsInput) -> EconomicsInput:
        """填充默认值（使用DTC行业基准）"""
        d = self.defaults

        # COGS
        if inp.cogs == 0 and inp.cogs_pct == 0:
            inp.cogs_pct = d.get("cogs_pct", self.DEFAULT_COGS_PCT)
            inp.cogs = inp.predicted_revenue * inp.cogs_pct

        # 广告成本
        if inp.advertising_cost == 0 and inp.advertising_cost_pct == 0:
            inp.advertising_cost_pct = d.get("ad_cost_pct", self.DEFAULT_AD_COST_PCT)
            inp.advertising_cost = inp.predicted_revenue * inp.advertising_cost_pct

        # 物流
        if inp.shipping_cost == 0:
            inp.shipping_cost = inp.predicted_revenue * (
                d.get("shipping_pct", self.DEFAULT_SHIPPING_PCT)
            )

        # 包装
        if inp.packaging_cost == 0:
            inp.packaging_cost = inp.predicted_revenue * (
                d.get("packaging_pct", self.DEFAULT_PACKAGING_PCT)
            )

        # 支付手续费（默认2.9% + $0.30/单，简化用2.9%）
        if inp.transaction_fee == 0 and inp.transaction_fee_pct == 0:
            inp.transaction_fee_pct = d.get("tx_fee_pct", 0.029)
            inp.transaction_fee = inp.predicted_revenue * inp.transaction_fee_pct

        # 平台佣金
        if inp.platform_fee == 0 and inp.platform_fee_pct == 0:
            inp.platform_fee_pct = d.get("platform_fee_pct", self.DEFAULT_PLATFORM_FEE_PCT)
            inp.platform_fee = inp.predicted_revenue * inp.platform_fee_pct

        return inp

    def _build_forecast(self, inp: EconomicsInput) -> EconomicsForecast:
        """构建完整经济模型"""

        # 成本计算
        cogs = inp.predicted_revenue * inp.cogs_pct if inp.cogs == 0 else inp.cogs
        ad_cost = inp.predicted_revenue * inp.advertising_cost_pct if inp.advertising_cost == 0 else inp.advertising_cost
        ship_cost = inp.predicted_revenue * 0.05 if inp.shipping_cost == 0 else inp.shipping_cost
        pkg_cost = inp.predicted_revenue * 0.02 if inp.packaging_cost == 0 else inp.packaging_cost
        tx_fee = inp.predicted_revenue * inp.transaction_fee_pct if inp.transaction_fee == 0 else inp.transaction_fee
        plat_fee = inp.predicted_revenue * inp.platform_fee_pct if inp.platform_fee == 0 else inp.platform_fee
        other_cost = inp.other_operating_cost

        # 总成本
        total_cost = cogs + ad_cost + ship_cost + pkg_cost + tx_fee + plat_fee + other_cost

        # 毛利
        gross_profit = inp.predicted_revenue - cogs
        gross_margin = gross_profit / inp.predicted_revenue if inp.predicted_revenue > 0 else 0
        gross_margin_pct = gross_margin * 100

        # 净利
        net_profit = gross_profit - ad_cost - ship_cost - pkg_cost - tx_fee - plat_fee - other_cost
        net_margin = net_profit / inp.predicted_revenue if inp.predicted_revenue > 0 else 0

        # ROI
        inv = inp.predicted_revenue * 0.5  # 典型：投入约为预测收入的50%（广告+COGS预付）
        roi = net_profit / inv if inv > 0 else 0
        roi_pct = roi * 100

        # 回本天数（用首期毛利 / 日均毛利估算）
        horizon_days = inp.horizon_days or 90
        daily_gross_profit = gross_profit / horizon_days if horizon_days > 0 else 0
        daily_net_profit = net_profit / horizon_days if horizon_days > 0 else 0
        payback_days = (inv / daily_net_profit) if daily_net_profit > 0 else float('inf')

        # 首期现金流
        gross_profit_first = gross_profit * 0.3  # 估算首30天
        net_profit_first = net_profit * 0.3
        cumulative_cashflow = net_profit  # 简化版

        # 误差字段（当有实际值时填充）
        revenue_error_pct = 0.0
        roi_error_pct = 0.0
        roi_error_direction = ""

        return EconomicsForecast(
            # 收入
            revenue=round(inp.predicted_revenue, 2),
            revenue_low=round(inp.predicted_revenue_low, 2),
            revenue_high=round(inp.predicted_revenue_high, 2),
            revenue_pct_of_predicted=100.0,

            # 成本分解
            cogs=round(cogs, 2),
            cogs_pct=round(inp.cogs_pct * 100, 1),
            advertising_cost=round(ad_cost, 2),
            advertising_cost_pct=round(inp.advertising_cost_pct * 100, 1),
            shipping_cost=round(ship_cost, 2),
            packaging_cost=round(pkg_cost, 2),
            transaction_fee=round(tx_fee, 2),
            transaction_fee_pct=round(inp.transaction_fee_pct * 100, 1),
            platform_fee=round(plat_fee, 2),
            platform_fee_pct=round(inp.platform_fee_pct * 100, 1),
            other_cost=round(other_cost, 2),
            total_cost=round(total_cost, 2),

            # 利润分层
            gross_profit=round(gross_profit, 2),
            gross_margin=round(gross_margin, 4),
            gross_margin_pct=round(gross_margin_pct, 1),

            net_profit=round(net_profit, 2),
            net_margin=round(net_margin, 4),

            # ROI
            investment_amount=round(inv, 2),
            roi=round(roi, 4),
            roi_pct=round(roi_pct, 2),

            # Payback
            payback_days=round(payback_days, 1),

            # Cashflow
            gross_profit_first=round(gross_profit_first, 2),
            net_profit_first=round(net_profit_first, 2),
            cumulative_cashflow=round(cumulative_cashflow, 2),

            # 误差
            revenue_error_pct=revenue_error_pct,
            roi_error_pct=roi_error_pct,
            roi_error_direction=roi_error_direction,

            horizon_days=inp.horizon_days,
            currency=inp.currency,
            model_version=self.VERSION,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ─────────────────────────────────────────────────────────────────────
    # ROI 误差诊断（多维度归因）
    # ─────────────────────────────────────────────────────────────────────

    def attribute_roi_error(
        self,
        predicted: EconomicsForecast,
        actual: EconomicsForecast,
    ) -> dict:
        """
        将 ROI 误差分解到具体成本项。

        诊断结果示例：
        {
            "roi_error_total": 49.3,
            "revenue_miss_pct": 6.2,     ← 收入少预测了6.2%导致
            "cogs_overrun_pct": 0.0,     ← COGS无超支
            "ad_cost_overrun_pct": 30.1,  ← 广告花了太多
            "root_cause": "advertising_cost",
            "recommendation": "降低广告ACOS或提高转化率"
        }
        """
        # 收入误差
        rev_err = (
            (actual.revenue - predicted.revenue) / predicted.revenue * 100
            if predicted.revenue > 0 else 0
        )

        # 各项成本误差
        def cost_err_pct(pred_cost, actual_cost, pred_rev):
            if pred_rev <= 0:
                return 0.0
            return (actual_cost - pred_cost) / pred_rev * 100

        cogs_err = cost_err_pct(predicted.cogs, actual.cogs, predicted.revenue)
        ad_err = cost_err_pct(predicted.advertising_cost, actual.advertising_cost, predicted.revenue)
        ship_err = cost_err_pct(predicted.shipping_cost, actual.shipping_cost, predicted.revenue)
        tx_err = cost_err_pct(predicted.transaction_fee, actual.transaction_fee, predicted.revenue)
        plat_err = cost_err_pct(predicted.platform_fee, actual.platform_fee, predicted.revenue)

        roi_err_total = abs(actual.roi - predicted.roi) / abs(predicted.roi) * 100 if predicted.roi != 0 else 0

        # 找最大根因
        cost_errors = {
            "revenue": rev_err,
            "cogs": cogs_err,
            "advertising_cost": ad_err,
            "shipping_cost": ship_err,
            "transaction_fee": tx_err,
            "platform_fee": plat_err,
        }

        # 最大误差项（按影响排序）
        sorted_errors = sorted(cost_errors.items(), key=lambda x: abs(x[1]), reverse=True)

        root_cause = sorted_errors[0][0]
        root_cause_pct = sorted_errors[0][1]

        recommendations = {
            "revenue": "增加SEO/内容营销投入，提高自然流量占比",
            "cogs": "优化供应链，寻找更具性价比的供应商或批量采购",
            "advertising_cost": "降低ACOS目标或优化广告素材提高CTR和转化率",
            "shipping_cost": "与物流商重新谈判合同，或调整产品定价覆盖成本",
            "transaction_fee": "考虑更换支付服务商（如Stripe vs PayPal费率差异）",
            "platform_fee": "评估平台佣金是否值得，可考虑DTC独立站直销",
        }

        return {
            "roi_error_total_pct": round(roi_err_total, 1),
            "revenue_miss_pct": round(rev_err, 2),
            "cogs_overrun_pct": round(cogs_err, 2),
            "ad_cost_overrun_pct": round(ad_err, 2),
            "shipping_overrun_pct": round(ship_err, 2),
            "tx_fee_overrun_pct": round(tx_err, 2),
            "platform_overrun_pct": round(plat_err, 2),
            "root_cause": root_cause,
            "root_cause_pct": round(root_cause_pct, 2),
            "recommendation": recommendations.get(root_cause, "需进一步分析"),
            "cost_breakdown": {
                k: round(v, 2) for k, v in cost_errors.items()
            },
        }

    # ─────────────────────────────────────────────────────────────────────
    # CLI
    # ─────────────────────────────────────────────────────────────────────

    def demo(self):
        """演示完整经济模型"""
        inp = EconomicsInput(
            predicted_revenue=13800.0,
            predicted_revenue_low=11000.0,
            predicted_revenue_high=16500.0,
            cogs_pct=0.28,
            advertising_cost_pct=0.15,
            horizon_days=90,
        )
        forecast = self.forecast_full(inp)
        print("=== EconomicsEngine 演示 ===")
        print(f"预测收入: ${forecast.revenue:,.2f}")
        print(f"  区间: ${forecast.revenue_low:,.2f} ~ ${forecast.revenue_high:,.2f}")
        print()
        print(f"成本分解:")
        print(f"  COGS ({forecast.cogs_pct:.0f}%):         -${forecast.cogs:,.2f}")
        print(f"  广告 ({forecast.advertising_cost_pct:.0f}%):    -${forecast.advertising_cost:,.2f}")
        print(f"  物流:            -${forecast.shipping_cost:,.2f}")
        print(f"  包装:            -${forecast.packaging_cost:,.2f}")
        print(f"  支付手续费:      -${forecast.transaction_fee:,.2f}")
        print(f"  平台佣金:         -${forecast.platform_fee:,.2f}")
        print(f"  总成本:           -${forecast.total_cost:,.2f}")
        print()
        print(f"毛利:              ${forecast.gross_profit:,.2f} ({forecast.gross_margin_pct:.0f}%)")
        print(f"净利:              ${forecast.net_profit:,.2f}")
        print()
        print(f"投入:              ${forecast.investment_amount:,.2f}")
        print(f"ROI:               {forecast.roi:.2f}x ({forecast.roi_pct:.0f}%)")
        print(f"回本周期:           {forecast.payback_days:.0f}天")

        # ROI 误差演示
        print()
        print("--- ROI 误差诊断演示 ---")
        pred_roi = forecast.roi
        actual_roi = 1.17  # 来自真实数据
        error = self.compute_roi_error(pred_roi, actual_roi)
        print(f"预测ROI: {error['predicted_roi']:.2f}x | 实际ROI: {error['actual_roi']:.2f}x")
        print(f"误差率: {error['roi_error_pct']:.1f}% | {error['verdict']}")
        print(f"诊断: {error['diagnosis']['description']}")


if __name__ == "__main__":
    engine = EconomicsEngine()
    engine.demo()
