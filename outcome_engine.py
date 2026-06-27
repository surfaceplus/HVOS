"""
HVOS Outcome Engine — 商业结果预测引擎
======================================

职责：
  1. OutcomePrediction 数据契约（标准化预测输出）
  2. 历史ROI回归（从 outcome_log 学习真实ROI分布）
  3. 多因子 → 概率转换（logistic 映射）
  4. 蒙特卡洛模拟（预期结果分布）
  5. Confidence Score（数据质量 × 模型稳定性）
  6. 预测回写 KG（kg_nodes + predictions 表）

CLI 用法：
  python outcome_engine.py --opp_id TEST001 --trend 8.0 --supply 7.0 --risk 6.0 --margin 0.30
  python outcome_engine.py --opp_id TEST001 --trend 8.0 --supply 7.0 --risk 6.0 --margin 0.30 --invest_amt 50000 --mc_iter 10000

Author: HVOS X Outcome Engine
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

HVOS_ROOT = os.path.dirname(os.path.abspath(__file__))
KG_DB = os.path.join(HVOS_ROOT, "knowledge_graph", "kg.db")

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("outcome_engine")


# ─────────────────────────────────────────────────────────────────────────────
# 1. OutcomePrediction 数据契约
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OutcomePrediction:
    """
    标准化商业结果预测契约。

    属性按四个层次组织：
      - 输入因子（raw factors supplied by caller）
      - 中间结果（probability, monte carlo samples）
      - 输出结果（expected ROI, worst/best case）
      - 元数据（confidence, model version, timestamp）
    """

    # ── 标识 ──────────────────────────────────────────────
    opp_id: str = ""
    opp_name: str = ""

    # ── 输入因子（0–10 评分）──────────────────────────────
    trend_score: float = 0.0   # 市场趋势：0=衰退，10=爆发
    supply_score: float = 0.0  # 供给优势：0=红海，10=蓝海
    risk_score: float = 0.0     # 风险等级：0=高风险，10=低风险
    margin_pct: float = 0.0    # 毛利率（小数，如 0.30 = 30%）

    # ── 投资金额（用于ROI计算）───────────────────────────
    investment_usd: float = 0.0

    # ── 中间结果 ─────────────────────────────────────────
    success_probability: float = 0.0   # P(success)，logistic 映射后概率
    historical_roi_mu: float = 0.0     # 历史 ROI 均值（从 outcome_log 回归）
    historical_roi_sigma: float = 0.0  # 历史 ROI 标准差

    # ── Monte Carlo 输出 ─────────────────────────────────
    mc_samples: List[float] = field(default_factory=list)
    expected_roi: float = 0.0        # MC 期望 ROI（均值）
    expected_revenue: float = 0.0    # 90 天预期收入
    worst_case_roi: float = 0.0      # 5th percentile ROI
    best_case_roi: float = 0.0       # 95th percentile ROI
    probability_of_loss: float = 0.0 # P(ROI < 0)

    # ── Confidence Score ─────────────────────────────────
    confidence_score: float = 0.0   # 综合置信度 0–1
    confidence_factors: dict = field(default_factory=dict)  # 细分因子

    # ── 推荐决策 ─────────────────────────────────────────
    recommendation: str = "HOLD"   # INVEST / HOLD / REJECT
    verdict: str = ""                # 决策理由（短句）

    # ── 元数据 ───────────────────────────────────────────
    model_version: str = "v1.0"
    prediction_id: str = ""
    predicted_at: str = ""

    def __post_init__(self):
        if not self.prediction_id:
            self.prediction_id = f"outc_{uuid.uuid4().hex[:12]}"
        if not self.predicted_at:
            self.predicted_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        # 列表需要 JSON 序列化
        d["mc_samples"] = json.dumps(d["mc_samples"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomePrediction":
        if isinstance(d.get("mc_samples"), str):
            d["mc_samples"] = json.loads(d["mc_samples"])
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 历史 ROI 回归（简化版线性回归）
# ─────────────────────────────────────────────────────────────────────────────

class HistoricalROIRegessor:
    """
    从 outcome_log 表学习历史 ROI 分布参数。
    使用加权线性回归：ROI ~ β₀ + β₁·trend + β₂·supply + β₃·risk + β₄·margin
    """

    def __init__(self, kg_db: str = KG_DB):
        self.kg_db = kg_db
        self.beta: List[float] = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.residual_std: float = 1.0
        self.n_samples: int = 0
        self._fit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.kg_db)
        conn.row_factory = sqlite3.Row
        return conn

    def _fit(self):
        """用最小二乘法拟合历史 ROI 数据。"""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT verdict, roi_actual, net_margin_actual
            FROM outcome_log
            WHERE roi_actual IS NOT NULL
              AND roi_actual != 0
        """)
        rows = cur.fetchall()
        conn.close()

        if len(rows) < 3:
            logger.warning("历史ROI数据不足（<3条），使用默认参数")
            self.beta = [1.0, 0.15, 0.15, 0.15, 5.0]
            self.residual_std = 2.0
            self.n_samples = 0
            return

        # 准备 X（添加截距项）和 y
        X: List[List[float]] = []
        y: List[float] = []

        for r in rows:
            verdict = r["verdict"]
            roi = r["roi_actual"]
            margin = float(r["net_margin_actual"]) if r["net_margin_actual"] else 0.25
            # 历史数据中 trend/supply/risk 不可用 → 使用中性值 5.0
            # 注：最终预测时输入因子由调用方提供，这里仅建立 margin→ROI 先验
            trend = 5.0
            supply = 5.0
            risk = 5.0

            # 加权：成功的样本权重更高
            weight = 2.0 if verdict in ("INVEST", "success") else 1.0

            X.append([1.0, trend, supply, risk, margin])
            y.append(roi)

        # ── 简化 OLS（无 scipy 依赖，直接解正规方程）────────
        # β = (XᵀX)⁻¹ Xᵀy
        XtX = self._mat_mul(self._mat_transpose(X), X)
        Xty = self._mat_vec_mul(self._mat_transpose(X), y)
        try:
            XtX_inv = self._mat_inverse_2x2(XtX) if len(XtX) == 2 else self._pinv(XtX)
            self.beta = [sum(a * b for a, b in zip(row, Xty)) for row in XtX_inv]
        except Exception:
            logger.warning("矩阵求逆失败，使用默认参数")
            self.beta = [1.0, 0.15, 0.15, 0.15, 5.0]

        # 计算残差标准差
        residuals = []
        for i, row in enumerate(X):
            pred = sum(b * x for b, x in zip(self.beta, row))
            residuals.append(y[i] - pred)
        self.residual_std = (sum(r * r for r in residuals) / max(len(residuals) - 5, 1)) ** 0.5
        self.n_samples = len(rows)
        logger.info(f"ROI回归完成: n={self.n_samples}, β={self.beta}, σ={self.residual_std:.3f}")

    # ── 简单矩阵工具（避免 numpy 依赖）───────────────────

    @staticmethod
    def _mat_transpose(m: List[List[float]]) -> List[List[float]]:
        return list(map(list, zip(*m)))

    @staticmethod
    def _mat_mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
        return [
            [sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))]
            for i in range(len(a))
        ]

    @staticmethod
    def _mat_vec_mul(m: List[List[float]], v: List[float]) -> List[float]:
        return [sum(row[i] * v[i] for i in range(len(v))) for row in m]

    @staticmethod
    def _mat_inverse_2x2(m: List[List[float]]) -> List[List[float]]:
        """2×2 矩阵求逆"""
        det = m[0][0] * m[1][1] - m[0][1] * m[1][0]
        if abs(det) < 1e-10:
            raise ValueError("Singular matrix")
        inv = [
            [m[1][1] / det, -m[0][1] / det],
            [-m[1][0] / det, m[0][0] / det],
        ]
        return inv

    @staticmethod
    def _pinv(m: List[List[float]], eps: float = 1e-8) -> List[List[float]]:
        """伪逆（用于小型矩阵）"""
        # 转置乘自身，再求逆
        MtM = [[sum(m[k][i] * m[k][j] for k in range(len(m))) for j in range(len(m[0]))]
               for i in range(len(m[0]))]
        # 加正则化防止奇异
        for i in range(len(MtM)):
            MtM[i][i] += eps
        MtM_inv = [[MtM[j][i] for j in range(len(MtM))] for i in range(len(MtM[0]))]
        return [[sum(m[i][k] * MtM_inv[k][j] for k in range(len(m[0])))
                 for j in range(len(m[0]))] for i in range(len(m))]

    def predict(self, trend: float, supply: float, risk: float, margin: float) -> Tuple[float, float]:
        """
        预测 ROI 均值和残差标准差。
        返回 (predicted_roi_mean, residual_sigma)
        """
        X = [1.0, trend, supply, risk, margin]
        pred = sum(b * x for b, x in zip(self.beta, X))
        return pred, self.residual_std


