# V1 analysis publication and replay milestone

Feature work is paused. This change addresses the boundary between execution and a completed answer.

## Root causes

The agent used one mutable `last_results` value for calculations and presentation. A `visualization` call could reload the dataset, replace an aggregate with raw rows, and still reach the normal success path. Python execution, captured images, and a confident final message were also treated as completion signals. Output transformations, result scope, factual prose, and saved context had separate sources of truth.

## Implemented boundary

`services/analysis_package.py` is the publication boundary used by the JSON and progress endpoints. A package contains requested output requirements, completion checks, named tables, charts referencing those tables, factual metadata, provenance, and a complete/incomplete/failed status. The existing `results` field is a compatibility projection of the first published table.

- Aggregation requirements identify grouping and requested measures. Scope defaults to all groups; predicates default to none. A tool name alone is insufficient. Units, divisors, output names, derived metrics, sources, filters, and actual result limits can be checked against the calculation output.
- Presentation attaches to calculated tables and cannot reload source rows or replace them.
- Related outputs can coexist. Independent source subsets execute separately; they are not blindly joined. Declared joins still go through the existing SQLite key and grain checks.
- Replacing a named valid output with a result that no longer satisfies its requirements fails. Missing requested metrics and unrelated calculations cannot become completed answers. Partial outputs carry an incomplete status; failed turns do not replace the last successful conversation context.
- Oversized results are explicitly rejected rather than silently truncated or saved as unreopenable raw snapshots.
- Factual replies are rendered from calculation outputs. The model's draft explanation is not published as verified facts. `interpretation` currently remains empty; free-form analytical interpretation is deliberately deferred until it has its own validation boundary.
- Table/chart selections use package outputs. Saved snapshots and past chats retain the package. Per-output sources remain separate from the dataset selected for browsing. Tables remain mounted while switching views, preserving their sort/page state. Several chart specifications can reference one table.
- Normal conversational responses remain conversational. Statistical summaries can complete without returning source rows or forcing a chart.

## Custom Python

Python can export named DataFrames and explicit calculation plans:

```python
summary = df.groupby('region', dropna=False)['revenue'].sum().reset_index()
analysis_tables = {'regional_sales': summary}
analysis_plans = {'regional_sales': {
    'tool': 'aggregation',
    'parameters': {'group_by': ['region'], 'aggregations': {'revenue': 'sum'}}
}}
```

The sandbox executes the program and exports the values. The backend then recomputes the declared plan on the original resolved input and checks shape, labels, missing values, and numeric values. Canonical plans currently cover aggregation, comparison_summary, correlation, and monthly_revenue. Export plans must contain the actual filters and transformations, not rely on mutations made to `df` inside Python.

Captured PNG/Plotly files remain downloadable and independently addressable. They are marked `export_only`, not assigned to an arbitrary table or assumed to prove the requested calculation. The verified chart view uses calculated table values. Arbitrary chart-only Python without supported calculation evidence remains incomplete, including older image-only examples. Existing saved responses are not retrospectively certified by this change.

## Automated checks

From the repository root, with the existing containers running:

```sh
docker --context desktop-linux exec offline-analyst-backend python scripts/replay_analysis_checks.py
npm --prefix client test
docker --context desktop-linux exec offline-analyst-frontend npm run build
```

The replay command blocks unexpected Python HTTP/model requests. Recorded model responses drive real planner parsing, table selection, agent dispatch, calculation, sandbox execution, route serialization, SQLite chat storage, and saved/past-chat restoration. This is not a live-model evaluation or browser test.

New replays include captured Olist status/payment chart overwrites, all 27 states versus a Top 10 chart, explicitly missing payment coverage, separate source outputs, all Northwind product totals/order against SQLite, unrelated fixture vocabulary with negative/null currency values, verified Python subprocess exports, stream completion/incompletion, and summaries without unsolicited charts. Existing suites cover calendar follow-ups, date predicates, correlation, duplicate incompatible calls, artifact delivery/deletion, and safe joins.

The Olist sequence covers month → quarter → two-year comparison → failed turn → reload → month. Every returned month is compared with independent SQLite SUM(payment_total_cents)/100. Annual totals remain BRL 7,249,746.73 and 8,699,763.05. The Northwind sequence checks both comparison years after reload; annual revenue remains 41,355,549.74 and 39,742,066.18.

## Remaining limits

A planner-generated contract is an executable interpretation of the request, not a proof that the model understood its meaning. These replays demonstrate the covered pipeline behavior; they do not establish universal semantic reliability. Future evaluations should add held-out natural-language questions and additional valid/invalid plans, without weakening completion checks just to make examples pass.

Arbitrary Python calculations outside the canonical export plans, arbitrary custom figure/table correspondence, and free-form interpretation remain unverified. They must not be labelled complete merely because execution or capture succeeded. No new chart types or model-provider changes are part of this pass.

Browser rendering has not been inspected in this environment. After automated checks pass, confirm the experience with these steps:

1. Select Northwind → Orders. Ask monthly revenue for 2021 after discounts; regroup quarterly; compare with 2022. Refresh, then ask to show that monthly instead. Expect 12 periods, both year columns/series, and the annual totals above.
2. While browsing Customers, open that saved analysis. The browsing dataset must remain Customers; the result must name Orders and Order Details. Switch Table/Chart and back; sorting/page and chart choices must remain.
3. Select Olist → orders. Ask for order_id counts by order_status named Order Count, descending, with a bar chart. Expect eight categories totalling 99,441, not raw order records. Refresh and reopen.
4. Ask for payment totals by payment_type divided by 100 in BRL. Table/chart must agree; credit_card must be 12,542,084.19.
5. For an unsupported or deliberately incomplete calculation, expect an incomplete status and no claim of completion. A subsequent follow-up must still refer to the last successful analysis.
6. Open a package containing multiple outputs. Check each output selector and its sources, then check multiple chart selections where present. The center canvas must not change merely because another request finishes.

## Check results for this implementation

- Backend replay/regression suite: **113 tests passed**, 177.692 seconds, with unexpected Python HTTP/model calls blocked.
- After final output-source/retry review: the 20 pipeline/comparison tests passed again in 33.242 seconds.
- Frontend: all three test files passed; the production build passed separately (576 ms in the existing frontend container).
- `git diff --check` passed. Northwind SHA256 remains `2f4f5c68dfcd33ba27373eae48c7a4869800c68095ee0f9f0da494f83382a877`.
- No live model calls or browser checks were used. Browser appearance, focus behavior, and interactive table/chart state still need the steps above.
