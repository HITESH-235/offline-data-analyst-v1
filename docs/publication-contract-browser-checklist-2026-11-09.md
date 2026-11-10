# Browser checks after the contract fix

Use existing captures first; these steps need no new model calls. Rendered layout and interaction remain unverified.

Open project **publication-contract-release-regression-2026-11-09 2026-11-09 13:01:34**, ID `e66abb92-98e5-4bdc-82a5-9d32a932bf3e`. It contains the last unblocked live run, not the final quota-blocked project. Q03 failed in this captured run and Q04 asked for clarification; those old messages are preserved evidence, not repaired records.

1. Select **northwind.db → Customers** for browsing. Open the saved/chat result for Q06. Expect **12 month rows**, separate **Net Sales 2021 / Net Sales 2022** columns, two chronological line series, and result sources **Orders + Order Details** while the browsing context stays **Customers**. Annual sums: **41,355,549.74 / 39,742,066.18**. Change table sorting/page, switch Chart/Table, collapse/resize chat, refresh and reopen. Check values, series, selection, layout and the initially collapsed calculation toggle.
2. Open Q08. Expect **74 category rows**, **Unknown = BRL 179,535.28**, and **10 chart bars**. Sorting/page changes must leave chart ranking unchanged. Refresh and reopen; currency values in table/chart/hover must agree.
3. Open Q10. Inspect all three named outputs: **99,441 total orders**, **99,440 with payments**, **1 without**. They belong to one saved analysis package. The answer must not require manual subtraction.
4. Inspect Q12 in restored chat. Expect an explicit unsupported cross-database-join message, with no fabricated match count or successful numeric Open result.

Exact captured questions:

**Q06**

> Switch that comparison back to months, leaving both years and the sales calculation as they are. Give twelve aligned month rows and two lines.

**Q08**

> Report merchandise sales for every product category, joining order_items and products by product_id. Treat a missing or blank product_category_name as Unknown. Use SUM(price_cents)/100 as Merchandise Sales (BRL), sorted largest first. The result table must retain every category; only the chart should show the leading ten.

**Q10**

> Audit payment coverage in order_financials without joining any line-item tables. Return three explicit numbers: total orders, orders with at least one payment record, and orders with no payment record. Calculate the missing count rather than leaving me to subtract it; a compact table is enough.

**Q12**

> Can the current application join northwind.db::Products to olist.db::products using ProductID = product_id and calculate the number of matched products? If cross-database joins or that relationship are unsupported, clearly decline this calculation instead of inventing a product mapping.

For a real browser refresh/follow-up test **after provider quota resets**, create a separate test project and select **Northwind → Orders**. Submit these exact questions in order. Q03 should return 12 months, Q04 four quarters, Q05 four quarters with two year columns/lines. Refresh after Q05, then submit Q06; it must retain both years and return 12 aligned months. Independent totals remain 41,355,549.74 and 39,742,066.18. A request finishing must leave the current canvas alone until Open result is clicked. Do not rerun these while the provider still returns HTTP 429.

**Q03**

> For calendar 2021, total net sales separately for each month using OrderDate. Join Orders with Order Details on OrderID and calculate UnitPrice times Quantity times (one minus Discount). Call the measure Net Sales, keep the original currency units, and draw a chronological line.

**Q04**

> Keep that same sales definition and year, but roll the months up into calendar quarters. Please calculate the four quarterly amounts and use a line chart.

**Q05**

> Put those four periods side by side with 2022, retaining 2021 and exactly the same net-sales formula. I want one row per quarter and a separate sales column and line for each year.

**Q06**

> Switch that comparison back to months, leaving both years and the sales calculation as they are. Give twelve aligned month rows and two lines.

Final held-out expectations are frozen separately, but the live model has not answered them because of HTTP 429. After quota resets, their exact questions and SQL are in `workspace/evaluations/publication-contract-final-heldout-2026-11-09/expected.json`: H07 expects 24 installment groups totaling BRL 12,542,084.19; H08 expects population 1,683, missing actual 2, missing comparison 0, comparable 1,681, late 367 and 21.83224271267103%. These are SQLite expectations, not claimed live results.
