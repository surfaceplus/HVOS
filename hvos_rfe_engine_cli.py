"""
HVOS 核心引擎 — 真实世界反馈系统 (Reality Feedback Engine)
============================================================
核心理念：预测必须被验证。
记录每次预测，30天后录入真实数据，计算 Prediction Error，自动修正模型。

使用方法：
  python hvos_rfe_engine.py --action record_prediction --product_id prod_xxx --type sales --horizon 30 --value 350 --low 280 --high 420 --basis "基于TikTok播放量测算"
  python hvos_rfe_engine.py --action record_actual --prediction_id xxx --actual 295
  python hvos_rfe_engine.py --action status
  python hvos_rfe_engine.py --action error_trend
"""

import sqlite3
import json
import uuid
import sys
import os
from datetime import datetime, date, timedelta

KG_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_graph", "kg.db")

def get_conn():
    return sqlite3.connect(KG_DB)


def calculate_prediction_error(predicted, actual):
    """
    计算预测误差
    返回: (error_rate, direction, verdict)
    """
    if actual == 0:
        error_rate = abs(predicted) * 100 if predicted > 0 else 0
    else:
        error_rate = abs(predicted - actual) / actual * 100

    direction = "over" if predicted > actual else "under"

    if error_rate < 10:
        verdict = "高精准"
    elif error_rate < 20:
        verdict = "可接受"
    elif error_rate < 40:
        verdict = "偏差大"
    else:
        verdict = "严重偏差"

    return round(error_rate, 1), direction, verdict


def record_prediction(product_id, pred_type, horizon_days, predicted_value,
                     predicted_low=None, predicted_high=None, basis="", model_version="v1.0"):
    """
    记录一次预测
    """
    conn = get_conn()
    cur = conn.cursor()
    pred_id = f"pred_{pred_type}_{horizon_days}d_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    cur.execute("""INSERT INTO predictions 
        (id, product_id, prediction_date, prediction_type, horizon_days,
         predicted_value, predicted_low, predicted_high, prediction_basis, model_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pred_id, product_id, date.today().isoformat(), pred_type, horizon_days,
         predicted_value, predicted_low, predicted_high, basis, model_version,
         datetime.now().isoformat()))

    conn.commit()
    print(f"[RFE] 预测记录: {pred_id}")
    print(f"       产品: {product_id} | 类型: {pred_type} | 周期: {horizon_days}天")
    print(f"       预测值: {predicted_value} (区间: {predicted_low}-{predicted_high})")
    return pred_id


