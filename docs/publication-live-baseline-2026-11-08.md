# Analysis-publication live baseline — 8 November 2026

The milestone is **not ready to be called reliable**. All documented automated checks passed, but only **3 of 11 answerable fresh live questions** produced an accepted, SQLite-correct analysis. Two additional questions calculated correct values and were falsely marked incomplete. The deliberately unsupported twelfth request produced an irrelevant clarification rather than the requested clear refusal.

**No production fixes were made during this evaluation.** Only evaluation scripts and this report were added. The existing local provider setup and pending UI CSS change were retained.

**Method and controls.** The configured model was `nvidia/nemotron-3.5-super-vl:free` through the existing OpenRouter setup. Twelve questions and their SQLite expectations were frozen before the first live request. There were no model mocks, injected expected answers, direct substitute model calls, repaired saved records, or reruns of failed questions. Every question used the running application's normal `POST /api/v1/chat/message/stream` path. Model-call counts below come from existing planner, selector and agent logs, rather than provider usage telemetry.

A separate project was created: **Publication baseline 2026-11-08 23:06:00**, ID `ceab1bdf-9b64-4e8e-a591-6aff39e2b2c7`. Other projects/chats were not cleared or changed.

Before live calls, `python scripts/replay_analysis_checks.py` passed **113 backend tests in 179.742 seconds**; all **three frontend test files** passed; the separate frontend production build passed in **702 ms**. These are checks against the current working copy, including the local provider integration and pane-layout correction, not just the last committed tree.

The backend resolved `/app/datasets/northwind.db` and `/app/datasets/olist.db`. Their SHA256 values matched the host files used for SQLite expectations:

- Northwind: `2f4f5c68dfcd33ba27373eae48c7a4869800c68095ee0f9f0da494f83382a877`.
- Olist: `4bc4c5c3eb3a560294b857569ec5be6b75fe0e0257443f57674a3dc0a9c808a7`.

Comparison SQL deliberately stores long-form year/period values (eight quarterly or 24 monthly rows). The requested application output is their wide equivalent: four or twelve period rows with separate 2021 and 2022 measure columns. Checks compare every year/period value, not just annual sums.

The frozen oracle checksum remained unchanged: `36b592a6859cd4e174537c4510c7fa8398b1d7ef40a85bce4991b15bbbcba525`. Each oracle records the population, formula, units, sources, SQL and output scope. Q12 intentionally has no numeric oracle: V1 does not support the cross-database join or declare a relationship between those unrelated identifier domains.

**Results by question.** “Unknown” means a planner contract was rejected before execution and the existing logging does not retain its raw JSON. That limits assessment of semantic understanding; schema rejection alone does not prove the model misunderstood the calculation.

| ID | Request | Understanding | Calculation versus SQLite | Publication | Latency | Observed model calls |
|---|---|---|---|---|---:|---:|
| Q01 | Actual top ten products by units, Products × Order Details | Unknown | Not executed | Failed: invalid planner contract | 9.86 s | 1 |
| Q02 | Distinct customers per ShipCountry | Initially distinct; drifted to ordinary count | Wrong: e.g. USA 2,328 rows instead of 93 distinct customers | Incomplete, correctly blocked; misleading partial label remains | 78.63 s | 6 |
| Q03 | 2021 monthly net sales after discounts | Correct | All 12 months agree | Correctly accepted | 57.02 s | 1 |
| Q04 | Follow-up: same metric/year by quarter | Correct | All four quarters agree | **False negative:** correct result marked incomplete | 30.78 s | 1 |
| Q05 | Follow-up: compare quarters with 2022 | Unknown | Not executed | Failed: invalid planner contract | 55.38 s | 1 |
| Q06 | After reload: monthly comparison, both years | Wrong scope: resolved only 2021 | Executed context retained one year; output was discarded | Incomplete; wrong result was not certified | 171.71 s | 1 |
| Q07 | Payment totals per type, cents → BRL | Correct | All five types agree | Correctly accepted | 23.73 s | 4 |
| Q08 | Every merchandise category, Unknown retained, chart Top 10 | Correct | All 74 categories agree | Correctly accepted | 55.61 s | 4 |
| Q09 | Delivered-only late percentage using calendar dates | Unknown | Not executed | Failed: invalid planner contract | 48.02 s | 1 |
| Q10 | Total/with-payment/without-payment counts | Correct | All three counts agree across two related tables | **False negative:** equivalent outputs did not bind to three named requirements | 61.73 s | 6 |
| Q11 | 2018 paid BRL by all states through three joined tables | Unknown | Not executed | Failed: invalid planner contract | 48.93 s | 1 |
| Q12 | Deliberately unsupported Northwind/Olist product join | Standalone request misrouted as a reference | No calculation; no guessed mapping | Wrong clarification: “Which previous analysis should this refer to?” | 30.85 s | 1 |