# ─────────────────────────────────────────────────────────────────────────────
# 3. 多因子 → 概率转换（Logistic 映射）
# ─────────────────────────────────────────────────────────────────────────────

class ProbabilityMapper:
    """
    将多因子评分向量映射为成功概率 P(success)。

    公式：P = sigmoid(w · x + b)
    参数通过历史数据拟合，或使用经验默认值。
    """

    def __init__(self):
        # 经验权重（方向：越高越好的因子为正）
        # [trend, supply, risk, margin_scaled]
        # 归一化使各因子对概率贡献均衡
        self.weights: List[float] = [0.25, 0.20, 0.15, 0.25]
        self.bias: float = -1.2  # 基准偏移，使合理因子组合达到 50–70%

    def map(self, trend: float, supply: float, risk: float, margin_pct: float) -> float:
        """
        计算成功概率。

        Args:
            trend:      0–10 市场趋势
            supply:     0–10 供给优势
            risk:       0–10 风险等级（值越高风险越低）
            margin_pct: 毛利率，如 0.30

        Returns:
            P(success) ∈ [0, 1]
        """
        # 归一化到 0–1
        t = max(0.0, min(10.0, trend)) / 10.0
        s = max(0.0, min(10.0, supply)) / 10.0
        r = max(0.0, min(10.0, risk)) / 10.0
        m = max(0.0, min(1.0, margin_pct))

        score = self.weights[0] * t + self.weights[1] * s + self.weights[2] * r + self.weights[3] * m + self.bias
        prob = 1.0 / (1.0 + math.exp(-score))
        return round(prob, 4)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 蒙特卡洛模拟
