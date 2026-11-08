# Live comparison_summary contract correction

## Captured mismatch

Failed response `2d80d2d8-8e6c-4120-9d27-e3b8e11d2872` contained the original delivered-order/calendar-date question and a planner-selected comparison_summary call with matched_label: Late and eligibility_filters containing order_status operator = value delivered.

The calculator accepted filters rather than eligibility_filters. Its generic error did not mention matched_label even though matched_label was already accepted. After fixing the population field, the = equality alias would also have failed the scalar filter engine's == operator contract. The planner prose said “eligibility filters” without a concrete field schema, while the agent example used filters. Thus the planner and tool had different effective schemas. Previous controlled tests supplied the supported filters/== spelling and did not reproduce this live call. Planner-selected tool failures also returned immediately instead of entering the agent's correction path.

## Canonical contract

comparison_summary.py defines PARAMETER_SCHEMA, EXAMPLE_PARAMETERS, contract_instructions and normalize_parameters. The same generated schema/example is included in both planner and agent tool prompts. The canonical population argument is eligibility_filters, with predicates using == for equality. matched_label is explicitly documented and validated.

The dispatch boundary explicitly normalizes two compatibility spellings: legacy filters → eligibility_filters, and = → ==. This is a bounded, documented normalization, not ignoring unknown arguments or removing a failed predicate. Supplying both population fields is an error, as are unknown fields, malformed predicates, unsupported operators and missing columns. Event comparisons remain separate from population filters so the denominator cannot be prefiltered to late orders. Date parsing and same-calendar-day behavior are unchanged.

Both planner-selected and agent-selected execution use the same dispatch normalization and calculation. Raw arguments remain in the step trace; canonical arguments, including the complete population predicates, are stored in comparison_audit.parameters. Fingerprints canonicalize equivalent aliases, preventing an incompatible failed call from being executed again under a different spelling.

A failed planner-selected call now seeds the existing bounded agent correction loop with its failed step, error, canonical contract and requirement to retain eligibility. Corrected calls can execute; repeated failures stop. Once comparison_summary is selected, finalization requires its validated result, even if the model tries to return an unrelated successful aggregation. Uncorrected failures expose no unrelated result as success.

## Verification

The exact captured call is preserved in server/tests/fixtures/comparison_summary_live.json and replayed through process_chat_message for both dispatch routes, with actual Olist calculation and saved-result reopening. Tests also cover correction on both paths, alias-equivalent duplicate prevention, conflicting population fields, unknown fields/predicates, missing references, same-day timestamps with different times, missing dates, and rejection of an unrelated successful aggregation after a comparison failure.

The main regression run passed 21 tests, covering comparison contracts, shared result operations and provider failure handling. A final focused contract suite includes the additional wording-independent finalization guard. Production build passed.

The original natural-language question was submitted unchanged through the running HTTP chat endpoint. Fresh response `662ab4bf-1c18-4b30-ab7a-ca3857140c29` completed in 9.14 seconds with one successful comparison_summary step and canonical eligibility_filters: order_status == delivered. Its saved Open result payload was reopened through the running Saved Analyses endpoint and matched the response.

Independent SQLite date comparisons confirm:

| Fact | Result |
|---|---:|
| Delivered orders | 96,478 |
| Missing actual delivery dates | 8 |
| Eligible/comparable orders | 96,470 |
| Missing estimated dates among eligible | 0 |
| Late orders | 6,534 |
| Late percentage | 6.7730900798175595% |

The numerator uses date(actual) > date(estimated), so delivery later in time on the same estimated calendar day is on time. No dataset values or previous failed responses were rewritten.

## Browser retest

Refresh the app, select Olist → orders, and reuse the original question:

> Among delivered orders, calculate the percentage whose order_delivered_customer_date is after order_estimated_delivery_date. Compare calendar dates, report missing actual and estimated dates separately, and exclude missing dates from comparisons.

Expect the figures above. Open the new result, inspect calculation provenance and the preserved delivered-only predicate, then reload/reopen the saved result. Browser inspection remains with the user; the new live result above is already available to open.
