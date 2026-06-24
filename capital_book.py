"""
HVOS Capital Book — 资金账本
============================
最小赚钱闭环的核心组件。

追踪：
- 资金池（Core/Growth/Exploration）
- 每笔投资（投入 / 收入 / 利润）
- 预测 ROI vs 实际 ROI 闭环

Stage 1 MVP：
  Opportunity → Reality (真实订单) → Capital Book → ROI 对比

Author: HVOS X Capital Layer
Version: 1.0.0
"""

from __future__ import annotations

import json
import sqlite3
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 数据路径
# ─────────────────────────────────────────────────────────────────────────────

_HVOS_ROOT = __file__.rsplit("/", 1)[0] if "/" in __file__ else __file__.rsplit("\\", 1)[0]
CAPITAL_DB = f"{_HVOS_ROOT}/capital_book.db"

# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

class PoolType(Enum):
    """资金池类型

    资金分配策略（Stage 1.5）：
    - Core (70%): 主要投资于已验证的机会
    - Growth (20%): 成长型投资，用于扩大成功项目
    - Exploration (10%): 探索新机会/新品类
    - Reserve (自动): 应急储备金，默认10%，低于5%触发警报
    """
    CORE = "core"           # 核心仓位
    GROWTH = "growth"       # 成长仓位
    EXPLORATION = "exploration"  # 探索仓位
    RESERVE = "reserve"     # 储备金（自动计算，不手动分配）


class TransactionType(Enum):
    """资金流水类型"""
    INVESTMENT = "investment"     # 投入（购买/广告费/采购）
    REVENUE = "revenue"          # 收入（订单收入）
    REFUND = "refund"            # 退款
    COST = "cost"                # 运营成本
    RESERVE = "reserve"          # 预留
    ALLOCATION = "allocation"     # 资金调配


@dataclass
class CapitalPool:
    """资金池"""
    pool_type: PoolType
    total_capital: float = 0.0       # 总资金
    allocated: float = 0.0            # 已投出
    available: float = 0.0           # 可用
    reserved: float = 0.0           # 预留

    @property
    def utilization_pct(self) -> float:
        return (self.allocated / self.total_capital * 100) if self.total_capital > 0 else 0.0