def record_actual(prediction_id, actual_value, data_source="manual", notes=""):
    """
    录入实际结果，自动计算误差
    """
    conn = get_conn()
    cur = conn.cursor()

    # 获取原始预测
    cur.execute("SELECT product_id, prediction_type, horizon_days, predicted_value, predicted_low, predicted_high, prediction_basis FROM predictions WHERE id=?", (prediction_id,))
    row = cur.fetchone()
    if not row:
        print(f"[RFE] 错误：未找到预测记录 {prediction_id}")
        return None

    product_id, pred_type, horizon_days, pred_val, pred_low, pred_high, basis = row
    actual_id = f"actual_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # 录入实际值
    cur.execute("""INSERT INTO actuals (id, prediction_id, actual_date, actual_value, data_source, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actual_id, prediction_id, date.today().isoformat(), actual_value, data_source, notes,
         datetime.now().isoformat()))

    # 计算误差
    error_rate, direction, verdict = calculate_prediction_error(pred_val, actual_value)

    # 记录误差
    error_id = f"err_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    cur.execute("""INSERT INTO prediction_errors (id, prediction_id, actual_id, error_rate, error_direction, error_category, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (error_id, prediction_id, actual_id, error_rate, direction, verdict, datetime.now().isoformat()))

    conn.commit()

    print(f"\n[RFE] 实际结果录入完成 ✅")
    print(f"       预测值: {pred_val} | 实际值: {actual_value}")
    print(f"       误差率: {error_rate}% | 方向: {direction} | 判定: {verdict}")

    if error_rate > 30:
        print(f"       ⚠️  误差超过 30%，建议触发模型复盘")

    return actual_id


def get_model_bias_summary(days=90):
    """
    获取模型偏见摘要
    """
    conn = get_conn()
    cur = conn.cursor()

    since_date = (date.today() - timedelta(days=days)).isoformat()

    print(f"\n{'='*60}")
    print(f"  RFE 模型偏见摘要（近{days}天）")
    print(f"{'='*60}")

    # 按预测类型统计误差
    cur.execute("""SELECT p.prediction_type, 
                          COUNT(*) as n,
                          AVG(pe.error_rate) as avg_error,
                          SUM(CASE WHEN pe.error_direction='over' THEN 1 ELSE 0 END) as over_count,
                          SUM(CASE WHEN pe.error_direction='under' THEN 1 ELSE 0 END) as under_count
                   FROM prediction_errors pe
                   JOIN predictions p ON pe.prediction_id = p.id
                   WHERE pe.created_at >= ?
                   GROUP BY p.prediction_type""", (since_date,))

    rows = cur.fetchall()

    if not rows:
        print("\n  暂无预测误差数据")
        return

    overall_avg_error = sum(r[2] * r[1] for r in rows) / sum(r[1] for r in rows)
    print(f"\n  整体平均误差率: {overall_avg_error:.1f}%\n")

    for pred_type, n, avg_err, over_c, under_c in rows:
        bias = "高估" if over_c > under_c else "低估"
        bias_magnitude = abs(over_c - under_c) / n * 100
        emoji = "🟢" if avg_err < 15 else "🟡" if avg_err < 30 else "🔴"
        print(f"  {emoji} {pred_type.upper()}（{n}条样本）")
        print(f"     平均误差: {avg_err:.1f}% | 系统性偏差: {bias}（{bias_magnitude:.0f}%）")

    print(f"\n{'='*60}")


def get_error_trend(days=90):
    """
    获取误差趋势（月度）
    """
    conn = get_conn()
    cur = conn.cursor()

    since_date = (date.today() - timedelta(days=days)).isoformat()

    cur.execute("""SELECT strftime('%Y-%m', pe.created_at) as month,
                          AVG(pe.error_rate) as avg_error,
                          COUNT(*) as n
                   FROM prediction_errors pe
                   WHERE pe.created_at >= ?
                   GROUP BY month
                   ORDER BY month""", (since_date,))

    rows = cur.fetchall()

    print(f"\n{'='*60}")
    print(f"  RFE 误差趋势（近{days}天）")
    print(f"{'='*60}\n")

    if not rows:
        print("  暂无数据")
        return

    prev_error = None
    for month, avg_err, n in rows:
        trend = ""
        if prev_error:
            diff = avg_err - prev_error
            trend = "↓ 改善" if diff < 0 else "→ 持平" if abs(diff) < 3 else "↑ 恶化"
        bar_len = int(avg_err / 2)
        bar = "█" * bar_len + "░" * (25 - bar_len)
        print(f"  {month}  {bar}  {avg_err:.1f}% ({n}条) {trend}")
        prev_error = avg_err

    print(f"\n{'='*60}")


def rfe_status():
    """
    打印 RFE 系统状态
    """
    conn = get_conn()
    cur = conn.cursor()

    print(f"\n{'='*60}")
    print(f"  HVOS Reality Feedback Engine — SYSTEM STATUS")
    print(f"{'='*60}")

    cur.execute("SELECT COUNT(*) FROM predictions")
    pred_count = cur.fetchone()[0]
    print(f"\n  预测记录总数: {pred_count}")

    cur.execute("SELECT COUNT(*) FROM actuals")
    actual_count = cur.fetchone()[0]
    print(f"  实际结果录入: {actual_count}")

    if pred_count > 0 and actual_count > 0:
        cur.execute("SELECT AVG(error_rate) FROM prediction_errors")
        avg_err = cur.fetchone()[0] or 0
        print(f"  平均误差率: {avg_err:.1f}%")

        cur.execute("SELECT COUNT(*) FROM prediction_errors WHERE error_rate < 20")
        good = cur.fetchone()[0]
        print(f"  高精准/可接受: {good}/{actual_count} 条")

    # 待录入的预测（超过Horizon仍未录入）
    cur.execute("""SELECT p.id, p.product_id, p.prediction_type, p.horizon_days, p.predicted_value, p.prediction_date
                   FROM predictions p
                   WHERE p.id NOT IN (SELECT prediction_id FROM actuals)
                   ORDER BY p.prediction_date""")
    pending = cur.fetchall()

    if pending:
        print(f"\n  ⚠️  待录入实际结果: {len(pending)} 条")
        for row in pending[:5]:
            days_since = (date.today() - date.fromisoformat(str(row[5]))).days
            overdue = f"（已逾期 {days_since - row[3]} 天）" if days_since > row[3] else ""
            print(f"    {row[0]} | {row[2]} {row[3]}d | 预测:{row[4]} {overdue}")
        if len(pending) > 5:
            print(f"    ... 还有 {len(pending)-5} 条")

    print(f"\n{'='*60}")


def trigger_model_review(prediction_id, notes=""):
    """
    触发模型复盘
    """
    conn = get_conn()
    cur = conn.cursor()

    evo_id = f"evo_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # 获取相关预测信息
    cur.execute("""SELECT p.product_id, p.prediction_type, p.horizon_days, p.predicted_value,
                           a.actual_value, pe.error_rate, pe.error_direction
                    FROM predictions p
                    JOIN actuals a ON a.prediction_id = p.id
                    JOIN prediction_errors pe ON pe.actual_id = a.id
                    WHERE p.id = ?""", (prediction_id,))
    row = cur.fetchone()

    if not row:
        print("[RFE] 未找到对应的预测-实际配对记录")
        return

    product_id, pred_type, horizon, pred_val, actual_val, err_rate, direction = row

    print(f"\n[RFE] 触发模型复盘: {evo_id}")
    print(f"       预测类型: {pred_type} | Horizon: {horizon}天")
    print(f"       预测值: {pred_val} | 实际值: {actual_val}")
    print(f"       误差率: {err_rate}% | 方向: {direction}")
    print(f"       建议人工分析: 5Why 根因分析")

    return evo_id


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS 真实世界反馈引擎")
    parser.add_argument("--action", required=True,
                        choices=["record_prediction", "record_actual", "status",
                                 "error_trend", "model_bias", "model_review", "trigger_review"],
                        help="操作类型")
    parser.add_argument("--product_id", help="产品节点ID")
    parser.add_argument("--type", help="预测类型: sales/cpa/cvr/roas/margin")
    parser.add_argument("--horizon", type=int, help="预测周期（天）")
    parser.add_argument("--value", type=float, help="预测值")
    parser.add_argument("--low", type=float, help="预测下限")
    parser.add_argument("--high", type=float, help="预测上限")
    parser.add_argument("--basis", default="", help="预测依据")
    parser.add_argument("--model", default="v1.0", help="模型版本")
    parser.add_argument("--prediction_id", help="预测ID（录入实际值时用）")
    parser.add_argument("--actual", type=float, help="实际值")
    parser.add_argument("--source", default="manual", help="数据来源")
    parser.add_argument("--notes", default="", help="备注")
    parser.add_argument("--days", type=int, default=90, help="统计天数")
    parser.add_argument("--evidence", help="修正证据（JSON格式）")

    args = parser.parse_args()

    if args.action == "status":
        rfe_status()

    elif args.action == "record_prediction":
        if not all([args.product_id, args.type, args.horizon, args.value is not None]):
            print("[RFE] 错误：需要 --product_id --type --horizon --value")
            sys.exit(1)
        record_prediction(args.product_id, args.type, args.horizon, args.value,
                         args.low, args.high, args.basis, args.model)

    elif args.action == "record_actual":
        if not all([args.prediction_id, args.actual is not None]):
            print("[RFE] 错误：需要 --prediction_id --actual")
            sys.exit(1)
        record_actual(args.prediction_id, args.actual, args.source, args.notes)

    elif args.action == "error_trend":
        get_error_trend(args.days)

    elif args.action == "model_bias":
        get_model_bias_summary(args.days)

    elif args.action == "trigger_review":
        if not args.prediction_id:
            print("[RFE] 错误：需要 --prediction_id")
            sys.exit(1)
        trigger_model_review(args.prediction_id, args.notes)

    elif args.action == "model_review":
        print("\n[模型复盘指南]")
        print("="*60)
        print("""
  当 Prediction Error > 30% 时，执行以下分析：

  1. 计算具体误差
  2. 判断失败类型（DATA_ERROR/MODEL_ASSUMPTION_ERROR/BIAS_ACCUMULATION）
  3. 5Why 根因分析
  4. 生成修正规则
  5. 更新 Skill 文件

  示例 5Why 分析：
    销量预测高估 200%

    Why1: 为什么实际销量远低于预测？
    → 因为自然流量远低于预期

    Why2: 为什么自然流量远低于预期？
    → 因为 SEO 关键词排名没有起来

    Why3: 为什么 SEO 没有起来？
    → 因为新品评论太少（4条），信任度不足

    Why4: 为什么评论积累这么慢？
    → 因为 CVR 太低，100访客只有1个购买

    Why5: 为什么 CVR 这么低？
    → 因为 listing 缺少 A+ 内容，主图不够吸引人

    Root Cause：listing 质量不足
    Proposed Fix：新品前30天 CVR 默认假设从 2.5% 降至 1.2%
        """)
