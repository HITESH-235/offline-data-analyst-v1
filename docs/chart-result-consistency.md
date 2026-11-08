# Histogram result consistency

The captured response `52bccfb6-6dca-4ae6-ba1d-8e621c63150d` contained two successful Python attempts. The first plotted raw net line amounts; the second grouped those amounts by OrderID before plotting. The narrative described only the second attempt, but the agent appended artifacts from both and the UI opened the first by default.

The second saved PNG was inspected. Its axes describe order totals and number of orders. A read-only SQLite query on `datasets/northwind.db` independently returned:

```sql
SELECT OrderID, SUM(UnitPrice * Quantity * (1 - Discount)) AS OrderTotal
FROM "Order Details"
GROUP BY OrderID;
```

There are 16,282 orders. Their minimum, maximum, mean, median and sample standard deviation are 12.50, 73,431.42, 27,538.793340468, 27,013.56 and 17,726.107464197. Their total is 448,386,633.1695. These match the final captured narrative to its displayed precision.

The saved response now exposes only the second PNG. The earlier calculation is retained as superseded. The old chart files and original database were backed up under `/tmp/histogram-consistency-backup-jevnehrd`. This historical capture has no plot-time population fingerprint and is not retroactively labelled as automatically verified.

For new analyses:

- A later successful chart-producing Python call replaces the earlier candidate chart set. All intended final charts must be created together. Superseded steps remain in calculation history, while their unpublished artifact files are removed.
- The supported request “Show a histogram of individual order totals after discounts” has an explicit deterministic contract: compute net line amounts and sum by OrderID.
- Matplotlib histograms record observation summaries at plotting time, including figures closed before capture; Plotly histograms record their actual trace observations. Validation compares the count and a digest of sorted values rounded to eight decimal places with the deterministic per-order population. Renaming a line-item chart, or supplying different values with the same count, fails.
- Weighted, missing, unsupported or mismatched histogram captures fail before artifact persistence and return actionable feedback to the agent. A final success requires verified artifacts. Its narrative statistics are generated from the same verified population, rather than model-supplied numbers.
- The frontend displays the population for newly verified artifacts. No new chart types or model calls were added.

## Scope and manual check

This deterministic population guard covers the supported order-total histogram wording and resolved Northwind columns. It is not a general verifier of arbitrary Python analyses. Custom pre-binned bar histograms and other unverifiable renderers fail explicitly for this guarded request.

Refresh the app, reopen the saved histogram through its chat card or Saved Analyses, and confirm only the order-total PNG appears. Expand calculation details to see the superseded first attempt. Submit the same histogram question against Order Details and confirm the chart and narrative both describe 16,282 orders, with the verified population note beneath the chart. Save/reopen or reload that new response to check the metadata persists.

Regression coverage was added in `server/tests/test_chart_consistency.py`: wrong population despite a plausible title, same count but wrong values, both axes sharing the correct population, weighted/unverifiable captures, empty/invalid inputs, actual Matplotlib/Plotly sandbox delivery, and revised artifacts replacing prior candidates. These tests, the build, live model requests, and browser checks were intentionally not run in this pass; user requested to handle testing.
