"""
HVOS Reality → Capital 每日闭环
================================
每日 Cron Job 调用的统一入口。

执行流程：
  1. WooCommerce DB → 拉取最新订单
  2. Capital Book → 录入资金流水
  3. RFE Engine → 对比预测 vs 实际
  4. Board Report → 微信推送（如有异常）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖
from capital_book import CapitalBook, PoolType, TransactionType


def run_daily_reality_capital_cycle() -> dict:
    """
    每日 Reality → Capital 闭环主函数。
    被 Cron Job 调用。
    """
    from woo_to_capital import sync_orders_to_capital, get_recent_orders

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "woo_orders": 0,
        "woo_revenue": 0.0,
        "portfolio_summary": None,
        "roi_feedback": [],
        "alerts": [],
    }

    # Step 1: WooCommerce → Capital Book
    try:
        sync_result = sync_orders_to_capital(since_days=1)
        results["woo_orders"] = sync_result.get("orders_processed", 0)
        results["woo_revenue"] = sync_result.get("revenue", 0.0)
    except Exception as e:
        logger.error(f"WooCommerce sync failed: {e}")
        results["woo_sync_error"] = str(e)

    # Step 2: Portfolio Summary
    try:
        book = CapitalBook()
        summary = book.get_portfolio_summary()
        results["portfolio_summary"] = summary

        # 检查异常
        pools = summary.get("pools", {})
        for pool_name, pool in pools.items():
            util = pool.get("utilization_pct", 0)
            if util > 90:
                results["alerts"].append({
                    "type": "high_utilization",
                    "pool": pool_name,
                    "value": f"{util:.1f}%",
                    "message": f"{pool_name.upper()} 资金池利用率 {util:.1f}%，超过 90% 警戒线",
                })
    except Exception as e:
        logger.error(f"Portfolio summary failed: {e}")

    # Step 3: ROI 反馈分析
    try:
        book = CapitalBook()
        investments = book.get_all_investments(status="closed")
        for inv in investments:
            if inv.roi_vs_prediction is not None:
                error_pct = abs(inv.roi_vs_prediction) / abs(inv.predicted_roi or 1) * 100
                if error_pct > 20:
                    results["roi_feedback"].append({
                        "opp_id": inv.opp_id,
                        "opp_name": inv.opp_name,
                        "predicted_roi": inv.predicted_roi,
                        "actual_roi": round(inv.actual_roi, 3),
                        "error_pct": round(error_pct, 1),
                        "verdict": "偏差过大需复盘" if error_pct > 30 else "正常波动",
                    })
    except Exception as e:
        logger.error(f"ROI analysis failed: {e}")

    return results


def get_board_readable_summary() -> str:
    """生成 Board 可读的简短摘要"""
    try:
        book = CapitalBook()
        summary = book.get_portfolio_summary()
        pools = summary.get("pools", {})

        lines = [
            "📊 HVOS Reality → Capital 每日报告",
            f"时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            "",
            f"💰 资金池:",
        ]

        for pool_name in ["core", "growth", "exploration"]:
            p = pools.get(pool_name, {})
            util = p.get("utilization_pct", 0)
            lines.append(
                f"  {pool_name.upper():12s} "
                f"总 \${p.get('total', 0):>9,.0f} "
                f"可用 \${p.get('available', 0):>9,.0f} "
                f"({util:.0f}%)"
            )

        lines.extend([
            "",
            f"📈 Portfolio: 总收入 \${summary.get('total_revenue', 0):,.2f} | "
            f"净利润 \${summary.get('total_profit', 0):,.2f} | "
            f"ROI {summary.get('overall_roi', 0):.2f}x",
        ])

        return "\n".join(lines)

    except Exception as e:
        return f"❌ 获取摘要失败: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HVOS Reality → Capital 每日闭环")
    parser.add_argument("--summary", action="store_true", help="显示 Board 可读摘要")
    parser.add_argument("--status", action="store_true", help="显示 Portfolio 状态")
    parser.add_argument("--sync", action="store_true", help="执行 WooCommerce 同步")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if args.summary:
        print(get_board_readable_summary())
        return

    if args.status:
        book = CapitalBook()
        print(json.dumps(book.get_portfolio_summary(), indent=2, default=str))
        return

    if args.sync:
        result = run_daily_reality_capital_cycle()
        print(json.dumps(result, indent=2, default=str))
        return

    # 默认：完整报告
    print(get_board_readable_summary())


if __name__ == "__main__":
    main()
