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


def _load_snapshot(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _prediction_id(product_id: str, prediction_type: str, run_id: str) -> str:
    return f"phase3_{run_id}_{product_id}_{prediction_type}"


def _insert_prediction(
    conn: sqlite3.Connection,
    *,
    prediction_id: str,
    product_id: str,
    prediction_type: str,
    horizon_days: int,
    predicted_value: float,
    low: float,
    high: float,
    basis: str,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT OR REPLACE INTO predictions
          (id, product_id, prediction_date, prediction_type, horizon_days,
           predicted_value, predicted_low, predicted_high, prediction_basis,
           model_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prediction_id,
            product_id,
            date.today().isoformat(),
            prediction_type,
            horizon_days,
            round(predicted_value, 4),
            round(low, 4),
            round(high, 4),
            basis,
            MODEL_VERSION,
            now,
        ),
    )


def generate_predictions(input_path: Path = DEFAULT_INPUT, db_path: Path = KG_DB, run_id: str | None = None) -> dict[str, object]:
    snapshot = _load_snapshot(input_path)
    products = snapshot.get("products", [])
    if not isinstance(products, list):
        raise ValueError("Cart snapshot does not contain a products list.")

    run_id = run_id or datetime.now().strftime("%Y%m%d%H%M%S")
    window_days = float(snapshot.get("window_days", 7) or 7)
    scale_to_30d = 30.0 / window_days
    prediction_ids: list[str] = []

    print(f"[RFE Predict] Generating Phase 3 predictions for {len(products)} products...")
    with sqlite3.connect(db_path) as conn:
        for product in products:
            product_id = str(product["product_id"])
            product_name = str(product.get("product_name") or "")
            cart_add_count = float(product.get("cart_add_count", 0) or 0)
            total_value = float(product.get("total_value", 0) or 0)
            demand_score = float(product.get("demand_intensity_score", 0) or 0)
            basis_common = (
                f"Phase 3 cart-add RFE. Prior {window_days:g}d observed "
                f"{cart_add_count:g} cart adds, attempted value ${total_value:.2f}. "
                f"Product: {product_name or product_id}."
            )

            forecast_count = cart_add_count * scale_to_30d
            count_id = _prediction_id(product_id, "cart_add_count_30d", run_id)
            _insert_prediction(
                conn,
                prediction_id=count_id,
                product_id=product_id,
                prediction_type="cart_add_count_30d",
                horizon_days=30,
                predicted_value=forecast_count,
                low=max(forecast_count * 0.7, 0.0),
                high=forecast_count * 1.3,
                basis=f"{basis_common} Forecast = observed cart adds scaled to 30d.",
            )
            prediction_ids.append(count_id)

            conversion_id = _prediction_id(product_id, "cart_conversion_rate_30d", run_id)
            _insert_prediction(
                conn,
                prediction_id=conversion_id,
                product_id=product_id,
                prediction_type="cart_conversion_rate_30d",
                horizon_days=30,
                predicted_value=0.0,
                low=0.0,
                high=0.0,
                basis=f"{basis_common} Current validated sales are zero, so cart-to-purchase rate remains 0%.",
            )
            prediction_ids.append(conversion_id)

            score_id = _prediction_id(product_id, "demand_intensity_score", run_id)
            _insert_prediction(
                conn,
                prediction_id=score_id,
                product_id=product_id,
                prediction_type="demand_intensity_score",
                horizon_days=30,
                predicted_value=demand_score,
                low=max(demand_score * 0.75, 0.0),
                high=demand_score * 1.25,
                basis=f"{basis_common} Weighted score uses cart count, quantity, session breadth, and attempted value.",
            )
            prediction_ids.append(score_id)
        conn.commit()

    print(f"[RFE Predict] Stored {len(prediction_ids)} predictions in {db_path}.")
    return {"run_id": run_id, "prediction_ids": prediction_ids, "product_count": len(products)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate cart-demand predictions into kg.db.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--db", type=Path, default=KG_DB)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    generate_predictions(args.input, args.db, args.run_id)


if __name__ == "__main__":
    main()
