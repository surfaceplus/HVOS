from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
KG_DB = REPO_ROOT / "knowledge_graph" / "kg.db"
DEFAULT_INPUT = REPO_ROOT / "data" / "real_cart_events.json"
MODEL_VERSION = "phase3-cart-demand-v1"
PREDICTION_TYPES = (
    "cart_add_count_30d",
    "cart_conversion_rate_30d",
    "demand_intensity_score",
)


def _load_actuals(path: Path) -> dict[tuple[str, str], float]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    window_days = float(snapshot.get("window_days", 7) or 7)
    scale_to_30d = 30.0 / window_days
    actuals: dict[tuple[str, str], float] = {}
    for product in snapshot.get("products", []):
        product_id = str(product["product_id"])
        observed_cart_adds = float(product.get("cart_add_count", 0) or 0)
        actuals[(product_id, "cart_add_count_30d")] = observed_cart_adds * scale_to_30d
        actuals[(product_id, "cart_conversion_rate_30d")] = 0.0
        actuals[(product_id, "demand_intensity_score")] = float(product.get("demand_intensity_score", 0) or 0)
    return actuals


def _error_category(error_rate: float) -> str:
    if error_rate < 10:
        return "high_accuracy"
    if error_rate < 20:
        return "acceptable"
    if error_rate < 40:
        return "material_error"
    return "severe_error"


def _calculate_error(predicted: float, actual: float) -> tuple[float, str, float]:
    if actual == 0:
        error_rate = 0.0 if predicted == 0 else abs(predicted) * 100.0
    else:
        error_rate = abs(predicted - actual) / abs(actual) * 100.0
    if predicted > actual:
        direction = "over"
    elif predicted < actual:
        direction = "under"
    else:
        direction = "match"
    model_bias = predicted - actual
    return round(error_rate, 4), direction, round(model_bias, 4)


def _actual_id(prediction_id: str) -> str:
    return f"actual_{prediction_id}"


def _error_id(prediction_id: str) -> str:
    return f"err_{prediction_id}"


def validate_predictions(
    input_path: Path = DEFAULT_INPUT,
    db_path: Path = KG_DB,
    run_id: str | None = None,
) -> dict[str, object]:
    cart_actuals = _load_actuals(input_path)
    params: list[object] = [MODEL_VERSION, *PREDICTION_TYPES]
    run_filter = ""
    if run_id:
        run_filter = "AND id LIKE ?"
        params.append(f"phase3_{run_id}_%")

    placeholders = ",".join("?" for _ in PREDICTION_TYPES)
    sql = f"""
        SELECT id, product_id, prediction_type, predicted_value
        FROM predictions
        WHERE model_version = ?
          AND prediction_type IN ({placeholders})
          {run_filter}
        ORDER BY created_at, id
    """

    now = datetime.now().isoformat(timespec="seconds")
    matched = 0
    error_rates: list[float] = []
    actual_records = 0

    print("[RFE Validate] Matching predictions to cart-derived actuals...")
    with sqlite3.connect(db_path) as conn:
        predictions = conn.execute(sql, params).fetchall()
        for prediction_id, product_id, prediction_type, predicted_value in predictions:
            key = (str(product_id), str(prediction_type))
            if key not in cart_actuals:
                continue
            actual_value = cart_actuals[key]
            actual_id = _actual_id(str(prediction_id))
            err_id = _error_id(str(prediction_id))
            error_rate, direction, model_bias = _calculate_error(float(predicted_value), actual_value)

            conn.execute(
                """
                INSERT OR REPLACE INTO actuals
                  (id, prediction_id, actual_date, actual_value, data_source, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    actual_id,
                    prediction_id,
                    date.today().isoformat(),
                    round(actual_value, 4),
                    "woocommerce_cart_sessions",
                    f"Phase 3 cart-add actual matched by product_id={product_id}, prediction_type={prediction_type}",
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO prediction_errors
                  (id, prediction_id, actual_id, error_rate, error_direction,
                   error_category, model_bias, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    err_id,
                    prediction_id,
                    actual_id,
                    error_rate,
                    direction,
                    _error_category(error_rate),
                    model_bias,
                    now,
                ),
            )
            matched += 1
            error_rates.append(error_rate)
        conn.commit()
        actual_records = conn.execute(
            """
            SELECT COUNT(*)
            FROM actuals a
            JOIN predictions p ON p.id = a.prediction_id
            WHERE p.model_version = ?
            """,
            (MODEL_VERSION,),
        ).fetchone()[0]

    total_predictions = len(predictions)
    coverage = (matched / total_predictions * 100.0) if total_predictions else 0.0
    avg_error = (sum(error_rates) / len(error_rates)) if error_rates else 0.0
    summary = {
        "total_predictions": total_predictions,
        "matched_actuals": matched,
        "total_actuals": actual_records,
        "coverage_pct": round(coverage, 2),
        "avg_error_rate": round(avg_error, 2),
    }
    print("[RFE Validate] Summary")
    print(f"  total predictions: {summary['total_predictions']}")
    print(f"  matched actuals:   {summary['matched_actuals']}")
    print(f"  coverage:          {summary['coverage_pct']}%")
    print(f"  avg error rate:    {summary['avg_error_rate']}%")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate cart-demand predictions against cart actuals.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--db", type=Path, default=KG_DB)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    validate_predictions(args.input, args.db, args.run_id)


if __name__ == "__main__":
    main()