**Safety and correctness counts.** There were **zero wrongly certified completed numeric analyses**, but that is not a high success rate. Eight answerable requests failed or remained incomplete. Within those eight were two correct calculations falsely rejected, four planner-schema failures, the wrong distinct-count fallback, and the wrong one-year follow-up scope. There was **one misleading partial answer**: Q02's incomplete table/chart still used the label “Distinct Customer Count” for ordinary order-row counts. It is counted separately from a completed wrong answer, not dismissed as harmless. Q12 did not certify numbers, but it also did not provide the requested clear unsupported-operation explanation.

**Independent numeric controls.** Q03 totals 41,355,549.74 in original dataset currency units; no USD assumption was made. Q04's four correct quarterly values are 9,862,848.04; 10,086,366.80; 10,547,876.35; and 10,858,458.55. The independently expected 2022 total is 39,742,066.18, but no successful two-year comparison was generated in this sequence. Q07 includes credit-card payments of BRL 12,542,084.19; all types total BRL 16,008,872.12. Q08 totals BRL 13,591,643.70, including Unknown at BRL 179,535.28 from 1,603 item rows. Q10 calculated 99,441 total orders, 99,440 with payments and 1 without.

The unexecuted Q09 oracle is 96,478 delivered orders; 8 missing actual dates; 0 missing estimates among orders with actual dates; 96,470 comparable orders; 6,534 late orders; and 6.7730900798175595%. Same-calendar-day delivery is on time. The unexecuted Q11 oracle has 27 states totalling BRL 8,699,763.05; SP is BRL 3,419,478.51 and RJ BRL 1,075,017.63. These are **SQLite expectations**, not claims that the live application produced them.

**Persistence, charts and factual replies.** All 12 responses restored from chat with identical content and package metadata. All six results containing tables reopened from Saved Analyses with identical first-table projections and complete package contents. Q10's second table survived in that package. The three accepted factual replies agree with every requested SQLite result, with matching source and units. Q02's partial numbers agree with its saved table but are not the requested statistic; persistence does not make them correct.

The actual frontend's offline `inspectResult`/`makeChart` code was run on the saved packages without a browser or extra model requests. All six generated plot specifications used their saved table values. Q03 has a 12-point chronological line; Q04 has four points in the incomplete result; Q07 has five bars; Q08 ranks the complete 74-row table and displays exactly the correct leading ten values. Q02's optional bar chart faithfully plots the **wrong partial statistic**. Q10 offers a two-point scatter of the numeric 0/1 flag against count; it is numerically consistent but an unhelpful optional chart for a coverage summary. No conclusion about rendered labels, clipping, focus or interactive state follows from these offline checks.

**Reload assessment.** Immediately before Q06, the runner fetched the normal persisted chat and Saved Analyses endpoints, then submitted the follow-up without supplying client-side analysis context. This tests the backend request pattern after a reload, not an actual browser refresh. Q05 never produced a successful comparison, so there was no successful 2021/2022 context to restore; the latest successful Northwind context was still Q03's 2021-only analysis. Q06 nevertheless set `compare: true` with `years: [2021]`, instead of clarifying the missing comparison. Publication blocked it for a separate kind mismatch. Thus the desired successful comparison → refresh → monthly comparison sequence **remains unverified live**, and this run does not establish that persistence itself lost a successfully stored 2022 year.

**Latency and retries.** The requests took **672.249 seconds** in total; median terminal latency was **52.16 seconds**, range **9.86–171.71 seconds**. Initial progress arrived over HTTP in **24–36 ms**; browser paint time was not measured. Accepted API-ready results took 23.73, 55.61 and 57.02 seconds. Q06 spent about **165.7 seconds in planning**, before calculation started. These delays primarily precede execution; they are not evidence of expensive chart rendering.

There were **28 observed model calls**. Q02 attempted unsupported `count_distinct`, downgraded to ordinary `count`, then executed an effectively duplicate count: the second attempt's `limit:100` was removed by the all-results contract. Q10 first failed because tool parameters contained `filters:[]`, then retried without that field; the contract and tool do not share the same representation of “no filters.” Those are two avoidable failed tool attempts plus one redundant successful execution. Q02/Q07/Q08/Q10 also made four final-answer model calls despite deterministic factual publication replacing the draft prose. No evaluator-level retries or provider/key changes were made. No provider HTTP 429 or authentication failure was observed in this baseline.

