# Latest Olist test results: audit

This audit inspected the latest saved responses corresponding to the 15 supplied test questions. It read actual calculation traces, result payloads, artifact metadata and saved PNGs, compared values independently with SQLite, and ran the frontend's real inspectResult/makeChart functions on captured saved snapshots. No model calls, application code changes, dataset edits or saved-result repairs were made.

Browser automation/tools and a usable local browser runtime were unavailable. Static PNGs were visually inspected. Interactive chart data was checked, but actual dashboard rendering, resizing, hover interaction, keyboard behavior and pagination remain visually unverified.

## Findings by question

| Test | Assessment |
|---|---|
| 1. Status counts/bar | **FAIL.** Chat describes eight aggregated statuses, but the saved result contains 99,441 raw orders. A subsequent visualization tool call replaced the correct aggregation. Saved metadata is 38,887,446 bytes and exceeds the 8 MiB reopening limit. |
| 2. Actual top-ten categories | **PASS data/chart specification.** Ten rows are the independent top ten category sums in BRL. Chart bars match saved rows. |
| 3. All categories, Top 10 chart | **PASS data/chart specification.** All 74 groups remain in Table, including Unknown. The chart model selects the correct ten largest values across the complete result. |
| 4. Payment totals by type/bar | **FAIL.** Chat lists BRL aggregates, but visualization replaced them with 103,886 raw payment rows in cents. Saved metadata is 16,764,998 bytes and exceeds the reopening limit. |
| 5. Credit-card-only total | **NOT OBSERVED.** No recent saved response to this standalone filtered question was found. Independent source baseline is BRL 12,542,084.19; this is not a verified application result for that missing question. |
| 6. Order-level payment totals and missing payment records | **PARTIAL.** Every returned status payment sum, order count and orders-with-payments count matches SQLite. However, there is no explicit missing-payment result or answer: the user must subtract the two counts. Their difference is one, in delivered orders. |
| 7. Late percentage | **PASS numerical result.** Delivered 96,478; missing actual 8; comparable 96,470; missing comparison among eligible 0; late 6,534; percentage 6.7730900798175595. |
| 8. Before/on/after calendar dates | **PASS counts, limited result delivery.** Narrative matches SQLite: before 88,644; on 1,292; after 6,534; total 96,470. Python prints results and returns prose only: no structured result table or chart artifact is available through Open result. |
| 9. All customer states with Top 10 chart | **FAIL requested scope.** The ten returned state counts individually match SQLite, but 17 states were omitted from Table. Saved rows sum to 89,954 instead of the all-state 99,441. The requested table should contain 27 states. |
| 10. Monthly paid totals 2017 | **PASS data/chart specification.** Twelve values independently match SQLite. Annual total BRL 7,249,746.73. |
| 11. Quarterly 2017 follow-up | **PASS data/chart specification.** Four quarters match SQLite and sum to the same annual total. |
| 12. Quarterly 2017/2018 comparison | **PASS data/chart specification.** Four aligned quarters and two series preserve both years. Annual totals BRL 7,249,746.73 and BRL 8,699,763.05. |
| 13. Monthly comparison after refresh | **PASS saved data/chart specification.** Twelve rows, both years, two 12-point series and the same annual totals. Saved endpoint returns the same payload. Actual browser reload behavior was not exercised during this audit. |
| 14. Order-total histogram | **PASS population; FAIL explanatory sentence.** Its recorded plotted-value fingerprint exactly matches all 98,666 independently queried order totals in BRL. Text incorrectly says each bar is one observation/order; bars are bins containing multiple orders. The PNG is readable, but most observations are compressed into the first bin by the long tail. |
| 15. Correlation matrix/heatmap | **PASS coefficients/chart specification; export layout issue.** Both recent runs match an independent centered-dot-product Pearson calculation: r=0.4142043103630345 (stored value differs only by floating-point precision). Matrix Table and generated heatmap z agree; axes share order, labels show four decimals, and scale is fixed at -1/+1 centered at zero. The latest original PNG export has a long title overlapping the colorbar area. The center workspace uses the canonical interactive matrix heatmap, whose visual layout was not inspected here. |

## Main shared causes still present

1. **Visualization overwrites calculated data.** AnalysisEngine's visualization branch reloads/packages the source dataframe, and the agent replaces last_results with that tool result after a successful aggregation. The aggregate is consequently absent from Open result and its provenance/grounded final explanation is lost. This affects tests 1 and 4, creates huge snapshots, and prevents reopening those saved results. Increasing the snapshot limit would conceal rather than fix the error.
2. **All-group intent is recognized using a small noun list.** normalize_request recognizes all categories/groups/rows/results, but not all states. In test 9, Top 10 in Chart became an actual limit of ten rows. Request scope and chart subset need separate structured fields rather than noun-specific detection.
3. **Derived coverage metrics are not computed.** Test 6 returned total orders and orders with payments instead of executing the requested difference and naming the missing-payment count. The numbers permit the answer but do not directly deliver it.
4. **Custom Python's prose remains insufficiently grounded.** Histogram population and values are correct, while its narrative incorrectly describes the bins. Printed Python summaries also lack a general structured table contract, as seen in test 8.

The generic comparison summary currently offers numeric scatter pairings if the user opens Chart and chooses count fields. That is not a verified meaningful visualization of a rate; Table is the useful representation for this result. The payment/status table also has multiple measures, so the chart's explicit measure selector may be required. The audit checked its Total Payments (BRL) bar data rather than claiming automatic selection was visually verified.

## Evidence

- Bad status result: 508d88c1-720c-4f82-ae5a-d3bdfac73a4f.
- Bad payment result: da55d2a0-a3e5-4e50-8186-7a2890698db4.
- Incomplete state result: 5f5523a5-0b6d-4cc8-bf06-a0ddfa3c2eda.
- Payment/coverage result: 11dc364e-c3a9-423c-80c0-050846996bd4.
- Latest monthly comparison: 8d8e1b5a-7c01-4238-9772-99ddffe255db.
- Histogram: cb0d4d29-5c2b-4fea-bf0d-107a4acba75a, artifact 8125e643b2304302b1cbdb705245aa10.
- Latest correlation: 18e4f10f-2435-4ce3-a76e-922e130740e5, artifact 796c14540e554d9c9ca98916524d8413.

Read-only running API checks confirmed the two oversized results are explicitly unavailable in Saved Analyses and the sampled good calendar/correlation/aggregation payloads reopen unchanged. Data/chart assertions for eleven small captured snapshots passed. Those passes prove consistency with the saved payload, not correctness of a scope already identified as wrong.

## Independent baselines

All categories: 74; Unknown BRL 179,535.28; total merchandise BRL 13,591,643.70. All customer states: 27; all-state order total 99,441. Credit-card payments: BRL 12,542,084.19. Payment total across statuses: BRL 16,008,872.12; missing-payment order count one. Histogram min BRL 0.85, max BRL 13,440.00, mean BRL 137.75407637889444, population 98,666. Both correlation matrices match independently within absolute tolerance 1e-12; category/payment/calendar amounts matched within 1e-5.

The suite is not clean. The aggregate-overwrite and result-scope failures need correction before this run can be considered passed. No existing results were rewritten during verification.
