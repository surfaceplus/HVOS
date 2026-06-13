# Phase 3 RFE Closeout - Cart-Add Demand Signal

Generated: 2026-06-13T23:33:56
Run ID: 20260613233327

## Source Signal

- Sessions scanned: 67
- Cart sessions: 55
- Browse-only sessions: 12
- Cart events: 55
- Unique products: 17
- Attempted cart value: $1247.00

## Validation

- Total predictions: 51
- Matched actuals: 51
- Coverage: 100.0%
- Average error rate: 0.0%

## Top Cart-Add Products

| Product ID | Product | Cart Adds | Qty | Attempted Value | Demand Score |
| --- | --- | ---: | ---: | ---: | ---: |
| 7168 | Hiugift Ice Cubes Chilling Stones Set - Bar Accessories Gift | 7 | 7 | $98.00 | 114.80 |
| 7944 | Hiugift Premium Waterproof Throw Blanket - Soft Home Gift | 5 | 5 | $140.00 | 89.00 |
| 7121 | Hiugift 8.8 inch Stainless Steel Steak Knives - Premium Cutlery Gift | 5 | 5 | $90.00 | 84.00 |
| 7943 |  | 5 | 6 | $84.00 | 85.40 |
| 7090 | Hiugift Bluetooth Sleep Headband - Music & Sleep Gift | 4 | 4 | $152.00 | 75.20 |
| 6253 | Hiugift 3-in-1 Magnetic Wireless Charger - Fast Charge Gift Box | 4 | 4 | $128.00 | 72.80 |
| 7977 | Hiugift Personalized Wooden Piggy Bank - Creative Savings Gift | 4 | 4 | $80.00 | 68.00 |
| 6251 | Hiugift 3-In-1 Foldable Wireless Charging Station - Premium Tech Gift | 3 | 3 | $108.00 | 55.80 |
| 7472 | Hiugift Mini Ultrasonic Glasses Cleaning Machine - Tech Gift | 3 | 3 | $60.00 | 51.00 |
| 7842 | Hiugift Japanese BBQ Tongs Set - Premium Grill Gift | 3 | 3 | $33.00 | 48.30 |

## Created Pipeline

- `scripts/rfe/rfe_cart_collector.py`
- `scripts/rfe/rfe_demand_predictor.py`
- `scripts/rfe/rfe_validator.py`
- `scripts/rfe/run_phase3_pipeline.py`
