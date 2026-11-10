# Resumed live evaluation — 9 November 2026

The user-authorized replacement credential is loaded by Docker Desktop's existing backend and works with `nvidia/nemotron-3.5-super-vl:free`. Its local identifier ends in `40a89ad9`; the credential is stored in the ignored local environment file, not this report or Git. The backend was recreated so the changed environment actually took effect. Frontend: http://localhost:3001/.

**This is an API recovery and evaluation result, not a claim that every analysis now succeeds.** No production code was changed during this retry. All 74 application-source hashes match the revision whose 139 backend tests, frontend tests and separate production build passed. No full test/build rerun was needed for a credential-only change.

The original frozen questions, expectations, results, and both databases remain unchanged. New captures are retained in [publication-contract-resumed-regression-2026-11-09](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/publication-contract-resumed-regression-2026-11-09) and [publication-contract-resumed-heldout-2026-11-09](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/publication-contract-resumed-heldout-2026-11-09). These are normal HTTP chat requests with real model responses and real calculations, saving and reopening. Independent SQLite expectations were prepared before the model calls; none were supplied to the model. H07/H08 previously received only quota errors, so this is their first live-model response.

| Metric | Frozen baseline | Resumed original set | Separate held-out set |
|---|---:|---:|---:|
| Correct, accepted answerable requests | 3/11 | **10/11** | **2/2** |
| Correct unsupported-join refusal | 0/1 | **1/1** | — |
| Confidently wrong completed answers | 0 | **0** | **0** |
| Misleading partial numeric outputs | 1 | **0** | **0** |
| Correct executed calculations falsely rejected | 2 | **0** | **0** |
| Schema-repair false rejection before calculation | Unknown for four missing raw captures | **1 (Q04)** | **0** |
| Provider HTTP 429 errors | 0 | **0** | **0** |
| Total terminal time | 672.249 s | **471.294 s** | **59.35 s** |
| Median terminal time | 52.156 s | **29.519 s** | **29.675 s** |
| Median first HTTP progress | 29.5 ms | **30.0 ms** | **32.0 ms** |
| Observed model-call attempts | 28 | **16** | **2** |

Timings are HTTP receipt/terminal timings, not browser paint measurements or a controlled provider-speed benchmark. The changed credential and variable provider load prevent attributing latency differences solely to code. All resumed calls used the same configured model.

**What passed.** Every requested value and ordering in Q01, Q02, Q03 and Q05–Q11 matches independent SQLite. Q12 explicitly refuses the unsupported cross-database join without inventing a mapping or count. Q06 restores the successful two-year comparison after persisted history is fetched, producing twelve aligned months, both year columns and both line series. Annual sums remain **41,355,549.74 / 39,742,066.18**. Category sales retain **74** groups including **Unknown = BRL 179,535.28**, with only ten chart bars. Credit-card payments remain **BRL 12,542,084.19**. The delivered comparison retains **96,478 / 8 / 0 / 96,470 / 6,534 / 6.7730900798175595%**. Payment coverage is **99,441 / 99,440 / 1**.

All ten successful main-set packages and both held-out packages save/reopen identically, including their full related-table packages; restored factual replies agree with returned data. All eight main-set chart specifications and the held-out installment chart use the saved table values through the actual offline frontend chart model. The installment chart is an optional scatter for its two numeric fields; the requested 24-row table remains complete. No browser rendering was inspected.

H07 returns **24 credit-card installment groups**, with total **BRL 12,542,084.19** and the one-installment group **BRL 2,440,445.43**. H08 uses a different Northwind population and dates: **1,683 Brazil orders**, **2** missing shipped dates, **0** missing required dates among eligible shipped records, **1,681** comparable, **367** shipped late, **21.83224271267103%**. Both match every independent SQLite value; H08 does not inherit Olist payment predicates from H07.

**Remaining failure, Q04.** The model understood the quarterly question and retained the correct source, year and net-sales formula, but its first JSON misplaced `chart_scope` inside an output and put `compare`, `filters` and `output` inside `metric`. The single repair fixed those locations. The semantic guard then treated the disappearance of the old `metric.compare` path as a changed calculation, although the corrected `parameters.compare` was still false. The exact error is `$.analysis_plan.outputs[0].parameters.metric.compare: schema repair changed a requested calculation field; clarify instead`.

This is a false schema-repair rejection **before execution**, not a wrong quarterly calculation or an accepted partial. No Q04 numeric table was published; Q03 remained the last successful result. Q05 subsequently executed the correct quarterly comparison, and Q06 restored it correctly. The actual rejected/repaired payloads are captured in Q04.json; they are a new observation, not a reconstruction of the old baseline. No code or saved response was patched to conceal this failure.

