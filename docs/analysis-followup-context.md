# Analysis follow-up context

## Diagnosis

The frontend submits project_id, dataset_id and only the latest message. Backend chat records were stored, but request processing did not load prior successful analyses. QueryPlanner saw only the latest text and active-table schema; TableSelector likewise saw only that text, the active dataset and global catalog. Agent conversations started from scratch. In the captured run, “Now show that quarterly” was classified CONVERSATION and returned generic Orders/Freight advice. The subsequent comparison had no retained metric, year, joined sources or grouping.

The original comparison failed the existing same-SQLite-database join guard. Its saved trace recorded only the guard error, omitting selected tables; the selector did not log its response. The exact bad historical IDs cannot be recovered from available records or logs. The guard triggers when resolved sources have different filepaths or a selected item is not a concrete SQLite table. This includes mixed file/table selections or whole-database IDs. The actual catalog includes CSV/JSON files alongside canonical `northwind.db::Orders` and `northwind.db::Order Details`; no claim is made about which incorrect combination the old model selected.

Selection now validates exact catalog identifiers, logs its output, and uses the resolved analysis source when available. Join-preparation failures preserve selected table IDs and join keys in calculation traces. Cross-database, missing-table and declared-foreign-key validation remain in place.

## Implementation

`analysis_context.py` loads at most three recent successful analyses from a bounded candidate window within the request project. SQL excludes failures and advice before applying the limit, so repeated failures do not displace a success. It selects bounded question/context/calculation metadata fields, not raw result datasets, image bytes or full chat transcripts. Existing Python analyses can provide bounded AST-derived formula/year/date/grouping facts; uncertain reconstruction requires clarification.

Each new successful analysis persists structured context: actual source database/table IDs and join keys; metric name and expression; date column; years/calendar filters; other predicates; grouping; comparison flag; and output. Reloads and backend restarts reconstruct context from SQLite, without frontend or process-memory state.

Planning receives this context and resolves standalone vs inherited vs ambiguous requests. Referenced successful-message IDs can select the relevant prior analysis; ambiguous references ask a short clarification. Standalone requests do not pass old context into table selection or execution. Inherited requests supply the relevant structured context to selection and the agent, not merely to the narrative generator.

A validated calendar aggregation executor handles sum/count with column/value expression trees and add/subtract/multiply operators, across month/quarter/year. It validates actual source columns and dates, preserves non-date predicates, and computes directly from joined source rows. It does not match the three Northwind sentences in application code. The resolved analysis supplies the grouping and years. Unsupported operations fail instead of returning advice or fabricated results.

Calendar comparison results contain one row per aligned period, separate measure columns per year, verification totals and source observation counts. Chat is generated from these calculated values. Open result uses the same rows, including an aligned line for each comparison year. Calendar order and all periods are preserved, independently of table sorting/pagination and Top N. Existing canvas ownership and request/progress flows remain unchanged.

## Independent Northwind comparison

Database: `/app/datasets/northwind.db`. Join `Orders.OrderID = "Order Details".OrderID`. Sum `UnitPrice * Quantity * (1 - Discount)` by calendar quarter, grouped independently using SQLite strftime and integer quarter arithmetic.

| Quarter | Revenue 2021 | Revenue 2022 |
|---|---:|---:|
| Q1 | 9,862,848.04 | 9,645,680.57 |
| Q2 | 10,086,366.80 | 9,725,436.11 |
| Q3 | 10,547,876.35 | 9,625,190.26 |
| Q4 | 10,858,458.55 | 10,745,759.24 |
| Annual total | 41,355,549.74 | 39,742,066.18 |

Live follow-up `528c9dd0-5057-4a22-b104-ba01134fd528` reconstructed the original successful Python monthly analysis and returned four 2021 quarters in 15.80 seconds. After restarting the backend, live comparison `1890ee26-667b-477b-9903-90f881d1ba78` returned all eight quarter values in a four-row comparison table in 29.31 seconds. Every value in the table, narrative and saved Open result payload matched independent SQLite totals within 1e-5; quarterly sums also match independent annual totals. Source observation counts: 56,229 for 2021 and 53,835 for 2022; combined 110,064.

The first follow-up verification attempt correctly failed validation because the expression evaluator initially accepted only binary multiplication while the planning schema permits three factors. The evaluator now supports bounded n-ary multiply/add and binary subtract; regression coverage compares both forms of the same revenue formula. Failed attempts were not promoted into successful history.

## Checks and browser steps

The backend run covering follow-up context, provider failures, monthly revenue, correlation and Python correlation passed 38 tests before the additional repeated-failure case. All seven focused context tests passed after final validation/history changes. A final targeted regression also passed for newly persisted Python formula facts. Frontend tests and the production build passed. No browser inspection was performed.

1. Select Northwind → Orders in a project. Ask “Show monthly revenue for 2021 after discounts.” Expect twelve months and annual revenue 41,355,549.74; calculation sources include Orders and Order Details joined on OrderID.
2. Ask “Now show that quarterly.” Expect four 2021 quarters matching the left column above, not SQL advice. Open result: four rows; source still lists both joined tables. Expand calculation details to inspect formula, 2021 and quarter grouping.
3. Refresh the page and select Orders if needed. Ask “Compare those quarters with 2022.” Expect the four-row, two-year table above. Chart should show both years over Q1–Q4, and the annual totals should match the last row above. Opening/sorting the table should not change the chart's chronological order.
4. Ask an explicit standalone question: “Show quarterly Freight from Orders for 2022.” Expect Freight from Orders only, with 2022 rather than inherited discounted revenue or 2021. No Order Details join is needed for this question. Independent SQLite Freight totals for Q1–Q4 are 86,820.25; 88,433.50; 85,994.25; 96,266.50 (1,352 Orders rows in total).
5. Switch/create a different project. Ask a referential question without a previous analysis. Expect a concise clarification; no state from the first project should be used.
6. For an ambiguity test, refer to an unspecified alternative metric/source. Expect clarification, not a guessed analysis. A failed or ambiguous turn must leave the last successful analysis available for an unambiguous follow-up.

Older failed/advice responses are preserved. New live follow-up cards can be opened directly; no old snapshots were repaired or chats deleted for this verification.