# ─────────────────────────────────────────────────────────────────────────────

class MonteCarloSimulator:
    """
    基于预期 ROI 分布（正态分布）和成功概率，执行蒙特卡洛模拟。

    逻辑：
      - 若随机 < P(success)，则模拟成功分支：ROI ~ Normal(expected_roi, sigma)
      - 若随机 >= P(success)，模拟失败分支：ROI = -1.0（损失全部投资）
      - 收入估算：investment_usd * (1 + ROI)
    """

    def __init__(self, n_iterations: int = 5000, random_seed: int = 42):
        self.n_iterations = n_iterations
        self.rng = random.Random(random_seed)

    def run(
        self,
        expected_roi: float,
        roi_sigma: float,
        success_probability: float,
        investment_usd: float,
    ) -> Tuple[float, float, float, float, float, List[float]]:
        """
        运行 MC 模拟。

        Returns:
            (expected_roi, expected_revenue,
             worst_case_roi, best_case_roi,
             probability_of_loss,
             mc_samples)
        """
        if roi_sigma <= 0:
            roi_sigma = 0.5  # 默认 sigma 防止退化

        samples: List[float] = []
        loss_count = 0

        for _ in range(self.n_iterations):
            rnd = self.rng.random()
            if rnd < success_probability:
                # 成功分支：正态 ROI
                u1 = self.rng.random()
                u2 = self.rng.random()
                z = math.sqrt(-2 * math.log(u1 + 1e-10)) * math.cos(2 * math.pi * u2)
                roi = expected_roi + roi_sigma * z
            else:
                # 失败分支：损失全部投资
                roi = -1.0
                loss_count += 1

            samples.append(round(roi, 4))

        # 计算统计量
        mc_mean = sum(samples) / len(samples)
        sorted_samples = sorted(samples)
        p5_idx = max(0, int(0.05 * len(sorted_samples)))
        p95_idx = min(len(sorted_samples) - 1, int(0.95 * len(sorted_samples)))
        worst_case = sorted_samples[p5_idx]
        best_case = sorted_samples[p95_idx]
        prob_loss = loss_count / len(samples)

        # 预期收入
        expected_revenue = investment_usd * (1 + mc_mean)

        return (
            round(mc_mean, 4),
            round(expected_revenue, 2),
            round(worst_case, 4),
            round(best_case, 4),
            round(prob_loss, 4),
            samples,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Confidence Score
# ─────────────────────────────────────────────────────────────────────────────

class ConfidenceScorer:
    """
    综合置信度评估。

    因子：
      - data_quality_factor：历史样本数量（越多越好）
      - factor_certainty：输入因子是否完整、极端程度
      - model_stability：ROI 回归残差标准差（越小越稳定）
      - probability_extremity：概率是否接近 0.5（最不确定）
    """

    @staticmethod
    def compute(
        n_historical_samples: int,
        roi_sigma: float,
        success_probability: float,
        trend: float,
        supply: float,
        risk: float,
        margin_pct: float,
    ) -> Tuple[float, dict]:
        """
        计算综合置信度 0–1，并返回细分因子。
        """

        # ── 数据质量因子（0–0.4）─────────────────────────
        # 10+ 条历史数据时接近 0.4，0 条时为 0
        data_factor = min(0.4, n_historical_samples / 30 * 0.4)

        # ── 因子完整性因子（0–0.2）───────────────────────
        factor_count = sum([
            0 <= trend <= 10,
            0 <= supply <= 10,
            0 <= risk <= 10,
            0 <= margin_pct <= 1,
        ])
        completeness_factor = (factor_count / 4) * 0.2

        # ── 模型稳定性因子（0–0.2）───────────────────────
        # sigma 越小 → 稳定性越高
        # sigma 在 0–3 之间映射到 0.2–0
        stability_sigma = max(0.0, min(3.0, roi_sigma))
        stability_factor = (1 - stability_sigma / 3) * 0.2

        # ── 概率极端性因子（0–0.2）───────────────────────
        # 概率接近 0.5 时最不确定（0），接近 0 或 1 时最确定（0.2）
        p_centered = 1 - abs(success_probability - 0.5) * 2  # 0.5→1, 0/1→0
        extremity_factor = p_centered * 0.2

        total = data_factor + completeness_factor + stability_factor + extremity_factor
        confidence = max(0.05, min(0.99, round(total, 4)))

        factors = {
            "data_quality_factor": round(data_factor, 4),
            "completeness_factor": round(completeness_factor, 4),
            "stability_factor": round(stability_factor, 4),
            "extremity_factor": round(extremity_factor, 4),
        }

        return confidence, factors


# ─────────────────────────────────────────────────────────────────────────────
# 6. 预测回写 KG
# ─────────────────────────────────────────────────────────────────────────────

class KGWriter:
    """
    将 OutcomePrediction 写入 Knowledge Graph。
    目标表：kg_nodes（OutcomePrediction 节点）+ predictions（预测记录）
    """

    def __init__(self, kg_db: str = KG_DB):
        self.kg_db = kg_db

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.kg_db)
        conn.row_factory = sqlite3.Row
        return conn

    def write_prediction(self, pred: OutcomePrediction) -> bool:
        """
        将预测结果写入 kg_nodes + predictions 表。
        """
        node_id = f"OutcomePrediction_{pred.prediction_id}"
        ts = datetime.now().isoformat()
        properties = {
            "opp_id": pred.opp_id,
            "opp_name": pred.opp_name,
            "trend_score": pred.trend_score,
            "supply_score": pred.supply_score,
            "risk_score": pred.risk_score,
            "margin_pct": pred.margin_pct,
            "investment_usd": pred.investment_usd,
            "success_probability": pred.success_probability,
            "expected_roi": pred.expected_roi,
            "worst_case_roi": pred.worst_case_roi,
            "best_case_roi": pred.best_case_roi,
            "expected_revenue": pred.expected_revenue,
            "probability_of_loss": pred.probability_of_loss,
            "confidence_score": pred.confidence_score,
            "recommendation": pred.recommendation,
            "verdict": pred.verdict,
            "model_version": pred.model_version,
        }

        conn = self._conn()
        cur = conn.cursor()

        # ── 写入 kg_nodes ────────────────────────────────
        cur.execute("""
            INSERT OR REPLACE INTO kg_nodes
                (node_id, entity_type, name, properties,
                 created_at, updated_at, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            node_id,
            "OutcomePrediction",
            f"OutcomePrediction_{pred.opp_id}",
            json.dumps(properties),
            ts, ts,
            pred.confidence_score,
        ))

        # ── 写入 predictions 表 ─────────────────────────
        pred_id = f"outc_{uuid.uuid4().hex[:12]}"
        cur.execute("""
            INSERT INTO predictions
                (id, product_id, prediction_date, prediction_type,
                 horizon_days, predicted_value, predicted_low, predicted_high,
                 prediction_basis, model_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pred_id,
            pred.opp_id,
            datetime.now().date().isoformat(),
            "outcome_roi",
            90,
            round(pred.expected_roi, 4),
            round(pred.worst_case_roi, 4),
            round(pred.best_case_roi, 4),
            f"trend={pred.trend_score}, supply={pred.supply_score}, "
            f"risk={pred.risk_score}, margin={pred.margin_pct}",
            pred.model_version,
            ts,
        ))

        # ── 建立与 Opportunity 节点的关系 ───────────────
        opp_node_id = f"Opportunity_{pred.opp_id}"
        relation_id = f"generatesOutcome_{pred.prediction_id}"
        cur.execute("""
            INSERT OR IGNORE INTO kg_relations
                (relation_id, from_node, to_node, rel_type,
                 properties, created_at, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            relation_id,
            opp_node_id,
            node_id,
            "GENERATES_OUTCOME_PREDICTION",
            json.dumps({"prediction_id": pred.prediction_id}),
            ts,
            pred.confidence_score,
        ))

        conn.commit()
        conn.close()
        logger.info(f"Prediction written to KG: {node_id}")
        return True


# ─────────────────────────────────────────────────────────────────────────────
# 7. 决策引擎
# ─────────────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """
    基于概率和 ROI 估算，给出投资推荐。
    """

    @staticmethod
    def recommend(
        success_probability: float,
        expected_roi: float,
        worst_case_roi: float,
        probability_of_loss: float,
        confidence: float,
    ) -> Tuple[str, str]:
        """
        返回 (recommendation, verdict)

        recommendation: INVEST / HOLD / REJECT
        verdict: 短句理由
        """
        # 低置信度时倾向于 HOLD
        if confidence < 0.25:
            return "HOLD", f"置信度过低({confidence:.0%})，数据不足"

        # 高概率亏损 → REJECT
        if probability_of_loss > 0.55:
            return "REJECT", f"亏损概率{probability_of_loss:.0%}过高"

        # 预期ROI < 0（均值亏损）→ REJECT
        if expected_roi < 0:
            return "REJECT", f"预期ROI{expected_roi:.2f}x亏损"

        # 高成功概率 + 高ROI → INVEST
        if success_probability >= 0.65 and expected_roi >= 1.5:
            return "INVEST", f"高成功概率{success_probability:.0%}，ROI{expected_roi:.2f}x，看涨"

        if success_probability >= 0.55 and expected_roi >= 0.8:
            return "INVEST", f"预期ROI{expected_roi:.2f}x，成功率{success_probability:.0%}"

        # 较差情况
        if success_probability < 0.35:
            return "REJECT", f"成功率{success_probability:.0%}过低"

        # 中等区间
        return "HOLD", f"成功概率{success_probability:.0%}，预期ROI{expected_roi:.2f}x，建议观察"


# ─────────────────────────────────────────────────────────────────────────────
# 8. 主预测引擎
# ─────────────────────────────────────────────────────────────────────────────

class OutcomeEngine:
    """
    商业结果预测引擎——协调所有子模块的 Facade。
    """

    def __init__(
        self,
        kg_db: str = KG_DB,
        mc_iterations: int = 5000,
        random_seed: int = 42,
    ):
        self.kg_db = kg_db
        self.regressor = HistoricalROIRegessor(kg_db)
        self.probability_mapper = ProbabilityMapper()
        self.mc_simulator = MonteCarloSimulator(n_iterations=mc_iterations, random_seed=random_seed)
        self.confidence_scorer = ConfidenceScorer()
        self.kg_writer = KGWriter(kg_db)

    def predict(
        self,
        opp_id: str,
        opp_name: str = "",
        trend_score: float = 5.0,
        supply_score: float = 5.0,
        risk_score: float = 5.0,
        margin_pct: float = 0.25,
        investment_usd: float = 0.0,
        write_to_kg: bool = True,
    ) -> OutcomePrediction:
        """
        执行完整预测流程。

        Args:
            opp_id:         机会 ID（业务层）
            opp_name:       机会名称（可选）
            trend_score:    市场趋势（0–10）
            supply_score:   供给优势（0–10）
            risk_score:     风险等级（0–10，越高越安全）
            margin_pct:     毛利率（小数）
            investment_usd: 投资金额（USD，用于收入估算）
            write_to_kg:    是否回写 KG

        Returns:
            OutcomePrediction 对象
        """
        logger.info(
            f"Predicting outcome: opp_id={opp_id}, "
            f"trend={trend_score}, supply={supply_score}, "
            f"risk={risk_score}, margin={margin_pct:.0%}"
        )

        # ── Step 1: 概率映射 ──────────────────────────────
        prob = self.probability_mapper.map(trend_score, supply_score, risk_score, margin_pct)

        # ── Step 2: ROI 回归 ──────────────────────────────
        roi_mean, roi_sigma = self.regressor.predict(trend_score, supply_score, risk_score, margin_pct)

        # ── Step 3: 蒙特卡洛模拟 ──────────────────────────
        inv_usd = investment_usd if investment_usd > 0 else 50000.0  # 默认 5 万
        (mc_mean, expected_revenue, worst_case, best_case, prob_loss, samples) = \
            self.mc_simulator.run(roi_mean, roi_sigma, prob, inv_usd)

        # ── Step 4: Confidence Score ─────────────────────
        confidence, factors = self.confidence_scorer.compute(
            n_historical_samples=self.regressor.n_samples,
            roi_sigma=roi_sigma,
            success_probability=prob,
            trend=trend_score,
            supply=supply_score,
            risk=risk_score,
            margin_pct=margin_pct,
        )

        # ── Step 5: 决策推荐 ──────────────────────────────
        recommendation, verdict = DecisionEngine.recommend(
            success_probability=prob,
            expected_roi=mc_mean,
            worst_case_roi=worst_case,
            probability_of_loss=prob_loss,
            confidence=confidence,
        )

        # ── Step 6: 构建返回对象 ──────────────────────────
        prediction = OutcomePrediction(
            opp_id=opp_id,
            opp_name=opp_name or opp_id,
            trend_score=trend_score,
            supply_score=supply_score,
            risk_score=risk_score,
            margin_pct=margin_pct,
            investment_usd=inv_usd,
            success_probability=prob,
            historical_roi_mu=round(roi_mean, 4),
            historical_roi_sigma=round(roi_sigma, 4),
            mc_samples=samples[:200],  # 只保留前 200 个样本节省空间
            expected_roi=mc_mean,
            expected_revenue=round(expected_revenue, 2),
            worst_case_roi=worst_case,
            best_case_roi=best_case,
            probability_of_loss=prob_loss,
            confidence_score=confidence,
            confidence_factors=factors,
            recommendation=recommendation,
            verdict=verdict,
        )

        # ── Step 7: 写 KG ────────────────────────────────
        if write_to_kg:
            try:
                self.kg_writer.write_prediction(prediction)
            except Exception as e:
                logger.warning(f"KG write failed (non-fatal): {e}")

        return prediction


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outcome_engine.py",
        description="HVOS 商业结果预测引擎",
    )
    parser.add_argument("--opp_id", required=True, help="机会 ID（如 TEST001）")
    parser.add_argument("--opp_name", default="", help="机会名称（可选）")
    parser.add_argument("--trend", type=float, required=True, help="市场趋势评分 0–10")
    parser.add_argument("--supply", type=float, required=True, help="供给优势评分 0–10")
    parser.add_argument("--risk", type=float, required=True, help="风险等级评分 0–10（越高越安全）")
    parser.add_argument("--margin", type=float, required=True, help="毛利率（0.30 表示 30%%）")
    parser.add_argument("--invest_amt", type=float, default=50000.0, help="投资金额 USD（默认 50000）")
    parser.add_argument("--mc_iter", type=int, default=5000, help="蒙特卡洛迭代次数（默认 5000）")
    parser.add_argument("--no_write", action="store_true", help="禁止回写 KG")
    return parser


def _format_output(pred: OutcomePrediction) -> str:
    lines = [
        "",
        "═══════════════════════════════════════════════════════",
        "  HVOS Outcome Prediction",
        "═══════════════════════════════════════════════════════",
        f"  opp_id          : {pred.opp_id}  ({pred.opp_name})",
        f"  prediction_id   : {pred.prediction_id}",
        f"  predicted_at    : {pred.predicted_at}",
        "───────────────────────────────────────────────────────",
        "  INPUT FACTORS",
        f"    trend_score   : {pred.trend_score}/10  (市场趋势)",
        f"    supply_score  : {pred.supply_score}/10  (供给优势)",
        f"    risk_score    : {pred.risk_score}/10   (风险等级，越高越安全)",
        f"    margin_pct    : {pred.margin_pct:.1%}   (毛利率)",
        f"    investment    : ${pred.investment_usd:,.0f}",
        "───────────────────────────────────────────────────────",
        "  PROBABILITY MAPPING",
        f"    success_prob  : {pred.success_probability:.2%}",
        f"    historical_roi_mu : {pred.historical_roi_mu:.3f}x",
        f"    historical_roi_sigma : {pred.historical_roi_sigma:.3f}",
        "───────────────────────────────────────────────────────",
        "  MONTE CARLO SIMULATION",
        f"    expected_roi  : {pred.expected_roi:.3f}x",
        f"    expected_rev : ${pred.expected_revenue:,.0f}",
        f"    worst_case   : {pred.worst_case_roi:.3f}x  (5th pct)",
        f"    best_case    : {pred.best_case_roi:.3f}x  (95th pct)",
        f"    prob_of_loss : {pred.probability_of_loss:.2%}",
        "───────────────────────────────────────────────────────",
        "  CONFIDENCE SCORE",
        f"    overall       : {pred.confidence_score:.2%}",
    ]
    for k, v in pred.confidence_factors.items():
        lines.append(f"      {k:<26}: {v:.4f}")

    lines += [
        "───────────────────────────────────────────────────────",
        "  RECOMMENDATION",
        f"    {pred.recommendation}  ← {pred.verdict}",
        "═══════════════════════════════════════════════════════",
    ]
    return "\n".join(lines)


def main():
    parser = _build_parser()
    args = parser.parse_args()

    engine = OutcomeEngine(mc_iterations=args.mc_iter)

    result = engine.predict(
        opp_id=args.opp_id,
        opp_name=args.opp_name,
        trend_score=args.trend,
        supply_score=args.supply,
        risk_score=args.risk,
        margin_pct=args.margin,
        investment_usd=args.invest_amt,
        write_to_kg=not args.no_write,
    )

    print(_format_output(result))


if __name__ == "__main__":
    main()
