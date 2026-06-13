from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rfe.rfe_cart_collector import DEFAULT_OUTPUT, collect_cart_demand
from scripts.rfe.rfe_demand_predictor import KG_DB, generate_predictions
from scripts.rfe.rfe_validator import validate_predictions


DEFAULT_REPORT = REPO_ROOT / "board-meetings" / "phase3_closeout_20260613.md"


def _write_report(
    report_path: Path,
    snapshot: dict[str, object],
    prediction_result: dict[str, object],
    validation: dict[str, object],
) -> None:
    products = snapshot.get("products", [])
    if not isinstance(products, list):
        products = []
    top_products = products[:10]
    lines = [
        "# Phase 3 RFE Closeout - Cart-Add Demand Signal",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Run ID: {prediction_result['run_id']}",
        "",
        "## Source Signal",
        "",
        f"- Sessions scanned: {snapshot.get('session_count', 0)}",
        f"- Cart sessions: {snapshot.get('cart_session_count', 0)}",
        f"- Browse-only sessions: {snapshot.get('browse_only_session_count', 0)}",
        f"- Cart events: {snapshot.get('cart_event_count', 0)}",
        f"- Unique products: {snapshot.get('unique_product_count', 0)}",
        f"- Attempted cart value: ${float(snapshot.get('total_cart_value', 0) or 0):.2f}",
        "",
        "## Validation",
        "",
        f"- Total predictions: {validation['total_predictions']}",
        f"- Matched actuals: {validation['matched_actuals']}",
        f"- Coverage: {validation['coverage_pct']}%",
        f"- Average error rate: {validation['avg_error_rate']}%",
        "",
        "## Top Cart-Add Products",
        "",
        "| Product ID | Product | Cart Adds | Qty | Attempted Value | Demand Score |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for product in top_products:
        lines.append(
            "| {product_id} | {name} | {adds} | {qty} | ${value:.2f} | {score:.2f} |".format(
                product_id=product.get("product_id", ""),
                name=str(product.get("product_name") or "").replace("|", "\\|"),
                adds=int(product.get("cart_add_count", 0) or 0),
                qty=int(product.get("total_qty", 0) or 0),
                value=float(product.get("total_value", 0) or 0),
                score=float(product.get("demand_intensity_score", 0) or 0),
            )
        )
    lines.extend(
        [
            "",
            "## Created Pipeline",
            "",
            "- `scripts/rfe/rfe_cart_collector.py`",
            "- `scripts/rfe/rfe_demand_predictor.py`",
            "- `scripts/rfe/rfe_validator.py`",
            "- `scripts/rfe/run_phase3_pipeline.py`",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[RFE Pipeline] Markdown report written: {report_path}")


def run_pipeline(snapshot_path: Path = DEFAULT_OUTPUT, db_path: Path = KG_DB, report_path: Path = DEFAULT_REPORT) -> dict[str, object]:
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    print("[RFE Pipeline] Step 1/3: collect cart events")
    snapshot = collect_cart_demand(snapshot_path)
    print("[RFE Pipeline] Step 2/3: generate demand predictions")
    prediction_result = generate_predictions(snapshot_path, db_path, run_id)
    print("[RFE Pipeline] Step 3/3: validate predictions")
    validation = validate_predictions(snapshot_path, db_path, run_id)
    _write_report(report_path, snapshot, prediction_result, validation)
    print("[RFE Pipeline] Complete.")
    return {"snapshot": snapshot, "predictions": prediction_result, "validation": validation}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 3 RFE cart-demand pipeline.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--db", type=Path, default=KG_DB)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    run_pipeline(args.snapshot, args.db, args.report)


if __name__ == "__main__":
    main()
