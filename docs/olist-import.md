# Olist SQLite import (V1, option 1)

The nine original files remain in `datasets/brazilian-ecommerce/`. The imported database is `datasets/olist.db`. No nested CSV discovery, cross-file join engine, or folder-import UI was added. Northwind remains independent.

## Repeatable import

From the repository root:

```sh
python server/scripts/import_olist.py
```

The script uses only the Python standard library. It validates explicit CSV headers/types, stages a database under a hidden unsupported suffix, checks source hashes again after import, validates integrity/foreign keys and monetary reconciliation, closes the database and atomically publishes it. A receipt in `workspace/imports/olist.json` records source SHA-256 values, schema version, source-to-column mapping, counts, totals and database checksum. It is outside the dataset catalog.

Running unchanged inputs again returns `unchanged: true`, without changing the database timestamp or appending rows. Changed inputs require `--replace`; stop the backend and retain the previous database/receipt before using it. The replacement must be importer-owned. Invalid input is rejected without replacing the published database. The importer refuses output names other than `olist.db`, protecting unrelated databases.

## Tables and data contract

| Table | Rows | Primary key |
|---|---:|---|
| customers | 99,441 | customer_id |
| orders | 99,441 | order_id |
| products | 32,951 | product_id |
| sellers | 3,095 | seller_id |
| order_items | 112,650 | order_id, order_item_id |
| order_payments | 103,886 | order_id, payment_sequential |
| order_reviews | 99,224 | order_id, review_id |
| category_translation | 71 | product_category_name |
| geolocation | 1,000,163 | geolocation_row_id (source row order) |
| order_financials | 99,441 | order_id |

Source IDs and five-digit ZIP prefixes are TEXT. Timestamp columns preserve the source timestamp values and legitimate nulls; no timezone is invented. Nullable product attributes and review text remain nullable. Geolocation duplicates are retained; neither ZIP prefix nor review_id alone is incorrectly declared unique. customer_unique_id remains nonunique.

Money is stored as exact integer **BRL cents**, using `price_cents`, `freight_value_cents` and `payment_value_cents`. All supplied amounts have cent precision; the importer rejects amounts requiring rounding. Divide an aggregated sum by 100 to display BRL. The CSVs retain the original price/freight_value/payment_value strings. No Northwind discount formula applies to Olist.

Declared relationships: orders→customers; items→orders/products/sellers; payments→orders; reviews→orders; order_financials→orders. Their reference checks pass. Incomplete category translations and repeated/missing geolocation ZIP references deliberately have no automatic FK joins. Those two tables are browsable; adding safe translated/geographic lookup relationships is deferred.

`order_financials` independently aggregates items and payments to one row per order before left-joining Orders. It includes item count, merchandise/freight totals, payment-record count, payment total, and presence flags. Missing item/payment totals remain NULL, not an invented zero payment. There are 775 orders without items and one without payments.

The database has an Olist application ID. V1's existing joined-dataframe loader uses that tag to conservatively reject combinations of two or more fact grains: order_items, order_payments, order_reviews and order_financials. This prevents multiplying payments by items and repeating an order-level total on each item. Existing same-database and declared-FK checks remain. Other SQLite datasets, including Northwind, are unaffected.

Safe examples: order_financials + orders + customers for order-level paid totals; order_items + products + sellers + orders for item-level merchandise totals. Cross-grain attribution requires an explicit future allocation/pre-aggregation design and is currently rejected.

## Registration and verification

The normal catalog scan discovers `olist.db::table` IDs. All ten tables were profiled using the existing installed local DuckDB SQLite extension. The 15 existing catalog entries were skipped as unchanged. Verified profile types include VARCHAR for IDs/ZIPs, TIMESTAMP for purchase dates and BIGINT for cents. No dependency download or model request was needed.

Validated totals:

- Merchandise: 1,359,164,370 cents (13,591,643.70 BRL).
- Item freight: 225,190,954 cents (2,251,909.54 BRL).
- Payments: 1,600,887,212 cents (16,008,872.12 BRL).

Summary sums match the raw fact totals exactly. The running V1 joined aggregation of order_financials + orders by order_status also summed to 1,600,887,212 payment cents. The running catalog endpoint exposes all ten tables and its relationship index includes all seven FKs.

Fourteen tests passed: five importer tests, four existing joined-Python/Northwind tests, and five summary-result tests. They cover repeat no-op, leading zeros, duplicate geolocation rows/nonunique review IDs, missing-payment nulls, summary totals, bad currency precision/headers, invalid replacement rollback, protection of unrelated databases, and permitted/rejected fact-grain combinations. Source hashes and Northwind's original checksum were verified after import. No browser inspection or live model calls were performed; frontend code was not changed in this pass.

## User check

Refresh the app and expand **olist.db**. Select **order_financials** and ask:

> Join order_financials with orders on order_id. Group by order_status and sum payment_total_cents. Keep values labelled as BRL cents.

The status totals should sum to **1,600,887,212 BRL cents**. Compare Table/Chart values, and retain the missing-payment coverage flag when interpreting the result. Browser/model behavior for this prompt remains for the user to check.
