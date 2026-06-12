"""
HVOS WooCommerce → Capital Book 集成
===================================
从 hiugift.com WooCommerce 数据库拉取真实订单，
自动录入 Capital Book，形成真实资金闭环。

使用方式（每日 Cron）：
  python woo_to_capital.py --sync

验收指标：
  python woo_to_capital.py --status
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce DB 配置（从 VPS 直接读取）
# ─────────────────────────────────────────────────────────────────────────────

VPS_IP = "89.117.22.200"
VPS_SSH_USER = "root"
VPS_SSH_PASS = "QQ33945551"
MYSQL_USER = "sql_hiugift_com"
MYSQL_PASS = "d441c6b635d2e8"
MYSQL_DB = "sql_hiugift_com"
TABLE_PREFIX = "wp_0dd69b_"  # WooCommerce 表前缀


# ─────────────────────────────────────────────────────────────────────────────
# SSH + MySQL 查询
# ─────────────────────────────────────────────────────────────────────────────

def ssh_query(query: str) -> list[dict]:
    """通过 SSH 连接到 VPS 执行 MySQL 查询"""
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_IP, username=VPS_SSH_USER, password=VPS_SSH_PASS, timeout=15)

    cmd = f"mysql -u {MYSQL_USER} -p'{MYSQL_PASS}' {MYSQL_DB}"
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=False)
    stdin.write(query + "\n")
    stdin.flush()
    stdin.channel.shutdown_write()
    result = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    client.close()

    if err and "ERROR" in err:
        logger.warning(f"MySQL error: {err[:200]}")

    lines = [l for l in result.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        vals = [v.strip() for v in line.split("\t")]
        rows.append(dict(zip(headers, vals)))
    return rows


def get_recent_orders(since_days: int = 7) -> list[dict]:
    """获取最近 N 天的 WooCommerce 订单"""
    now_utc = datetime.now(timezone.utc)
    since = (now_utc - timedelta(days=since_days)).strftime("%Y-%m-%d %H:%M:%S")
    query = (
        f"SELECT id, status, total_amount, currency, date_created_gmt, "
        f"billing_email, payment_method "
        f"FROM {TABLE_PREFIX}wc_orders "
        f"WHERE type='shop_order' "
        f"AND date_created_gmt >= '{since}' "
        f"ORDER BY date_created_gmt DESC"
    )
    return ssh_query(query)


def get_order_items(order_id: int) -> list[dict]:
    """获取订单产品列表（用于识别 Opportunity）"""
    query = (
        f"SELECT oi.order_item_id, oi.order_item_name, oi.order_item_type, "
        f"oim.meta_key, oim.meta_value "
        f"FROM {TABLE_PREFIX}woocommerce_order_items oi "
        f"LEFT JOIN {TABLE_PREFIX}woocommerce_order_itemmeta oim ON oi.order_item_id = oim.order_item_id "
        f"WHERE oi.order_id={order_id} "
        f"AND oi.order_item_type='line_item'"
    )
    return ssh_query(query)


def get_order_meta(order_id: int) -> dict:
    """获取订单元数据（自定义字段）"""
    items = ssh_query(
        f"SELECT meta_key, meta_value FROM {TABLE_PREFIX}wc_orders_meta WHERE order_id={order_id}"
    )
    return {item["meta_key"]: item["meta_value"] for item in items if item.get("meta_key")}


# ─────────────────────────────────────────────────────────────────────────────
# Capital Book 集成
# ─────────────────────────────────────────────────────────────────────────────

def _import_capital_book():
    """延迟导入，避免循环依赖"""
    from capital_book import CapitalBook, TransactionType
    return CapitalBook, TransactionType


def sync_orders_to_capital(since_days: int = 7) -> dict:
    """
    同步 WooCommerce 订单到 Capital Book。

    返回同步报告。
    """
    orders = get_recent_orders(since_days)
    if not orders:
        return {
            "status": "ok",
            "orders_processed": 0,
            "orders_total": 0,
            "revenue": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    CapitalBook, TransactionType = _import_capital_book()
    book = CapitalBook()

    processed = 0
    total_revenue = 0.0

    for order in orders:
        try:
            order_id = str(order.get("id", ""))
            status = order.get("status", "")
            total = float(order.get("total_amount") or 0)
            currency = order.get("currency", "USD")

            # 跳过无效状态
            if status in ("trash", "failed", "cancelled") or total <= 0:
                continue

            # 提取 Opportunity ID（元数据）
            meta = get_order_meta(int(order_id))
            opp_id = meta.get("_opp_id") or meta.get("opp_id")

            # 如果没有显式 opp_id，从产品名推断
            if not opp_id:
                items = get_order_items(int(order_id))
                product_names = [
                    i.get("order_item_name", "") for i in items
                    if i.get("order_item_type") == "line_item"
                ]
                if product_names:
                    safe_name = product_names[0].replace(" ", "_")[:30]
                    opp_id = f"woo_{safe_name}"
                else:
                    opp_id = None

            # 货币过滤（只处理 USD）
            if currency != "USD":
                logger.info(f"Skipping non-USD order {order_id}: {currency}")
                continue

            # 退款
            if status == "refunded":
                book.record_transaction(
                    tx_type=TransactionType.REFUND,
                    amount=-total,
                    source="woo",
                    opp_id=opp_id,
                    order_id=order_id,
                    description=f"WooCommerce refund: order {order_id}",
                    tags=["refund", "woo", status],
                    currency=currency,
                )
                total_revenue -= total
                processed += 1
                continue

            # 正常收入
            book.record_transaction(
                tx_type=TransactionType.REVENUE,
                amount=total,
                source="woo",
                opp_id=opp_id,
                order_id=order_id,
                description=f"WooCommerce {status}: order {order_id}",
                tags=["revenue", "woo", status],
                currency=currency,
            )
            total_revenue += total
            processed += 1

            logger.info(
                f"Order {order_id} ({status}): ${total:.2f} | opp={opp_id or 'unknown'}"
            )

        except Exception as e:
            logger.error(f"Failed to process order {order.get('id')}: {e}")

    return {
        "status": "ok",
        "orders_processed": processed,
        "orders_total": len(orders),
        "revenue": round(total_revenue, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="WooCommerce → Capital Book Sync")
    parser.add_argument("--sync", action="store_true", help="Sync recent orders to Capital Book")
    parser.add_argument("--status", action="store_true", help="Show current capital status")
    parser.add_argument("--since", type=int, default=7, help="Days to look back (default: 7)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if args.status:
        CapitalBook, _ = _import_capital_book()
        book = CapitalBook()
        summary = book.get_portfolio_summary()
        print(json.dumps(summary, indent=2, default=str))
        return

    if args.sync:
        result = sync_orders_to_capital(since_days=args.since)
        print(json.dumps(result, indent=2, default=str))
        if result["orders_processed"] > 0:
            print(f"\n✅ Processed {result['orders_processed']} orders, ${result['revenue']:.2f} revenue")


if __name__ == "__main__":
    main()
