# Result charts: implementation and verification

## Northwind data check

The supplied local `datasets/northwind.db` contains 77 products and **609,283**
order-detail rows. On 2026-11-05, an independent SQLite query was compared with
all six available saved ProductName/Quantity rankings in `workspace/metadata.db`:

```sql
SELECT p.ProductName, SUM(od.Quantity) AS Quantity
FROM Products AS p
JOIN "Order Details" AS od ON p.ProductID = od.ProductID
GROUP BY p.ProductID, p.ProductName
ORDER BY Quantity DESC, p.ProductName;
```

All 77 products and totals matched in each snapshot; all six snapshots were
ordered by descending quantity. No values or calculation logic were changed.
The leading products are:

| Product | Units |
|---|---:|
| Louisiana Hot Spiced Okra | 206,213 |
| Sir Rodney's Marmalade | 205,637 |
| Teatime Chocolate Biscuits | 205,487 |
| Sirop d'érable | 205,005 |
| Gumbär Gummibärchen | 204,761 |

A captured 77-row snapshot is in `client/tests/fixtures/northwind-ranking.json`.
The data is larger than the familiar small Northwind sample; this check confirms
consistency with the provided local database, not the provenance of its rows.

## Rendering architecture

The Result workspace now uses the same Plotly renderer family as Python
`ChartEngine`, replacing the former CSS-only bars. Its offline Plotly.js bundle
is copied from the existing Python package and loaded locally only when a chart
is first opened. There is no new npm dependency or CDN request. Python remains
responsible for standalone HTML artifacts; it does not generate live Result
charts or choose their types. Both paths use opaque white surfaces and the
ink/porcelain/teal palette.

`chartModel.js` is the single deterministic selection/transform implementation
for Results. It considers actual cell types, declared types when provided,
calculation provenance, question hints, and explicit raw-observation confirmation.
Only compatible types/field pairs are offered. Conflicting, missing, or ambiguous
information does not trigger a model call. Users choose fields or confirm row
meaning. IDs are excluded. Summary values never enable distribution charts.

Bars rank the full result once per field selection and retain only the top 20.
Top 5/10/20 slices reuse that ranking. Other chart types do not apply Top N.
Time series use parsed ISO dates rather than lexical sorting and never silently
combine duplicate timestamps. Bars do not combine duplicate categories.
Histograms count finite observations; boxes use linear quartiles and 1.5 IQR
whiskers, displaying outliers. Heatmaps use supplied correlation values rather
than recomputing correlations from already-calculated coefficients.

## Checks

Run the build and browser checks separately:

```bash
docker --context desktop-linux compose exec -T frontend npm test
docker --context desktop-linux compose exec -T frontend npm run build
node client/tests/browser-charts.mjs
```

The browser script requires Chrome and a running app on localhost:3001. Override
`CHROME_PATH` or `APP_URL` if needed. It replaces saved-analysis reads and chat
responses with fixtures and forbids live model requests. It does not save test
messages or modify the project database.

Checks cover all six types, negative values, nulls, long labels, empty and
ambiguous results, automatic selection, manual overrides, numeric axes, opaque
surfaces, keyboard value inspection, and 390px narrow layouts. Northwind Top
5/10/20 are checked against the captured table, with Customers still selected.
Table sorting/page and chart choices survive view switching. Calculation details
start collapsed. Captured progress/completion leaves the current canvas in place;
opening the resulting chat card shows the same ranking. A 50,000-row ranking
fixture renders at most 20 bars. Chart interactions make zero backend requests.

## Limits

- The local Plotly bundle adds approximately 4.8 MB uncompressed, loaded on demand.
- Dates must be unambiguous ISO months/dates or timezone-qualified ISO timestamps.
  Ambiguous locale dates and numeric epoch units are not guessed.
- Duplicate categories/timestamps need an explicit grouping analysis before a
  ranking/time-series chart is available; the browser never silently aggregates.
- Very large scatter plots, large correlation matrices, and hundreds of box
  groups are not performance-benchmarked. The large-fixture check covers ranking.
- Keyboard value inspection is checked in Chrome; a full screen-reader audit and
  other browser engines remain untested.
