"""HVOS V10.2 - RFE + Event Backbone Integration"""
from __future__ import annotations
import sqlite3, json, uuid, logging, os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
KG_DB = rf"{HVOS_ROOT}\knowledge-graph\kg.db"

# Try to import event backbone, gracefully degrade if not available
try:
    from hvos_event_backbone import HvosEventSystem
    _eb_available = True
except Exception:
    _eb_available = False
    HvosEventSystem = None


def get_conn():
    conn = sqlite3.connect(KG_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def calculate_prediction_error(predicted, actual):
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


def record_prediction(
    product_id: str,
    pred_type: str,
    horizon_days: int,
    predicted_value: float,
    predicted_low: Optional[float] = None,
    predicted_high: Optional[float] = None,
    basis: str = "",
    model_version: str = "v1.0",
    causation_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """
    Record a prediction + emit PREDICTION_RECORDED event to Event Backbone.
    """
    conn = get_conn()
    cur = conn.cursor()
    pred_id = f"pred_{pred_type}_{horizon_days}d_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

    try:
        cur.execute(
            """INSERT INTO predictions
            (id, product_id, prediction_date, prediction_type, horizon_days,
             predicted_value, predicted_low, predicted_high, prediction_basis, model_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pred_id, product_id, datetime.now().date().isoformat(), pred_type, horizon_days,
                predicted_value, predicted_low, predicted_high, basis, model_version,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise e
    conn.close()

    # Emit event to Event Backbone
    if _eb_available and HvosEventSystem is not None:
        try:
            eb = HvosEventSystem()
            ev = eb.emit(
                event_type="PREDICTION_RECORDED",
                payload={
                    "prediction_id": pred_id,
                    "product_id": product_id,
                    "pred_type": pred_type,
                    "horizon_days": horizon_days,
                    "predicted_value": predicted_value,
                    "predicted_low": predicted_low,
                    "predicted_high": predicted_high,
                    "basis": basis,
                    "model_version": model_version,
                },
                partition_key=product_id,
                causation_id=causation_id,
                correlation_id=correlation_id,
                source="hvos_rfe_engine",
            )
            logger.info(f"[RFE] Emitted PREDICTION_RECORDED: {pred_id} seq={ev.sequence}")
        except Exception as e:
            logger.warning(f"[RFE] Failed to emit event: {e}")

    return pred_id


def record_actual(
    prediction_id: str,
    actual_value: float,
    data_source: str = "manual",
    notes: str = "",
    causation_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Record actual result + compute error + emit ACTUAL_RECORDED and PREDICTION_ERROR_COMPUTED events.
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT product_id, prediction_type, horizon_days, predicted_value, predicted_low, predicted_high FROM predictions WHERE id=?",
        (prediction_id,),
    )
    row = cur.fetchone()
    if not row:
        print(f"[RFE] Error: prediction {prediction_id} not found")
        return None

    product_id, pred_type, horizon_days, pred_val, pred_low, pred_high = row
    error_rate, direction, verdict = calculate_prediction_error(pred_val or 0, actual_value)

    uid = uuid.uuid4().hex[:6]
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    actual_id = f"actual_{ts}_{uid}"
    try:
        cur.execute(
            """INSERT INTO actuals
            (id, prediction_id, actual_date, actual_value, data_source, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                actual_id, prediction_id, datetime.now().date().isoformat(), actual_value,
                data_source, notes, datetime.now().isoformat(),
            ),
        )

        error_id = f"err_{ts}_{uid}"
        error_category = "model_bias" if abs(error_rate) < 20 else "systematic_error" if abs(error_rate) < 40 else "anomaly"
        model_bias = "high" if error_rate > 15 else "low" if error_rate < 5 else "medium"

        cur.execute(
            """INSERT INTO prediction_errors
            (id, prediction_id, actual_id, error_rate, error_direction, error_category, model_bias, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (error_id, prediction_id, actual_id, error_rate, direction, error_category, model_bias, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise e
    conn.close()

    # Emit events to Event Backbone
    if _eb_available and HvosEventSystem is not None:
        try:
            eb = HvosEventSystem()
            # Emit ACTUAL_RECORDED
            ev1 = eb.emit(
                event_type="ACTUAL_RECORDED",
                payload={
                    "actual_id": actual_id,
                    "prediction_id": prediction_id,
                    "product_id": product_id,
                    "actual_value": actual_value,
                    "data_source": data_source,
                },
                partition_key=product_id,
                causation_id=prediction_id,
                correlation_id=correlation_id,
                source="hvos_rfe_engine",
            )
            # Emit PREDICTION_ERROR_COMPUTED
            ev2 = eb.emit(
                event_type="PREDICTION_ERROR_COMPUTED",
                payload={
                    "error_id": error_id,
                    "prediction_id": prediction_id,
                    "actual_id": actual_id,
                    "product_id": product_id,
                    "predicted_value": pred_val,
                    "actual_value": actual_value,
                    "error_rate": error_rate,
                    "direction": direction,
                    "verdict": verdict,
                    "error_category": error_category,
                    "model_bias": model_bias,
                },
                partition_key=product_id,
                causation_id=ev1.event_id,
                correlation_id=correlation_id,
                source="hvos_rfe_engine",
            )
            logger.info(f"[RFE] Emitted ACTUAL_RECORDED (seq={ev1.sequence}) and PREDICTION_ERROR_COMPUTED (seq={ev2.sequence})")
        except Exception as e:
            logger.warning(f"[RFE] Failed to emit events: {e}")

    return {
        "error_id": error_id,
        "actual_id": actual_id,
        "error_rate": error_rate,
        "direction": direction,
        "verdict": verdict,
        "error_category": error_category,
        "model_bias": model_bias,
    }


if __name__ == "__main__":
    import sys
    # Quick CLI test
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        pid = record_prediction(
            product_id="test_product_001",
            pred_type="monthly_profit",
            horizon_days=30,
            predicted_value=10525,
            predicted_low=5262,
            predicted_high=15788,
            basis="BSR=500 1688成本模型 V10.1",
            model_version="V10.1-BSR",
        )
        print(f"Recorded prediction: {pid}")
        # Record actual after a short delay
        result = record_actual(pid, 9800, data_source="woo_commerce", notes="First month actual")
        if result:
            print(f"Error: {result['error_rate']}% verdict={result['verdict']}")