**Shared fixes proposed, not implemented.**

1. Establish one executable, typed contract registry shared by planning, tool schemas and completion validation. Give calendar analyses their actual date/grain/years/formula evidence, rather than interpreting `group_by: [OrderDate]` and derived expressions as ordinary aggregation provenance. Q04 must pass because its verified calculation satisfies the request; retain full population/formula/year checks. Do not fix it by dropping those checks or trusting any successful Python execution. Validate output kinds and supported operations early, and return precise JSON-path errors instead of the generic invalid-output message.
2. Execute and bind named outputs from the validated plan. Q10's three planned counts could be executed directly, or an explicit, validated projection could bind the two has_payments rows to the requested with/without counts. Keep multi-table packages; do not force everything into one table, and do not require users to compute missing metrics from prose. Canonicalize omitted filters and empty filters consistently without discarding nonempty predicates.
3. Treat measure identity as operation + population + units, not a model-provided alias. Never retain “Distinct” after downgrading to ordinary count. Until a canonical distinct-count implementation exists across planning, execution and verification, reject that requested measure explicitly or route to a genuinely verifiable supported plan. An incomplete panel must not promote a different statistic under the original label.
4. Separate last successful calculation context from unresolved continuation intent. Keep the successful context intact, but require at least two resolved years for a year comparison or ask a precise clarification. Require a structured standalone/inherit/clarify decision; the current fallback matching any occurrence of “that/those/same” misroutes Q12 even though it explicitly names both sources. Fix the reference-resolution rule, not these exact sentences.
5. Add sanitized planner-contract diagnostics and request-level timing/call records. Existing logs expose agent drafts and tool arguments but not rejected planner JSON, so understanding cannot be reconstructed for Q01/Q05/Q09/Q11. Replay these **actual** live outputs as regressions, then rerun a separate held-out live set. A bounded schema-repair attempt may be appropriate; unlimited retries and incompatible-operation downgrades are not.
6. Once correctness is restored, finalize from verified completion evidence instead of requesting draft factual prose that is discarded. Measure a true request wall-time budget; the provider socket timeout did not cap Q06 at 120 seconds. Latency work should follow the shared correctness fixes rather than changing the UI or removing checks.

**Short browser checklist.** Use the existing evaluation project and saved messages first; no new model calls are needed for these checks. Exact original questions are included below.

- Open Q03 while browsing Customers. Expect Orders × Order Details as result sources, a separate Customers browsing context, 12 month rows and the same 12-point line. Change table sort/page, switch Chart/Table, collapse chat, then refresh and reopen. Confirm the saved data and source stay intact and the plot fits the available space. This run did not visually verify state restoration.
- Open Q08. Expect 74 table rows, Unknown at BRL 179,535.28, BRL units in table/hover, and only ten chart bars. Table pagination or sorting must not change the chart ranking. Reopen it from Saved Analyses after refresh.
- Open Q02 and Q04. Both must visibly say incomplete, including their chat cards and saved entries. Q02 must not look like a successfully verified distinct-count answer; its misleading label is a baseline defect. Q04's four correct values must remain inspectable despite the false-negative status.
- Inspect Q12 in restored chat. The current observed text is the irrelevant previous-analysis clarification, not the desired cross-database refusal. After a future context fix, the expected behavior is a clear unsupported-join explanation with no fabricated numeric result. Do not treat the current completed transport event as completion of that calculation.

**Local evidence and repeatability.** Full HTTP progress, tool parameters, existing logs, saved snapshots, restored messages, offline chart traces and all SQL oracle rows are retained under [the evaluation directory](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/publication-live-2026-11-08). The fixed expectations are in [expected.json](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/publication-live-2026-11-08/expected.json). The runner and assessment scripts were added only as evaluation tooling. Browser rendering remains unverified, and the twelve cases are evidence of specific behavior rather than a statistical guarantee of general reliability.

**Exact questions and predeclared expectations.**

**Q01 — northwind.db::Products**

> Which ten products account for the greatest number of units sold over the entire database? Link Products to Order Details through ProductID, add Quantity for each ProductName, and return only those ten in descending order, with a horizontal bar chart.

Population: Every joined order-detail line; no year/status filter. Formula: `SUM(Quantity) per ProductName`. Units: units. Sources: Products, Order Details. Output scope: `{"table": "top 10", "chart": "top 10"}`.