The remaining shared correction should compare typed, schema-owned semantic fields when a repair relocates an unambiguously misplaced field, while rejecting conflicting copies and any dropped real predicate, year, unit, source, formula or scope. Simply ignoring missing JSON paths or relaxing population checks would be unsafe. This correction has **not** been implemented in this credential-only retry. The milestone therefore remains short of a fully passing original live set.

There were four bounded schema-repair attempts in the original set: Q01 corrected an expression used as an `output_names` key; Q07 corrected a transform's column reference; Q12 corrected `changed_fields: null`; Q04 exhausted the one-repair budget as described above. No incompatible operation was repeatedly executed, and no selector or draft-final-answer model calls were made. The held-out cases each used one model call.

**Short browser checklist — use saved captures first, no extra model calls.** Open project **publication-contract-resumed-regression-2026-11-09 2026-11-09 16:29:59**, ID `bd775a14-a741-466b-b247-3998cedaaeda`.

1. Browse **Northwind → Customers**, then open Q06 from chat or Saved Analyses. Expect separate Customers browsing context and Orders × Order Details result source, 12 month rows and two line series. Sort/page the table, switch Table/Chart, resize/collapse chat, refresh and reopen. Confirm the calculation toggle starts collapsed and source/data persist.
2. Open Q08: 74 table rows, Unknown BRL 179,535.28, ten chart bars. Table sorting/pagination must leave chart ranking unchanged; hover values must agree with BRL table values.
3. Open Q10 and inspect all three named counts: 99,441, 99,440, 1. Reopen after refresh and confirm the entire package survives.
4. Inspect Q04: it must remain a clear failed request with no successful numeric Open result. Inspect Q12: a clear unsupported-join refusal and no invented number.
5. Open project **publication-contract-resumed-heldout-2026-11-09 2026-11-09 16:37:53**, ID `63306cfe-de8b-44e5-847c-cd5f4a265ff1`. H07 must retain all 24 installment groups; H08 must show the Brazil counts/percentage above with Northwind source and provenance.

Exact questions identifying the saved messages (rerun only if intentionally testing a fresh request):

**Q03**

> For calendar 2021, total net sales separately for each month using OrderDate. Join Orders with Order Details on OrderID and calculate UnitPrice times Quantity times (one minus Discount). Call the measure Net Sales, keep the original currency units, and draw a chronological line.

**Q04**

> Keep that same sales definition and year, but roll the months up into calendar quarters. Please calculate the four quarterly amounts and use a line chart.

**Q05**

> Put those four periods side by side with 2022, retaining 2021 and exactly the same net-sales formula. I want one row per quarter and a separate sales column and line for each year.

**Q06**

> Switch that comparison back to months, leaving both years and the sales calculation as they are. Give twelve aligned month rows and two lines.

**Q08**

> Report merchandise sales for every product category, joining order_items and products by product_id. Treat a missing or blank product_category_name as Unknown. Use SUM(price_cents)/100 as Merchandise Sales (BRL), sorted largest first. The result table must retain every category; only the chart should show the leading ten.

**Q10**

> Audit payment coverage in order_financials without joining any line-item tables. Return three explicit numbers: total orders, orders with at least one payment record, and orders with no payment record. Calculate the missing count rather than leaving me to subtract it; a compact table is enough.

**Q12**

> Can the current application join northwind.db::Products to olist.db::products using ProductID = product_id and calculate the number of matched products? If cross-database joins or that relationship are unsupported, clearly decline this calculation instead of inventing a product mapping.

**H07**

> Using Olist order_payments only, keep credit_card payment records and show how much was paid for each payment_installments value. Add payment_value_cents, divide by 100, and call it Installment Payments (BRL). Return every installment group, sorted from the largest paid amount to the smallest; do not cut the table off at a Top N.

**H08**

> Use Northwind Orders shipped to Brazil. Compare the ShippedDate calendar day with the RequiredDate calendar day: shipping later on the same day is on time. Report the whole Brazil population, missing shipped dates, missing required dates among records with a shipped date, the comparable count, the number shipped after the required day, and that number as a percentage of comparable orders.

Integrity, timing, source-state and persistence checks are recorded in [resumed verification](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/publication-contract-fix-2026-11-09/resumed-live-verification.json). Browser layout, focus, hover, resizing and an actual browser refresh remain unverified. No commits or pushes were made.
