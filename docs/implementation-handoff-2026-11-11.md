# Implementation handoff: diagnostics, follow-ups, repairs, and UI verification

Prepared from the current working-tree diff on 2026-11-11. No commits or pushes have been made. This document describes this review/testing session's changes; it does not claim ownership of earlier architectural work already in HEAD.

## Read this before staging

The working tree already contained changes to `docker-compose.yml`, `server/app/core/config.py`, and `server/app/llm/client.py` before this session's implementation work. Those changes introduced optional OpenRouter configuration/provider support. This session added usage instrumentation to the same client file, so it contains mixed ownership. The untracked `datasets/brazilian-ecommerce/` directory also predates this session.

Preserve those existing changes. Review their intended scope before committing them; do not treat the entire diff as newly authored here. The config describes the provider settings as a local override. Do not stage `.env`, credentials, imported datasets, generated builds, temporary chat databases, or complete evaluation directories.

Earlier removal of English/regex planning shortcuts, the single-specification architecture, base statistics/presentation contracts, and the original output-identity layer were existing work. The changes below extend that architecture.

## 1. Provider-reported usage diagnostics

Problem: request diagnostics recorded model calls and duration but not actual token usage, making slow/expensive requests hard to assess.

Changes:

- New `server/app/llm/usage.py` normalizes OpenRouter and Ollama counters. Records input, output, total, cached input, and reasoning counts when supplied. Malformed or absent counts remain null; real zero counts remain zero.
- `server/app/services/request_control.py` adds scoped model metadata and per-call usage records. Request totals include reported sums and known/unknown call coverage. Cached/reasoning details are subsets, not additional totals.
- `server/app/llm/client.py` records provider/model, purpose, input character count and response usage inside existing provider-call scopes. This instrumentation is layered onto preexisting provider support.
- `server/app/llm/planner.py` labels planning versus schema-repair calls and records character counts for contract, schema, history, catalog, question and repair additions. Character counts are not token estimates.
- New `server/tests/test_token_accounting.py` covers both providers, missing/malformed usage, errors, deadlines, scope isolation, repair accounting, and diagnostic persistence.

Diagnostics remain under `workspace/evaluations/request-deadlines/<request-id>.json`, using `model_calls` and `token_usage`. No new raw-prompt or credential logging was added, and accounting does not cause extra model calls. There is no new usage UI, historical backfill, price calculation, or prompt-size optimization.

## 2. Follow-up context and output ownership

Problems reproduced live:

- A count-to-late-percentage follow-up was rejected because an output's operation kind was immutable.
- An implied follow-up was classified standalone and silently lost delivered-order/year filters.
- Correct plans failed because the model renamed a single output, omitted change declarations, or mistyped a long stored message ID.

Changes:

- `server/app/analysis/operations.py`: planner guidance resolves context before choosing the operation. A referenced population remains inherited across metric/type changes; a self-contained question does not inherit unrelated filters. Validation checks operation-change permissions against the successful baseline when history is available.
- `server/app/services/change_paths.py`: operation replacement requires both `outputs.<id>.kind` and whole `outputs.<id>.parameters`, with complete valid parameters for the new operation. Missing declarations are a repairable contract error, using the existing one-repair budget.
- `server/app/services/output_identity.py`: a one-output baseline and one-output draft have one structural owner regardless of draft name. Multi-output ambiguity still requires explicit references or a unique structural anchor. History shown to the planner uses request-local `success_1`, `success_2`, etc.; references resolve to real stored message IDs before execution/persistence. Unknown/colliding references reject, and canonical identities remain unchanged.
- `server/app/llm/planner.py`: serializes that short-handle history view. This hunk shares the file with diagnostics changes and should be split if making separate commits.
- New `server/tests/test_operation_transition.py` and `server/tests/test_context_metadata.py` cover captured failures, single-output binding, canonical-ID round trips, guarded repair, unchanged stored baselines, ambiguous references, and population-changing repair rejection.

No runtime keyword classifier or second English interpreter was added. Adding/removing outputs in a follow-up remains unsupported. Semantic context interpretation still depends on the planner. An explicitly declared whole-parameter replacement is broad permission; request interpretation is not independently proved by the structural validator. These tests do not establish correctness for every possible calculation pair or phrasing.

## 3. Presentation ownership during schema repair

Problem: a valid no-chart setting placed at the envelope level could be moved to the correct analysis-plan field by repair, then wrongly rejected as a calculation change.

`server/app/analysis/repair_semantics.py` now recognizes envelope `chart_scope` and `presentation` as fields with one analysis-plan owner in the repair comparison. Conflicting copies, changed chart preferences and changed measurements still reject. Strict execution still requires the valid schema; arbitrary containers are not automatically promoted.

Captured fixtures required by the new tests:

- `server/tests/fixtures/operation_transition_failure.json`
- `server/tests/fixtures/single_output_followup_failure.json`
- `server/tests/fixtures/envelope_presentation_repair.json`

