# V1 aggregation outputs and date comparisons

## Root causes

Aggregation retained input column names and discarded output semantics. Counting order_id returned numeric counts under an ID name, and Chart's identifier exclusion then hid the measure. Tool parameters also lacked an executed conversion/alias/missing-group/limit pipeline. The captured payment tool call returned summed cents; only the model narrative divided them by 100. Grouping dropped null categories. Chart Top N controls changed the picture, not the result table, despite narratives describing a top-ten result.

Filtering accepted scalar literals only. Supplying the estimated-date column name as a date value failed parsing. Separate filtering calls did not create state for later aggregations; repeated attempts could leave only a partial population or unrelated count. The date-rate request in the capture even attempted an invalid sort_by=count followed by unrelated status counts.

## Shared implementation

The aggregation path executes row filters, missing-group replacement, aggregation, numeric division, output aliases, sorting and a result row limit in one calculation. It returns measure provenance, units, transformation audit, source count and full/returned row counts. Count outputs receive explicit names such as Order Count; sorting accepts input names or final aliases, and count is accepted when there is one count measure. Count provenance makes legacy ID-named counts chartable; raw ID fields remain excluded.

Aggregation supports output_names and transforms (column, divide_by, as, unit), fill_missing, filters and limit. Explicit BRL requests on the project's BRL-cent measures normalize to a /100 result transformation. Requests to retain cents are respected. The final numeric payload is transformed before saving; neither table/chart nor narrative performs another division. BRL tables and hover details carry units. All-null sums remain unknown rather than fabricated zero. Invalid divisions, sources, labels and unsupported fields fail.

Requested top-N results are sorted and actually truncated. Explicit all-category results remain complete while the chart can rank a visible subset. Grounded narratives state the actual returned/full group counts and limit. Missing categories are labelled before grouping and ranking. A requested Unknown group may fall outside a top-ten result; it is still included in the underlying grouping.

Column comparisons require value_column explicitly, mutually exclusive with literal value. Ordered numeric comparisons and explicitly typed dates are supported; date_part=date normalizes dates before comparison. Malformed dates and unsupported arguments fail. A date-typed value naming another column returns a precise error instead of being treated as a successful filter or silently reinterpreted.

comparison_summary executes population filters and a validated column comparison together, returning eligible actual values, missing actual values, missing comparison values, comparable denominator, matched numerator and percentage. It excludes missing comparison dates only from the denominator and reports them. Strict > excludes same-day equality regardless of time. The event comparison cannot be supplied as a population filter because that would corrupt the denominator. An empty denominator returns an undefined percentage.

Planning and tool instructions describe this operation. A planner-selected comparison_summary can dispatch directly, without repeated agent tool calls. Other rate attempts cannot finalize unrelated aggregation/raw filter results as a completed date-comparison percentage. Aggregation and comparison narratives are generated from their final tool payload, replacing model-only arithmetic and unsupported claims. Unsupported comparison shapes are directed to custom Python in the capability instructions.

## Verification

Controlled fresh responses execute actual tools against the Olist database, save to chat storage, then reopen through Saved Analyses and past-chat metadata. They cover status counts, category BRL totals/top-ten scope, payment BRL totals and the late-date summary. Saved payloads, units, transformations and values equal the response payloads. No historical results were rewritten. No live provider or browser requests were needed for these automated checks.

Independent SQLite JOIN/SUM/GROUP BY/date comparisons confirm:

- Status counts sum to 99,441.
- All category sales contain 74 groups, including Unknown at BRL 179,535.28. Their sum is BRL 13,591,643.70. Every category coefficient/value matches SUM(price_cents)/100; actual top-ten rows match independent sorted SQLite results.
- Credit-card payments equal BRL 12,542,084.19.
- Delivered orders: 96,478; missing actual delivery dates: 8; eligible/comparable dates: 96,470; missing estimated dates among eligible: 0; late dates: 6,534; late percentage: 6.7730900798175595%.

The test runs passed: 26 tests covering new operations, existing summaries and Northwind date/revenue checks; 25 covering new operations, provider failures, importer safeguards and joined-data paths; the final seven-operation focused suite; frontend tests; and production build. Overlapping tests are not counted as distinct tests. Synthetic cases include null dates, malformed/unknown references, same-day timestamps, empty populations, raw versus counted IDs, transformed money, all-null sums, unknown categories and actual result limits. Frontend tests verify bars/hover data use the transformed saved numbers and count provenance does not enable raw IDs.

## Browser retest

Use fresh responses, then save/reopen or reload them to check persistence.

1. Select olist.db → orders. Ask: "Count order_id by order_status and sort descending by Order Count." Expect Order Count as a sortable numeric result/chart field; status counts sum to 99,441. Choose Chart and confirm order_status/Order Count are usable. Raw order_id in Data Preview must not become a numeric measure.
2. Select order_items. Ask: "Join order_items with products on product_id. Return the top 10 product categories by total price_cents divided by 100 in BRL. Label missing categories Unknown and sort sales descending." Expect exactly ten result rows, BRL-named measure/units and the same values in chat, Table, Chart and hover. The narrative must say a limited result, not all categories.
3. Ask a standalone version: "Join order_items with products on product_id. Return all categories by total price_cents divided by 100 in BRL, with missing categories Unknown. Show a Top 10 chart." Expect 74 table rows, Unknown = 179,535.28 BRL, and all-category sum 13,591,643.70 BRL. Chart displays ten bars; Table retains all groups.
4. Select order_payments. Ask: "Show total payment value in BRL by payment_type, converting payment_value_cents by dividing by 100." Expect credit_card = 12,542,084.19 in Table, Chart/hover and chat. Reopen the fresh saved analysis and confirm values have not reverted to cents or been divided again.
5. Select orders. Ask: "what t." Expect eligible/compared = 96,470, late = 6,534, percentage ≈ 6.773090%, missing actual = 8, missing comparison = 0. Same estimated-day delivery is on time. Check the calculation details show comparison_summary and explicit value_column rather than a literal column-name date.

Browser appearance and live model interpretation of these prompts remain for the user to verify.

## Follow-up: bare table identifiers in monthly paid totals

The planner's resolved source could contain bare order_financials/orders names. Table selection now resolves unambiguous bare names and join endpoints within the active or explicitly selected database before exact-ID validation. Qualified unknown IDs are never redirected, ambiguous names fail, and existing cross-database/FK/fact-grain checks remain. The planner now receives the actual catalog IDs, columns and declared relationships; previously it could copy the illustrative database.db prefix because its source context was incomplete.

The same reproduction exposed metric validation running before year selection. Calendar aggregation now selects the requested years before evaluating numeric measures, so a missing payment outside 2017 does not block the 2017 calculation. Missing/non-finite values within the selected period still fail explicitly.

Resolution, ambiguity, cross-database protection, scoped-null handling and the actual monthly calculation have regression coverage. The final planner/resolution/provider suite passed 15 tests; an earlier resolution/importer/provider run passed 19 overlapping tests. No frontend changes or browser inspection were needed.

Fresh live response d66db8e4-27c7-4b92-8a99-2e4858e5b5fc reused the original question unchanged and returned twelve chronological 2017 Paid Total (BRL) rows in 39.38 seconds. All twelve values matched an independent SQLite Orders/order_financials join and SUM(payment_total_cents)/100. The annual total is BRL 7,249,746.73; the canonical source and declared OrderID join are retained in calculation provenance.
