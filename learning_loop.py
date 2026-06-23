"""
HVOS Learning Loop — 持续学习闭环模块
======================================
持续从真实投资结果中学习，更新知识图谱边权重，识别失败模式。

核心功能：
  1. LearningLoop 主闭环（run）
  2. extract_causal_factors     — 从投资结果提取因果因素
  3. update_kg_edge_weights     — 根据ROI/CVR/AOV更新KG边权重
  4. detect_failure_patterns    — 识别失败模式
  5. decay_weak_edges          — 权重衰减机制
  6. record_learning_event      — 发布学习事件到EventBus
  7. EventBus 集成（订阅 reality.reality_hub.EventBus）

数据库：
  KG: knowledge-graph/kg.db
  Capital: knowledge-graph/capital_book.db

CLI:
  python learning_loop.py --capture --opp_id TEST001 --roi 1.8 --cvr 0.035 --ctr 0.042 --aov 89 --refund 0.04 --success
  python learning_loop.py --detect
  python learning_loop.py --decay
  python learning_loop.py --summary

Author: HVOS X Learning Loop
Version: 1.0.0
"""

from __future__ import annotations

import json
import math
import sqlite3
import logging
import argparse
import py_compile
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 路径配置
# ─────────────────────────────────────────────────────────────────────────────

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
KG_DB = rf"{HVOS_ROOT}\knowledge-graph\kg.db"
CAPITAL_DB = rf"{HVOS_ROOT}\knowledge-graph\capital_book.db"
EVENTS_DB = rf"{HVOS_ROOT}\reality\events.db"

# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LearningRecord:
    """单条学习记录"""
    opp_id: str
    success: bool
    roi: float = 0.0
    cvr: float = 0.0
    ctr: float = 0.0
    aov: float = 0.0
    refund_rate: float = 0.0
    category: str = ""
    market: str = "US"
    causal_factors: list[str] = None
    failure_pattern: str = ""
    detected_at: str = None

    def __post_init__(self):
        if self.causal_factors is None:
            self.causal_factors = []
        if self.detected_at is None:
            self.detected_at = datetime.now(timezone.utc).isoformat()


@dataclass
class KGLearningEvent:
    """KG学习事件（发布到EventBus）"""
    event_type: str  # causal_factors_extracted | edge_weights_updated | failure_pattern_detected | edges_decayed
    opp_id: str
    payload: dict
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：数据库连接
# ─────────────────────────────────────────────────────────────────────────────

