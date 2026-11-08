# Monthly regrouping after a comparison

## Observed failure

The saved comparison `e697411d-3469-491a-81b9-e49a1a078e0c` already contained the correct resolved context in both metadata and result: years `[2021,2022]`, `compare:true`, quarter grouping, the discounted revenue expression, Orders/Order Details and OrderID join keys. The subsequent “Show that monthly instead” response `4ee1f528-d3ce-47dc-934a-bd74db6a0df0` persisted `[2021]`, `compare:false` and month grouping.

This was not a missing comparison write. The planner received several successful analyses, was permitted to select an older reference, and returned a full replacement state. The API shallow merge allowed that full state to overwrite the comparison scope. The original request did not persist the planner's selected reference, so the exact reference choice versus replacement-field overwrite cannot be distinguished retrospectively.

## Correction

A reference-only calendar grouping edit is resolved before the model, against the latest successful analysis. A generic vocabulary of calendar grains and regrouping language recognizes these edits without using Northwind identifiers or the exact reproduction sentence. Explicit metric/source/year changes continue through semantic planning; ambiguous references retain the clarification flow.

The grouping resolver returns only a grain patch and the latest successful message ID. Applying the patch preserves comparison years/flag, metric/expression, filters, date column, source database/tables/join keys and output. It cannot reselect the original monthly question or replace years with a one-year model default.

Persistence now treats the calculated result's resolved analysis context as authoritative, with the top-level context as a fallback. Restoration uses the same precedence, rather than reconstructing scope from the original question. Each new response records the selected reference, the latest successful reference, resolution kind and changed fields in context_resolution metadata. The resolved state is saved after successful calculation through the existing result, chat and Saved Analyses paths.

## Regression checks

The full monthly → quarterly → comparison → monthly sequence is exercised with and without closing/reopening the database session. The test deliberately supplies a stale planner reference and single-year replacement state; the grouping-only request bypasses that plan and inherits the latest comparison. It checks 12 rows, Revenue 2021/Revenue 2022 columns, both chart series, all unchanged context fields, persisted result/top-level contexts and selected-reference audit metadata.

All 24 monthly values are compared independently against SQLite JOIN/SUM/GROUP BY. The expected annual totals are 41,355,549.74 for 2021 and 39,742,066.18 for 2022. Frontend coverage verifies the monthly comparison produces two chronological 12-point series, unaffected by Top N. Additional coverage checks authoritative nested result context and that explicit metric/year changes do not enter the grouping-only resolver.

Browser verification is left to the user: run the three initial questions, refresh, submit “Show that monthly instead”, then open Result. Expect 12 month rows, separate Revenue 2021/Revenue 2022 columns, two chart series and the annual totals above. Calculation details must still show Orders × Order Details on OrderID and UnitPrice × Quantity × (1 − Discount).

## Completed verification

All 18 backend context/planner tests passed, including the full sequence with and without a new database session, followed by frontend tests and the production build. The live first-three-turn sequence created comparison `91f741f1-0e78-4f00-9e94-d3dfa3f8b58a`. After restarting the backend, “Show that monthly instead” created `f57421ee-8dd0-40d8-aae2-8ca26ba4d5dd` in 6.38 seconds. The saved resolution references that latest comparison and updates only grain. Both years and comparison mode remain intact.

All 24 returned monthly values matched independent SQLite calculations within 1e-5. The response contains 12 rows, Revenue 2021/Revenue 2022 columns, and two chart series. Annual sums remain 41,355,549.74 and 39,742,066.18. Narrative, top-level/result contexts, and the running Saved Analyses endpoint agree. No historical responses were edited. Browser testing remains with the user.
