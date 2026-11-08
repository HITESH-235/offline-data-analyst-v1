# Monthly revenue for 2022: investigation and correction

Investigated the saved response to `show monthly revenue for year 2022` on
2026-11-07. No live model calls or browser tests were used for this investigation.

## Data source actually used

The backend resolves `northwind.db::Orders` to `/app/datasets/northwind.db`.
The host copy is `/home/hit235/Projects/offline-data-analyst/datasets/northwind.db`.
Both are 24,702,976 bytes and have identical SHA-256:

`2f4f5c68dfcd33ba27373eae48c7a4869800c68095ee0f9f0da494f83382a877`

Full Orders coverage: **2012-07-10 15:40:46 through 2023-10-28 00:09:48**.
There are **16,282 Orders**, including **1,352 in 2022**.

| Year | Orders |
|---|---:|
| 2012 | 654 |
| 2013 | 1,351 |
| 2014 | 1,351 |
| 2015 | 1,449 |
| 2016 | 1,506 |
| 2017 | 1,780 |
| 2018 | 1,549 |
| 2019 | 1,362 |
| 2020 | 1,376 |
| 2021 | 1,420 |
| 2022 | 1,352 |
| 2023 | 1,132 |

## Root cause

The model emitted a filtering call with these predicates:

```json
{"filters":[
  {"column":"OrderDate","operator":">=","value":"2022-01-01"},
  {"column":"OrderDate","operator":"<=","value":"2022-12-31"}
]}
```

The old `filter_data()` implemented all ordered comparisons using `float(value)`.
ISO dates cannot be converted to floats. Its broad exception handler silently
continued after both failures, leaving all **609,283 joined rows** unchanged.
Unknown columns, unsupported operators, malformed `in` values, and invalid filter
containers also had silent no-op paths.

The tool wrapper validated aggregation parameters but not filter semantics. It
called the unchanged result successful, exposed its first five rows to the model,
and returned the entire join to the frontend. The model then incorrectly treated
an old-date preview and unchanged row count as evidence that 2022 was absent.
Neither establishes date coverage. No revenue formula or month grouping had run.
The saved metadata containing raw rows was approximately 298 MB.

## Fix

- Validate every predicate, column, operator, value, and type before applying any
  mask, including on empty frames. Unsupported inputs raise precise errors.
- Parse mixed ISO dates/timestamps strictly with `format='mixed'`, UTC, and
  `errors='raise'`. No invalid date is silently discarded.
- Preserve legitimate numeric/string/boolean filters; literal `contains` does not
  interpret input as a regular expression. Audit input/matched row counts.
- Use a half-open calendar-year interval: `>= 2022-01-01` and `< 2023-01-01`.
  An inclusive midnight bound `<= 2022-12-31` excludes later times on December 31.
- Add a validated `monthly_revenue` tool with separate year/date/price/quantity/
  discount fields. It filters, derives line-item revenue, groups by YYYY-MM, and
  returns only the monthly aggregate plus date/count facts.
- Bounded standard requests such as the original question use this calculation
  after source-table selection, without model-written calculation/final claims.
  The broader agent can also call the named tool. A SIMPLE monthly-revenue request
  cannot finish by exposing raw filter rows; verified monthly explanations are
  generated from calculated facts instead of the model's final text.
- Clearly label preview rows as non-exhaustive. An unchanged validated filter means
  all rows matched, never that a year is absent. Exhausted/failed calculations do
  not return partial raw tables as successful answers.
- Monthly aggregates enable the existing chronological line renderer and cannot
  be reclassified as raw distributions.

## Independent comparison

```sql
SELECT strftime('%Y-%m', o.OrderDate) AS Month,
       SUM(d.UnitPrice * d.Quantity * (1 - d.Discount)) AS Revenue
FROM Orders AS o
JOIN "Order Details" AS d ON o.OrderID = d.OrderID
WHERE o.OrderDate >= '2022-01-01' AND o.OrderDate < '2023-01-01'
GROUP BY strftime('%Y-%m', o.OrderDate)
ORDER BY Month;
```

The application computes from the independently loaded joined dataframe using
Pandas filtering, arithmetic, and grouping. The SQL query separately joins and
aggregates in SQLite. All 12 values match with **maximum absolute difference 0**.
The year contains **53,835 joined line items**.

| Month | Application | SQLite | Difference |
|---|---:|---:|---:|
| 2022-01 | 3,591,353.72 | 3,591,353.72 | 0 |
| 2022-02 | 2,832,321.16 | 2,832,321.16 | 0 |
| 2022-03 | 3,222,005.69 | 3,222,005.69 | 0 |
| 2022-04 | 2,628,034.83 | 2,628,034.83 | 0 |
| 2022-05 | 3,719,270.11 | 3,719,270.11 | 0 |
| 2022-06 | 3,378,131.17 | 3,378,131.17 | 0 |
| 2022-07 | 3,358,177.30 | 3,358,177.30 | 0 |
| 2022-08 | 3,660,257.83 | 3,660,257.83 | 0 |
| 2022-09 | 2,606,755.13 | 2,606,755.13 | 0 |
| 2022-10 | 3,717,586.61 | 3,717,586.61 | 0 |
| 2022-11 | 3,542,815.27 | 3,542,815.27 | 0 |
| 2022-12 | 3,485,357.36 | 3,485,357.36 | 0 |
| Total | **39,742,066.18** | **39,742,066.18** | **0** |

No currency symbol is inferred from UnitPrice alone.

## Saved-result repair and checks

The existing incorrect assistant response was corrected in place, retaining the
original question, source tables, and an audit of its superseded invalid filter.
The replacement `results` has just `Month`, `Revenue`, and 12 rows. Saved Analyses
and past-chat API reads return this aggregate with a line-chart blueprint.

Replacing the large record through Docker's shared mount reported an SQLite I/O
error and an invalid freelist. The healthy pre-correction backup was restored
host-side with only the checked response correction. All 20 chats were retained;
all unrelated chat records, projects, and datasets were compared unchanged.
The repaired database passed `integrity_check`; the restarted backend passed
`quick_check`. There was no workspace reset or deletion of old chats.

Regression coverage includes the exact emitted filters on mixed-date fixtures and
the real full join; malformed filters even on empty input; bad source dates;
end-of-year timestamps; wrong measure inputs; the revenue formula; all 12 SQL
comparisons; original-question API processing and saved-result roundtrip; and
rejection of false model conclusions/raw-filter substitutes. Frontend coverage
checks chronological line selection and excludes distribution charts for aggregates.

Browser testing remains with the user:

1. Refresh the dashboard and open the relevant project's Saved Analyses or Past chats.
2. Open `show monthly revenue for year 2022`.
3. Confirm a 12-row Month/Revenue table, the total above, and both source tables.
4. Switch to Chart: expect a chronological line from January through December.
5. Inspect calculation details: the superseded filter is documented; the final
   `monthly_revenue` operation succeeded with the corrected half-open year bounds.
6. For a fresh run, select Orders and submit the original question again.