```sql
SELECT p.ProductName,SUM(d.Quantity) AS Units FROM Products p JOIN "Order Details" d ON p.ProductID=d.ProductID GROUP BY p.ProductName ORDER BY Units DESC,p.ProductName LIMIT 10
```

**Q02 — northwind.db::Orders**

> For every ShipCountry, how many different CustomerID values occur in Orders? Count a customer once per shipping country even if they placed many orders. List every country from highest distinct-customer count to lowest; a table is sufficient.

Population: All Orders; distinct non-null CustomerID within each ShipCountry. Formula: `COUNT(DISTINCT CustomerID)`. Units: customers. Sources: Orders. Output scope: `{"table": "all countries", "chart": "not requested"}`.

```sql
SELECT ShipCountry,COUNT(DISTINCT CustomerID) AS DistinctCustomers FROM Orders GROUP BY ShipCountry ORDER BY DistinctCustomers DESC,ShipCountry
```

**Q03 — northwind.db::Orders**

> For calendar 2021, total net sales separately for each month using OrderDate. Join Orders with Order Details on OrderID and calculate UnitPrice times Quantity times (one minus Discount). Call the measure Net Sales, keep the original currency units, and draw a chronological line.

Population: Order-detail lines whose joined OrderDate falls in [2021]. Formula: `SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) per calendar month`. Units: dataset currency units; no USD assumption. Sources: Orders, Order Details. Output scope: `{"table": 12, "comparison": false, "chart": "chronological line", "series": [2021]}`.

```sql
SELECT CAST(strftime('%Y',o.OrderDate) AS INTEGER) AS Year,CAST(strftime('%m',o.OrderDate) AS INTEGER) AS Period,SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) AS NetSales FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021') GROUP BY 1,2 ORDER BY 1,2
```

**Q04 — northwind.db::Orders**

> Keep that same sales definition and year, but roll the months up into calendar quarters. Please calculate the four quarterly amounts and use a line chart.

Population: Order-detail lines whose joined OrderDate falls in [2021]. Formula: `SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) per calendar quarter`. Units: dataset currency units; no USD assumption. Sources: Orders, Order Details. Output scope: `{"table": 4, "comparison": false, "chart": "chronological line", "series": [2021]}`.

```sql
SELECT CAST(strftime('%Y',o.OrderDate) AS INTEGER) AS Year,(CAST(strftime('%m',o.OrderDate) AS INTEGER)+2)/3 AS Period,SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) AS NetSales FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021') GROUP BY 1,2 ORDER BY 1,2
```

**Q05 — northwind.db::Orders**

> Put those four periods side by side with 2022, retaining 2021 and exactly the same net-sales formula. I want one row per quarter and a separate sales column and line for each year.

Population: Order-detail lines whose joined OrderDate falls in [2021, 2022]. Formula: `SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) per calendar quarter`. Units: dataset currency units; no USD assumption. Sources: Orders, Order Details. Output scope: `{"table": 4, "comparison": true, "chart": "chronological line", "series": [2021, 2022]}`.

```sql
SELECT CAST(strftime('%Y',o.OrderDate) AS INTEGER) AS Year,(CAST(strftime('%m',o.OrderDate) AS INTEGER)+2)/3 AS Period,SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) AS NetSales FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1,2 ORDER BY 1,2
```

**Q06 — northwind.db::Orders**

> Switch that comparison back to months, leaving both years and the sales calculation as they are. Give twelve aligned month rows and two lines.

Population: Order-detail lines whose joined OrderDate falls in [2021, 2022]. Formula: `SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) per calendar month`. Units: dataset currency units; no USD assumption. Sources: Orders, Order Details. Output scope: `{"table": 12, "comparison": true, "chart": "chronological line", "series": [2021, 2022]}`.

```sql
SELECT CAST(strftime('%Y',o.OrderDate) AS INTEGER) AS Year,CAST(strftime('%m',o.OrderDate) AS INTEGER) AS Period,SUM(d.UnitPrice*d.Quantity*(1-d.Discount)) AS NetSales FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1,2 ORDER BY 1,2
```

**Q07 — olist.db::order_payments**

> How much money was recorded for each payment_type across all Olist payment records? Sum payment_value_cents, convert the summed amounts to BRL by dividing by 100, call the measure Paid Amount (BRL), and list every payment type in descending amount order with a bar chart.

Population: All payment records; not just delivered orders. Formula: `SUM(payment_value_cents)/100`. Units: BRL. Sources: order_payments. Output scope: `{"table": "all payment types", "chart": "bar"}`.