These are curated plan/diagnostic captures, not imported source datasets.

## 4. Existing test-fixture corrections

The broad suite exposed outdated expectations and tests stopping before their intended assertion boundary:

- `server/tests/test_analysis_context.py`: expects canonical `outputs.calendar.parameters.grain` rather than shorthand `grain` in stored change metadata.
- `server/tests/test_nullable_requirements.py`: expects canonical `chart_scope.preference == 'automatic'` rather than the old `required` flag.
- `server/tests/test_operation_registry.py`: checks successful automatic binding of the sole renamed output. Its negative semantic-repair cases bind to the intended stored output so they exercise repair rejection, rather than failing earlier on identity ambiguity. The negative rejection assertions remain.

## 5. UI source-label fixes found in Chrome

- `client/src/components/chat/ChatPanel.jsx`: completed progress labels use actual calculation source tables, including restored messages, instead of retaining the dataset selected at send time. Tooltips show full source IDs; visible labels use table names.
- `client/src/App.jsx`: the chat dataset heading falls back to the selected database ID when the catalog contains only its tables. Whole-database selections no longer misleadingly show “Select a dataset.”

These are presentation changes; no calculation logic changed during final browser verification.

## Suggested commit organization

Review the whole diff first, then stage explicit paths/hunks. Suggested boundaries:

1. **Provider integration and usage diagnostics**: usage module, request-control instrumentation, token tests, and the telemetry hunks in client/planner. Decide explicitly whether the preexisting OpenRouter config/client/Compose work belongs in this commit or a preceding provider commit. The token tests exercise that provider path, so do not create an intermediate commit with missing referenced configuration or client methods.
2. **Follow-up ownership and guarded repair**: operations, change paths, output identity, repair semantics, planner history-handle hunk, new context/transition tests, three curated fixtures, and relevant registry-test updates. Keep the mutually dependent validation changes together.
3. **Canonical fixture maintenance**, optionally separate: existing context/nullable assertions and any remaining fixture-only changes. Avoid including the runtime-dependent registry updates before their implementation.
4. **UI source labels**: App and ChatPanel. Include this handoff document in an appropriate documentation commit or the final commit.

Use the final implementation in commit messages, not the chronological debugging history. Do not use blanket `git add .`. Review each staged diff for coherent imports/dependencies and unintended local-only settings. Do not push without a separate request.

## Final verification

All of the following passed on the final relevant code:

| Check | Result |
| --- | --- |
| Complete backend suite | 269 tests, 0 failures/errors; 360.655 seconds |
| Frontend suite | 73 tests, 0 failures |
| Frontend production build | Passed after both UI fixes |
| Real Chrome browser replay | 38 checks, 0 runtime/API errors |
| Diff whitespace checks | Passed |
| Preceding live chat batch | 6 questions, 53 numerical/context/storage checks |

Backend verification preceded only the two UI changes; frontend tests/build and browser checks were rerun after those changes. Browser checks used the real local app with intercepted, verified API responses: no new live model calls or mutations to user projects. Coverage included scalar presentation, calculation details, no-chart requests, full tables/pagination, bar/line/heatmap rendering, keyboard inspection, source switching, narrative statistics, undefined rates, timeouts, past-chat reload, saved-result reopening, project isolation, whole-database headings, dark-theme redraw, and a 900px layout. Representative screenshots were visually inspected.

The earlier live batch used the configured provider and an isolated persisted chat database. Controls: 52,783 delivered orders purchased in 2018; 52,777 comparable; 4,078 late (7.726851%); 48,699 on time (92.273149%); six missing actual dates; zero missing estimated dates. The 2025 comparison has an undefined rate with zero comparable orders. Product-weight statistics matched underlying nonmissing values without inherited order filters.

Reproduction commands, with the existing containers running:

```sh
docker --context desktop-linux exec -e PYTHONPATH=/app/server -w /app/server offline-analyst-backend python -m unittest discover -s tests -v
docker --context desktop-linux exec offline-analyst-frontend npm test
docker --context desktop-linux exec offline-analyst-frontend npm run build
git diff --check
```

Evidence is local and gitignored:

- `workspace/evaluations/final-verification-2026-11-11/verification.json` — final aggregate results.
- Same directory: `backend.log`, `frontend.log`, `browser-verification.json`, `browser.mjs`, `browser-fixtures.json`, screenshots, and `report.md`.
- `workspace/evaluations/final-batch-2026-11-11/verification.json` and `report.md` — final live sequence and findings.
- `workspace/evaluations/token-accounting-2026-11-11/` — initial diagnostics verification.

Do not force-add complete evaluation folders. If retaining browser automation in the repository, curate a portable driver and minimal fixtures rather than committing session databases, raw run artifacts, or absolute-path-dependent scripts unchanged.