@dataclass
class Transaction:
    """资金流水"""
    tx_id: str = field(default_factory=lambda: f"tx_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tx_type: TransactionType = TransactionType.ALLOCATION

    # 资金关联
    opp_id: Optional[str] = None      # 关联机会 ID
    pool_type: PoolType = PoolType.CORE

    # 金额
    amount: float = 0.0               # 正=收入, 负=支出
    currency: str = "USD"

    # 来源
    source: str = "woo"              # woo/meta/tiktok/manual
    order_id: Optional[str] = None     # WooCommerce 订单 ID

    # 元数据
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tx_type"] = self.tx_type.value
        d["pool_type"] = self.pool_type.value
        return d


@dataclass
class Investment:
    """投资记录 — 针对单个机会"""
    inv_id: str = field(default_factory=lambda: f"inv_{uuid.uuid4().hex[:12]}")
    opp_id: str = ""
    opp_name: str = ""

    # 资金池
    pool_type: PoolType = PoolType.CORE

    # 投资金额
    invested_amount: float = 0.0      # 总投入
    currency: str = "USD"

    # 预测（来自 RFE）
    predicted_roi: Optional[float] = None
    predicted_revenue: Optional[float] = None
    prediction_id: Optional[str] = None  # RFE prediction ID

    # 实际（来自 WooCommerce）
    actual_revenue: float = 0.0
    actual_cost: float = 0.0

    # 时间
    invested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    closed_at: Optional[str] = None

    # 状态
    status: Literal["active", "closed", "written_off"] = "active"

    @property
    def actual_roi(self) -> float:
        if self.actual_cost == 0:
            return 0.0
        return (self.actual_revenue - self.actual_cost) / self.actual_cost

    @property
    def profit(self) -> float:
        return self.actual_revenue - self.actual_cost

    @property
    def roi_vs_prediction(self) -> Optional[float]:
        if self.predicted_roi and self.predicted_roi != 0:
            return self.actual_roi - self.predicted_roi
        return None

    @property
    def is_profitable(self) -> bool:
        return self.profit > 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pool_type"] = self.pool_type.value
        d["actual_roi"] = round(self.actual_roi, 4)
        d["profit"] = round(self.profit, 2)
        d["roi_vs_prediction"] = round(self.roi_vs_prediction, 4) if self.roi_vs_prediction else None
        return d


# ─────────────────────────────────────────────────────────────────────────────
# CapitalBook — 主入口
# ─────────────────────────────────────────────────────────────────────────────

class CapitalBook:
    """
    资金账本主类

    核心职责：
    1. 管理三个资金池（Core/Growth/Exploration）
    2. 记录每笔资金流水
    3. 管理每个 Opportunity 的投资组合
    4. 计算预测 ROI vs 实际 ROI
    5. 与 RFE Engine 联动

    Stage 1 MVP 与 WooCommerce 直连，
    自动录入真实订单 → 资金流水 → ROI 计算
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CAPITAL_DB
        self._init_db()

    # ─────────────────────────────────────────────────────────────────────
    # 数据库初始化
    # ─────────────────────────────────────────────────────────────────────

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # 资金池快照
        c.execute("""
            CREATE TABLE IF NOT EXISTS capital_pools (
                pool_type TEXT PRIMARY KEY,
                total_capital REAL DEFAULT 0,
                allocated REAL DEFAULT 0,
                available REAL DEFAULT 0,
                reserved REAL DEFAULT 0,
                updated_at TEXT
            )
        """)

        # 资金流水
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                tx_id TEXT PRIMARY KEY,
                timestamp TEXT,
                tx_type TEXT,
                opp_id TEXT,
                pool_type TEXT,
                amount REAL,
                currency TEXT DEFAULT 'USD',
                source TEXT,
                order_id TEXT,
                description TEXT,
                tags TEXT,
                created_at TEXT
            )
        """)

        # 投资组合（每个 Opportunity 一条记录）
        c.execute("""
            CREATE TABLE IF NOT EXISTS investments (
                inv_id TEXT PRIMARY KEY,
                opp_id TEXT UNIQUE,
                opp_name TEXT,
                pool_type TEXT,
                invested_amount REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                predicted_roi REAL,
                predicted_revenue REAL,
                prediction_id TEXT,
                actual_revenue REAL DEFAULT 0,
                actual_cost REAL DEFAULT 0,
                invested_at TEXT,
                closed_at TEXT,
                status TEXT DEFAULT 'active'
            )
        """)

        # 预测 vs 实际 ROI 记录
        c.execute("""
            CREATE TABLE IF NOT EXISTS roi_records (
                roi_id TEXT PRIMARY KEY,
                inv_id TEXT,
                opp_id TEXT,
                predicted_roi REAL,
                actual_roi REAL,
                error_rate REAL,
                error_direction TEXT,
                verdict TEXT,
                recorded_at TEXT,
                FOREIGN KEY (inv_id) REFERENCES investments(inv_id)
            )
        """)

        # 初始化四个资金池
        for pool in PoolType:
            c.execute("""
                INSERT OR IGNORE INTO capital_pools (pool_type, total_capital, allocated, available, reserved, updated_at)
                VALUES (?, 0, 0, 0, 0, ?)
            """, (pool.value, datetime.now(timezone.utc).isoformat()))

        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────────────────────────────
    # 资金池管理
    # ─────────────────────────────────────────────────────────────────────

    def set_total_capital(self, total: float, pool: PoolType = PoolType.CORE):
        """设置资金池总规模（初始资金）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            UPDATE capital_pools
            SET total_capital = ?,
                available = ? - allocated,
                updated_at = ?
            WHERE pool_type = ?
        """, (total, total, datetime.now(timezone.utc).isoformat(), pool.value))
        conn.commit()
        conn.close()

    def allocate_to_pool(self, pool: PoolType, amount: float, source_pool: PoolType = PoolType.CORE):
        """资金池间调配"""
        if pool == source_pool:
            return
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()

        # 从源池减少
        c.execute("""
            UPDATE capital_pools SET allocated = allocated - ?, available = available + ?, updated_at = ?
            WHERE pool_type = ?
        """, (amount, amount, now, source_pool.value))

        # 到目标池增加
        c.execute("""
            UPDATE capital_pools SET allocated = allocated + ?, available = available - ?, updated_at = ?
            WHERE pool_type = ?
        """, (amount, amount, now, pool.value))

        conn.commit()
        conn.close()

    def get_pool(self, pool: PoolType) -> CapitalPool:
        """获取资金池状态"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM capital_pools WHERE pool_type = ?", (pool.value,))
        row = c.fetchone()
        conn.close()
        if not row:
            return CapitalPool(pool_type=pool)
        return CapitalPool(
            pool_type=PoolType(row[0]),
            total_capital=row[1],
            allocated=row[2],
            available=row[3],
            reserved=row[4],
        )

    def get_all_pools(self) -> dict[PoolType, CapitalPool]:
        return {p: self.get_pool(p) for p in PoolType}

    # ─────────────────────────────────────────────────────────────────────
    # 资金流水
    # ─────────────────────────────────────────────────────────────────────

    def record_transaction(
        self,
        tx_type: TransactionType,
        amount: float,
        source: str = "woo",
        opp_id: Optional[str] = None,
        pool: PoolType = PoolType.CORE,
        order_id: Optional[str] = None,
        description: str = "",
        tags: Optional[list[str]] = None,
        currency: str = "USD",
    ) -> Transaction:
        """记录一笔资金流水"""
        tx = Transaction(
            tx_type=tx_type,
            amount=amount,
            source=source,
            opp_id=opp_id,
            pool_type=pool,
            order_id=order_id,
            description=description,
            tags=tags or [],
        )

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO transactions
            (tx_id, timestamp, tx_type, opp_id, pool_type, amount, currency, source, order_id, description, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx.tx_id,
            tx.timestamp,
            tx.tx_type.value,
            tx.opp_id,
            tx.pool_type.value,
            tx.amount,
            tx.currency,
            tx.source,
            tx.order_id,
            tx.description,
            json.dumps(tx.tags),
            tx.timestamp,
        ))

        # 更新资金池
        if tx_type == TransactionType.REVENUE:
            # 收入：增加 available，并更新对应投资的实际收入
            c.execute("""
                UPDATE capital_pools SET available = available + ?, updated_at = ?
                WHERE pool_type = ?
            """, (amount, datetime.now(timezone.utc).isoformat(), pool.value))
            # 自动更新对应投资的 actual_revenue
            if opp_id:
                c.execute("""
                    UPDATE investments SET actual_revenue = actual_revenue + ?
                    WHERE opp_id=? AND status='active'
                """, (amount, opp_id))

        elif tx_type in (TransactionType.INVESTMENT, TransactionType.COST):
            # 支出：减少 available，增加 allocated
            c.execute("""
                UPDATE capital_pools SET available = available + ?, allocated = allocated + ?, updated_at = ?
                WHERE pool_type = ?
            """, (-amount, amount, datetime.now(timezone.utc).isoformat(), pool.value))

        conn.commit()
        conn.close()
        return tx

    def get_transactions(self, opp_id: Optional[str] = None, limit: int = 100) -> list[Transaction]:
        """查询资金流水"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if opp_id:
            c.execute("""
                SELECT * FROM transactions WHERE opp_id=? ORDER BY timestamp DESC LIMIT ?
            """, (opp_id, limit))
        else:
            c.execute("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return [self._row_to_tx(r) for r in rows]

    def _row_to_tx(self, row) -> Transaction:
        return Transaction(
            tx_id=row[0], timestamp=row[1],
            tx_type=TransactionType(row[2]),
            opp_id=row[3], pool_type=PoolType(row[4]),
            amount=row[5], currency=row[6],
            source=row[7], order_id=row[8],
            description=row[9], tags=json.loads(row[10]) if row[10] else [],
        )

    # ─────────────────────────────────────────────────────────────────────
    # 投资组合管理
    # ─────────────────────────────────────────────────────────────────────

    def create_investment(
        self,
        opp_id: str,
        opp_name: str,
        amount: float,
        pool: PoolType = PoolType.CORE,
        predicted_roi: Optional[float] = None,
        predicted_revenue: Optional[float] = None,
        prediction_id: Optional[str] = None,
        currency: str = "USD",
    ) -> Investment:
        """创建一个投资记录"""
        inv = Investment(
            opp_id=opp_id,
            opp_name=opp_name,
            invested_amount=amount,
            pool_type=pool,
            predicted_roi=predicted_roi,
            predicted_revenue=predicted_revenue,
            prediction_id=prediction_id,
            currency=currency,
        )

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO investments
            (inv_id, opp_id, opp_name, pool_type, invested_amount, currency,
             predicted_roi, predicted_revenue, prediction_id, actual_revenue, actual_cost,
             invested_at, closed_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, 'active')
        """, (
            inv.inv_id, inv.opp_id, inv.opp_name, pool.value, amount, currency,
            predicted_roi, predicted_revenue, prediction_id,
            amount,  # actual_cost starts = invested
            datetime.now(timezone.utc).isoformat(),
        ))

        # 更新资金池
        c.execute("""
            UPDATE capital_pools
            SET allocated = allocated + ?, available = available - ?, updated_at = ?
            WHERE pool_type = ?
        """, (amount, amount, datetime.now(timezone.utc).isoformat(), pool.value))

        # 记录资金流水
        c.execute("""
            INSERT INTO transactions
            (tx_id, timestamp, tx_type, opp_id, pool_type, amount, currency, source, order_id, description, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"tx_inv_{inv.inv_id}",
            datetime.now(timezone.utc).isoformat(),
            TransactionType.INVESTMENT.value,
            opp_id, pool.value, -amount, currency,
            "capital_book",
            None,
            f"Invest in {opp_name}",
            json.dumps(["investment", opp_id]),
            datetime.now(timezone.utc).isoformat(),
        ))

        conn.commit()
        conn.close()
        return inv

    def update_investment_revenue(
        self,
        opp_id: str,
        revenue: float,
        cost: Optional[float] = None,
    ) -> Optional[Investment]:
        """更新投资实际收入（被 WooCommerce 订单调用）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM investments WHERE opp_id=? AND status='active'", (opp_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return None

        new_revenue = row[9] + revenue  # actual_revenue column
        new_cost = cost if cost is not None else row[10]  # actual_cost column

        c.execute("""
            UPDATE investments SET actual_revenue=?, actual_cost=? WHERE opp_id=?
        """, (new_revenue, new_cost, opp_id))

        inv = self.get_investment(opp_id)
        conn.commit()
        conn.close()
        return inv

    def close_investment(self, opp_id: str) -> Optional[Investment]:
        """关闭投资，计算 ROI"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM investments WHERE opp_id=?", (opp_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return None

        inv = self.get_investment(opp_id)
        actual_roi = inv.actual_roi
        roi_error = None
        verdict = ""

        if inv.predicted_roi is not None and inv.predicted_roi != 0:
            roi_error = abs(actual_roi - inv.predicted_roi) / abs(inv.predicted_roi) * 100
            verdict = "高精准" if roi_error < 10 else "可接受" if roi_error < 30 else "严重偏差"

        # 记录 ROI
        if roi_error is not None:
            roi_id = f"roi_{uuid.uuid4().hex[:12]}"
            c.execute("""
                INSERT INTO roi_records
                (roi_id, inv_id, opp_id, predicted_roi, actual_roi, error_rate, error_direction, verdict, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                roi_id, inv.inv_id, opp_id,
                inv.predicted_roi, actual_roi,
                roi_error,
                "over" if actual_roi > (inv.predicted_roi or 0) else "under",
                verdict,
                datetime.now(timezone.utc).isoformat(),
            ))

        # 更新状态
        c.execute("""
            UPDATE investments SET status='closed', closed_at=? WHERE opp_id=?
        """, (datetime.now(timezone.utc).isoformat(), opp_id))

        # 回收资金到 available
        c.execute("""
            UPDATE capital_pools
            SET allocated = allocated - ?, available = available + ?, updated_at = ?
            WHERE pool_type = ?
        """, (inv.invested_amount, inv.invested_amount,
              datetime.now(timezone.utc).isoformat(), inv.pool_type.value))

        conn.commit()
        conn.close()
        return inv

    def get_investment(self, opp_id: str) -> Optional[Investment]:
        """获取投资记录"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT * FROM investments WHERE opp_id=?", (opp_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_inv(row)

    def get_all_investments(self, status: Optional[str] = None) -> list[Investment]:
        """获取所有投资"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if status:
            c.execute("SELECT * FROM investments WHERE status=?", (status,))
        else:
            c.execute("SELECT * FROM investments ORDER BY invested_at DESC")
        rows = c.fetchall()
        conn.close()
        return [self._row_to_inv(r) for r in rows]

    def _row_to_inv(self, row) -> Investment:
        return Investment(
            inv_id=row[0], opp_id=row[1], opp_name=row[2],
            pool_type=PoolType(row[3]),
            invested_amount=row[4], currency=row[5],
            predicted_roi=row[6], predicted_revenue=row[7], prediction_id=row[8],
            actual_revenue=row[9], actual_cost=row[10],
            invested_at=row[11], closed_at=row[12],
            status=row[13],
        )

    # ─────────────────────────────────────────────────────────────────────
    # ROI 报表
    # ─────────────────────────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """生成 Portfolio 汇总报表"""
        investments = self.get_all_investments()
        active = [i for i in investments if i.status == "active"]
        closed = [i for i in investments if i.status == "closed"]

        total_invested = sum(i.invested_amount for i in investments)
        total_revenue = sum(i.actual_revenue for i in investments)
        total_cost = sum(i.actual_cost for i in investments)
        total_profit = total_revenue - total_cost
        overall_roi = (total_profit / total_cost) if total_cost > 0 else 0.0

        pools = self.get_all_pools()
        total_capital = sum(p.total_capital for p in pools.values())

        # ROI 偏差分析
        roi_errors = []
        for i in closed:
            if i.roi_vs_prediction is not None:
                roi_errors.append(i.roi_vs_prediction)

        avg_roi_error = sum(roi_errors) / len(roi_errors) if roi_errors else None

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_capital": round(total_capital, 2),
            "total_invested": round(total_invested, 2),
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "overall_roi": round(overall_roi, 4),
            "active_investments": len(active),
            "closed_investments": len(closed),
            "avg_roi_error_pct": round(avg_roi_error, 2) if avg_roi_error else None,
            "pools": {
                pt.value: {
                    "total": round(cap.total_capital, 2),
                    "allocated": round(cap.allocated, 2),
                    "available": round(cap.available, 2),
                    "utilization_pct": round(cap.utilization_pct, 1),
                }
                for pt, cap in pools.items()
            },
        }

    def get_investor_report(self, opp_id: str) -> dict:
        """生成单个 Opportunity 的投资报告"""
        inv = self.get_investment(opp_id)
        if not inv:
            return {"error": f"Investment for {opp_id} not found"}

        txs = self.get_transactions(opp_id=opp_id)
        roi_record = None
        if inv.status == "closed":
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM roi_records WHERE opp_id=? ORDER BY recorded_at DESC LIMIT 1", (opp_id,))
            row = c.fetchone()
            conn.close()
            if row:
                roi_record = {
                    "predicted_roi": row[3], "actual_roi": row[4],
                    "error_rate": row[5], "verdict": row[7],
                }

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "investment": inv.to_dict(),
            "transactions": [tx.to_dict() for tx in txs],
            "roi_record": roi_record,
        }

    # ─────────────────────────────────────────────────────────────────────
    # WooCommerce 集成 — 核心闭环
    # ─────────────────────────────────────────────────────────────────────

    def process_woo_order(self, order: dict) -> Optional[Transaction]:
        """
        处理一个 WooCommerce 订单，自动识别对应 Opportunity 并更新收入。

        Args:
            order: WooCommerce 订单字典，包含 id, total, status, date_created 等字段

        Returns:
            录入的资金流水，如果没有匹配的 Opportunity 则返回 None
        """
        order_id = str(order.get("id", ""))
        total = float(order.get("total", 0))
        currency = order.get("currency", "USD")
        status = order.get("status", "")
        date_created = order.get("date_created", "")

        # 过滤无效状态
        if status in ("trash", "failed", "cancelled"):
            return None

        # 退款处理
        if status == "refunded":
            tx = self.record_transaction(
                tx_type=TransactionType.REFUND,
                amount=-total,
                source="woo",
                order_id=order_id,
                description=f"WooCommerce refund: order {order_id}",
                tags=["refund", "woo"],
                currency=currency,
            )
            return tx

        # 尝试从订单元数据找 opp_id
        meta_data = order.get("meta_data", []) or []
        opp_id = None
        for meta in meta_data:
            if meta.get("key") == "_opp_id":
                opp_id = meta.get("value")
                break

        # 如果没有 opp_id，尝试从产品名推断
        if not opp_id:
            line_items = order.get("line_items", []) or []
            if line_items:
                # 查找第一个产品的 SKU 作为 opp_id 前缀
                sku = line_items[0].get("sku", "")
                if sku:
                    opp_id = f"woo_{sku}"

        # 找到对应投资，更新收入
        if opp_id:
            self.update_investment_revenue(opp_id, total)

        # 记录资金流水
        tx = self.record_transaction(
            tx_type=TransactionType.REVENUE,
            amount=total,
            source="woo",
            opp_id=opp_id,
            order_id=order_id,
            description=f"WooCommerce order: {order_id} ({status})",
            tags=["revenue", "woo", status],
            currency=currency,
        )
        return tx

    # ─────────────────────────────────────────────────────────────────────
    # Stage 1.5: 自动调仓引擎
    # ─────────────────────────────────────────────────────────────────────

    def compute_reserve(self, total_capital: float, reserve_pct: float = 0.10) -> float:
        """
        计算储备金（自动，不手动分配）

        储备金 = 总资金 × 储备比例
        用于应对突发风险（如物流延误、竞品价格战、退款潮）
        """
        return total_capital * reserve_pct

    def check_pool_health(self) -> dict:
        """
        检查所有资金池健康度

        返回：
        {
            "total_capital": float,
            "reserve": {"allocated": float, "healthy": bool},
            "core": {"allocated_pct": float, "healthy": bool, "alert": str},
            "growth": {"allocated_pct": float, "healthy": bool, "alert": str},
            "exploration": {"allocated_pct": float, "healthy": bool, "alert": str},
            "rebalance_needed": bool,
            "rebalance_suggestions": list[str],
        }
        """
        pools = self.get_all_pools()
        total = sum(p.total_capital for p in pools.values())
        reserve = pools.get(PoolType.RESERVE, CapitalPool(PoolType.RESERVE))

        # 储备金健康度：储备金应该 >= 总资金的 5%
        reserve_min = total * 0.05
        reserve_healthy = reserve.total_capital >= reserve_min

        result = {
            "total_capital": round(total, 2),
            "reserve": {
                "amount": round(reserve.total_capital, 2),
                "pct_of_total": round(reserve.total_capital / total * 100, 1) if total > 0 else 0,
                "healthy": reserve_healthy,
                "alert": "⚠️ 储备金低于 5%" if not reserve_healthy else "✅",
            },
            "rebalance_needed": False,
            "rebalance_suggestions": [],
        }

        # 各仓位健康度
        target_allocations = {
            PoolType.CORE: 0.70,
            PoolType.GROWTH: 0.20,
            PoolType.EXPLORATION: 0.10,
        }

        for pool_type, target_pct in target_allocations.items():
            pool = pools.get(pool_type, CapitalPool(pool_type))
            if total == 0:
                continue

            actual_pct = pool.allocated / total
            deviation = abs(actual_pct - target_pct)

            # 偏离超过 10% 需要调仓
            healthy = deviation <= 0.10
            alert = ""
            if deviation > 0.15:
                alert = f"❌ 偏离 {deviation*100:.0f}%，建议调仓"
                result["rebalance_needed"] = True
            elif deviation > 0.10:
                alert = f"⚠️ 偏离 {deviation*100:.0f}%，观察中"
                result["rebalance_needed"] = True
            else:
                alert = "✅ 健康"

            result[pool_type.value] = {
                "allocated": round(pool.allocated, 2),
                "actual_pct": round(actual_pct * 100, 1),
                "target_pct": round(target_pct * 100, 1),
                "deviation_pct": round(deviation * 100, 1),
                "healthy": healthy,
                "alert": alert,
            }

            if deviation > 0.10:
                direction = "减持" if actual_pct > target_pct else "增持"
                result["rebalance_suggestions"].append(
                    f"{pool_type.value.upper()}: {direction} "
                    f"${abs(pool.allocated - total * target_pct):,.0f}"
                )

        return result

    def auto_rebalance(self, dry_run: bool = True) -> dict:
        """
        自动调仓（将偏离的资金池恢复到目标比例）

        Args:
            dry_run: True=只报告不执行，False=执行调仓

        调仓策略：
        - Core 偏离 > 10%：卖出/买入到 70%
        - Growth 偏离 > 10%：卖出/买入到 20%
        - Exploration 偏离 > 10%：卖出/买入到 10%
        """
        health = self.check_pool_health()
        if not health["rebalance_needed"]:
            return {"action": "none", "reason": "all pools within tolerance"}

        total = health["total_capital"]
        if total <= 0:
            return {"action": "none", "reason": "no capital"}

        rebalances = []
        executed = []

        for pool_type in [PoolType.CORE, PoolType.GROWTH, PoolType.EXPLORATION]:
            pool_data = health.get(pool_type.value, {})
            if not pool_data:
                continue

            actual_pct = pool_data["actual_pct"] / 100
            target_pct = pool_data["target_pct"] / 100
            deviation = abs(actual_pct - target_pct)

            if deviation <= 0.10:
                continue

            target_amount = total * target_pct
            current_amount = pool_data["allocated"]
            diff = target_amount - current_amount

            rebalances.append({
                "pool": pool_type.value,
                "current": round(current_amount, 2),
                "target": round(target_amount, 2),
                "diff": round(diff, 2),
                "direction": "add" if diff > 0 else "reduce",
            })

            if not dry_run and abs(diff) > 1:  # 只调仓差异 > $1
                self.allocate_to_pool(
                    pool_type,
                    abs(diff),
                    source_pool=(
                        PoolType.CORE if pool_type != PoolType.CORE and diff > 0
                        else PoolType.EXPLORATION if pool_type == PoolType.CORE and diff < 0
                        else PoolType.CORE
                    ),
                )
                executed.append(pool_type.value)

        return {
            "action": "executed" if not dry_run else "planned",
            "total_capital": health["total_capital"],
            "rebalances": rebalances,
            "executed": executed,
            "warnings": health["rebalance_suggestions"],
        }

    def set_initial_capital(self, total: float, strategy: str = "standard") -> dict:
        """
        初始化总资金，自动分配到各仓位

        Args:
            total: 总资金
            strategy: 分配策略
                - standard: 70/20/10 + 10% Reserve
                - conservative: 60/25/15 (无 Reserve)
                - aggressive: 80/15/5 + 10% Reserve
        """
        strategies = {
            "standard": {"core": 0.70, "growth": 0.20, "exploration": 0.10},
            "conservative": {"core": 0.60, "growth": 0.25, "exploration": 0.15},
            "aggressive": {"core": 0.80, "growth": 0.15, "exploration": 0.05},
        }

        alloc = strategies.get(strategy, strategies["standard"])

        self.set_total_capital(total * alloc["core"], PoolType.CORE)
        self.set_total_capital(total * alloc["growth"], PoolType.GROWTH)
        self.set_total_capital(total * alloc["exploration"], PoolType.EXPLORATION)
        # Reserve 10% 自动从 Core 预留
        reserve_amount = total * 0.10
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            UPDATE capital_pools
            SET total_capital = total_capital - ?,
                reserved = ?,
                available = available - ?,
                updated_at = ?
            WHERE pool_type = ?
        """, (reserve_amount, reserve_amount, reserve_amount,
              datetime.now(timezone.utc).isoformat(), PoolType.CORE.value))
        conn.commit()
        conn.close()

        return {
            "strategy": strategy,
            "total": total,
            "allocated": {
                "core": round(total * alloc["core"] - reserve_amount, 2),
                "growth": round(total * alloc["growth"], 2),
                "exploration": round(total * alloc["exploration"], 2),
                "reserve": round(reserve_amount, 2),
            }
        }


# ─────────────────────────────────────────────────────────────────────────────
# Capital Allocator — 资金分配决策引擎（Stage 1.5）
# ─────────────────────────────────────────────────────────────────────────────

class CapitalAllocator:
    """
    资金分配决策引擎

    核心问题：为什么投A不投B？

    决策逻辑：
    1. 计算每个 Opportunity 的 Score = f(ROI预测, 风险, 战略契合度)
    2. Score 最高的优先获得 Core 资金
    3. Growth/Exploration 用于高风险高回报机会
    """

    def __init__(self, capital_book: Optional[CapitalBook] = None):
        self.capital_book = capital_book or CapitalBook()

    def score_opportunity(
        self,
        opp_id: str,
        predicted_roi: float,
        risk_score: float = 0.5,      # 0-1, 越高风险越高
        strategic_fit: float = 0.5,   # 0-1, 越高战略契合度越高
    ) -> dict:
        """
        计算 Opportunity 的投资评分

        Score = (ROI × Strategic Fit) / (Risk ^ 0.5)

        Returns:
            {
                "score": float,
                "recommended_pool": "core" | "growth" | "exploration",
                "max_investment": float,
                "reason": str,
            }
        """
        import math

        # 风险调整后的 ROI
        risk_adjusted_roi = predicted_roi / math.sqrt(risk_score + 0.1)

        # 综合评分（0-100）
        score = risk_adjusted_roi * strategic_fit * 100

        # 推荐资金池
        if strategic_fit >= 0.7 and risk_score <= 0.3:
            pool = PoolType.CORE
            reason = "高战略契合 + 低风险 → Core"
        elif strategic_fit >= 0.5 or risk_score <= 0.5:
            pool = PoolType.GROWTH
            reason = "中等战略/风险 → Growth"
        else:
            pool = PoolType.EXPLORATION
            reason = "高风险/新领域 → Exploration"

        # 最大投资额 = 池子可用资金的 50%
        pool_data = self.capital_book.get_pool(pool)
        max_investment = pool_data.available * 0.5 if pool_data.available > 0 else 0

        return {
            "opp_id": opp_id,
            "score": round(score, 2),
            "predicted_roi": predicted_roi,
            "risk_score": risk_score,
            "strategic_fit": strategic_fit,
            "recommended_pool": pool.value,
            "max_investment": round(max_investment, 2),
            "reason": reason,
        }

    def recommend_allocation(self, opportunities: list[dict]) -> list[dict]:
        """
        给定一组 Opportunities，推荐资金分配方案

        Args:
            opportunities: [
                {
                    "opp_id": str,
                    "predicted_roi": float,
                    "risk_score": float,
                    "strategic_fit": float,
                    "requested_amount": float,
                }
            ]

        Returns:
            list[dict]: 每个 Opportunity 的分配建议
        """
        # 按评分排序
        scored = [
            self.score_opportunity(
                o["opp_id"],
                o["predicted_roi"],
                o.get("risk_score", 0.5),
                o.get("strategic_fit", 0.5),
            )
            for o in opportunities
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)

        # 分配资金
        allocations = []
        for s in scored:
            s["allocated_amount"] = min(
                s["max_investment"],
                next((o["requested_amount"] for o in opportunities if o["opp_id"] == s["opp_id"]), 0),
            )
            s["fully_funded"] = s["allocated_amount"] >= next(
                (o["requested_amount"] for o in opportunities if o["opp_id"] == s["opp_id"]), 0
            )
            allocations.append(s)

        return allocations


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="HVOS Capital Book")
    parser.add_argument("--action", required=True,
                        choices=["init", "summary", "invest", "revenue", "pools", "report"])
    parser.add_argument("--opp-id", help="Opportunity ID")
    parser.add_argument("--opp-name", help="Opportunity name")
    parser.add_argument("--amount", type=float, help="Amount in USD")
    parser.add_argument("--predicted-roi", type=float, help="Predicted ROI")
    parser.add_argument("--pool", default="core", choices=["core", "growth", "exploration"])
    args = parser.parse_args()

    book = CapitalBook()

    if args.action == "init":
        total = args.amount or 100000
        book.set_total_capital(total * 0.7, PoolType.CORE)
        book.set_total_capital(total * 0.2, PoolType.GROWTH)
        book.set_total_capital(total * 0.1, PoolType.EXPLORATION)
        print(f"✅ Capital Book initialized with ${total:,}")
        print(f"   Core: ${total*0.7:,.0f} | Growth: ${total*0.2:,.0f} | Exploration: ${total*0.1:,.0f}")

    elif args.action == "pools":
        pools = book.get_all_pools()
        for p in PoolType:
            pool = pools[p]
            print(f"\n{p.value.upper()} Pool:")
            print(f"  Total: ${pool.total_capital:,.2f}")
            print(f"  Allocated: ${pool.allocated:,.2f} ({pool.utilization_pct:.1f}%)")
            print(f"  Available: ${pool.available:,.2f}")

    elif args.action == "summary":
        summary = book.get_portfolio_summary()
        print(json.dumps(summary, indent=2, default=str))

    elif args.action == "invest":
        if not args.opp_id or not args.amount:
            print("ERROR: --opp-id and --amount required")
            return
        inv = book.create_investment(
            args.opp_id, args.opp_name or args.opp_id,
            args.amount, PoolType(args.pool),
            predicted_roi=args.predicted_roi,
        )
        print(f"✅ Investment created: {inv.inv_id}")
        print(f"   Opp: {inv.opp_name} | Amount: ${inv.invested_amount:,.2f}")
        print(f"   Predicted ROI: {inv.predicted_roi}")

    elif args.action == "revenue":
        if not args.opp_id or not args.amount:
            print("ERROR: --opp-id and --amount required")
            return
        tx = book.record_transaction(
            TransactionType.REVENUE, args.amount,
            source="woo", opp_id=args.opp_id,
            description=f"Revenue for {args.opp_id}",
        )
        print(f"✅ Revenue recorded: {tx.tx_id} | ${tx.amount:,.2f}")

    elif args.action == "report":
        if not args.opp_id:
            print("ERROR: --opp-id required")
            return
        report = book.get_investor_report(args.opp_id)
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────────────────────────────────────
# HVOS Pricing Engine — 精确定价 × 中国电商平台扣点
# 来源: solo-ecom-pilot (CC-BY), 整合自一人电商运营助手
# 6 大平台 × 7 大类目 = 30+ 条精确扣点数据
# ─────────────────────────────────────────────────────────────────────────────

from enum import Enum


class EcommPlatform(Enum):
    """中国电商平台枚举"""
    TAOBAO = "淘宝"
    TMALL = "天猫"
    DOUYIN = "抖音"
    XIAOHONGSHU = "小红书"
    PDD = "拼多多"
    JD = "京东"
    AMAZON_US = "Amazon US"
    SHOPIFY = "Shopify"


# 平台默认扣点（无类目信息时使用）
PLATFORM_RATES = {
    EcommPlatform.TAOBAO:      {"min": 0.005, "max": 0.01,  "default": 0.008},
    EcommPlatform.TMALL:        {"min": 0.02,  "max": 0.05,  "default": 0.04},
    EcommPlatform.PDD:          {"min": 0.006, "max": 0.03,  "default": 0.015},
    EcommPlatform.DOUYIN:       {"min": 0.02,  "max": 0.10,  "default": 0.05},
    EcommPlatform.XIAOHONGSHU:  {"min": 0.05,  "max": 0.20,  "default": 0.10},
    EcommPlatform.JD:           {"min": 0.03,  "max": 0.08,  "default": 0.05},
    EcommPlatform.AMAZON_US:    {"min": 0.06,  "max": 0.17,  "default": 0.15},
    EcommPlatform.SHOPIFY:      {"min": 0.0,   "max": 0.0,   "default": 0.0},
}

# 类目级精确扣点表（平台 × 类目）
CATEGORY_COMMISSIONS = {
    # 淘宝（个人店多数类目 0.5%-1%）
    (EcommPlatform.TAOBAO, "服装鞋包"): 0.005,
    (EcommPlatform.TAOBAO, "3C数码"):   0.005,
    (EcommPlatform.TAOBAO, "家居日用"): 0.005,
    (EcommPlatform.TAOBAO, "美妆个护"): 0.008,
    (EcommPlatform.TAOBAO, "食品饮料"): 0.005,
    (EcommPlatform.TAOBAO, "母婴玩具"): 0.005,
    (EcommPlatform.TAOBAO, "珠宝首饰"): 0.008,
    (EcommPlatform.TAOBAO, "礼品盒"):   0.006,
    # 天猫
    (EcommPlatform.TMALL, "服装鞋包"): 0.05,
    (EcommPlatform.TMALL, "3C数码"):   0.03,
    (EcommPlatform.TMALL, "美妆个护"): 0.04,
    (EcommPlatform.TMALL, "家居日用"): 0.03,
    (EcommPlatform.TMALL, "食品饮料"): 0.02,
    (EcommPlatform.TMALL, "礼品盒"):   0.04,
    # 抖音
    (EcommPlatform.DOUYIN, "服装鞋包"): 0.05,
    (EcommPlatform.DOUYIN, "3C数码"):   0.03,
    (EcommPlatform.DOUYIN, "食品饮料"): 0.02,
    (EcommPlatform.DOUYIN, "美妆个护"): 0.05,
    (EcommPlatform.DOUYIN, "珠宝首饰"): 0.08,
    (EcommPlatform.DOUYIN, "家居日用"): 0.03,
    (EcommPlatform.DOUYIN, "礼品盒"):   0.04,
    # 小红书
    (EcommPlatform.XIAOHONGSHU, "服装鞋包"): 0.10,
    (EcommPlatform.XIAOHONGSHU, "美妆个护"): 0.15,
    (EcommPlatform.XIAOHONGSHU, "食品饮料"): 0.05,
    (EcommPlatform.XIAOHONGSHU, "家居日用"): 0.10,
    (EcommPlatform.XIAOHONGSHU, "礼品盒"):  0.10,
    # 拼多多
    (EcommPlatform.PDD, "服装鞋包"): 0.01,
    (EcommPlatform.PDD, "3C数码"): 0.01,
    (EcommPlatform.PDD, "食品饮料"): 0.008,
    (EcommPlatform.PDD, "美妆个护"): 0.015,
    (EcommPlatform.PDD, "家居日用"): 0.008,
    (EcommPlatform.PDD, "礼品盒"):  0.01,
    # 京东
    (EcommPlatform.JD, "服装鞋包"): 0.08,
    (EcommPlatform.JD, "3C数码"): 0.03,
    (EcommPlatform.JD, "美妆个护"): 0.05,
    (EcommPlatform.JD, "食品饮料"): 0.03,
    (EcommPlatform.JD, "家居日用"): 0.05,
    (EcommPlatform.JD, "礼品盒"):  0.05,
    # Amazon US
    (EcommPlatform.AMAZON_US, "礼品盒"): 0.15,
    (EcommPlatform.AMAZON_US, "3C数码"): 0.15,
    (EcommPlatform.AMAZON_US, "家居日用"): 0.15,
    (EcommPlatform.AMAZON_US, "美妆个护"): 0.15,
}

# 类目别名映射（模糊匹配）
CATEGORY_ALIASES = {
    "服装鞋包": ["服装", "鞋", "包", "服饰", "女装", "男装", "童装", "鞋子", "箱包"],
    "3C数码":   ["数码", "手机", "电脑", "耳机", "充电器", "数码配件", "3c"],
    "美妆个护": ["美妆", "化妆品", "护肤品", "个护", "面膜", "口红", "洗护"],
    "食品饮料": ["食品", "饮料", "零食", "茶叶", "咖啡", "保健品"],
    "家居日用": ["家居", "日用品", "家纺", "厨具", "收纳", "清洁"],
    "母婴玩具": ["母婴", "玩具", "婴儿", "童装", "奶粉", "纸尿裤"],
    "珠宝首饰": ["珠宝", "首饰", "黄金", "银饰", "钻石", "手表"],
    "礼品盒":   ["礼品", "礼盒", "gift box", "gift set", "礼盒套装", "生日礼物", "节日礼品"],
}


class PricingEngine:
    """
    HVOS 定价引擎 — 精确到平台 × 类目的科学定价

    使用方式:
        engine = PricingEngine()
        result = engine.calculate_price(
            cost=50.0,          # 1688 采购价（人民币）
            platform="天猫",
            category="服装鞋包",
            target_margin=0.40,  # 目标毛利率 40%
            marketing_reserve=0.08,
        )
    """

    @staticmethod
    def _resolve_platform(platform_input: str) -> EcommPlatform:
        """将字符串映射到 EcommPlatform"""
        p = platform_input.strip().lower()
        mapping = {
            "淘宝": EcommPlatform.TAOBAO, "taobao": EcommPlatform.TAOBAO,
            "天猫": EcommPlatform.TMALL, "tmall": EcommPlatform.TMALL,
            "抖音": EcommPlatform.DOUYIN, "douyin": EcommPlatform.DOUYIN,
            "小红书": EcommPlatform.XIAOHONGSHU, "xhs": EcommPlatform.XIAOHONGSHU,
            "拼多多": EcommPlatform.PDD, "pdd": EcommPlatform.PDD, "pinduoduo": EcommPlatform.PDD,
            "京东": EcommPlatform.JD, "jd": EcommPlatform.JD,
            "amazon": EcommPlatform.AMAZON_US, "amazon us": EcommPlatform.AMAZON_US,
            "shopify": EcommPlatform.SHOPIFY,
        }
        for key, val in mapping.items():
            if key in p:
                return val
        return EcommPlatform.TAOBAO  # default

    @staticmethod
    def _resolve_category(category_input: str) -> str:
        """将任意类目字符串映射到标准类目"""
        cat = category_input.strip().lower()
        for std_cat, aliases in CATEGORY_ALIASES.items():
            if cat in aliases or cat == std_cat:
                return std_cat
        return category_input.strip()

    @staticmethod
    def get_rate(platform: EcommPlatform, category: str = None, custom_rate: float = None) -> float:
        """获取平台扣点（优先精确类目 > 自定义 > 默认）"""
        if custom_rate is not None:
            return custom_rate
        if category:
            std_cat = PricingEngine._resolve_category(category)
            key = (platform, std_cat)
            if key in CATEGORY_COMMISSIONS:
                return CATEGORY_COMMISSIONS[key]
        return PLATFORM_RATES[platform]["default"]

    @staticmethod
    def calculate_price(
        cost: float,
        platform: str,
        category: str = None,
        target_margin: float = 0.40,
        marketing_reserve: float = 0.08,
        return_rate: float = 0.03,
        custom_rate: float = None,
    ) -> dict:
        """
        计算精确售价

        总成本 = (采购 + 包装 + 物流) × (1 + 退换货损耗率)
        建议售价 = 总成本 ÷ (1 - 平台扣点% - 营销预留% - 目标毛利率%)

        Args:
            cost: 采购成本（人民币）
            platform: 目标平台（淘宝/天猫/抖音/小红书/拼多多/京东/Amazon US）
            category: 商品类目（用于精确扣点）
            target_margin: 目标毛利率（默认 40%）
            marketing_reserve: 营销预留比例（默认 8%）
            return_rate: 退换货损耗率（默认 3%）
            custom_rate: 自定义扣点（覆盖类目扣点）

        Returns:
            dict: 含三档定价、利润模拟、合规检查
        """
        ec_platform = PricingEngine._resolve_platform(platform)
        rate = PricingEngine.get_rate(ec_platform, category, custom_rate)

        # 包装 + 物流估算（基于成本比例）
        packaging = cost * 0.06  # 采购价的 6%
        logistics = cost * 0.05   # 采购价的 5%（国内小包）

        total_cost = (cost + packaging + logistics) * (1 + return_rate)

        # 三档定价
        # 保守：target_margin - 5%
        conservative = total_cost / (1 - rate - marketing_reserve - (target_margin - 0.05))
        # 建议：target_margin
        recommended = total_cost / (1 - rate - marketing_reserve - target_margin)
        # 激进：target_margin + 5%（低毛利抢市场）
        aggressive = total_cost / (1 - rate - marketing_reserve - (target_margin + 0.05))

        # 利润率检查
        def net_margin(price):
            gross = price - total_cost
            net = gross - (price * rate) - (price * marketing_reserve)
            return net / price if price > 0 else 0

        conservative_margin = net_margin(conservative)
        recommended_margin = net_margin(recommended)
        aggressive_margin = net_margin(aggressive)

        # 合规检查
        compliance_warnings = []
        if aggressive_margin < 0.05:
            compliance_warnings.append("激进定价低于成本价，涉嫌不正当竞争")
        if recommended_margin > 0.70:
            compliance_warnings.append("高利润率需有真实成本支撑，避免虚高定价")

        return {
            "platform": ec_platform.value,
            "category": category or "通用",
            "rate_used": f"{rate*100:.1f}%",
            "cost_breakdown": {
                "product_cost": cost,
                "packaging": round(packaging, 2),
                "logistics": round(logistics, 2),
                "return_loss": round(cost * return_rate, 2),
                "total_cost": round(total_cost, 2),
            },
            "pricing_tiers": {
                "conservative": {
                    "price": round(conservative, 2),
                    "gross_margin": f"{conservative_margin*100:.1f}%",
                    "strategy": "防守型 — 保障利润，适合成熟产品",
                },
                "recommended": {
                    "price": round(recommended, 2),
                    "gross_margin": f"{recommended_margin*100:.1f}%",
                    "strategy": "标准型 — 平衡利润与竞争力",
                },
                "aggressive": {
                    "price": round(aggressive, 2),
                    "gross_margin": f"{aggressive_margin*100:.1f}%",
                    "strategy": "进攻型 — 低毛利抢流量，适合新品冷启动",
                },
            },
            "compliance_warnings": compliance_warnings,
        }

    @staticmethod
    def simulate_profit_table(cost: float, platform: str, category: str = None) -> list:
        """生成利润模拟表（不同售价下的毛利/净利）"""
        ec_platform = PricingEngine._resolve_platform(platform)
        rate = PricingEngine.get_rate(ec_platform, category)
        packaging = cost * 0.06
        logistics = cost * 0.05
        total_cost = cost + packaging + logistics

        rows = []
        for markup_pct in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
            price = total_cost * (1 + markup_pct)
            platform_fee = price * rate
            marketing = price * 0.08
            net = price - total_cost - platform_fee - marketing
            rows.append({
                "markup_pct": f"{markup_pct*100:.0f}%",
                "price": round(price, 2),
                "gross_margin": f"{((price-total_cost)/price)*100:.1f}%" if price > 0 else "N/A",
                "net_margin": f"{net/price*100:.1f}%" if price > 0 else "N/A",
                "net_profit": round(net, 2),
            })
        return rows