```sql
SELECT payment_type,SUM(payment_value_cents)/100.0 AS PaidBRL FROM order_payments GROUP BY payment_type ORDER BY PaidBRL DESC,payment_type
```

**Q08 — olist.db::order_items**

> Report merchandise sales for every product category, joining order_items and products by product_id. Treat a missing or blank product_category_name as Unknown. Use SUM(price_cents)/100 as Merchandise Sales (BRL), sorted largest first. The result table must retain every category; only the chart should show the leading ten.

Population: Every item with its declared product relationship; missing category retained. Formula: `SUM(price_cents)/100 per category; NULL/blank -> Unknown`. Units: BRL. Sources: order_items, products. Output scope: `{"table": "all categories", "chart": "top 10"}`.

```sql
SELECT COALESCE(NULLIF(p.product_category_name,''),'Unknown') AS Category,SUM(i.price_cents)/100.0 AS SalesBRL FROM order_items i JOIN products p ON i.product_id=p.product_id GROUP BY 1 ORDER BY SalesBRL DESC,Category
```

**Q09 — olist.db::orders**

> Among orders marked delivered, what fraction reached the customer later than the estimated delivery date? Compare calendar days, so a delivery later in the day on the estimated date is on time. Show the delivered population, missing actual dates, missing estimates among orders with actual dates, comparable order count, late count, and late percentage. Do not drop missing dates without reporting them.

Population: Delivered orders; percentage denominator has both comparison dates. Formula: `date(actual)>date(estimated); 100*Late/Comparable`. Units: orders and percent. Sources: orders. Output scope: `{"table": "population summary", "chart": "not requested"}`.

```sql
SELECT COUNT(*) AS Delivered,SUM(order_delivered_customer_date IS NULL) AS MissingActual,SUM(order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NULL) AS MissingEstimate,COUNT(CASE WHEN order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL THEN 1 END) AS Comparable,SUM(CASE WHEN order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL AND date(order_delivered_customer_date)>date(order_estimated_delivery_date) THEN 1 ELSE 0 END) AS Late,100.0*SUM(CASE WHEN date(order_delivered_customer_date)>date(order_estimated_delivery_date) THEN 1 ELSE 0 END)/COUNT(CASE WHEN order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL THEN 1 END) AS LatePercent FROM orders WHERE order_status='delivered'
```

**Q10 — olist.db::order_financials**

> Audit payment coverage in order_financials without joining any line-item tables. Return three explicit numbers: total orders, orders with at least one payment record, and orders with no payment record. Calculate the missing count rather than leaving me to subtract it; a compact table is enough.

Population: All one-row-per-order financial records. Formula: `COUNT(*), SUM(has_payments), COUNT(*)-SUM(has_payments)`. Units: orders. Sources: order_financials. Output scope: `{"table": "three calculated counts", "chart": "not requested"}`.

```sql
SELECT COUNT(*) AS TotalOrders,SUM(has_payments) AS WithPayments,COUNT(*)-SUM(has_payments) AS WithoutPayments FROM order_financials
```

**Q11 — olist.db::order_financials**

> For purchases made during 2018, show total paid BRL for every customer_state. Use order_financials joined to orders on order_id and then customers on customer_id. Keep only has_payments = 1, sum payment_total_cents and divide by 100, and rank all states by Paid Amount (BRL). Do not join order_items or multiply payments by item counts.

Population: One financial record per paid order purchased in 2018. Formula: `SUM(payment_total_cents)/100 per customer_state`. Units: BRL. Sources: order_financials, orders, customers. Output scope: `{"table": "all states", "chart": "not requested"}`.

```sql
SELECT c.customer_state,SUM(f.payment_total_cents)/100.0 AS PaidBRL FROM order_financials f JOIN orders o ON f.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE f.has_payments=1 AND o.order_purchase_timestamp>='2018-01-01' AND o.order_purchase_timestamp<'2019-01-01' GROUP BY c.customer_state ORDER BY PaidBRL DESC,c.customer_state
```

**Q12 — northwind.db::Products**

> Can the current application join northwind.db::Products to olist.db::products using ProductID = product_id and calculate the number of matched products? If cross-database joins or that relationship are unsupported, clearly decline this calculation instead of inventing a product mapping.

Population: Two different SQLite databases with unrelated identifier domains. Formula: `Cross-database join is deliberately unsupported by V1; no approved relationship`. Units: no numeric result should be certified. Sources: northwind.db::Products, olist.db::products. Output scope: `{"table": "none", "chart": "none"}`.

```sql
-- Unsupported cross-database relationship: no certified numeric answer expected.
```
