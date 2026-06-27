"""
HVOS Workflow Engine
===================
Automated product selection + advertising workflow.

Workflow steps:
1. Scan → 扫描信号源，获取机会列表
2. Score → Alpha Score 过滤
3. ROI → 经济模型计算
4. Alert → 微信推送通知
5. Listing → WooCommerce 上架（可选）

Usage:
    wf = HVOSWorkflow()
    result = wf.run_full_pipeline(
        category="kitchen",
        min_alpha_score=60,
        min_net_margin=0.30,
        send_alert=True,
        create_listing=True
    )
"""

import sys
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

HVOS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [HVOS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hvos_api.tools.selector import ProductSelector
from hvos_api.tools.roi_calculator import ROICalculator
from hvos_api.tools.wechat_pusher import WeChatPusher
from hvos_api.tools.wc_writer import WCWriter


@dataclass
class WorkflowConfig:
    """Configuration for workflow thresholds"""
    min_alpha_score: float = 60.0      # Alpha Score 最低门槛
    min_net_margin: float = 0.25        # 净利率最低门槛
    min_roi_pct: float = 50.0          # ROI 最低门槛（%）
    max_payback_days: float = 60.0      # 回本天数上限
    alert_on_strict_pass: bool = True   # 同时满足所有门槛才推送
    alert_on_partial_pass: bool = False # 只满足部分门槛也推送
    create_listing_on_pass: bool = True # 通过后自动上架 WooCommerce
    max_listings_per_run: int = 3       # 每次最多上架数量


@dataclass
class WorkflowProduct:
    """Product with workflow analysis"""
    opp_id: str
    name: str
    category: str
    alpha_score: float
    recommendation: str

    # ROI data
    predicted_revenue: float = 0.0
    net_margin_pct: float = 0.0
    roi_pct: float = 0.0
    payback_days: float = 999.0

    # Pass/fail status
    alpha_pass: bool = False
    margin_pass: bool = False
    roi_pass: bool = False
    payback_pass: bool = False

    # Overall
    overall_pass: bool = False
    pass_count: int = 0

    # Actions taken
    alert_sent: bool = False
    listing_created: bool = False
    listing_id: Optional[int] = None

    def check_pass(self, config: WorkflowConfig) -> None:
        """Check all thresholds and set pass flags"""
        self.alpha_pass = self.alpha_score >= config.min_alpha_score
        self.margin_pass = self.net_margin_pct >= config.min_net_margin * 100
        self.roi_pass = self.roi_pct >= config.min_roi_pct
        self.payback_pass = self.payback_days <= config.max_payback_days

        self.pass_count = sum([
            self.alpha_pass,
            self.margin_pass,
            self.roi_pass,
            self.payback_pass,
        ])

        # All 4 must pass
        self.overall_pass = all([
            self.alpha_pass,
            self.margin_pass,
            self.roi_pass,
            self.payback_pass,
        ])


class HVOSWorkflow:
    """
    HVOS 自动选品 + 投放 Workflow

    端到端流程：
    Scan → Filter → ROI Calculate → WeChat Alert → WooCommerce Listing
    """

    def __init__(self, config: WorkflowConfig = None):
        self.config = config or WorkflowConfig()
        self._selector = ProductSelector()
        self._roi = ROICalculator()
        self._wechat = WeChatPusher()
        self._wc = WCWriter()

    def scan_opportunities(
        self,
        category: str = "",
        limit: int = 20,
        timeout_seconds: float = 8.0,
    ) -> List[WorkflowProduct]:
        """
        Step 1: 扫描机会列表（带超时保护）

        Args:
            category: 类目过滤（空=全部）
            limit: 返回数量上限
            timeout_seconds: 扫描超时秒数（超时返回空列表）

        Returns:
            List[WorkflowProduct]
        """
        import threading

        result_holder = [None]  # closure-safe container

        def scan_task():
            try:
                result_holder[0] = self._selector.select(
                    category=category,
                    limit=limit,
                    min_alpha_score=0,
                )
            except Exception as e:
                result_holder[0] = {"success": False, "error": str(e), "products": []}

        t = threading.Thread(target=scan_task, daemon=True)
        t.start()
        t.join(timeout=timeout_seconds)

        if t.is_alive():
            # Timed out
            result = {"success": False, "error": "Scan timed out", "products": []}
        elif result_holder[0] is None:
            result = {"success": False, "error": "Unknown error", "products": []}
        else:
            result = result_holder[0]

        if not result.get("success"):
            # Return empty on error/timeout
            return []

        products = []
        for p in result.get("products", []):
            wp = WorkflowProduct(
                opp_id=p.get("opp_id", ""),
                name=p.get("name", ""),
                category=p.get("category", category or "general"),
                alpha_score=p.get("alpha_score", 0.0),
                recommendation=p.get("recommendation", "WATCH"),
            )
            products.append(wp)

        return products

    def calculate_roi(
        self,
        product: WorkflowProduct,
        revenue_estimate: float = None,
    ) -> WorkflowProduct:
        """
        Step 2: 计算 ROI
        
        Args:
            product: WorkflowProduct
            revenue_estimate: 预估收入（自动用 alpha_score * 基准估算）
        """
        # 估算收入：如果没提供，用 alpha_score 估算
        if revenue_estimate is None:
            # 基准：alpha_score 80 = $5000/月，线性插值
            revenue_estimate = (product.alpha_score / 80.0) * 5000

        roi_result = self._roi.calculate(
            predicted_revenue=revenue_estimate,
            horizon_days=30,
        )

        if roi_result.get("success"):
            output = roi_result.get("output", {})
            summary = roi_result.get("summary", {})

            product.predicted_revenue = revenue_estimate
            product.net_margin_pct = float(summary.get("net_margin_pct", "0%").rstrip("%"))
            product.roi_pct = float(summary.get("roi_pct", "0%").rstrip("%"))
            payback_str = summary.get("payback_days", "999 days")
            product.payback_days = float(payback_str.rstrip(" days").rstrip(" days"))

            # Check pass/fail
            product.check_pass(self.config)
        else:
            product.roi_pct = 0.0
            product.net_margin_pct = 0.0
            product.payback_days = 999

        return product

    def run_full_pipeline(
        self,
        category: str = "",
        revenue_estimate: float = None,
        send_alert: bool = True,
        create_listing: bool = False,
        limit: int = 20,
        scan_timeout: float = 8.0,
    ) -> Dict[str, Any]:
        """
        完整流水线：Scan → ROI → Alert → Listing
        
        Args:
            category: 类目过滤
            revenue_estimate: 统一收入估算（用于所有产品）
            send_alert: 是否发送微信通知
            create_listing: 是否创建 WooCommerce 列表
            limit: 扫描数量上限
            
        Returns:
            Full pipeline result with all products and actions taken
        """
        results = {
            "workflow": "full_pipeline",
            "category": category or "all",
            "config": {
                "min_alpha_score": self.config.min_alpha_score,
                "min_net_margin": self.config.min_net_margin,
                "min_roi_pct": self.config.min_roi_pct,
                "max_payback_days": self.config.max_payback_days,
            },
            "products": [],
            "summary": {
                "total_scanned": 0,
                "alpha_passed": 0,
                "fully_passed": 0,
                "alerts_sent": 0,
                "listings_created": 0,
            },
        }

        # Step 1: Scan (with timeout)
        products = self.scan_opportunities(category=category, limit=limit, timeout_seconds=scan_timeout)
        results["summary"]["total_scanned"] = len(products)

        if not products:
            results["note"] = "No opportunities found in scan"
            return results

        # Step 2: Calculate ROI for each product
        for wp in products:
            self.calculate_roi(wp, revenue_estimate)

        # Step 3: Evaluate and take actions
        passed_products = []
        for wp in products:
            if wp.overall_pass:
                passed_products.append(wp)
                results["summary"]["fully_passed"] += 1

        # Step 4: WeChat Alert for passing products
        if send_alert and passed_products:
            alert_lines = [
                f"🎯 HVOS 自动选品报告",
                f"📦 扫描: {category or '全部类目'} | 发现: {len(products)} 个机会",
                f"✅ 通过门槛: {len(passed_products)} 个",
                f"",
            ]

            for i, wp in enumerate(passed_products[:5], 1):  # 最多5个
                alert_lines.append(
                    f"{i}. {wp.name[:30]} | "
                    f"Alpha: {wp.alpha_score:.0f} | "
                    f"净利: {wp.net_margin_pct:.1f}% | "
                    f"ROI: {wp.roi_pct:.0f}% | "
                    f"回本: {wp.payback_days:.0f}天"
                )

            if len(passed_products) > 5:
                alert_lines.append(f"... 还有 {len(passed_products) - 5} 个")

            alert_msg = "\n".join(alert_lines)
            alert_result = self._wechat.push(message=alert_msg)
            wp.alert_sent = alert_result.get("success", False)
            results["summary"]["alerts_sent"] += 1 if wp.alert_sent else 0

        # Step 5: Create WooCommerce listings for top products
        if create_listing:
            listing_count = 0
            for wp in passed_products:
                if listing_count >= self.config.max_listings_per_run:
                    break

                listing_result = self._wc.write(
                    product_name=wp.name,
                    price=max(19.99, wp.predicted_revenue / 30),  # 估算价格
                    stock_quantity=50,
                    product_status="draft",  # 先草稿，等人工确认
                    categories=wp.category,
                    opportunity_id=wp.opp_id,
                )

                wp.listing_created = listing_result.get("success", False)
                if wp.listing_created:
                    wp.listing_id = listing_result.get("product_id")
                    listing_count += 1
                    results["summary"]["listings_created"] += 1

        # Build product results
        for wp in products:
            results["products"].append({
                "name": wp.name,
                "category": wp.category,
                "alpha_score": wp.alpha_score,
                "alpha_pass": wp.alpha_pass,
                "net_margin_pct": wp.net_margin_pct,
                "margin_pass": wp.margin_pass,
                "roi_pct": wp.roi_pct,
                "roi_pass": wp.roi_pass,
                "payback_days": wp.payback_days,
                "payback_pass": wp.payback_pass,
                "overall_pass": wp.overall_pass,
                "alert_sent": wp.alert_sent,
                "listing_created": wp.listing_created,
                "listing_id": wp.listing_id,
            })

        return results

    def run_silent_scan(
        self,
        category: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        静默扫描：只返回通过门槛的产品，不发通知不上架。
        用于定时 cron job 快速检查。
        """
        return self.run_full_pipeline(
            category=category,
            send_alert=False,
            create_listing=False,
            limit=limit,
        )