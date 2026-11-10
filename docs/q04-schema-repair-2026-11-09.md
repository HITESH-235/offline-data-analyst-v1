# Q04 schema-repair correction — 9 November 2026

The captured Q04 failure was a false semantic rejection, not an incorrect revenue calculation. The first planner response placed `chart_scope` inside an output and placed `compare`, `filters` and `output` inside its `metric`. Its single repair returned strict, correctly nested JSON. The old guard nevertheless froze `metric.compare` at its original path and treated relocation as deletion. It also lacked canonical comparison for omitted chart defaults.

[repair_semantics.py](/home/hit235/Projects/offline-data-analyst/server/app/analysis/repair_semantics.py) now provides a comparison-only ownership projection using the execution registry's models. Calendar fields that Metric does not own can move to their immediate Calendar owner. A misplaced chart scope can move from a single output to the analysis-wide owner. Equal duplicate copies are compared canonically; conflicting copies fail. Multiple-output chart-scope relocation is refused because ownership would be ambiguous. Arbitrary containers and unknown relocation routes are not guessed.

The rejected JSON is never executed. The repaired response must pass strict planner and operation validation. Canonical snapshots compare resolved sources and join edges, years, grouping, formula, predicates, units, transformations, table/output scope and chart scope, plus reference decisions. Schema defaults, predicate aliases/order and supported associative formula forms are normalized. Literal nulls and boolean versus numeric predicates remain distinct. Rejected data is copied for comparison without altering the captured diagnostic.

The existing conservative guard remains for inputs that still cannot be interpreted strictly. It now protects semantic values inside unknown containers and scope fields without exempting an entire invalid JSON subtree. The single-repair budget, actual-error repair prompt, execution validators and publication/completion requirements remain intact.

**Regression evidence.** [misplaced_calendar_scope_observation.json](/home/hit235/Projects/offline-data-analyst/server/tests/fixtures/misplaced_calendar_scope_observation.json) contains the exact original and repaired payloads from the resumed live Q04 capture, with its SHA256 and the real successful Q03 reference plan. The normal request processor calculates the monthly seed and saves it with the captured reference ID; Q04 then runs through actual planning, execution, publication, saving and reopening. All four quarter values match SQLite. Both captured payloads remain unchanged; only test-generated message IDs are controlled to recreate the original reference.

Negative variants through the normal processor change years, remove a real predicate, change a formula operand, units, source, join keys, table/chart output and chart scope, or introduce conflicting copies/unknown ownership. Each fails before calculation, publishes no numeric result and leaves the previous successful context and saved result intact. Additional tests cover equivalent duplicate fields, predicate ordering/equality aliases, formula association, unknown containers, ambiguous multi-output scope and strict rejection of a still-malformed repaired plan.

**Checks.** The five focused regression methods passed (17.725 seconds). The full automated backend suite passed **144 tests** (1463.779 seconds wall time). All three frontend test files passed. The separate production build passed (**544 ms**). `git diff --check` passed. The first full run exposed only a diagnostic-wording regression; the final error retains explicit population wording and the precise semantic field path. Browser testing was not performed.

**Live verification: all four requests passed.** The unchanged frozen Q03 → Q04 → Q05 → Q06 questions ran through the configured live model and normal HTTP endpoint in a new project. Existing SQLite expectations were reused. No production source changed during the batch; no provider quota error occurred. The runner retains its stop-on-HTTP-429 behavior.


| Case | Live result | Rows / series | SQLite values and labels | Time | Model calls |
|---|---|---|---|---:|---:|
| Q03 | 2021 monthly net sales — complete | 12 rows / 1 series | Every period matches | 108.965 s | 2 |
| Q04 | Same metric/year quarterly — complete | 4 rows / 1 series | Every period matches | 44.355 s | 1 |
| Q05 | 2021 versus 2022 quarterly — complete | 4 rows / 2 series | Every period matches | 36.754 s | 1 |
| Q06 | Same comparison monthly after persisted-history reload — complete | 12 rows / 2 series | Every period matches | 28.448 s | 1 |

Q03 needed one schema repair for `changed_fields: null`; its calculation remained unchanged. Q04, Q05 and Q06 each succeeded on their first response. Thus the fresh Q04 did not itself reproduce the malformed nesting; the exact captured two-response replay separately verifies the new relocation handling through execution and storage. Total live time was **218.522 seconds**, with **5 model calls**. First HTTP progress arrived in 30–47 ms; browser paint time was not measured.

Every month/quarter label and value matches the independent SQLite expectations. Both quarter and month comparisons retain annual sums **41,355,549.74 (2021)** and **39,742,066.18 (2022)**. Q06 returns twelve aligned month rows and both year columns/line series after the runner fetches restored history and Saved Analyses, then posts the follow-up without client-supplied context. This verifies the backend reload pattern; it is not an actual browser refresh.

All four completed packages reopen identically, including their tables, sources, calculation provenance and stored chat metadata. Factual replies contain the same formatted period values. The actual offline frontend chart model produces matching line data for every period: one series for Q03/Q04 and two for Q05/Q06. No browser rendering was used to infer those checks.

The new project is **q04-repair-live-2026-11-09 2026-11-09 18:00:42**, ID `6b6deceb-45d7-4fea-80c1-e097c3ff4672`. Full HTTP events, sanitized planner diagnostics, saved/reopened packages, restored messages, source hashes, test/build logs and the numeric checks are in [the new evidence directory](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/q04-repair-live-2026-11-09); the compact machine-readable outcome is [verification.json](/home/hit235/Projects/offline-data-analyst/workspace/evaluations/q04-repair-live-2026-11-09/verification.json). All **63** baseline/resumed evidence files stayed byte-for-byte unchanged; both source SQLite databases are unchanged. No old saved response was modified. There were **no remaining failures in this four-request live sequence**.

**Browser checks left to the user.** Select the new project above and use its saved/chat results, so no additional model calls are required:

1. Browse **Northwind → Customers**, then open Q04. Expect four 2021 quarters with Orders × Order Details as the separate result source. Confirm the four table values match the line, and calculation details start collapsed.
2. Open Q05: four quarters, separate Net Sales 2021/2022 columns and two lines. Open Q06: twelve aligned months and two lines. Table sort/page changes, Table/Chart switching and chat collapse/resize should preserve the result and browsing contexts.
3. Refresh and reopen Q06 from Saved Analyses and past chat. Confirm the same values, both years and calculation/source provenance remain available. A real interactive refresh followed by a new follow-up remains a browser check.

Exact frozen questions identifying these results (or for a deliberate fresh browser sequence; refresh after Q05 before Q06):

**Q03**

> For calendar 2021, total net sales separately for each month using OrderDate. Join Orders with Order Details on OrderID and calculate UnitPrice times Quantity times (one minus Discount). Call the measure Net Sales, keep the original currency units, and draw a chronological line.

**Q04**

> Keep that same sales definition and year, but roll the months up into calendar quarters. Please calculate the four quarterly amounts and use a line chart.

**Q05**

> Put those four periods side by side with 2022, retaining 2021 and exactly the same net-sales formula. I want one row per quarter and a separate sales column and line for each year.

**Q06**

> Switch that comparison back to months, leaving both years and the sales calculation as they are. Give twelve aligned month rows and two lines.


The ownership normalization remains deliberately conservative. Unknown layouts, conflicting copies and ambiguous per-output chart scopes in multiple-output plans are rejected rather than guessed. The full 12-question baseline and the separate held-out sets were not rerun in this focused task; their earlier reports remain historical evidence. Browser layout/focus/hover/resize and actual interactive refresh remain unverified. No commit or push was made.