def _kg_conn():
    conn = sqlite3.connect(KG_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _capital_conn():
    conn = sqlite3.connect(CAPITAL_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _events_conn():
    conn = sqlite3.connect(EVENTS_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 1. 因果因素提取
# ─────────────────────────────────────────────────────────────────────────────

class CausalFactorExtractor:
    """
    从投资结果提取因果因素。

    逻辑：
    - ROI < 1.0   → 资金效率不足
    - CVR < 0.02  → 转化漏斗顶部流失
    - CTR < 0.01  → 创意/受众不匹配
    - AOV < 50    → 客单价过低
    - refund > 5% → 产品质量/描述不符
    - CVR高但ROI低 → 毛利空间不足
    """

    THRESHOLDS = {
        "roi": {"low": 1.0, "high": 2.0},
        "cvr": {"low": 0.02, "high": 0.05},
        "ctr": {"low": 0.01, "high": 0.04},
        "aov": {"low": 50, "high": 120},
        "refund_rate": {"low": 0.02, "high": 0.05},
    }

    @classmethod
    def extract(cls, record: LearningRecord) -> list[dict]:
        """
        从 LearningRecord 提取因果因素列表。

        Returns:
            list[dict]: [{"factor": str, "severity": str, "description": str}]
        """
        factors = []
        r = record

        # ROI 因素
        if r.roi < cls.THRESHOLDS["roi"]["low"]:
            severity = "critical" if r.roi < 0.5 else "warning"
            factors.append({
                "factor": "LOW_ROI",
                "severity": severity,
                "description": f"ROI={r.roi:.2f} < {cls.THRESHOLDS['roi']['low']}，资金效率严重不足",
                "metric": "roi",
                "value": r.roi,
                "threshold": cls.THRESHOLDS["roi"]["low"],
            })
        elif r.roi > cls.THRESHOLDS["roi"]["high"]:
            factors.append({
                "factor": "HIGH_ROI",
                "severity": "positive",
                "description": f"ROI={r.roi:.2f} > {cls.THRESHOLDS['roi']['high']}，资金效率优秀",
                "metric": "roi",
                "value": r.roi,
                "threshold": cls.THRESHOLDS["roi"]["high"],
            })

        # CVR 因素
        if r.cvr < cls.THRESHOLDS["cvr"]["low"]:
            factors.append({
                "factor": "LOW_CVR",
                "severity": "critical",
                "description": f"CVR={r.cvr:.3f} < {cls.THRESHOLDS['cvr']['low']}，转化漏斗顶部严重流失",
                "metric": "cvr",
                "value": r.cvr,
                "threshold": cls.THRESHOLDS["cvr"]["low"],
            })
        elif r.cvr > cls.THRESHOLDS["cvr"]["high"]:
            factors.append({
                "factor": "HIGH_CVR",
                "severity": "positive",
                "description": f"CVR={r.cvr:.3f} > {cls.THRESHOLDS['cvr']['high']}，转化效率优秀",
                "metric": "cvr",
                "value": r.cvr,
                "threshold": cls.THRESHOLDS["cvr"]["high"],
            })

        # CTR 因素
        if r.ctr < cls.THRESHOLDS["ctr"]["low"]:
            factors.append({
                "factor": "LOW_CTR",
                "severity": "warning",
                "description": f"CTR={r.ctr:.3f} < {cls.THRESHOLDS['ctr']['low']}，创意/受众不匹配",
                "metric": "ctr",
                "value": r.ctr,
                "threshold": cls.THRESHOLDS["ctr"]["low"],
            })

        # AOV 因素
        if r.aov > 0:
            if r.aov < cls.THRESHOLDS["aov"]["low"]:
                factors.append({
                    "factor": "LOW_AOV",
                    "severity": "warning",
                    "description": f"AOV=${r.aov:.0f} < ${cls.THRESHOLDS['aov']['low']}，客单价过低压缩利润空间",
                    "metric": "aov",
                    "value": r.aov,
                    "threshold": cls.THRESHOLDS["aov"]["low"],
                })
            elif r.aov > cls.THRESHOLDS["aov"]["high"]:
                factors.append({
                    "factor": "HIGH_AOV",
                    "severity": "positive",
                    "description": f"AOV=${r.aov:.0f} > ${cls.THRESHOLDS['aov']['high']}，高客单价支撑利润",
                    "metric": "aov",
                    "value": r.aov,
                    "threshold": cls.THRESHOLDS["aov"]["high"],
                })

        # 退款率因素
        if r.refund_rate > cls.THRESHOLDS["refund_rate"]["high"]:
            factors.append({
                "factor": "HIGH_REFUND_RATE",
                "severity": "critical",
                "description": f"退款率={r.refund_rate:.1%} > {cls.THRESHOLDS['refund_rate']['high']:.1%}，产品质量或描述不符",
                "metric": "refund_rate",
                "value": r.refund_rate,
                "threshold": cls.THRESHOLDS["refund_rate"]["high"],
            })
        elif r.refund_rate > cls.THRESHOLDS["refund_rate"]["low"]:
            factors.append({
                "factor": "ELEVATED_REFUND_RATE",
                "severity": "warning",
                "description": f"退款率={r.refund_rate:.1%} 偏高，需关注产品质量",
                "metric": "refund_rate",
                "value": r.refund_rate,
                "threshold": cls.THRESHOLDS["refund_rate"]["low"],
            })

        # 组合诊断：CVR高但ROI低 → 毛利空间不足
        if r.cvr > cls.THRESHOLDS["cvr"]["high"] and r.roi < cls.THRESHOLDS["roi"]["low"]:
            factors.append({
                "factor": "MARGIN_INSUFFICIENT",
                "severity": "critical",
                "description": "CVR高但ROI低 → 毛利率不足，选品定价策略需优化",
                "metric": "cvr_roi_mismatch",
                "value": f"cvr={r.cvr:.3f}, roi={r.roi:.2f}",
                "threshold": "cvr_high+roi_low",
            })

        return factors


def extract_causal_factors(record: LearningRecord) -> list[dict]:
    """提取因果因素的公开接口"""
    return CausalFactorExtractor.extract(record)


# ─────────────────────────────────────────────────────────────────────────────
# 2. KG边权重更新
# ─────────────────────────────────────────────────────────────────────────────

class KGEdgeWeightUpdater:
    """
    根据投资结果更新KG边权重。

    边权重更新逻辑：
    - success=True + ROI高 → 强化相关边（×1.2，上限1.0）
    - success=True + ROI低 → 轻微强化（×1.05）
    - success=False → 弱化相关边（×0.8）

    边类型影响因子：
    - BELONGS_TO / SHIPPED_TO  → category/market 相关
    - MANUFACTURED_BY / SUPPLIED_BY → 供应链相关
    - PROMOTED_BY → 渠道/广告相关
    """

    SUCCESS_BOOST = 1.2
    MARGINAL_BOOST = 1.05
    FAILURE_PENALTY = 0.8
    MAX_WEIGHT = 1.0
    MIN_WEIGHT = 0.01

    def __init__(self, kg_db: str = KG_DB):
        self.kg_db = kg_db

    def _conn(self):
        return _kg_conn()

    def _update_edge_weight(self, rel_type: str, from_node: str, to_node: str, multiplier: float) -> bool:
        """更新单条边的权重"""
        conn = self._conn()
        cur = conn.cursor()

        # 查询现有权重
        cur.execute("""
            SELECT relation_id, properties, confidence
            FROM kg_relations
            WHERE from_node = ? AND to_node = ? AND rel_type = ?
        """, (from_node, to_node, rel_type))

        row = cur.fetchone()
        if not row:
            conn.close()
            return False

        rel_id = dict(row)["relation_id"]
        props = json.loads(dict(row)["properties"] or "{}")
        current_conf = dict(row)["confidence"]

        # 计算新权重
        new_conf = min(self.MAX_WEIGHT, current_conf * multiplier)
        new_conf = max(self.MIN_WEIGHT, new_conf)

        # 更新 properties 中的 weight 字段
        props["learned_weight"] = round(new_conf, 4)
        props["last_updated"] = datetime.now(timezone.utc).isoformat()

        cur.execute("""
            UPDATE kg_relations
            SET confidence = ?, properties = ?
            WHERE relation_id = ?
        """, (new_conf, json.dumps(props, ensure_ascii=False), rel_id))

        conn.commit()
        conn.close()
        return True

    def update_for_opportunity(
        self,
        opp_id: str,
        success: bool,
        roi: float,
        cvr: float,
        category: str = "",
        market: str = "US",
    ) -> dict:
        """
        根据投资结果更新所有相关KG边。

        Returns:
            {"updated": int, "skipped": int}
        """
        conn = self._conn()
        cur = conn.cursor()

        # 找到该opp_id对应的所有边
        cur.execute("""
            SELECT relation_id, from_node, to_node, rel_type, confidence, properties
            FROM kg_relations
            WHERE from_node LIKE ? OR to_node LIKE ?
        """, (f"%{opp_id}%", f"%{opp_id}%"))

        rows = cur.fetchall()
        conn.close()

        updated = 0
        skipped = 0

        for row in rows:
            d = dict(row)
            rel_type = d["rel_type"]

            # 确定乘数
            if success and roi >= 2.0:
                multiplier = self.SUCCESS_BOOST
            elif success:
                multiplier = self.MARGINAL_BOOST
            else:
                multiplier = self.FAILURE_PENALTY

            # 对特定边类型应用不同策略
            if rel_type in ("BELONGS_TO", "SHIPPED_TO"):
                # category/market 相关边：对成功/失败都更敏感
                if success:
                    multiplier *= 1.1
                else:
                    multiplier *= 0.9

            ok = self._update_edge_weight(rel_type, d["from_node"], d["to_node"], multiplier)
            if ok:
                updated += 1
            else:
                skipped += 1

        return {"updated": updated, "skipped": skipped, "opp_id": opp_id, "success": success}


def update_kg_edge_weights(opp_id: str, success: bool, roi: float = 0.0,
                            cvr: float = 0.0, category: str = "", market: str = "US") -> dict:
    """更新KG边权重的公开接口"""
    updater = KGEdgeWeightUpdater()
    return updater.update_for_opportunity(opp_id, success, roi, cvr, category, market)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 失败模式识别
# ─────────────────────────────────────────────────────────────────────────────

class FailurePatternDetector:
    """
    从历史投资记录中识别失败模式。

    诊断维度：
    - 品类失败率（某品类整体投资成功率）
    - 市场失败率（某市场整体投资成功率）
    - 组合模式（品类×市场×广告平台）
    - 退款模式（高退款率 → 产品质量/描述问题）
    - CVR模式（低CVR → 流量质量问题）
    """

    def __init__(self, kg_db: str = KG_DB, capital_db: str = CAPITAL_DB):
        self.kg_db = kg_db
        self.capital_db = capital_db

    def _kg(self):
        return _kg_conn()

    def _cap(self):
        return _capital_conn()

    def detect_from_investments(self, lookback_days: int = 90) -> list[dict]:
        """
        从投资记录中检测失败模式。

        分析维度：
        1. 品类失败率（失败数/总数）
        2. 市场失败率
        3. 组合失败模式（category×market）
        4. 高退款模式
        5. 低CVR模式
        """
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        patterns = []

        # ── 1. 从 KG Relations 提取投资 verdict ────────────────────
        kg_conn = self._kg()
        cur = kg_conn.cursor()

        # 找所有 INVESTED_IN 关系及其 verdicts
        cur.execute("""
            SELECT r.from_node, r.to_node, r.rel_type, r.properties, r.confidence,
                   n.properties as node_props
            FROM kg_relations r
            JOIN kg_nodes n ON r.to_node = n.node_id
            WHERE r.rel_type = 'INVESTED_IN'
            ORDER BY r.created_at DESC
        """)

        investments = []
        for row in cur.fetchall():
            d = dict(row)
            inv_props = json.loads(d["properties"] or "{}")
            node_props = json.loads(d["node_props"] or "{}")
            verdict = inv_props.get("verdict", "").upper()
            category = node_props.get("category", "")
            market = node_props.get("market", "")
            investments.append({
                "opp_id": d["to_node"],
                "verdict": verdict,
                "category": category,
                "market": market,
                "confidence": d["confidence"],
            })
        kg_conn.close()

        if not investments:
            return [{"error": "No investment records found"}]

        # ── 2. 品类失败率 ───────────────────────────────────────────
        cat_stats: dict[str, dict] = {}
        for inv in investments:
            cat = inv["category"] or "UNKNOWN"
            if cat not in cat_stats:
                cat_stats[cat] = {"total": 0, "rejected": 0}
            cat_stats[cat]["total"] += 1
            if inv["verdict"] in ("REJECT", "REJECTED"):
                cat_stats[cat]["rejected"] += 1

        for cat, stats in cat_stats.items():
            if stats["total"] >= 3:
                reject_rate = stats["rejected"] / stats["total"]
                if reject_rate > 0.5:
                    patterns.append({
                        "pattern_type": "CATEGORY_REJECTION_RATE",
                        "category": cat,
                        "reject_rate": round(reject_rate, 3),
                        "total_investments": stats["total"],
                        "severity": "critical" if reject_rate > 0.7 else "warning",
                        "description": f"品类【{cat}】拒绝率 {reject_rate:.1%}，超过50%阈值",
                        "recommendation": f"降低【{cat}】品类投资权重，优先审查该品类合规性",
                    })

        # ── 3. 市场失败率 ───────────────────────────────────────────
        mkt_stats: dict[str, dict] = {}
        for inv in investments:
            mkt = inv["market"] or "UNKNOWN"
            if mkt not in mkt_stats:
                mkt_stats[mkt] = {"total": 0, "rejected": 0}
            mkt_stats[mkt]["total"] += 1
            if inv["verdict"] in ("REJECT", "REJECTED"):
                mkt_stats[mkt]["rejected"] += 1

        for mkt, stats in mkt_stats.items():
            if stats["total"] >= 3:
                reject_rate = stats["rejected"] / stats["total"]
                if reject_rate > 0.5:
                    patterns.append({
                        "pattern_type": "MARKET_REJECTION_RATE",
                        "market": mkt,
                        "reject_rate": round(reject_rate, 3),
                        "total_investments": stats["total"],
                        "severity": "critical" if reject_rate > 0.7 else "warning",
                        "description": f"市场【{mkt}】拒绝率 {reject_rate:.1%}，超过50%阈值",
                        "recommendation": f"重新评估【{mkt}】市场进入策略",
                    })

        # ── 4. 组合模式（category×market）───────────────────────────
        combo_stats: dict[str, dict] = {}
        for inv in investments:
            key = f"{inv['category']}|{inv['market']}"
            if key not in combo_stats:
                combo_stats[key] = {"total": 0, "rejected": 0}
            combo_stats[key]["total"] += 1
            if inv["verdict"] in ("REJECT", "REJECTED"):
                combo_stats[key]["rejected"] += 1

        for combo, stats in combo_stats.items():
            if stats["total"] >= 2:
                reject_rate = stats["rejected"] / stats["total"]
                if reject_rate == 1.0 and stats["total"] >= 2:
                    cat, mkt = combo.split("|", 1)
                    patterns.append({
                        "pattern_type": "COMBO_100_REJECT",
                        "category": cat,
                        "market": mkt,
                        "reject_rate": 1.0,
                        "total_investments": stats["total"],
                        "severity": "critical",
                        "description": f"组合【{cat}×{mkt}】连续{stats['total']}次全部拒绝",
                        "recommendation": f"立即暂停【{cat}×{mkt}】组合投资，需重新尽调",
                    })

        # ── 5. 从 Capital Book 检测财务异常 ─────────────────────────
        try:
            cap_conn = self._cap()
            cap_cur = cap_conn.cursor()

            cap_cur.execute("""
                SELECT opp_id, actual_roi, actual_cvr, actual_ctr,
                       aov, refund_rate, verdict
                FROM investments
                WHERE recorded_at >= ?
                ORDER BY recorded_at DESC
                LIMIT 100
            """, (since,))

            cap_investments = [dict(row) for row in cap_cur.fetchall()]
            cap_conn.close()

            # 退款率模式
            refund_issues = [i for i in cap_investments if i.get("refund_rate", 0) > 0.05]
            if len(refund_issues) >= 2:
                avg_refund = sum(i["refund_rate"] for i in refund_issues) / len(refund_issues)
                patterns.append({
                    "pattern_type": "HIGH_REFUND_CLUSTER",
                    "avg_refund_rate": round(avg_refund, 4),
                    "affected_count": len(refund_issues),
                    "severity": "warning",
                    "description": f"近{lookback_days}天有{len(refund_issues)}个投资退款率>5%，可能存在产品质量/描述问题",
                    "recommendation": "审查相关产品供应商质量，更新产品描述准确性",
                })

            # 低CVR模式
            cvr_issues = [i for i in cap_investments if i.get("actual_cvr", 0) < 0.02]
            if len(cvr_issues) >= 3:
                patterns.append({
                    "pattern_type": "LOW_CVR_CLUSTER",
                    "affected_count": len(cvr_issues),
                    "avg_cvr": round(sum(i["actual_cvr"] for i in cvr_issues) / len(cvr_issues), 4),
                    "severity": "warning",
                    "description": f"近{lookback_days}天有{len(cvr_issues)}个投资CVR<2%，流量质量问题",
                    "recommendation": "优化广告创意和受众定向，审查落地页质量",
                })

        except Exception as e:
            logger.warning(f"Capital Book query failed (table may not exist): {e}")

        # 去重
        seen = set()
        unique_patterns = []
        for p in patterns:
            key = p.get("pattern_type", "") + "_" + p.get("category", "") + "_" + p.get("market", "")
            if key not in seen:
                seen.add(key)
                unique_patterns.append(p)

        return unique_patterns


def detect_failure_patterns(lookback_days: int = 90) -> list[dict]:
    """识别失败模式的公开接口"""
    detector = FailurePatternDetector()
    return detector.detect_from_investments(lookback_days)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 权重衰减机制
# ─────────────────────────────────────────────────────────────────────────────

class EdgeWeightDecayer:
    """
    弱边衰减机制。

    逻辑：
    - 边权重 < 0.1 → 每7天衰减20%（指数衰减）
    - 边权重 0.1~0.3 → 每30天衰减10%
    - 边权重 > 0.3 → 不衰减
    - 权重 < 0.01 → 软删除（保留记录但标记inactive）

    衰减 = last_decay后经过的天数 × 衰减率
    """

    DECAY_TIERS = [
        {"max_weight": 0.1, "days": 7, "rate": 0.20},   # 弱边：7天衰减20%
        {"max_weight": 0.3, "days": 30, "rate": 0.10},  # 中边：30天衰减10%
        {"max_weight": 1.0, "days": 9999, "rate": 0.0}, # 强边：不衰减
    ]
    MIN_ACTIVE_WEIGHT = 0.01

    def __init__(self, kg_db: str = KG_DB):
        self.kg_db = kg_db

    def _conn(self):
        return _kg_conn()

    def decay_all(self, dry_run: bool = False) -> dict:
        """
        对所有KG边执行衰减。

        Args:
            dry_run: 若True，只返回受影响边列表，不实际修改

        Returns:
            {"decayed": int, "soft_deleted": int, "skipped": int, "details": [...]}
        """
        conn = self._conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT relation_id, from_node, to_node, rel_type,
                   confidence, properties
            FROM kg_relations
            ORDER BY confidence ASC
        """)

        rows = [dict(row) for row in cur.fetchall()]
        conn.close()

        decayed = 0
        soft_deleted = 0
        skipped = 0
        details = []

        now = datetime.now(timezone.utc)

        for row in rows:
            rel_id = row["relation_id"]
            props = json.loads(row["properties"] or "{}")
            current_conf = row["confidence"]

            # 跳过已软删除的边
            if props.get("inactive"):
                skipped += 1
                continue

            # 确定衰减层级
            tier = None
            for t in self.DECAY_TIERS:
                if current_conf <= t["max_weight"]:
                    tier = t
                    break

            if not tier or tier["rate"] == 0.0:
                skipped += 1
                continue

            # 计算距离上次衰减的时间
            last_decay = props.get("last_decay_at")
            if last_decay:
                try:
                    last_dt = datetime.fromisoformat(last_decay.replace("Z", "+00:00"))
                    days_since = (now - last_dt).total_seconds() / 86400
                except Exception:
                    days_since = tier["days"]  # 默认已到衰减周期
            else:
                # 首次衰减检查：假设上次更新是创建时间
                created_at = props.get("created_at", now.isoformat())
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    days_since = (now - created_dt).total_seconds() / 86400
                except Exception:
                    days_since = tier["days"]

            # 判断是否需要衰减
            if days_since < tier["days"]:
                skipped += 1
                continue

            # 计算衰减次数（向下取整）
            periods = int(days_since / tier["days"])
            new_conf = current_conf
            for _ in range(periods):
                new_conf *= (1 - tier["rate"])

            new_conf = max(self.MIN_ACTIVE_WEIGHT, new_conf)

            detail = {
                "relation_id": rel_id,
                "from_node": row["from_node"],
                "to_node": row["to_node"],
                "rel_type": row["rel_type"],
                "old_confidence": round(current_conf, 4),
                "new_confidence": round(new_conf, 4),
                "decay_periods": periods,
            }

            if new_conf < self.MIN_ACTIVE_WEIGHT:
                # 软删除
                if not dry_run:
                    self._soft_delete(rel_id, props, new_conf, now)
                detail["action"] = "soft_deleted"
                soft_deleted += 1
            else:
                if not dry_run:
                    self._apply_decay(rel_id, props, new_conf, now)
                detail["action"] = "decayed"
                decayed += 1

            details.append(detail)

        return {
            "decayed": decayed,
            "soft_deleted": soft_deleted,
            "skipped": skipped,
            "total": len(rows),
            "details": details[:50],  # 最多返回50条详情
            "dry_run": dry_run,
        }

    def _apply_decay(self, rel_id: str, props: dict, new_conf: float, now: datetime):
        conn = self._conn()
        cur = conn.cursor()
        props["learned_weight"] = round(new_conf, 4)
        props["last_decay_at"] = now.isoformat()
        cur.execute("""
            UPDATE kg_relations
            SET confidence = ?, properties = ?
            WHERE relation_id = ?
        """, (new_conf, json.dumps(props, ensure_ascii=False), rel_id))
        conn.commit()
        conn.close()

    def _soft_delete(self, rel_id: str, props: dict, new_conf: float, now: datetime):
        props["learned_weight"] = round(new_conf, 4)
        props["last_decay_at"] = now.isoformat()
        props["inactive"] = True
        props["inactive_at"] = now.isoformat()
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE kg_relations
            SET confidence = ?, properties = ?
            WHERE relation_id = ?
        """, (new_conf, json.dumps(props, ensure_ascii=False), rel_id))
        conn.commit()
        conn.close()


def decay_weak_edges(dry_run: bool = False) -> dict:
    """权重衰减的公开接口"""
    decayer = EdgeWeightDecayer()
    return decayer.decay_all(dry_run=dry_run)


# ─────────────────────────────────────────────────────────────────────────────
# 5. EventBus 集成
# ─────────────────────────────────────────────────────────────────────────────

class LearningEventBus:
    """
    学习事件发布器。

    内部集成 reality_hub.EventBus，将学习结果发布给其他子系统。
    """

    def __init__(self):
        self._bus = None
        self._connected = False

    def _get_bus(self):
        """懒加载 EventBus"""
        if self._bus is None:
            try:
                import sys
                import os
                sys.path.insert(0, HVOS_ROOT)
                from reality.reality_hub import EventBus, EventType, EventSeverity
                self._bus = EventBus()
                self._EventType = EventType
                self._EventSeverity = EventSeverity
                self._connected = True
                logger.info("[LearningEventBus] Connected to reality_hub.EventBus")
            except Exception as e:
                logger.warning(f"[LearningEventBus] Could not connect to EventBus: {e}")
                self._connected = False
        return self._bus

    LEARNING_EVENT_TYPE_MAP = {
        "learning_completed": "opportunity_detected",
        "causal_factors_extracted": "opportunity_detected",
        "edge_weights_updated": "opportunity_detected",
        "failure_pattern_detected": "anomaly_detected",
        "edges_decayed": "anomaly_detected",
    }

    def publish(self, event: KGLearningEvent) -> bool:
        """发布学习事件到 EventBus"""
        bus = self._get_bus()
        if not self._connected or bus is None:
            logger.debug("[LearningEventBus] EventBus not connected, skipping publish")
            return False

        try:
            # 构造 RealityEvent
            from reality.reality_hub import RealityEvent, EventSource, EventType
            # 映射到有效的 EventType
            mapped_type = self.LEARNING_EVENT_TYPE_MAP.get(event.event_type, "opportunity_detected")
            reality_ev = RealityEvent(
                source=EventSource.MANUAL,
                event_type=mapped_type,
                severity=self._EventSeverity.INFO,
                metric_name=f"learning_{event.event_type}",
                metric_value=1.0,
                raw_data=event.payload,
                tags=["learning_loop", event.event_type],
            )
            bus.publish(reality_ev)
            logger.info(f"[LearningEventBus] Published {event.event_type} for opp_id={event.opp_id}")
            return True
        except Exception as e:
            logger.warning(f"[LearningEventBus] Publish failed: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# 6. 学习事件记录
# ─────────────────────────────────────────────────────────────────────────────

def record_learning_event(
    event_type: str,
    opp_id: str,
    payload: dict,
    publish_to_bus: bool = True,
) -> KGLearningEvent:
    """
    记录学习事件并可选发布到 EventBus。

    Args:
        event_type: 事件类型（causal_factors_extracted | edge_weights_updated |
                    failure_pattern_detected | edges_decayed）
        opp_id: 机会ID
        payload: 事件数据
        publish_to_bus: 是否发布到 EventBus

    Returns:
        KGLearningEvent
    """
    event = KGLearningEvent(
        event_type=event_type,
        opp_id=opp_id,
        payload=payload,
    )

    if publish_to_bus:
        bus = LearningEventBus()
        bus.publish(event)

    return event


# ─────────────────────────────────────────────────────────────────────────────
# 7. LearningLoop 主闭环
# ─────────────────────────────────────────────────────────────────────────────

class LearningLoop:
    """
    持续学习闭环主类。

    工作流程：
    1. 接收投资结果（ROI/CVR/CTR/AOV/退款率）
    2. 提取因果因素
    3. 更新KG边权重
    4. 检测失败模式
    5. 衰减弱边（定期）
    6. 发布学习事件到EventBus

    用法：
        loop = LearningLoop()
        result = loop.run(
            opp_id="TEST001",
            success=True,
            roi=1.8,
            cvr=0.035,
            ctr=0.042,
            aov=89,
            refund_rate=0.04,
        )
    """

    def __init__(self, kg_db: str = KG_DB, capital_db: str = CAPITAL_DB):
        self.kg_db = kg_db
        self.capital_db = capital_db
        self.event_bus = LearningEventBus()

    def run(
        self,
        opp_id: str,
        success: bool,
        roi: float = 0.0,
        cvr: float = 0.0,
        ctr: float = 0.0,
        aov: float = 0.0,
        refund_rate: float = 0.0,
        category: str = "",
        market: str = "US",
        publish: bool = True,
    ) -> dict:
        """
        执行完整学习闭环。

        Returns:
            {
                "opp_id": str,
                "causal_factors": [...],
                "edge_update": {...},
                "learning_event": KGLearningEvent,
            }
        """
        # 1. 构建学习记录
        record = LearningRecord(
            opp_id=opp_id,
            success=success,
            roi=roi,
            cvr=cvr,
            ctr=ctr,
            aov=aov,
            refund_rate=refund_rate,
            category=category,
            market=market,
        )

        # 2. 提取因果因素
        factors = extract_causal_factors(record)

        # 3. 更新KG边权重
        edge_result = update_kg_edge_weights(
            opp_id=opp_id,
            success=success,
            roi=roi,
            cvr=cvr,
            category=category,
            market=market,
        )

        # 4. 记录学习事件
        event = record_learning_event(
            event_type="learning_completed",
            opp_id=opp_id,
            payload={
                "success": success,
                "roi": roi,
                "cvr": cvr,
                "factors_count": len(factors),
                "factors": factors,
                "edge_update": edge_result,
            },
            publish_to_bus=publish,
        )

        return {
            "opp_id": opp_id,
            "success": success,
            "causal_factors": factors,
            "edge_update": edge_result,
            "learning_event": event.to_dict(),
        }

    def summary(self) -> dict:
        """生成学习闭环状态摘要"""
        conn = _kg_conn()
        cur = conn.cursor()

        # KG 统计
        cur.execute("SELECT COUNT(*) FROM kg_nodes")
        node_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM kg_relations")
        rel_count = cur.fetchone()[0]

        cur.execute("""
            SELECT rel_type, COUNT(*) as cnt
            FROM kg_relations
            GROUP BY rel_type
            ORDER BY cnt DESC
        """)
        rel_types = [dict(r) for r in cur.fetchall()]

        # 低权重边统计
        cur.execute("SELECT COUNT(*) FROM kg_relations WHERE confidence < 0.1")
        weak_edges = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM kg_relations WHERE confidence < 0.01")
        very_weak_edges = cur.fetchone()[0]

        conn.close()

        # Capital Book 统计
        invest_count = 0
        try:
            cap_conn = _capital_conn()
            cap_cur = cap_conn.cursor()
            cap_cur.execute("SELECT COUNT(*) FROM investments")
            invest_count = cap_cur.fetchone()[0]
            cap_conn.close()
        except Exception:
            pass

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kg": {
                "nodes": node_count,
                "relations": rel_count,
                "weak_edges_below_01": weak_edges,
                "very_weak_edges_below_001": very_weak_edges,
                "top_relation_types": rel_types[:10],
            },
            "capital_book": {
                "total_investments": invest_count,
            },
            "decay_tiers": [
                {"max_weight": t["max_weight"], "days": t["days"], "rate": f"{t['rate']:.0%}"}
                for t in EdgeWeightDecayer.DECAY_TIERS
            ],
        }



# ─────────────────────────────────────────────────────────────────────────────
# V9.2 — Error Attribution Engine（预测误差归因引擎）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PredictionErrorRecord:
    """预测误差记录"""
    prediction_id: str
    opp_id: str
    predicted_roi: float
    actual_roi: float
    predicted_at: str
    recorded_at: str = None
    error_pct: float = None
    error_magnitude: str = ""  # under/over/correct
    causal_factors: list = None
    attribution: dict = None

    def __post_init__(self):
        if self.recorded_at is None:
            self.recorded_at = datetime.now(timezone.utc).isoformat()
        if self.error_pct is None and self.actual_roi > 0:
            self.error_pct = round((self.actual_roi - self.predicted_roi) / self.predicted_roi * 100, 2) if self.predicted_roi != 0 else 0
            if abs(self.error_pct) < 15:
                self.error_magnitude = "correct"
            elif self.error_pct < 0:
                self.error_magnitude = "over"  # 预测过高
            else:
                self.error_magnitude = "under"  # 预测过低
        if self.causal_factors is None:
            self.causal_factors = []
        if self.attribution is None:
            self.attribution = {}


class ErrorAttributionEngine:
    """
    V9.2 预测误差归因引擎。

    解决 OpenAI 分析的核心问题：
      - "Outcome → Knowledge 反馈链太弱"
      - "没有 '为什么预测错'，没有 '哪个模块导致预测错'"

    工作流：
      Outcome → Prediction Error → Root Cause → Policy Update → Agent Update → KG Update
    """

    def __init__(self, kg_db: str = KG_DB, strategy_db: str = None):
        self.kg_db = kg_db
        self.strategy_db = strategy_db or rf"{HVOS_ROOT}\knowledge-graph\strategy_memory.db"

    def _kg(self):
        return _kg_conn()

    def _strat(self):
        conn = sqlite3.connect(self.strategy_db, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ----------------------------------------------------------
    # 1. 记录预测误差
    # ----------------------------------------------------------

    def record_prediction_error(
        self,
        prediction_id: str,
        opp_id: str,
        predicted_roi: float,
        actual_roi: float,
        actual_cvr: float = 0.0,
        actual_ctr: float = 0.0,
        actual_aov: float = 0.0,
        actual_refund_rate: float = 0.0,
        category: str = "",
        market: str = "",
    ) -> PredictionErrorRecord:
        """
        记录预测 vs 实际，并自动执行归因。

        Returns:
            PredictionErrorRecord（已填充 attribution）
        """
        # 构建误差记录
        error_pct = round((actual_roi - predicted_roi) / predicted_roi * 100, 2) if predicted_roi != 0 else 0
        if abs(error_pct) < 15:
            magnitude = "correct"
        elif error_pct < 0:
            magnitude = "over"
        else:
            magnitude = "under"

        record = PredictionErrorRecord(
            prediction_id=prediction_id,
            opp_id=opp_id,
            predicted_roi=predicted_roi,
            actual_roi=actual_roi,
            predicted_at=datetime.now(timezone.utc).isoformat(),
            error_pct=error_pct,
            error_magnitude=magnitude,
        )

        # 执行归因
        attribution = self.attribute_error(
            record,
            cvr=actual_cvr,
            ctr=actual_ctr,
            aov=actual_aov,
            refund_rate=actual_refund_rate,
            category=category,
            market=market,
        )
        record.attribution = attribution

        # 写入 KG 的 prediction_errors 表
        conn = self._kg()
        cur = conn.cursor()
        # 使用 V9.2 新表（兼容旧表结构，不覆盖旧表）
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prediction_error_attributions (
                prediction_id TEXT PRIMARY KEY,
                opp_id TEXT,
                predicted_roi REAL,
                actual_roi REAL,
                error_pct REAL,
                error_magnitude TEXT,
                attribution TEXT,
                recorded_at TEXT
            )
        """)
        cur.execute("""
            INSERT OR REPLACE INTO prediction_error_attributions
            (prediction_id, opp_id, predicted_roi, actual_roi,
             error_pct, error_magnitude, attribution, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.prediction_id, record.opp_id,
            record.predicted_roi, record.actual_roi,
            record.error_pct, record.error_magnitude,
            json.dumps(attribution, ensure_ascii=False),
            record.recorded_at,
        ))
        conn.commit()
        conn.close()

        logger.info(
            f"[ErrorAttribution] {opp_id}: "
            f"pred={predicted_roi:.2f}, actual={actual_roi:.2f}, "
            f"error={error_pct:+.1f}% → {attribution.get('primary_engine', 'unknown')}"
        )

        return record

    # ----------------------------------------------------------
    # 2. 误差归因分析
    # ----------------------------------------------------------

    def attribute_error(
        self,
        record: PredictionErrorRecord,
        cvr: float = 0.0,
        ctr: float = 0.0,
        aov: float = 0.0,
        refund_rate: float = 0.0,
        category: str = "",
        market: str = "",
    ) -> dict:
        """
        归因分析：预测误差来自哪个引擎/模块。

        归因维度：
          - Outcome Engine（ROI回归/概率映射/MC模拟）
          - Policy Engine（Policy 评分调整偏差）
          - Agent（Agent 选择偏差）
          - Data（数据质量/样本不足）
          - External（外部冲击未建模）

        Returns:
            {
                "primary_engine": str,
                "confidence": float,
                "engine_scores": {...},
                "recommendation": str,
                "decomposition": {...}
            }
        """
        error = abs(record.error_pct or 0)

        # ── 各引擎嫌疑评分（越高越可能是根因）──
        # 每个引擎得分 0-1
        scores = {}

        # 1. Outcome Engine 嫌疑
        oe_score = 0.0
        if record.predicted_roi > 3.0:
            oe_score += 0.3  # 过高预测 → 回归模型偏差
        if record.predicted_roi < -0.5:
            oe_score += 0.3  # 过低预测
        if error > 80:
            oe_score += 0.3  # 大幅偏离 → 模型校准问题
        # CVR高但ROI预测错 → 毛利参数错误
        if cvr > 0.05 and record.error_magnitude == "over":
            oe_score += 0.2
        scores["outcome_engine"] = min(1.0, oe_score)

        # 2. Policy Engine 嫌疑
        pe_score = 0.0
        if error > 50:
            pe_score += 0.2  # Policy 评分可能引入偏差
        if record.error_magnitude == "over":
            pe_score += 0.1  # Policy 过度乐观
        if error > 100:
            pe_score += 0.2  # 严重偏离 → 政策过强
        scores["policy_engine"] = min(1.0, pe_score)

        # 3. Agent 嫌疑
        ag_score = 0.0
        if record.error_magnitude == "under":
            ag_score += 0.1  # Agent 可能过于保守
        if error > 60:
            ag_score += 0.1
        scores["agent"] = min(1.0, ag_score)

        # 4. 数据质量嫌疑
        dq_score = 0.0
        conn = self._kg()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM prediction_errors")
        n_errors = cur.fetchone()[0]
        conn.close()
        if n_errors < 10:
            dq_score += 0.3  # 样本太少 → 回归不可靠
        if category and not market:
            dq_score += 0.1  # 市场缺失
        scores["data_quality"] = min(1.0, dq_score)

        # 5. 外部冲击嫌疑
        ext_score = 0.0
        if record.error_magnitude == "under" and error > 70:
            ext_score += 0.3  # 远超预期 → 可能有外部利好
        if refund_rate > 0.08:
            ext_score += 0.2  # 高退款率 → 产品问题超出模型
        scores["external_shock"] = min(1.0, ext_score)

        # ── 确定主因 ──
        primary = max(scores, key=scores.get)
        primary_conf = scores[primary]

        # ── 建议 ──
        recommendations = {
            "outcome_engine": "校准 Outcome Engine 的 ROI 回归参数，增加 margin 因子权重",
            "policy_engine": "审查相关 Policy 的评分调整量，降低过度乐观 Policy 的权重",
            "agent": "降低相关 Agent 的 influence_weight，引入竞争 Agent",
            "data_quality": "积累更多真实数据（当前样本不足），暂时降低 Confidence Score 阈值",
            "external_shock": "记录外部因素并纳入模型，考虑添加市场事件检测器",
        }

        return {
            "primary_engine": primary,
            "confidence": round(primary_conf, 4),
            "engine_scores": scores,
            "recommendation": recommendations.get(primary, "继续监控"),
            "decomposition": {
                "predicted_roi": record.predicted_roi,
                "actual_roi": record.actual_roi,
                "error_pct": record.error_pct,
                "error_magnitude": record.error_magnitude,
                "analysis": f"主要误差来源: {primary} (置信度: {primary_conf:.0%})",
            }
        }

    # ----------------------------------------------------------
    # 3. 校准建议
    # ----------------------------------------------------------

    def calibration_actions(self) -> list[dict]:
        """
        基于历史预测误差生成校准建议。

        Returns:
            [{"engine": str, "action": str, "priority": str, "detail": str}]
        """
        conn = self._kg()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT prediction_id, opp_id, predicted_roi, actual_roi,
                       error_pct, error_magnitude, attribution
                FROM prediction_error_attributions
                ORDER BY recorded_at DESC
                LIMIT 100
            """)
            errors = [dict(r) for r in cur.fetchall()]
        except Exception:
            errors = []
        conn.close()

        if not errors:
            return [{"engine": "system", "action": "collect_data",
                     "priority": "high", "detail": "暂无误差数据，需要先积累真实结果"}]

        # 统计各引擎的归因次数
        engine_hits = {}
        for e in errors:
            attr = json.loads(e.get("attribution", "{}"))
            primary = attr.get("primary_engine", "unknown")
            engine_hits[primary] = engine_hits.get(primary, 0) + 1

        total = len(errors)
        actions = []

        for engine, count in sorted(engine_hits.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            if pct > 30:
                priority = "high"
            elif pct > 15:
                priority = "medium"
            else:
                priority = "low"

            recommendations = {
                "outcome_engine": f"Outcome Engine 被归因 {count}/{total} 次 ({pct:.0f}%)，需要校准 ROI 回归权重",
                "policy_engine": f"Policy Engine 被归因 {count}/{total} 次 ({pct:.0f}%)，需要审查 Policy 评分偏差",
                "agent": f"Agent 被归因 {count}/{total} 次 ({pct:.0f}%)，需要调整 Agent 竞争权重",
                "data_quality": f"数据质量被归因 {count}/{total} 次 ({pct:.0f}%)，需要增加真实数据采集",
                "external_shock": f"外部冲击被归因 {count}/{total} 次 ({pct:.0f}%)，需要添加外部因子检测",
            }

            actions.append({
                "engine": engine,
                "action": recommendations.get(engine, f"审查 {engine} 模块"),
                "priority": priority,
                "detail": f"归因次数: {count}/{total} ({pct:.0f}%)",
            })

        # 总体校准偏差
        over_count = sum(1 for e in errors if e.get("error_magnitude") == "over")
        under_count = sum(1 for e in errors if e.get("error_magnitude") == "under")
        if over_count > under_count * 1.5:
            actions.append({
                "engine": "system",
                "action": "系统存在乐观偏差（预测过高），需要整体下调 Confidence Score",
                "priority": "high",
                "detail": f"过度预测: {over_count}, 不足预测: {under_count}",
            })
        elif under_count > over_count * 1.5:
            actions.append({
                "engine": "system",
                "action": "系统存在保守偏差（预测过低），需要放松 Policy 限制",
                "priority": "medium",
                "detail": f"过度预测: {over_count}, 不足预测: {under_count}",
            })

        return actions

    # ----------------------------------------------------------
    # 4. 归因报告
    # ----------------------------------------------------------

    def generate_report(self) -> dict:
        """生成完整的误差归因报告"""
        conn = self._kg()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM prediction_error_attributions")
            total_errors = cur.fetchone()[0]
        except Exception:
            total_errors = 0

        # 安全查询 error_magnitude（兼容旧表结构）
        magnitude_dist = {}
        if total_errors > 0:
            try:
                cur.execute("""
                    SELECT error_magnitude, COUNT(*) as cnt
                    FROM prediction_error_attributions
                    WHERE error_magnitude IS NOT NULL AND error_magnitude != ''
                    GROUP BY error_magnitude
                """)
                magnitude_dist = dict(cur.fetchall())
            except Exception:
                pass

        avg_abs_error = 0
        if total_errors > 0:
            try:
                cur.execute("""
                    SELECT AVG(ABS(error_pct)) FROM prediction_error_attributions
                    WHERE error_pct IS NOT NULL
                """)
                avg_abs_error = cur.fetchone()[0] or 0
            except Exception:
                pass

        conn.close()

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_errors": total_errors,
            "avg_abs_error_pct": round(avg_abs_error, 2),
            "magnitude_distribution": magnitude_dist,
            "calibration_actions": self.calibration_actions(),
            "system_bias": "over" if magnitude_dist.get("over", 0) > magnitude_dist.get("under", 0) * 1.5
                          else "under" if magnitude_dist.get("under", 0) > magnitude_dist.get("over", 0) * 1.5
                          else "balanced",
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def _setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_capture(args) -> int:
    """--capture: 捕获投资结果，执行学习闭环"""
    _setup_logging(args.log)

    record = LearningRecord(
        opp_id=args.opp_id,
        success=args.success,
        roi=args.roi,
        cvr=args.cvr,
        ctr=args.ctr,
        aov=args.aov,
        refund_rate=args.refund,
        category=args.category or "",
        market=args.market or "US",
    )

    print(f"\n{'='*60}")
    print(f"  Learning Loop — Capture Mode")
    print(f"{'='*60}")
    print(f"  opp_id      : {record.opp_id}")
    print(f"  success     : {record.success}")
    print(f"  roi         : {record.roi:.2f}x")
    print(f"  cvr         : {record.cvr:.3f} ({record.cvr:.1%})")
    print(f"  ctr         : {record.ctr:.3f} ({record.ctr:.1%})")
    print(f"  aov         : ${record.aov:.2f}")
    print(f"  refund_rate : {record.refund_rate:.3f} ({record.refund_rate:.1%})")
    print(f"{'='*60}\n")

    # 提取因果因素
    factors = extract_causal_factors(record)
    print(f"[1/3] Causal Factors ({len(factors)} found):")
    if factors:
        for f in factors:
            icon = "🔴" if f["severity"] == "critical" else ("🟡" if f["severity"] == "warning" else "🟢")
            print(f"  {icon} [{f['factor']}] {f['description']}")
    else:
        print("  (none detected)")
    print()

    # 执行学习闭环
    loop = LearningLoop()
    result = loop.run(
        opp_id=record.opp_id,
        success=record.success,
        roi=record.roi,
        cvr=record.cvr,
        ctr=record.ctr,
        aov=record.aov,
        refund_rate=record.refund_rate,
        category=record.category,
        market=record.market,
        publish=True,
    )

    print(f"[2/3] KG Edge Update:")
    eu = result["edge_update"]
    print(f"  updated={eu['updated']}, skipped={eu['skipped']}")

    print(f"\n[3/3] Learning Event Published:")
    ev = result["learning_event"]
    print(f"  type={ev['event_type']}, opp_id={ev['opp_id']}, ts={ev['timestamp']}")

    print(f"\n✅ Learning loop completed for {record.opp_id}")
    return 0


def cmd_detect(args) -> int:
    """--detect: 检测失败模式"""
    _setup_logging(args.log)

    print(f"\n{'='*60}")
    print(f"  Learning Loop — Failure Pattern Detection")
    print(f"  lookback: {args.lookback} days")
    print(f"{'='*60}\n")

    patterns = detect_failure_patterns(lookback_days=args.lookback)

    if not patterns or "error" in patterns[0]:
        print("  No patterns detected.")
        return 0

    print(f"  Detected {len(patterns)} pattern(s):\n")
    for i, p in enumerate(patterns, 1):
        icon = "🔴" if p["severity"] == "critical" else "🟡"
        print(f"  {i}. {icon} [{p['pattern_type']}]")
        print(f"     {p['description']}")
        print(f"     → {p['recommendation']}")
        print()

    # 发布检测事件
    record_learning_event(
        event_type="failure_pattern_detected",
        opp_id="SYSTEM",
        payload={"patterns": patterns, "lookback_days": args.lookback},
        publish_to_bus=True,
    )

    return 0


def cmd_decay(args) -> int:
    """--decay: 执行权重衰减"""
    _setup_logging(args.log)

    print(f"\n{'='*60}")
    print(f"  Learning Loop — Edge Weight Decay")
    print(f"  dry_run: {args.dry_run}")
    print(f"{'='*60}\n")

    result = decay_weak_edges(dry_run=args.dry_run)

    print(f"  Total edges  : {result['total']}")
    print(f"  Decayed      : {result['decayed']}")
    print(f"  Soft-deleted : {result['soft_deleted']}")
    print(f"  Skipped      : {result['skipped']}")

    if result["details"]:
        print(f"\n  Top affected edges:")
        for d in result["details"][:10]:
            arrow = "→" if d["action"] == "decayed" else "✗"
            print(f"    {arrow} [{d['rel_type']}] {d['from_node'][:30]} → {d['to_node'][:30]}")
            print(f"        {d['old_confidence']:.4f} → {d['new_confidence']:.4f}")

    if args.dry_run:
        print("\n  [DRY RUN] No changes written to KG.")

    # 发布衰减事件
    record_learning_event(
        event_type="edges_decayed",
        opp_id="SYSTEM",
        payload={
            "decayed": result["decayed"],
            "soft_deleted": result["soft_deleted"],
            "dry_run": result["dry_run"],
        },
        publish_to_bus=True,
    )

    return 0


def cmd_summary(args) -> int:
    """--summary: 输出学习闭环状态摘要"""
    _setup_logging(args.log)

    print(f"\n{'='*60}")
    print(f"  Learning Loop — System Summary")
    print(f"{'='*60}\n")

    loop = LearningLoop()
    s = loop.summary()

    print(f"  Generated: {s['generated_at']}")
    print(f"\n  KG Statistics:")
    kg = s["kg"]
    print(f"    Nodes            : {kg['nodes']:,}")
    print(f"    Relations        : {kg['relations']:,}")
    print(f"    Weak edges (<0.1): {kg['weak_edges_below_01']}")
    print(f"    Very weak (<0.01): {kg['very_weak_edges_below_001']}")

    if kg["top_relation_types"]:
        print(f"\n    Top relation types:")
        for rt in kg["top_relation_types"][:5]:
            print(f"      {rt['rel_type']:30s} {rt['cnt']:>6}")

    print(f"\n  Decay Tiers:")
    for t in s["decay_tiers"]:
        print(f"    weight ≤ {t['max_weight']:.2f}: every {t['days']} days × {t['rate']} decay")

    cap = s.get("capital_book", {})
    print(f"\n  Capital Book:")
    print(f"    Total investments: {cap.get('total_investments', 'N/A')}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HVOS Learning Loop — 持续学习闭环模块",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 捕获投资结果并执行学习
  python learning_loop.py --capture --opp_id TEST001 --roi 1.8 --cvr 0.035 --ctr 0.042 --aov 89 --refund 0.04 --success

  # 检测失败模式（默认90天回溯）
  python learning_loop.py --detect --lookback 30

  # 权重衰减（dry-run）
  python learning_loop.py --decay --dry_run

  # 权重衰减（正式执行）
  python learning_loop.py --decay

  # 系统状态摘要
  python learning_loop.py --summary

  # V9.2: 预测误差归因报告
  python learning_loop.py --attribution

  # V9.2: 生成校准建议
  python learning_loop.py --calibrate
        """,
    )

    parser.add_argument("--capture", action="store_true", help="捕获投资结果并执行学习闭环")
    parser.add_argument("--detect", action="store_true", help="检测失败模式")
    parser.add_argument("--decay", action="store_true", help="执行KG边权重衰减")
    parser.add_argument("--summary", action="store_true", help="输出学习系统状态摘要")
    parser.add_argument("--attribution", action="store_true", help="V9.2: 生成预测误差归因报告")
    parser.add_argument("--calibrate", action="store_true", help="V9.2: 生成校准建议")

    # --capture 参数
    parser.add_argument("--opp_id", type=str, help="机会ID")
    parser.add_argument("--roi", type=float, default=0.0, help="投资回报率 (e.g. 1.8)")
    parser.add_argument("--cvr", type=float, default=0.0, help="转化率 (e.g. 0.035)")
    parser.add_argument("--ctr", type=float, default=0.0, help="点击率 (e.g. 0.042)")
    parser.add_argument("--aov", type=float, default=0.0, help="平均订单金额 (e.g. 89)")
    parser.add_argument("--refund", type=float, default=0.0, help="退款率 (e.g. 0.04)")
    parser.add_argument("--success", action="store_true", help="标记为成功投资")
    parser.add_argument("--category", type=str, default="", help="产品品类")
    parser.add_argument("--market", type=str, default="US", help="目标市场")

    # --detect 参数
    parser.add_argument("--lookback", type=int, default=90, help="回溯天数 (default: 90)")

    # --decay 参数
    parser.add_argument("--dry_run", action="store_true", help="只读模式，不写入KG")

    # 全局参数
    parser.add_argument("--log", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别")

    args = parser.parse_args()

    # 至少指定一个命令
    if not any([args.capture, args.detect, args.decay, args.summary,
                args.attribution, args.calibrate]):
        parser.print_help()
        return 1

    # 验证 --capture 需要 --opp_id
    if args.capture and not args.opp_id:
        print("❌ --capture requires --opp_id", file=__import__("sys").stderr)
        return 1

    if args.capture:
        return cmd_capture(args)
    elif args.detect:
        return cmd_detect(args)
    elif args.decay:
        return cmd_decay(args)
    elif args.summary:
        return cmd_summary(args)
    elif args.attribution:
        """V9.2: 生成预测误差归因报告"""
        eae = ErrorAttributionEngine()
        report = eae.generate_report()
        print(f"\n{'='*60}")
        print(f"  Error Attribution Report — V9.2")
        print(f"{'='*60}")
        print(f"\n  总误差记录: {report['total_errors']}")
        print(f"  平均绝对误差: {report['avg_abs_error_pct']:.1f}%")
        print(f"  系统偏差: {report['system_bias']}")
        print(f"\n  偏差分布: {report['magnitude_distribution']}")
        print(f"\n  校准建议:")
        for a in report['calibration_actions']:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a['priority'], '⚪')
            print(f"    {emoji} [{a['priority']}] {a['action']}")
            print(f"       {a['detail']}")
        print(f"\n{'='*60}")
        return 0
    elif args.calibrate:
        """V9.2: 生成校准建议"""
        eae = ErrorAttributionEngine()
        actions = eae.calibration_actions()
        print(f"\n{'='*60}")
        print(f"  Calibration Actions — V9.2")
        print(f"{'='*60}")
        if not actions:
            print("  (暂无校准建议)")
        for i, a in enumerate(actions, 1):
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a['priority'], '⚪')
            print(f"\n  {i}. {emoji} [{a['priority'].upper()}] {a['engine']}")
            print(f"     {a['action']}")
            print(f"     {a['detail']}")
        print(f"\n{'='*60}")
        return 0

    return 0


if __name__ == "__main__":
    exit(main())
